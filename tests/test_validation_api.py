import json
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from conftest import GOAL_PAYLOAD
from coscientist.models.evidence import EvidenceRecord
from coscientist.schemas.validation import (
    AgentValidationOutput,
    CriterionResult,
    ValidationDecisionEnum,
)

MOCK_VALIDATED = AgentValidationOutput(
    decision=ValidationDecisionEnum.validated,
    confidence=0.92,
    reasoning="All criteria passed.",
    criterion_results=[
        CriterionResult(name="acoustic_contrast", measured=18.5, target=15.0,
                        operator=">=", passed=True, unit="dB"),
    ],
    refinement_suggestions=[],
)

MOCK_REFUTED = AgentValidationOutput(
    decision=ValidationDecisionEnum.refuted,
    confidence=0.85,
    reasoning="Criterion failed.",
    criterion_results=[
        CriterionResult(name="acoustic_contrast", measured=12.0, target=15.0,
                        operator=">=", passed=False, unit="dB"),
    ],
    refinement_suggestions=["Increase speaker count"],
)


def _create_goal(client):
    return client.post("/co-scientist/goals", json=GOAL_PAYLOAD).json()


def _seed_evidence(db, workspace_id, method_family="beamforming"):
    now = datetime.now(timezone.utc)
    for _ in range(2):
        rec = EvidenceRecord(
            id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            scout_run_id="sr-test",
            query_text="test query",
            paper_id=f"paper-{uuid.uuid4().hex[:8]}",
            title="Test Paper",
            chunk_id=f"chunk-{uuid.uuid4().hex[:8]}",
            chunk_index=0,
            chunk_text="Acoustic contrast control for personal sound zones.",
            score=0.9,
            method_families=json.dumps([method_family]),
            metric_names=json.dumps([]),
            hardware_assumptions=json.dumps([]),
            failure_modes=json.dumps([]),
            is_primary_method=True,
            evidence_strength="strong",
            created_at=now,
        )
        db.add(rec)
    db.commit()


def _create_scored_approach(client, db_session, goal_id, method_family="beamforming"):
    _seed_evidence(db_session, goal_id, method_family)
    client.post(f"/co-scientist/goals/{goal_id}/approaches/generate",
                json={"method_families": [method_family]})
    approaches = client.get(f"/co-scientist/goals/{goal_id}/approaches").json()["items"]
    approach = next(a for a in approaches if a["method_family"] == method_family)
    client.post(f"/co-scientist/goals/{goal_id}/approaches/{approach['id']}/transition",
                json={"status": "reviewed"})
    client.post(f"/co-scientist/goals/{goal_id}/approaches/{approach['id']}/score", json={})
    return approach


def _create_running_experiment(client, goal_id, approach_id):
    exp = client.post(f"/co-scientist/goals/{goal_id}/experiments", json={
        "name": "Test Experiment",
        "objective": "Evaluate method",
        "hypothesis_text": "Method achieves target",
        "approach_ids": [approach_id],
    }).json()
    for status in ["reviewed", "approved", "running"]:
        client.post(f"/co-scientist/goals/{goal_id}/experiments/{exp['id']}/transition",
                    json={"status": status})
    return exp


def test_post_results_returns_201(client, db_session):
    with patch("coscientist.services.validation._run_validation_agent",
               return_value=MOCK_VALIDATED):
        goal = _create_goal(client)
        approach = _create_scored_approach(client, db_session, goal["id"])
        client.post(
            f"/co-scientist/goals/{goal['id']}/approaches/{approach['id']}/transition",
            json={"status": "experiment_proposed"},
        )
        exp = _create_running_experiment(client, goal["id"], approach["id"])
        resp = client.post(
            f"/co-scientist/goals/{goal['id']}/experiments/{exp['id']}/results",
            json={"measured_metrics": {"acoustic_contrast": 18.5, "latency": 8.2}},
        )
    assert resp.status_code == 201
    assert resp.json()["decision"] == "validated"


def test_post_results_experiment_not_found_returns_404(client):
    goal = _create_goal(client)
    with patch("coscientist.services.validation._run_validation_agent",
               return_value=MOCK_VALIDATED):
        resp = client.post(
            f"/co-scientist/goals/{goal['id']}/experiments/nonexistent/results",
            json={"measured_metrics": {}},
        )
    assert resp.status_code == 404


def test_post_results_wrong_goal_returns_404(client, db_session):
    with patch("coscientist.services.validation._run_validation_agent",
               return_value=MOCK_VALIDATED):
        goal = _create_goal(client)
        approach = _create_scored_approach(client, db_session, goal["id"])
        client.post(
            f"/co-scientist/goals/{goal['id']}/approaches/{approach['id']}/transition",
            json={"status": "experiment_proposed"},
        )
        exp = _create_running_experiment(client, goal["id"], approach["id"])
        resp = client.post(
            f"/co-scientist/goals/wrong-goal/experiments/{exp['id']}/results",
            json={"measured_metrics": {}},
        )
    assert resp.status_code == 404


