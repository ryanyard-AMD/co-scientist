"""Tests for CS-EPIC-APPROACH: execution evidence links + status refresh."""

from conftest import GOAL_PAYLOAD
from test_approval_api import _create_scored_approach

PREFIX = "/co-scientist"


def _goal_approach_experiment(client, db_session):
    goal = client.post(f"{PREFIX}/goals", json=GOAL_PAYLOAD).json()
    approach = _create_scored_approach(client, db_session, goal["id"])
    exp = client.post(
        f"{PREFIX}/goals/{goal['id']}/experiments",
        json={
            "name": "Evidence Experiment",
            "objective": "Evaluate method",
            "hypothesis_text": "Method achieves target",
            "approach_ids": [approach["id"]],
        },
    ).json()
    return goal, approach, exp


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


def _evidence(client, goal_id, approach_id):
    return client.get(
        f"{PREFIX}/goals/{goal_id}/approaches/{approach_id}/execution-evidence"
    ).json()


def _status(client, goal_id, approach_id):
    return client.get(f"{PREFIX}/goals/{goal_id}/approaches/{approach_id}").json()["status"]


def test_evidence_links_experiment_to_approach(client, db_session):
    goal, approach, exp = _goal_approach_experiment(client, db_session)
    ev = _evidence(client, goal["id"], approach["id"])

    assert ev["approach_id"] == approach["id"]
    assert len(ev["experiments"]) == 1
    block = ev["experiments"][0]
    assert block["experiment_id"] == exp["id"]
    assert block["experiment_name"] == "Evidence Experiment"


def test_evidence_groups_distinguish_literature_from_execution(client, db_session):
    goal, approach, exp = _goal_approach_experiment(client, db_session)
    client.post(f"{PREFIX}/result-bundles", json=_bundle(exp["id"], "rr-1", status="passed"))

    ev = _evidence(client, goal["id"], approach["id"])
    groups = ev["evidence_groups"]
    assert set(groups) >= {
        "source_literature",
        "inferred_synthesis",
        "generated_hypotheses",
        "approved_experiments",
        "completed_validation",
        "failed_validation",
        "inconclusive_validation",
    }
    assert groups["source_literature"] >= 1
    assert ev["literature_evidence_count"] == groups["source_literature"]
    assert groups["completed_validation"] == 1
    assert groups["failed_validation"] == 0


def test_passed_bundle_advances_approach_to_validated(client, db_session):
    goal, approach, exp = _goal_approach_experiment(client, db_session)
    assert _status(client, goal["id"], approach["id"]) == "scored"

    client.post(f"{PREFIX}/result-bundles", json=_bundle(exp["id"], "rr-1", status="passed"))

    assert _status(client, goal["id"], approach["id"]) == "validated"
    assert _evidence(client, goal["id"], approach["id"])["status"] == "validated"


def test_failed_bundle_refutes_approach_with_negative_evidence(client, db_session):
    goal, approach, exp = _goal_approach_experiment(client, db_session)
    client.post(
        f"{PREFIX}/result-bundles",
        json=_bundle(
            exp["id"],
            "rr-1",
            status="failed",
            failure_type="threshold_not_met",
            failure_summary="Contrast below target",
            deviations=["seed drift"],
            retryable=True,
        ),
    )

    assert _status(client, goal["id"], approach["id"]) == "refuted"

    ev = _evidence(client, goal["id"], approach["id"])
    assert ev["evidence_groups"]["failed_validation"] == 1
    neg = ev["experiments"][0]["negative_evidence"]
    assert len(neg) == 1
    assert neg[0]["failure_type"] == "threshold_not_met"
    assert neg[0]["retryable"] is True
    assert any("rr-1" in f or "Evidence Experiment" in f for f in ev["suggested_followups"])


def test_blocked_outcome_marks_approach_inconclusive(client, db_session):
    goal, approach, exp = _goal_approach_experiment(client, db_session)
    client.post(f"{PREFIX}/result-bundles", json=_bundle(exp["id"], "rr-1", status="blocked"))

    assert _status(client, goal["id"], approach["id"]) == "inconclusive"


def test_validated_wins_over_later_mixed_outcome(client, db_session):
    goal, approach, exp = _goal_approach_experiment(client, db_session)
    client.post(f"{PREFIX}/result-bundles", json=_bundle(exp["id"], "rr-1", status="passed"))
    client.post(f"{PREFIX}/result-bundles", json=_bundle(exp["id"], "rr-2", status="failed"))

    # Forward-only: a validated approach is not regressed by a later mixed sweep.
    assert _status(client, goal["id"], approach["id"]) == "validated"


def test_status_refresh_is_forward_only(client, db_session):
    goal, approach, exp = _goal_approach_experiment(client, db_session)
    client.post(f"{PREFIX}/result-bundles", json=_bundle(exp["id"], "rr-1", status="passed"))
    assert _status(client, goal["id"], approach["id"]) == "validated"

    # A later failed bundle must not regress a validated approach.
    client.post(f"{PREFIX}/result-bundles", json=_bundle(exp["id"], "rr-2", status="failed"))
    assert _status(client, goal["id"], approach["id"]) == "validated"


def test_evidence_404_for_unknown_approach(client, db_session):
    goal = client.post(f"{PREFIX}/goals", json=GOAL_PAYLOAD).json()
    resp = client.get(
        f"{PREFIX}/goals/{goal['id']}/approaches/nonexistent/execution-evidence"
    )
    assert resp.status_code == 404
