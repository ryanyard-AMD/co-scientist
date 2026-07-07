"""Tests for Phase 2 gap-closure stories:
CS-SCORE-012 (metric variance), CS-VALIDATION-012 (partial score gate),
CS-VALIDATION-013 (artifact manifest labels), CS-EXEC-007 (run-request
correlation), CS-APPROACH-011 / CS-UI-011 / CS-UI-013 (UI surfacing).
"""

from coscientist.config import settings
from coscientist.models.execution import RunRequestReference
from coscientist.models.experiment import ExperimentCard
from coscientist.models.validation import ResultBundleReference
from coscientist.services import result_bundle as rb_svc
from coscientist.services import score_update as score_update_svc
from test_evaluation_handoff import PREFIX, _ingest, _submitted_experiment


# --- CS-SCORE-012: variance / stddev in metric summaries ---


def test_metric_summaries_computes_variance():
    import json

    def _b(v):
        return ResultBundleReference(metrics=json.dumps({"acoustic_contrast": v}))

    summaries = rb_svc._metric_summaries([_b(20.0), _b(30.0)])
    s = summaries["acoustic_contrast"]
    assert s["count"] == 2
    assert s["mean"] == 25.0
    # population variance of {20, 30} = 25.0, stddev = 5.0
    assert s["variance"] == 25.0
    assert s["stddev"] == 5.0


def test_metric_summary_surfaced_via_aggregation(client, db_session):
    goal, _, exp, sub = _submitted_experiment(client, db_session)
    _ingest(client, exp["id"], sub["runs"][0]["run_request_id"], status="passed")
    agg = rb_svc.get_aggregation(db_session, exp["id"])
    summary = agg.metric_summaries["acoustic_contrast"]
    assert summary.variance == 0.0
    assert abs(summary.stddev - summary.variance ** 0.5) < 1e-9


# --- CS-VALIDATION-012: partial aggregations don't drive score updates ---


def test_partial_aggregation_holds_score_update(client, db_session):
    goal, approach, exp, sub = _submitted_experiment(client, db_session)
    # Force a partial aggregation: expect more runs than we ingest so a run is missing.
    card = db_session.get(ExperimentCard, exp["id"])
    card.expected_run_count = len(sub["runs"]) + 1
    db_session.flush()
    assert settings.score_update_on_partial is False
    _ingest(client, exp["id"], sub["runs"][0]["run_request_id"], status="passed")
    agg = rb_svc.get_aggregation(db_session, exp["id"])
    assert agg.is_partial is True
    assert agg.missing_runs >= 1
    updates = score_update_svc.list_score_updates(db_session, goal["id"], experiment_id=exp["id"])
    assert updates.total == 0


def test_complete_aggregation_applies_score_update(client, db_session):
    goal, approach, exp, sub = _submitted_experiment(client, db_session)
    rr_ids = [r["run_request_id"] for r in sub["runs"]]
    for rr in rr_ids:
        _ingest(client, exp["id"], rr, status="passed")
    agg = rb_svc.get_aggregation(db_session, exp["id"])
    assert agg.is_partial is False
    updates = score_update_svc.list_score_updates(db_session, goal["id"], experiment_id=exp["id"])
    assert updates.total >= 1


# --- CS-VALIDATION-013: artifact manifest URI + access labels ---


def test_bundle_stores_manifest_and_access_labels(client, db_session):
    goal, _, exp, sub = _submitted_experiment(client, db_session)
    resp = _ingest(
        client,
        exp["id"],
        sub["runs"][0]["run_request_id"],
        status="passed",
        manifest_uri="s3://bucket/manifest.json",
        artifact_visibility="restricted",
        access_label="reviewers-only",
    )
    body = resp.json()["bundle"]
    assert body["manifest_uri"] == "s3://bucket/manifest.json"
    assert body["artifact_visibility"] == "restricted"
    assert body["access_label"] == "reviewers-only"


def test_bundle_manifest_defaults(client, db_session):
    goal, _, exp, sub = _submitted_experiment(client, db_session)
    resp = _ingest(client, exp["id"], sub["runs"][0]["run_request_id"], status="passed")
    body = resp.json()["bundle"]
    assert body["manifest_uri"] is None
    assert body["artifact_visibility"] == "internal"


# --- CS-EXEC-007: run-request correlation to approach/hypothesis ---


def test_run_request_correlates_to_approach(client, db_session):
    goal, approach, exp, sub = _submitted_experiment(client, db_session)
    rr = db_session.query(RunRequestReference).filter(
        RunRequestReference.run_request_id == sub["runs"][0]["run_request_id"]
    ).one()
    import json

    assert approach["id"] in json.loads(rr.approach_ids)


# --- UI surfacing ---


def test_approach_detail_renders_execution_evidence(client, db_session):
    goal, approach, exp, sub = _submitted_experiment(client, db_session)
    _ingest(
        client,
        exp["id"],
        sub["runs"][0]["run_request_id"],
        status="failed",
        failure_type="oom",
        failure_summary="ran out of memory",
    )
    resp = client.get(f"/ui/goals/{goal['id']}/approaches/{approach['id']}")
    assert resp.status_code == 200
    assert "Execution Evidence" in resp.text


def test_validation_page_shows_score_policy_and_manifest(client, db_session):
    goal, _, exp, sub = _submitted_experiment(client, db_session)
    _ingest(
        client,
        exp["id"],
        sub["runs"][0]["run_request_id"],
        status="passed",
        manifest_uri="s3://bucket/m.json",
    )
    resp = client.get(f"/ui/goals/{goal['id']}/validation")
    assert resp.status_code == 200
    assert "score updates" in resp.text
    assert "manifest" in resp.text


def test_experiment_detail_shows_affected_roadmap(client, db_session):
    goal, _, exp, sub = _submitted_experiment(client, db_session)
    # A failed run auto-creates a roadmap follow-up (CS-ROADMAP-007).
    _ingest(
        client,
        exp["id"],
        sub["runs"][0]["run_request_id"],
        status="failed",
        failure_type="numerical_instability",
        failure_summary="diverged",
        artifacts={"logs": "s3://b/run.log"},
    )
    resp = client.get(f"/ui/goals/{goal['id']}/experiments/{exp['id']}")
    assert resp.status_code == 200
    assert "Affected roadmap items" in resp.text
