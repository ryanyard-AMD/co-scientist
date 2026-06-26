import json
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from conftest import GOAL_PAYLOAD
from coscientist.models.governance import AgentActionLog
from coscientist.schemas.roadmap import AgentRoadmapItem, RoadmapLaneEnum


def _create_goal(client, is_restricted=False):
    payload = {**GOAL_PAYLOAD, "is_restricted": is_restricted}
    return client.post("/co-scientist/goals", json=payload).json()


def _seed_log(db, workspace_id, service="validation"):
    now = datetime.now(timezone.utc)
    log = AgentActionLog(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        service=service,
        action="validate_experiment",
        model_used="claude-sonnet-4-6",
        prompt_tokens=512,
        completion_tokens=128,
        elapsed_ms=1200,
        response_summary='{"decision": "validated"}',
        error=None,
        created_at=now,
    )
    db.add(log)
    db.flush()
    return log


MOCK_ROADMAP_ITEMS = [
    AgentRoadmapItem(
        title="Run simulation baseline",
        description="Simulate beamforming baseline.",
        lane=RoadmapLaneEnum.conservative,
        priority_score=0.9,
        rationale="Lowest cost path.",
        estimated_cost="low",
        estimated_information_gain="high",
        source_approach_ids=[],
        source_experiment_id=None,
        source_device_id=None,
    ),
]


# --- GET /agent-logs ---


def test_list_logs_empty_returns_200(client, db_session):
    goal = _create_goal(client)
    resp = client.get(f"/co-scientist/goals/{goal['id']}/agent-logs")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 0
    assert body["items"] == []


def test_list_logs_with_seeded_logs_returns_200(client, db_session):
    goal = _create_goal(client)
    _seed_log(db_session, goal["id"], service="validation")
    _seed_log(db_session, goal["id"], service="roadmap")
    db_session.commit()
    resp = client.get(f"/co-scientist/goals/{goal['id']}/agent-logs")
    assert resp.status_code == 200
    assert resp.json()["total"] == 2


def test_list_logs_service_filter(client, db_session):
    goal = _create_goal(client)
    _seed_log(db_session, goal["id"], service="validation")
    _seed_log(db_session, goal["id"], service="roadmap")
    db_session.commit()
    resp = client.get(f"/co-scientist/goals/{goal['id']}/agent-logs?service=validation")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["service"] == "validation"


# --- GET /agent-logs/{log_id} ---


def test_get_log_returns_200(client, db_session):
    goal = _create_goal(client)
    log = _seed_log(db_session, goal["id"])
    db_session.commit()
    resp = client.get(f"/co-scientist/goals/{goal['id']}/agent-logs/{log.id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == log.id


def test_get_log_wrong_goal_returns_404(client, db_session):
    goal = _create_goal(client)
    log = _seed_log(db_session, goal["id"])
    db_session.commit()
    resp = client.get(f"/co-scientist/goals/wrong-goal-id/agent-logs/{log.id}")
    assert resp.status_code == 404


# --- PATCH /goals/{id} with is_restricted ---


def test_patch_goal_set_is_restricted_true(client):
    goal = _create_goal(client)
    resp = client.patch(f"/co-scientist/goals/{goal['id']}", json={"is_restricted": True})
    assert resp.status_code == 200
    assert resp.json()["is_restricted"] is True


def test_patch_goal_clear_is_restricted(client):
    goal = _create_goal(client, is_restricted=True)
    resp = client.patch(f"/co-scientist/goals/{goal['id']}", json={"is_restricted": False})
    assert resp.status_code == 200
    assert resp.json()["is_restricted"] is False


# --- Restriction integration ---


def test_restricted_goal_blocks_roadmap_generate(client, db_session):
    from coscientist.models.approach import ApproachCard
    goal = _create_goal(client, is_restricted=True)

    now = datetime.now(timezone.utc)
    approach = ApproachCard(
        id=str(uuid.uuid4()),
        workspace_id=goal["id"],
        name="Beamforming Baseline",
        method_family="beamforming",
        maturity="theoretical",
        status="reviewed",
        evidence_links=json.dumps([]),
        hardware_requirements=json.dumps([]),
        risks_and_limitations=json.dumps([]),
        device_relevance="Form factor: headphone",
        generation_run_id="run-test",
        created_at=now,
        updated_at=now,
    )
    db_session.add(approach)
    db_session.commit()

    with patch("coscientist.services.roadmap._run_roadmap_agent", return_value=MOCK_ROADMAP_ITEMS):
        resp = client.post(f"/co-scientist/goals/{goal['id']}/roadmap/generate", json={})
    assert resp.status_code == 403
