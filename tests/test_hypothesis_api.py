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


def test_generate_hypotheses_returns_201(client, db_session):
    goal = _create_goal(client)
    _create_scored_approach(client, db_session, goal["id"], "beamforming",
                           hardware=["loudspeaker_array"])
    _create_scored_approach(client, db_session, goal["id"], "pressure_matching",
                           hardware=["loudspeaker_array"])

    resp = client.post(f"/co-scientist/goals/{goal['id']}/hypotheses/generate", json={})
    assert resp.status_code == 201
    body = resp.json()
    assert body["hypotheses_created"] >= 1
    assert len(body["hypotheses"]) >= 1


def test_generate_insufficient_approaches(client, db_session):
    goal = _create_goal(client)
    _create_scored_approach(client, db_session, goal["id"], "beamforming")

    resp = client.post(f"/co-scientist/goals/{goal['id']}/hypotheses/generate", json={})
    assert resp.status_code == 201
    assert resp.json()["hypotheses_created"] == 0


def test_create_hypothesis_returns_201(client, db_session):
    goal = _create_goal(client)
    a1 = _create_scored_approach(client, db_session, goal["id"], "beamforming")
    a2 = _create_scored_approach(client, db_session, goal["id"], "pressure_matching")

    resp = client.post(f"/co-scientist/goals/{goal['id']}/hypotheses", json={
        "name": "BF + PM",
        "text": "Combine beamforming and pressure matching",
        "rationale": "Complementary strengths",
        "approach_ids": [a1["id"], a2["id"]],
    })
    assert resp.status_code == 201
    assert resp.json()["name"] == "BF + PM"
    assert resp.json()["status"] == "generated"


def test_list_hypotheses(client, db_session):
    goal = _create_goal(client)
    a1 = _create_scored_approach(client, db_session, goal["id"], "beamforming")
    a2 = _create_scored_approach(client, db_session, goal["id"], "pressure_matching")

    client.post(f"/co-scientist/goals/{goal['id']}/hypotheses", json={
        "name": "H1", "text": "t", "rationale": "r",
        "approach_ids": [a1["id"], a2["id"]],
    })
    resp = client.get(f"/co-scientist/goals/{goal['id']}/hypotheses")
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


def test_get_hypothesis(client, db_session):
    goal = _create_goal(client)
    a1 = _create_scored_approach(client, db_session, goal["id"], "beamforming")
    a2 = _create_scored_approach(client, db_session, goal["id"], "pressure_matching")
    created = client.post(f"/co-scientist/goals/{goal['id']}/hypotheses", json={
        "name": "H1", "text": "t", "rationale": "r",
        "approach_ids": [a1["id"], a2["id"]],
    }).json()

    resp = client.get(f"/co-scientist/goals/{goal['id']}/hypotheses/{created['id']}")
    assert resp.status_code == 200
    assert resp.json()["id"] == created["id"]


def test_get_hypothesis_not_found(client):
    goal = _create_goal(client)
    resp = client.get(f"/co-scientist/goals/{goal['id']}/hypotheses/nonexistent")
    assert resp.status_code == 404


def test_update_hypothesis(client, db_session):
    goal = _create_goal(client)
    a1 = _create_scored_approach(client, db_session, goal["id"], "beamforming")
    a2 = _create_scored_approach(client, db_session, goal["id"], "pressure_matching")
    created = client.post(f"/co-scientist/goals/{goal['id']}/hypotheses", json={
        "name": "H1", "text": "t", "rationale": "r",
        "approach_ids": [a1["id"], a2["id"]],
    }).json()

    resp = client.patch(
        f"/co-scientist/goals/{goal['id']}/hypotheses/{created['id']}",
        json={"name": "Updated H1"},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Updated H1"


def test_transition_hypothesis(client, db_session):
    goal = _create_goal(client)
    a1 = _create_scored_approach(client, db_session, goal["id"], "beamforming")
    a2 = _create_scored_approach(client, db_session, goal["id"], "pressure_matching")
    created = client.post(f"/co-scientist/goals/{goal['id']}/hypotheses", json={
        "name": "H1", "text": "t", "rationale": "r",
        "approach_ids": [a1["id"], a2["id"]],
    }).json()

    resp = client.post(
        f"/co-scientist/goals/{goal['id']}/hypotheses/{created['id']}/transition",
        json={"status": "reviewed"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "reviewed"


def test_delete_hypothesis_returns_204(client, db_session):
    goal = _create_goal(client)
    a1 = _create_scored_approach(client, db_session, goal["id"], "beamforming")
    a2 = _create_scored_approach(client, db_session, goal["id"], "pressure_matching")
    created = client.post(f"/co-scientist/goals/{goal['id']}/hypotheses", json={
        "name": "H1", "text": "t", "rationale": "r",
        "approach_ids": [a1["id"], a2["id"]],
    }).json()

    resp = client.delete(f"/co-scientist/goals/{goal['id']}/hypotheses/{created['id']}")
    assert resp.status_code == 204


def test_delete_non_generated_returns_409(client, db_session):
    goal = _create_goal(client)
    a1 = _create_scored_approach(client, db_session, goal["id"], "beamforming")
    a2 = _create_scored_approach(client, db_session, goal["id"], "pressure_matching")
    created = client.post(f"/co-scientist/goals/{goal['id']}/hypotheses", json={
        "name": "H1", "text": "t", "rationale": "r",
        "approach_ids": [a1["id"], a2["id"]],
    }).json()
    client.post(
        f"/co-scientist/goals/{goal['id']}/hypotheses/{created['id']}/transition",
        json={"status": "reviewed"},
    )

    resp = client.delete(f"/co-scientist/goals/{goal['id']}/hypotheses/{created['id']}")
    assert resp.status_code == 409


def test_hypothesis_goal_not_found(client):
    resp = client.post("/co-scientist/goals/nonexistent/hypotheses/generate", json={})
    assert resp.status_code == 404
