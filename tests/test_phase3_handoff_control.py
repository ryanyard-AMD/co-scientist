"""Tests for Phase 3 gap-closure stories:
CS-APPROVAL-010 (failed handoff record + idempotent retry),
CS-APPROVAL-011 / CS-UI-012 (cancel / resubmit requests, read-only display),
CS-GOV-011 (redaction of runner internals).
"""

import json

from coscientist.models.execution import RunRequestReference
from coscientist.models.experiment import ExperimentCard
from coscientist.models.handoff import HandoffRequest
from coscientist.services import governance as governance_svc
from coscientist.services import handoff as handoff_svc
from coscientist.services import submission as submission_svc
from test_evaluation_handoff import PREFIX, _ingest, _submitted_experiment
from test_approval_api import _create_reviewed_experiment, _create_scored_approach
from conftest import GOAL_PAYLOAD


def _approved_experiment(client, db_session):
    """A goal + approved (but not-yet-submitted) experiment card."""
    goal = client.post(f"{PREFIX}/goals", json=GOAL_PAYLOAD).json()
    approach = _create_scored_approach(client, db_session, goal["id"])
    exp = _create_reviewed_experiment(client, goal["id"], approach["id"])
    client.post(f"{PREFIX}/goals/{goal['id']}/experiments/{exp['id']}/approve", json={})
    return goal, approach, exp


# --- CS-APPROVAL-010: failed handoff record + idempotent retry ---


def test_failed_handoff_records_request_and_marks_card(client, db_session, monkeypatch):
    goal, approach, exp = _approved_experiment(client, db_session)

    def _boom(payload):
        raise RuntimeError("experimentation system unavailable")

    monkeypatch.setattr(submission_svc, "run_request_submitter", _boom)
    resp = client.post(f"{PREFIX}/goals/{goal['id']}/experiments/{exp['id']}/submit", json={})
    assert resp.status_code == 502

    card = db_session.get(ExperimentCard, exp["id"])
    db_session.refresh(card)
    assert card.handoff_status == "failed"

    rows = db_session.query(HandoffRequest).filter(
        HandoffRequest.experiment_id == exp["id"]
    ).all()
    assert len(rows) == 1
    row = rows[0]
    assert row.request_type == "submit"
    assert row.status == "failed"
    assert "unavailable" in row.error
    assert row.retryable is True
    assert row.approval_id is not None
    assert json.loads(row.payload_summary)["attempted_run_count"] >= 1


def test_retry_after_failure_creates_no_duplicate_run_requests(client, db_session, monkeypatch):
    goal, approach, exp = _approved_experiment(client, db_session)

    calls = {"n": 0}

    def _flaky(payload):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient network error")
        return submission_svc._default_run_request_submitter(payload)

    monkeypatch.setattr(submission_svc, "run_request_submitter", _flaky)

    first = client.post(f"{PREFIX}/goals/{goal['id']}/experiments/{exp['id']}/submit", json={})
    assert first.status_code == 502

    retry = client.post(f"{PREFIX}/goals/{goal['id']}/experiments/{exp['id']}/retry", json={})
    assert retry.status_code == 201
    body = retry.json()
    assert body["handoff_status"] == "submitted"

    runs = db_session.query(RunRequestReference).filter(
        RunRequestReference.experiment_id == exp["id"]
    ).all()
    # Retry reuses the batch; run count matches the preview, not doubled.
    assert len(runs) == body["run_request_count"]

    # A retry HandoffRequest was recorded on success.
    reqs = db_session.query(HandoffRequest).filter(
        HandoffRequest.experiment_id == exp["id"]
    ).all()
    types = {r.request_type for r in reqs}
    assert "retry" in types


def test_existing_run_for_params_reused(client, db_session):
    goal, approach, exp, sub = _submitted_experiment(client, db_session)
    rr = db_session.query(RunRequestReference).filter(
        RunRequestReference.experiment_id == exp["id"]
    ).first()
    params = json.loads(rr.parameters)
    found = submission_svc._existing_run_for_params(db_session, exp["id"], params)
    assert found is not None
    assert found.run_request_id == rr.run_request_id


def test_submit_twice_when_already_submitted_conflicts(client, db_session):
    goal, approach, exp, sub = _submitted_experiment(client, db_session)
    resp = client.post(f"{PREFIX}/goals/{goal['id']}/experiments/{exp['id']}/submit", json={})
    assert resp.status_code == 409


# --- CS-APPROVAL-011 / CS-UI-012: cancel + resubmit requests ---


