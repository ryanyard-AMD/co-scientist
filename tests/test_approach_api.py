import json
import uuid
from datetime import datetime, timezone

import pytest

from conftest import GOAL_PAYLOAD
from coscientist.models.evidence import EvidenceRecord


def _create_goal(client):
    return client.post("/co-scientist/goals", json=GOAL_PAYLOAD).json()


def _seed_evidence(db, workspace_id, method_families, metric_names=None,
                   hardware=None, failure_modes=None):
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
        chunk_text="Acoustic contrast control optimizes loudspeaker signals for personal sound zones.",
        score=0.9,
        method_families=json.dumps(method_families),
        metric_names=json.dumps(metric_names or []),
        hardware_assumptions=json.dumps(hardware or []),
        failure_modes=json.dumps(failure_modes or []),
        is_primary_method=True,
        evidence_strength="weak",
        created_at=now,
    )
    db.add(rec)
    db.commit()
    return rec


def test_generate_approaches_returns_201(client, db_session):
    goal = _create_goal(client)
    _seed_evidence(db_session, goal["id"], ["beamforming"])
    _seed_evidence(db_session, goal["id"], ["beamforming"])

    resp = client.post(f"/co-scientist/goals/{goal['id']}/approaches/generate", json={})
    assert resp.status_code == 201
    body = resp.json()
    assert body["approaches_created"] == 1
    assert body["approaches"][0]["method_family"] == "beamforming"


def test_generate_goal_not_found(client):
    resp = client.post("/co-scientist/goals/nonexistent/approaches/generate", json={})
    assert resp.status_code == 404


def test_create_approach_returns_201(client):
    goal = _create_goal(client)
    resp = client.post(f"/co-scientist/goals/{goal['id']}/approaches", json={
        "name": "Beamforming",
        "method_family": "beamforming",
    })
    assert resp.status_code == 201
    assert resp.json()["name"] == "Beamforming"
    assert resp.json()["status"] == "generated"


def test_list_approaches_empty(client):
    goal = _create_goal(client)
    resp = client.get(f"/co-scientist/goals/{goal['id']}/approaches")
    assert resp.status_code == 200
    assert resp.json() == {"items": [], "total": 0}


def test_list_approaches_after_generate(client, db_session):
    goal = _create_goal(client)
    _seed_evidence(db_session, goal["id"], ["beamforming"])
    _seed_evidence(db_session, goal["id"], ["beamforming"])
    client.post(f"/co-scientist/goals/{goal['id']}/approaches/generate", json={})

    resp = client.get(f"/co-scientist/goals/{goal['id']}/approaches")
    assert resp.json()["total"] == 1


def test_list_approaches_filter_status(client, db_session):
    goal = _create_goal(client)
    _seed_evidence(db_session, goal["id"], ["beamforming"])
    _seed_evidence(db_session, goal["id"], ["beamforming"])
    client.post(f"/co-scientist/goals/{goal['id']}/approaches/generate", json={})

    resp = client.get(f"/co-scientist/goals/{goal['id']}/approaches?status=generated")
    assert resp.json()["total"] == 1
    resp = client.get(f"/co-scientist/goals/{goal['id']}/approaches?status=reviewed")
    assert resp.json()["total"] == 0


def test_get_approach_by_id(client):
    goal = _create_goal(client)
    created = client.post(f"/co-scientist/goals/{goal['id']}/approaches", json={
        "name": "BF", "method_family": "beamforming",
    }).json()
    resp = client.get(f"/co-scientist/goals/{goal['id']}/approaches/{created['id']}")
    assert resp.status_code == 200
    assert resp.json()["id"] == created["id"]


def test_get_approach_not_found(client):
    goal = _create_goal(client)
    resp = client.get(f"/co-scientist/goals/{goal['id']}/approaches/nonexistent")
    assert resp.status_code == 404


def test_patch_approach(client):
    goal = _create_goal(client)
    created = client.post(f"/co-scientist/goals/{goal['id']}/approaches", json={
        "name": "BF", "method_family": "beamforming",
    }).json()
    resp = client.patch(
        f"/co-scientist/goals/{goal['id']}/approaches/{created['id']}",
        json={"name": "Updated BF", "unresolved_questions": ["How robust?"]},
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Updated BF"
    assert resp.json()["unresolved_questions"] == ["How robust?"]


def test_transition_approach_status(client):
    goal = _create_goal(client)
    created = client.post(f"/co-scientist/goals/{goal['id']}/approaches", json={
        "name": "BF", "method_family": "beamforming",
    }).json()
    resp = client.post(
        f"/co-scientist/goals/{goal['id']}/approaches/{created['id']}/transition",
        json={"status": "reviewed"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "reviewed"


def test_transition_invalid_status_422(client):
    goal = _create_goal(client)
    created = client.post(f"/co-scientist/goals/{goal['id']}/approaches", json={
        "name": "BF", "method_family": "beamforming",
    }).json()
    resp = client.post(
        f"/co-scientist/goals/{goal['id']}/approaches/{created['id']}/transition",
        json={"status": "validated"},
    )
    assert resp.status_code == 422


def test_delete_generated_approach_204(client):
    goal = _create_goal(client)
    created = client.post(f"/co-scientist/goals/{goal['id']}/approaches", json={
        "name": "BF", "method_family": "beamforming",
    }).json()
    resp = client.delete(f"/co-scientist/goals/{goal['id']}/approaches/{created['id']}")
    assert resp.status_code == 204


def test_delete_non_generated_approach_409(client):
    goal = _create_goal(client)
    created = client.post(f"/co-scientist/goals/{goal['id']}/approaches", json={
        "name": "BF", "method_family": "beamforming",
    }).json()
    client.post(
        f"/co-scientist/goals/{goal['id']}/approaches/{created['id']}/transition",
        json={"status": "reviewed"},
    )
    resp = client.delete(f"/co-scientist/goals/{goal['id']}/approaches/{created['id']}")
    assert resp.status_code == 409


def test_merge_approaches(client):
    goal = _create_goal(client)
    a1 = client.post(f"/co-scientist/goals/{goal['id']}/approaches", json={
        "name": "BF1", "method_family": "beamforming",
        "hardware_requirements": ["loudspeaker_array"],
    }).json()
    a2 = client.post(f"/co-scientist/goals/{goal['id']}/approaches", json={
        "name": "BF2", "method_family": "beamforming",
        "hardware_requirements": ["microphone_array"],
    }).json()
    resp = client.post(f"/co-scientist/goals/{goal['id']}/approaches/merge", json={
        "source_approach_id": a1["id"],
        "target_approach_id": a2["id"],
    })
    assert resp.status_code == 200
    merged = resp.json()
    assert "loudspeaker_array" in merged["hardware_requirements"]
    assert "microphone_array" in merged["hardware_requirements"]


def test_find_duplicates(client):
    goal = _create_goal(client)
    client.post(f"/co-scientist/goals/{goal['id']}/approaches", json={
        "name": "BF1", "method_family": "beamforming",
    })
    client.post(f"/co-scientist/goals/{goal['id']}/approaches", json={
        "name": "BF2", "method_family": "beamforming",
    })
    resp = client.get(f"/co-scientist/goals/{goal['id']}/approaches/duplicates")
    assert resp.status_code == 200
    assert len(resp.json()) == 2
