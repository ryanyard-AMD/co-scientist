"""Tests for CS-EVAL-010/011/012 quality metrics and CS-GOV-012 evidence labels."""

import uuid
from datetime import datetime, timedelta, timezone

from conftest import GOAL_PAYLOAD
from coscientist.models.execution import RunRequestReference
from coscientist.models.roadmap import ResearchRoadmapItem
from coscientist.services import evaluation as svc
from coscientist.services import governance as gov_svc
from test_approval_api import _create_reviewed_experiment, _create_scored_approach
from test_evaluation_handoff import _ingest, _submitted_experiment


# --- CS-EVAL-010: status freshness ---


def test_freshness_fresh_submit_is_not_stale(client, db_session):
    goal, _, _, sub = _submitted_experiment(client, db_session)
    m = svc.status_freshness(db_session, goal["id"])
    assert m.total_run_requests == sub["run_request_count"]
    assert m.in_flight_run_requests >= 1
    assert m.stale_run_requests == 0
    assert m.meets_target is True


def test_freshness_flags_stale_in_flight(client, db_session):
    goal, _, _, sub = _submitted_experiment(client, db_session)
    rr = db_session.query(RunRequestReference).filter(
        RunRequestReference.run_request_id == sub["runs"][0]["run_request_id"]
    ).one()
    rr.latest_update_at = datetime.now(timezone.utc) - timedelta(days=2)
    db_session.flush()
    m = svc.status_freshness(db_session, goal["id"])
    assert m.stale_run_requests == 1
    assert rr.run_request_id in m.stale_run_request_ids
    assert m.meets_target is False
    assert m.max_staleness_seconds > m.threshold_seconds


# --- CS-EVAL-011: failed-run usefulness ---


def test_failed_run_usefulness_full(client, db_session):
    goal, _, exp, sub = _submitted_experiment(client, db_session)
    run_request_id = sub["runs"][0]["run_request_id"]
    _ingest(
        client,
        exp["id"],
        run_request_id,
        status="failed",
        failure_type="numerical_instability",
        failure_summary="diverged after 200 steps",
        artifacts={"logs": "s3://bucket/run.log"},
    )
    # A follow-up roadmap item linked to the failed experiment makes it useful.
    db_session.add(
        ResearchRoadmapItem(
            id=str(uuid.uuid4()),
            workspace_id=goal["id"],
            title="Rerun with damped step size",
            description="Address the divergence observed in the failed run.",
            lane="short_term",
            status="open",
            priority_score=0.5,
            priority_rank=1,
            rationale="Failure follow-up.",
            source_experiment_id=exp["id"],
            generation_run_id=str(uuid.uuid4()),
        )
    )
    db_session.flush()
    m = svc.failed_run_usefulness(db_session, goal["id"])
    assert m.failed_run_count == 1
    assert m.with_failure_reason == 1
    assert m.with_artifacts == 1
    assert m.with_roadmap_action == 1
    assert m.useful_count == 1
    assert m.usefulness_rate == 1.0
    assert m.meets_target is True


def test_failed_run_without_artifacts_is_not_useful(client, db_session):
    goal, _, exp, sub = _submitted_experiment(client, db_session)
    # No artifacts supplied — a bare failure with no diagnostics is not useful,
    # even though the roadmap auto-creates a follow-up (CS-ROADMAP-007).
    _ingest(
        client,
        exp["id"],
        sub["runs"][0]["run_request_id"],
        status="failed",
        failure_type="oom",
    )
    m = svc.failed_run_usefulness(db_session, goal["id"])
    assert m.failed_run_count == 1
    assert m.with_artifacts == 0
    assert m.useful_count == 0
    assert m.meets_target is False


def test_failed_run_usefulness_empty_is_not_failing(client, db_session):
    goal, _, _, _ = _submitted_experiment(client, db_session)
    m = svc.failed_run_usefulness(db_session, goal["id"])
    assert m.failed_run_count == 0
    assert m.meets_target is True


# --- CS-EVAL-012: batch aggregation quality ---


def test_batch_aggregation_quality_after_ingest(client, db_session):
    goal, _, exp, sub = _submitted_experiment(client, db_session)
    _ingest(client, exp["id"], sub["runs"][0]["run_request_id"], status="passed")
    m = svc.batch_aggregation_quality(db_session, goal["id"])
    assert m.total_batches >= 1
    assert m.total_aggregations >= 1
    assert 0.0 <= m.batch_completion_rate <= 1.0
    assert 0.0 <= m.partial_aggregation_rate <= 1.0


# --- CS-GOV-012: evidence labels ---


def test_evidence_label_proposed_before_approval(client, db_session):
    goal = client.post("/co-scientist/goals", json=GOAL_PAYLOAD).json()
    approach = _create_scored_approach(client, db_session, goal["id"])
    exp = _create_reviewed_experiment(client, goal["id"], approach["id"])
    label = gov_svc.experiment_evidence_label(db_session, exp["id"])
    assert label.label in {"proposed", "approved"}
    assert label.validation_status is None


def test_evidence_label_validation_passed_after_ingest(client, db_session):
    goal, _, exp, sub = _submitted_experiment(client, db_session)
    _ingest(client, exp["id"], sub["runs"][0]["run_request_id"], status="passed")
    label = gov_svc.experiment_evidence_label(db_session, exp["id"])
    assert label.label == "validation-passed"
    assert label.validation_status == "passed"


def test_derive_evidence_label_precedence():
    assert gov_svc.derive_evidence_label("approved", "not_submitted", None) == "approved"
    assert gov_svc.derive_evidence_label("generated", "not_submitted", None) == "proposed"
    assert gov_svc.derive_evidence_label("approved", "running", None) == "queued"
    assert gov_svc.derive_evidence_label("approved", "completed", "failed") == "validation-failed"
    assert gov_svc.derive_evidence_label("approved", "completed", "mixed") == "mixed"


def test_report_includes_quality_sections(client, db_session):
    goal, _, _, _ = _submitted_experiment(client, db_session)
    report = svc.get_report(db_session, goal["id"])
    assert report.status_freshness.meets_target is True
    assert report.failed_run_usefulness.meets_target is True
    assert report.batch_aggregation_quality.total_batches >= 1


def test_evaluation_page_shows_quality_sections(client, db_session):
    goal, _, _, _ = _submitted_experiment(client, db_session)
    resp = client.get(f"/ui/goals/{goal['id']}/evaluation")
    assert resp.status_code == 200
    body = resp.text
    assert "Status Freshness" in body
    assert "Failed-Run Usefulness" in body
    assert "Batch Aggregation Quality" in body
