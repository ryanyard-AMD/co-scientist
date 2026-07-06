"""Tests for CS-EPIC-SCORE: execution-evidence score updates."""

from conftest import GOAL_PAYLOAD
from coscientist.schemas.score import ExecutionEvidenceTypeEnum
from test_approval_api import _create_scored_approach

PREFIX = "/co-scientist"


def _goal_approach_experiment(client, db_session):
    goal = client.post(f"{PREFIX}/goals", json=GOAL_PAYLOAD).json()
    approach = _create_scored_approach(client, db_session, goal["id"])
    exp = client.post(
        f"{PREFIX}/goals/{goal['id']}/experiments",
        json={
            "name": "Score Experiment",
            "objective": "Evaluate method",
            "hypothesis_text": "Method achieves target",
            "approach_ids": [approach["id"]],
        },
    ).json()
    return goal, approach, exp


def _evidence_strength(client, goal_id, approach_id):
    scores = client.get(f"{PREFIX}/goals/{goal_id}/approaches/{approach_id}/scores").json()
    dim = next(d for d in scores["dimensions"] if d["dimension"] == "evidence_strength")
    return dim["score"], dim["confidence"]


def _bundle(experiment_id, run_request_id, status="passed", **extra):
    body = {
        "result_bundle_id": f"rb-{run_request_id}",
        "run_request_id": run_request_id,
        "attempt_id": "1",
        "experiment_id": experiment_id,
        "validation_status": status,
        "metrics": {"acoustic_contrast": 22.0},
    }
    body.update(extra)
    return body


def test_passed_bundle_raises_score_and_confidence(client, db_session):
    goal, approach, exp = _goal_approach_experiment(client, db_session)
    score_before, conf_before = _evidence_strength(client, goal["id"], approach["id"])

    client.post(f"{PREFIX}/result-bundles", json=_bundle(exp["id"], "rr-1", status="passed"))

    updates = client.get(f"{PREFIX}/goals/{goal['id']}/score-updates").json()
    assert updates["total"] == 1
    u = updates["items"][0]
    assert u["approach_id"] == approach["id"]
    assert u["evidence_type"] == "validation_passed"
    assert u["score_delta"] > 0
    assert u["confidence_delta"] > 0
    assert u["previous_score"] == score_before

    score_after, conf_after = _evidence_strength(client, goal["id"], approach["id"])
    assert score_after > score_before
    assert conf_after > (conf_before or 0)


def test_failed_bundle_lowers_score_raises_confidence(client, db_session):
    goal, approach, exp = _goal_approach_experiment(client, db_session)
    client.post(f"{PREFIX}/result-bundles", json=_bundle(exp["id"], "rr-1", status="failed"))

    u = client.get(f"{PREFIX}/goals/{goal['id']}/score-updates").json()["items"][0]
    assert u["evidence_type"] == "validation_failed"
    assert u["score_delta"] < 0
    assert u["confidence_delta"] > 0
    assert u["failed_count"] == 1


def test_duplicate_bundle_produces_no_second_update(client, db_session):
    goal, approach, exp = _goal_approach_experiment(client, db_session)
    client.post(f"{PREFIX}/result-bundles", json=_bundle(exp["id"], "rr-1", status="passed"))
    score_after_first, _ = _evidence_strength(client, goal["id"], approach["id"])

    client.post(f"{PREFIX}/result-bundles", json=_bundle(exp["id"], "rr-1", status="passed"))

    updates = client.get(f"{PREFIX}/goals/{goal['id']}/score-updates").json()
    assert updates["total"] == 1
    score_after_second, _ = _evidence_strength(client, goal["id"], approach["id"])
    assert score_after_second == score_after_first


def test_mixed_outcome_moves_confidence_not_directional_score(client, db_session):
    goal, approach, exp = _goal_approach_experiment(client, db_session)
    client.post(f"{PREFIX}/result-bundles", json=_bundle(exp["id"], "rr-1", status="passed"))
    client.post(f"{PREFIX}/result-bundles", json=_bundle(exp["id"], "rr-2", status="failed"))

    updates = client.get(
        f"{PREFIX}/goals/{goal['id']}/score-updates",
        params={"experiment_id": exp["id"]},
    ).json()
    latest = updates["items"][0]  # newest first
    assert latest["validation_status"] == "mixed"
    assert latest["evidence_type"] == "mixed_validation"
    assert latest["score_delta"] == 0
    assert latest["confidence_delta"] > 0


def test_score_update_carries_batch_explainability(client, db_session):
    goal, approach, exp = _goal_approach_experiment(client, db_session)
    client.post(f"{PREFIX}/result-bundles", json=_bundle(exp["id"], "rr-1", status="passed"))

    u = client.get(f"{PREFIX}/goals/{goal['id']}/score-updates").json()["items"][0]
    assert u["run_count"] == 1
    assert u["passed_count"] == 1
    assert "acoustic_contrast" in u["aggregate_metrics"]
    assert u["result_bundle_refs"] == ["rb-rr-1"]
    assert u["rationale"]


def test_evidence_type_enum_covers_execution_evidence():
    values = {e.value for e in ExecutionEvidenceTypeEnum}
    assert {
        "approved_experiment_design",
        "queued_experiment",
        "completed_experiment",
        "failed_experiment",
        "validation_passed",
        "validation_failed",
        "mixed_validation",
    } <= values