def test_post_results_not_running_returns_409(client, db_session):
    goal = _create_goal(client)
    approach = _create_scored_approach(client, db_session, goal["id"])
    exp = client.post(f"/co-scientist/goals/{goal['id']}/experiments", json={
        "name": "Not Running",
        "objective": "Test",
        "hypothesis_text": "Hypothesis",
        "approach_ids": [approach["id"]],
    }).json()
    resp = client.post(
        f"/co-scientist/goals/{goal['id']}/experiments/{exp['id']}/results",
        json={"measured_metrics": {}},
    )
    assert resp.status_code == 409


def test_get_result_returns_200(client, db_session):
    with patch("coscientist.services.validation._run_validation_agent",
               return_value=MOCK_VALIDATED):
        goal = _create_goal(client)
        approach = _create_scored_approach(client, db_session, goal["id"])
        client.post(
            f"/co-scientist/goals/{goal['id']}/approaches/{approach['id']}/transition",
            json={"status": "experiment_proposed"},
        )
        exp = _create_running_experiment(client, goal["id"], approach["id"])
        client.post(
            f"/co-scientist/goals/{goal['id']}/experiments/{exp['id']}/results",
            json={"measured_metrics": {"acoustic_contrast": 18.5}},
        )
        resp = client.get(
            f"/co-scientist/goals/{goal['id']}/experiments/{exp['id']}/results"
        )
    assert resp.status_code == 200
    assert resp.json()["decision"] == "validated"


def test_get_result_not_found_returns_404(client, db_session):
    goal = _create_goal(client)
    approach = _create_scored_approach(client, db_session, goal["id"])
    client.post(
        f"/co-scientist/goals/{goal['id']}/approaches/{approach['id']}/transition",
        json={"status": "experiment_proposed"},
    )
    exp = _create_running_experiment(client, goal["id"], approach["id"])
    resp = client.get(
        f"/co-scientist/goals/{goal['id']}/experiments/{exp['id']}/results"
    )
    assert resp.status_code == 404


def test_get_results_list_returns_200(client, db_session):
    with patch("coscientist.services.validation._run_validation_agent",
               return_value=MOCK_VALIDATED):
        goal = _create_goal(client)
        approach = _create_scored_approach(client, db_session, goal["id"])
        client.post(
            f"/co-scientist/goals/{goal['id']}/approaches/{approach['id']}/transition",
            json={"status": "experiment_proposed"},
        )
        exp = _create_running_experiment(client, goal["id"], approach["id"])
        client.post(
            f"/co-scientist/goals/{goal['id']}/experiments/{exp['id']}/results",
            json={"measured_metrics": {"acoustic_contrast": 18.5}},
        )
        resp = client.get(f"/co-scientist/goals/{goal['id']}/experiments/results")
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


def test_get_results_list_empty_returns_200(client):
    goal = _create_goal(client)
    resp = client.get(f"/co-scientist/goals/{goal['id']}/experiments/results")
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


def test_post_results_experiment_transitions_to_completed(client, db_session):
    with patch("coscientist.services.validation._run_validation_agent",
               return_value=MOCK_VALIDATED):
        goal = _create_goal(client)
        approach = _create_scored_approach(client, db_session, goal["id"])
        client.post(
            f"/co-scientist/goals/{goal['id']}/approaches/{approach['id']}/transition",
            json={"status": "experiment_proposed"},
        )
        exp = _create_running_experiment(client, goal["id"], approach["id"])
        client.post(
            f"/co-scientist/goals/{goal['id']}/experiments/{exp['id']}/results",
            json={"measured_metrics": {}},
        )
    updated = client.get(
        f"/co-scientist/goals/{goal['id']}/experiments/{exp['id']}"
    ).json()
    assert updated["status"] == "completed"


def test_post_results_approach_transitions_to_validated(client, db_session):
    with patch("coscientist.services.validation._run_validation_agent",
               return_value=MOCK_VALIDATED):
        goal = _create_goal(client)
        approach = _create_scored_approach(client, db_session, goal["id"])
        client.post(
            f"/co-scientist/goals/{goal['id']}/approaches/{approach['id']}/transition",
            json={"status": "experiment_proposed"},
        )
        exp = _create_running_experiment(client, goal["id"], approach["id"])
        client.post(
            f"/co-scientist/goals/{goal['id']}/experiments/{exp['id']}/results",
            json={"measured_metrics": {}},
        )
    updated = client.get(
        f"/co-scientist/goals/{goal['id']}/approaches/{approach['id']}"
    ).json()
    assert updated["status"] == "validated"
