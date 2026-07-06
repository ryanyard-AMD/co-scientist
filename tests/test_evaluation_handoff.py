"""Tests for CS-EPIC-EVALUATION handoff metrics (CS-EVAL-007/008/009)."""

from conftest import GOAL_PAYLOAD
from coscientist.schemas.execution import RunRequestStatusEnum
from coscientist.services import evaluation as svc
from coscientist.services import execution as execution_svc
from test_approval_api import _create_reviewed_experiment, _create_scored_approach

PREFIX = "/co-scientist"


def _submitted_experiment(client, db_session):
    goal = client.post(f"{PREFIX}/goals", json=GOAL_PAYLOAD).json()
    approach = _create_scored_approach(client, db_session, goal["id"])
    exp = _create_reviewed_experiment(client, goal["id"], approach["id"])
    client.post(f"{PREFIX}/goals/{goal['id']}/experiments/{exp['id']}/approve", json={})
    sub = client.post(
        f"{PREFIX}/goals/{goal['id']}/experiments/{exp['id']}/submit", json={}
    ).json()
    return goal, approach, exp, sub


def _ingest(client, experiment_id, run_request_id, status="passed", **extra):
    body = {
        "result_bundle_id": f"rb-{run_request_id}",
        "run_request_id": run_request_id,
        "attempt_id": "1",
        "experiment_id": experiment_id,
        "validation_status": status,
        "metrics": {"acoustic_contrast": 22.0},
    }
    body.update(extra)
    return client.post(f"{PREFIX}/result-bundles", json=body)


# --- CS-EVAL-007: handoff success ---


def test_handoff_success_counts_submitted(client, db_session):
    goal, _, _, sub = _submitted_experiment(client, db_session)
    m = svc.handoff_success(db_session, goal["id"])
    assert m.approved_experiments == 1
    assert m.attempted_handoffs == 1
    assert m.successful_handoffs == 1
    assert m.failed_handoffs == 0
    assert m.handoff_success_rate == 1.0
    assert m.handoff_success_meets_target is True
    assert m.successful_run_requests == sub["run_request_count"]


def test_handoff_success_empty_is_not_failing(client, db_session):
    goal = client.post(f"{PREFIX}/goals", json=GOAL_PAYLOAD).json()
    m = svc.handoff_success(db_session, goal["id"])
    assert m.attempted_handoffs == 0
    assert m.handoff_success_meets_target is True
    assert m.retry_success_rate is None


# --- CS-EVAL-008: execution traceability ---


def test_traceability_full_after_submit(client, db_session):
    goal, _, exp, sub = _submitted_experiment(client, db_session)
    m = svc.execution_traceability(db_session, goal["id"])
    assert m.total_run_requests == sub["run_request_count"]
    assert m.linked_to_experiment == m.total_run_requests
    assert m.linked_to_approach == m.total_run_requests
    assert m.linked_to_approval == m.total_run_requests
    assert m.fully_traceable == m.total_run_requests
    assert m.traceability_rate == 1.0
    assert m.traceability_meets_target is True
    assert m.untraceable_run_request_ids == []


def test_traceability_flags_run_request_without_approval(client, db_session):
    goal = client.post(f"{PREFIX}/goals", json=GOAL_PAYLOAD).json()
    # A run request with no experiment card and no handoff audit record is untraceable.
    execution_svc.register_run_request(
        db_session,
        run_request_id="rr-orphan",
        experiment_id="missing-exp",
        goal_id=goal["id"],
        workspace_id=goal["id"],
        status=RunRequestStatusEnum.pending,
    )
    m = svc.execution_traceability(db_session, goal["id"])
    assert m.total_run_requests == 1
    assert m.fully_traceable == 0
    assert m.traceability_meets_target is False
    assert "rr-orphan" in m.untraceable_run_request_ids


# --- CS-EVAL-009: duplicate ingestion / idempotency ---


def test_duplicate_ingestion_zero_on_replay(client, db_session):
    goal, _, exp, sub = _submitted_experiment(client, db_session)
    run_request_id = sub["runs"][0]["run_request_id"]
    _ingest(client, exp["id"], run_request_id, status="passed")
    # Replay the identical bundle — must not create a second bundle or score change.
    _ingest(client, exp["id"], run_request_id, status="passed")
    m = svc.duplicate_ingestion(db_session, goal["id"])
    assert m.total_result_bundles == 1
    assert m.distinct_ingestion_keys == 1
    assert m.duplicate_bundle_count == 0
    assert m.duplicate_score_update_count == 0
    assert m.meets_target is True


def test_report_includes_handoff_sections(client, db_session):
    goal, _, _, _ = _submitted_experiment(client, db_session)
    report = svc.get_report(db_session, goal["id"])
    assert report.handoff_success.attempted_handoffs == 1
    assert report.execution_traceability.total_run_requests >= 1
    assert report.duplicate_ingestion.meets_target is True


def test_evaluation_page_shows_handoff_sections(client, db_session):
    goal, _, _, _ = _submitted_experiment(client, db_session)
    resp = client.get(f"/ui/goals/{goal['id']}/evaluation")
    assert resp.status_code == 200
    body = resp.text
    assert "Execution Handoff" in body
    assert "Execution Traceability" in body
    assert "Idempotent Ingestion" in body