def test_cancel_records_request(client, db_session):
    goal, approach, exp, sub = _submitted_experiment(client, db_session)
    resp = client.post(
        f"{PREFIX}/goals/{goal['id']}/experiments/{exp['id']}/cancel",
        json={"requester": "reviewer-a", "reason": "cost overrun"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["request_type"] == "cancel"
    assert body["status"] == "requested"
    assert body["payload_summary"]["reason"] == "cost overrun"


def test_resubmit_records_request(client, db_session):
    goal, approach, exp, sub = _submitted_experiment(client, db_session)
    resp = client.post(
        f"{PREFIX}/goals/{goal['id']}/experiments/{exp['id']}/resubmit",
        json={"requester": "reviewer-a"},
    )
    assert resp.status_code == 201
    assert resp.json()["request_type"] == "resubmit"


def test_cancel_before_submit_conflicts(client, db_session):
    goal, approach, exp = _approved_experiment(client, db_session)
    resp = client.post(
        f"{PREFIX}/goals/{goal['id']}/experiments/{exp['id']}/cancel", json={}
    )
    assert resp.status_code == 409


def test_list_handoff_requests(client, db_session):
    goal, approach, exp, sub = _submitted_experiment(client, db_session)
    client.post(f"{PREFIX}/goals/{goal['id']}/experiments/{exp['id']}/cancel", json={})
    resp = client.get(f"{PREFIX}/goals/{goal['id']}/experiments/{exp['id']}/handoff-requests")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["request_type"] == "cancel"


def test_cancel_does_not_change_run_status(client, db_session):
    """Execution control stays with the Experimentation System — cancelling only
    records the request; run statuses are unchanged until that system reports."""
    goal, approach, exp, sub = _submitted_experiment(client, db_session)
    before = {
        r.run_request_id: r.status
        for r in db_session.query(RunRequestReference).filter(
            RunRequestReference.experiment_id == exp["id"]
        )
    }
    client.post(f"{PREFIX}/goals/{goal['id']}/experiments/{exp['id']}/cancel", json={})
    db_session.expire_all()
    after = {
        r.run_request_id: r.status
        for r in db_session.query(RunRequestReference).filter(
            RunRequestReference.experiment_id == exp["id"]
        )
    }
    assert before == after


# --- CS-GOV-011: redaction of runner internals ---


def test_redact_secrets_always():
    data = {"api_key": "sk-123", "value": 5}
    out = governance_svc.redact_runner_internals(data, authorized=False)
    assert out["api_key"] == governance_svc.REDACTED
    assert out["value"] == 5
    # Even an authorized viewer never sees raw secrets.
    out2 = governance_svc.redact_runner_internals(data, authorized=True)
    assert out2["api_key"] == governance_svc.REDACTED


def test_redact_paths_and_logs_when_unauthorized():
    data = {
        "log_path": "/home/runner/job/out.log",
        "raw_log": "traceback ...",
        "metric": 1.0,
    }
    out = governance_svc.redact_runner_internals(data, authorized=False)
    assert out["log_path"] == "***path-redacted***"
    assert out["raw_log"] == governance_svc.REDACTED
    assert out["metric"] == 1.0
    # Operator view keeps them.
    out2 = governance_svc.redact_runner_internals(data, authorized=True)
    assert out2["log_path"] == "/home/runner/job/out.log"
    assert out2["raw_log"] == "traceback ..."


def test_restricted_bundle_artifacts_redacted(client, db_session):
    goal, approach, exp, sub = _submitted_experiment(client, db_session)
    resp = _ingest(
        client,
        exp["id"],
        sub["runs"][0]["run_request_id"],
        status="passed",
        artifact_visibility="restricted",
        artifacts={"secret_token": "abc", "workdir": "/home/runner/x", "plot": "s3://b/p.png"},
    )
    artifacts = resp.json()["bundle"]["artifacts"]
    assert artifacts["secret_token"] == governance_svc.REDACTED
    assert artifacts["workdir"] == "***path-redacted***"
    assert artifacts["plot"] == "s3://b/p.png"


def test_internal_bundle_artifacts_not_redacted(client, db_session):
    goal, approach, exp, sub = _submitted_experiment(client, db_session)
    resp = _ingest(
        client,
        exp["id"],
        sub["runs"][0]["run_request_id"],
        status="passed",
        artifacts={"workdir": "/home/runner/x"},
    )
    # Default visibility is "internal" — not redacted.
    assert resp.json()["bundle"]["artifacts"]["workdir"] == "/home/runner/x"


# --- CS-UI-012: read-only display ---


def test_experiment_detail_shows_handoff_requests(client, db_session):
    goal, approach, exp, sub = _submitted_experiment(client, db_session)
    client.post(f"{PREFIX}/goals/{goal['id']}/experiments/{exp['id']}/cancel", json={})
    resp = client.get(f"/ui/goals/{goal['id']}/experiments/{exp['id']}")
    assert resp.status_code == 200
    assert "Handoff control requests" in resp.text
