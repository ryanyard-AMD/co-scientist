import json
import uuid
from datetime import datetime, timezone

import pytest

from conftest import GOAL_PAYLOAD
from coscientist.models.evidence import EvidenceRecord


def _create_goal(client):
    return client.post("/co-scientist/goals", json=GOAL_PAYLOAD).json()


def _seed_evidence(db, workspace_id, method_families, metric_names=None,
                   hardware=None, failure_modes=None, strength="strong"):
    now = datetime.now(timezone.utc)
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
        method_families=json.dumps(method_families),
        metric_names=json.dumps(metric_names or []),
        hardware_assumptions=json.dumps(hardware or []),
        failure_modes=json.dumps(failure_modes or []),
        is_primary_method=True,
        evidence_strength=strength,
        created_at=now,
    )
    db.add(rec)
    db.commit()
    return rec


def _create_scored_approach(client, db_session, goal_id, method_family,
                             hardware=None, strength="strong"):
    _seed_evidence(db_session, goal_id, [method_family], hardware=hardware, strength=strength)
    _seed_evidence(db_session, goal_id, [method_family], strength=strength)
    client.post(f"/co-scientist/goals/{goal_id}/approaches/generate",
                json={"method_families": [method_family]})

    approaches = client.get(f"/co-scientist/goals/{goal_id}/approaches").json()["items"]
    approach = next(a for a in approaches if a["method_family"] == method_family)

    client.post(
        f"/co-scientist/goals/{goal_id}/approaches/{approach['id']}/transition",
        json={"status": "reviewed"},
    )
    client.post(
        f"/co-scientist/goals/{goal_id}/approaches/{approach['id']}/score",
        json={},
    )
    return approach


def _create_experiment(client, goal_id, approach_ids):
    return client.post(f"/co-scientist/goals/{goal_id}/experiments", json={
        "name": "Test Experiment",
        "objective": "Evaluate method",
        "hypothesis_text": "Method will achieve target performance",
        "approach_ids": approach_ids,
        "baseline_methods": ["delay_and_sum_beamforming"],
        "independent_variables": {"speaker_count": [4, 8]},
        "metrics": ["acoustic_contrast_db"],
    }).json()


def test_generate_experiments_returns_201(client, db_session):
    goal = _create_goal(client)
    _create_scored_approach(client, db_session, goal["id"], "beamforming")
    resp = client.post(f"/co-scientist/goals/{goal['id']}/experiments/generate", json={})
    assert resp.status_code == 201
    body = resp.json()
    assert body["experiments_created"] >= 1


def test_generate_goal_not_found(client):
    resp = client.post("/co-scientist/goals/nonexistent/experiments/generate", json={})
    assert resp.status_code == 404


def test_create_experiment_returns_201(client, db_session):
    goal = _create_goal(client)
    a1 = _create_scored_approach(client, db_session, goal["id"], "beamforming")
    resp = client.post(f"/co-scientist/goals/{goal['id']}/experiments", json={
        "name": "Test",
        "objective": "Test objective",
        "hypothesis_text": "Test hypothesis",
        "approach_ids": [a1["id"]],
    })
    assert resp.status_code == 201
    assert resp.json()["status"] == "generated"


def test_list_experiments(client, db_session):
    goal = _create_goal(client)
    a1 = _create_scored_approach(client, db_session, goal["id"], "beamforming")
    _create_experiment(client, goal["id"], [a1["id"]])
    resp = client.get(f"/co-scientist/goals/{goal['id']}/experiments")
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


def test_get_experiment(client, db_session):
    goal = _create_goal(client)
    a1 = _create_scored_approach(client, db_session, goal["id"], "beamforming")
    created = _create_experiment(client, goal["id"], [a1["id"]])
    resp = client.get(f"/co-scientist/goals/{goal['id']}/experiments/{created['id']}")
    assert resp.status_code == 200
    assert resp.json()["id"] == created["id"]


def test_get_experiment_not_found(client):
    goal = _create_goal(client)
    resp = client.get(f"/co-scientist/goals/{goal['id']}/experiments/nonexistent")
    assert resp.status_code == 404


