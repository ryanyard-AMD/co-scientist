"""Tests for CS-EPIC-VALIDATION ResultBundle ingestion + aggregation."""

from conftest import GOAL_PAYLOAD
from test_approval_api import _create_scored_approach, _create_reviewed_experiment

PREFIX = "/co-scientist"


def _goal_and_experiment(client, db_session, independent_variables=None):
    goal = client.post(f"{PREFIX}/goals", json=GOAL_PAYLOAD).json()
    approach = _create_scored_approach(client, db_session, goal["id"])
    payload = {
        "name": "Bundle Experiment",
        "objective": "Evaluate method",
        "hypothesis_text": "Method achieves target",
        "approach_ids": [approach["id"]],
    }
    if independent_variables:
        payload["independent_variables"] = independent_variables
        payload["submission_mode"] = "sweep_batch"
    exp = client.post(f"{PREFIX}/goals/{goal['id']}/experiments", json=payload).json()
    return goal, exp


def _bundle(experiment_id, run_request_id, status="passed", **extra):
    body = {
        "result_bundle_id": f"rb-{run_request_id}",
        "run_request_id": run_request_id,
        "run_id": f"run-{run_request_id}",
        "attempt_id": "1",
        "experiment_id": experiment_id,
        "validation_status": status,
        "metrics": {"acoustic_contrast": 22.0},
    }
    body.update(extra)
    return body


def test_ingest_creates_bundle_and_aggregation(client, db_session):
    goal, exp = _goal_and_experiment(client, db_session)
    resp = client.post(f"{PREFIX}/result-bundles", json=_bundle(exp["id"], "rr-1"))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ingested"] is True
    assert body["duplicate"] is False
    assert body["aggregation"]["aggregate_status"] == "passed"
    assert body["aggregation"]["total_runs"] == 1
    assert body["aggregation"]["metric_summaries"]["acoustic_contrast"]["mean"] == 22.0


def test_ingest_is_idempotent(client, db_session):
    goal, exp = _goal_and_experiment(client, db_session)
    client.post(f"{PREFIX}/result-bundles", json=_bundle(exp["id"], "rr-1"))
    resp = client.post(f"{PREFIX}/result-bundles", json=_bundle(exp["id"], "rr-1"))
    assert resp.json()["ingested"] is False
    assert resp.json()["duplicate"] is True
    listed = client.get(f"{PREFIX}/experiments/{exp['id']}/result-bundles").json()
    assert listed["total"] == 1


def test_mixed_outcome_across_runs(client, db_session):
    goal, exp = _goal_and_experiment(client, db_session)
    client.post(f"{PREFIX}/result-bundles", json=_bundle(exp["id"], "rr-1", status="passed"))
    client.post(f"{PREFIX}/result-bundles", json=_bundle(exp["id"], "rr-2", status="failed"))
    agg = client.get(f"{PREFIX}/experiments/{exp['id']}/validation-aggregation").json()
    assert agg["aggregate_status"] == "mixed"
    assert agg["passed_runs"] == 1
    assert agg["failed_runs"] == 1


def test_partial_when_runs_missing(client, db_session):
    goal, exp = _goal_and_experiment(
        client, db_session, independent_variables={"speaker_count": [2, 4, 8]}
    )
    assert exp["execution_handoff"]["expected_run_count"] == 3
    client.post(f"{PREFIX}/result-bundles", json=_bundle(exp["id"], "rr-1", status="passed"))
    agg = client.get(f"{PREFIX}/experiments/{exp['id']}/validation-aggregation").json()
    assert agg["aggregate_status"] == "partial"
    assert agg["missing_runs"] == 2
    assert agg["is_partial"] is True


def test_failed_bundle_records_diagnostics(client, db_session):
    goal, exp = _goal_and_experiment(client, db_session)
    resp = client.post(
        f"{PREFIX}/result-bundles",
        json=_bundle(
            exp["id"],
            "rr-1",
            status="failed",
            failure_type="oom",
            failure_summary="ran out of memory",
            retryable=True,
            deviations=["seed drift"],
        ),
    )
    bundle = resp.json()["bundle"]
    assert bundle["failure_type"] == "oom"
    assert bundle["retryable"] is True
    assert bundle["deviations"] == ["seed drift"]
    assert resp.json()["aggregation"]["aggregate_status"] == "failed"


def test_ingest_syncs_run_request_status(client, db_session):
    goal = client.post(f"{PREFIX}/goals", json=GOAL_PAYLOAD).json()
    approach = _create_scored_approach(client, db_session, goal["id"])
    exp = _create_reviewed_experiment(client, goal["id"], approach["id"])
    client.post(f"{PREFIX}/goals/{goal['id']}/experiments/{exp['id']}/approve", json={})
    sub = client.post(f"{PREFIX}/goals/{goal['id']}/experiments/{exp['id']}/submit", json={}).json()
    rr_id = sub["runs"][0]["run_request_id"]

    client.post(f"{PREFIX}/result-bundles", json=_bundle(exp["id"], rr_id, status="passed"))
    run = client.get(f"{PREFIX}/run-requests/{rr_id}").json()
    assert run["status"] == "completed"


def test_aggregation_404_when_absent(client, db_session):
    goal, exp = _goal_and_experiment(client, db_session)
    resp = client.get(f"{PREFIX}/experiments/{exp['id']}/validation-aggregation")
    assert resp.status_code == 404


def test_ingest_unknown_experiment_404(client):
    resp = client.post(f"{PREFIX}/result-bundles", json=_bundle("nope", "rr-1"))
    assert resp.status_code == 404