def test_update_experiment(client, db_session):
    goal = _create_goal(client)
    a1 = _create_scored_approach(client, db_session, goal["id"], "beamforming")
    created = _create_experiment(client, goal["id"], [a1["id"]])
    resp = client.patch(
        f"/co-scientist/goals/{goal['id']}/experiments/{created['id']}",
        json={"name": "Updated Experiment"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Updated Experiment"


def test_transition_experiment(client, db_session):
    goal = _create_goal(client)
    a1 = _create_scored_approach(client, db_session, goal["id"], "beamforming")
    created = _create_experiment(client, goal["id"], [a1["id"]])
    resp = client.post(
        f"/co-scientist/goals/{goal['id']}/experiments/{created['id']}/transition",
        json={"status": "reviewed"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "reviewed"


def test_delete_experiment_returns_204(client, db_session):
    goal = _create_goal(client)
    a1 = _create_scored_approach(client, db_session, goal["id"], "beamforming")
    created = _create_experiment(client, goal["id"], [a1["id"]])
    resp = client.delete(f"/co-scientist/goals/{goal['id']}/experiments/{created['id']}")
    assert resp.status_code == 204


def test_delete_non_generated_returns_409(client, db_session):
    goal = _create_goal(client)
    a1 = _create_scored_approach(client, db_session, goal["id"], "beamforming")
    created = _create_experiment(client, goal["id"], [a1["id"]])
    client.post(
        f"/co-scientist/goals/{goal['id']}/experiments/{created['id']}/transition",
        json={"status": "reviewed"},
    )
    resp = client.delete(f"/co-scientist/goals/{goal['id']}/experiments/{created['id']}")
    assert resp.status_code == 409


def test_export_experiment_yaml(client, db_session):
    goal = _create_goal(client)
    a1 = _create_scored_approach(client, db_session, goal["id"], "beamforming")
    created = _create_experiment(client, goal["id"], [a1["id"]])
    resp = client.get(f"/co-scientist/goals/{goal['id']}/experiments/{created['id']}/export?format=yaml")
    assert resp.status_code == 200
    assert resp.json()["format"] == "yaml"
    assert "experiment_card" in resp.json()["content"]


def test_export_experiment_python(client, db_session):
    goal = _create_goal(client)
    a1 = _create_scored_approach(client, db_session, goal["id"], "beamforming")
    created = _create_experiment(client, goal["id"], [a1["id"]])
    resp = client.get(f"/co-scientist/goals/{goal['id']}/experiments/{created['id']}/export?format=python")
    assert resp.status_code == 200
    assert resp.json()["format"] == "python"


def test_score_experiment(client, db_session):
    goal = _create_goal(client)
    a1 = _create_scored_approach(client, db_session, goal["id"], "beamforming")
    created = _create_experiment(client, goal["id"], [a1["id"]])
    resp = client.post(f"/co-scientist/goals/{goal['id']}/experiments/{created['id']}/score")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["dimensions"]) == 10
    assert body["total_score"] > 0


def test_run_request_preview_endpoint(client, db_session):
    goal = _create_goal(client)
    a1 = _create_scored_approach(client, db_session, goal["id"], "beamforming")
    created = _create_experiment(client, goal["id"], [a1["id"]])
    resp = client.get(
        f"/co-scientist/goals/{goal['id']}/experiments/{created['id']}/run-request-preview"
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["experiment_id"] == created["id"]
    assert body["expanded_run_count"] >= 1
    assert "approval_implication" in body


def test_execution_status_endpoint(client, db_session):
    goal = _create_goal(client)
    a1 = _create_scored_approach(client, db_session, goal["id"], "beamforming")
    created = _create_experiment(client, goal["id"], [a1["id"]])
    resp = client.post(
        f"/co-scientist/goals/{goal['id']}/experiments/{created['id']}/execution-status",
        json={"execution_status": "submitted"},
    )
    assert resp.status_code == 200
    assert resp.json()["execution_status"] == "submitted"
    # response exposes the handoff block
    assert resp.json()["execution_handoff"]["handoff_status"] == "not_submitted"


def test_execution_status_invalid_transition(client, db_session):
    goal = _create_goal(client)
    a1 = _create_scored_approach(client, db_session, goal["id"], "beamforming")
    created = _create_experiment(client, goal["id"], [a1["id"]])
    resp = client.post(
        f"/co-scientist/goals/{goal['id']}/experiments/{created['id']}/execution-status",
        json={"execution_status": "completed"},
    )
    assert resp.status_code == 422
