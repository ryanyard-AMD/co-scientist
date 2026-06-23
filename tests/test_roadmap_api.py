import json
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from conftest import GOAL_PAYLOAD
from coscientist.models.approach import ApproachCard
from coscientist.models.roadmap import ResearchRoadmapItem
from coscientist.schemas.roadmap import AgentRoadmapItem, RoadmapLaneEnum


MOCK_ITEMS = [
    AgentRoadmapItem(
        title="Run simulation baseline",
        description="Simulate beamforming baseline in headphone geometry.",
        lane=RoadmapLaneEnum.conservative,
        priority_score=0.9,
        rationale="Lowest cost path to fill evidence gap.",
        estimated_cost="low",
        estimated_information_gain="high",
        source_approach_ids=[],
    ),
    AgentRoadmapItem(
        title="Explore hybrid approach",
        description="Combine pressure matching with adaptive filter.",
        lane=RoadmapLaneEnum.exploratory,
        priority_score=0.6,
        rationale="Higher upside if validated.",
        estimated_cost="medium",
        estimated_information_gain="high",
        source_approach_ids=[],
    ),
]


def _create_goal(client):
    return client.post("/co-scientist/goals", json=GOAL_PAYLOAD).json()


def _seed_approach(db, workspace_id):
    now = datetime.now(timezone.utc)
    approach = ApproachCard(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
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
    db.add(approach)
    db.flush()
    return approach


def _seed_roadmap_item(db, workspace_id, status="open", lane="conservative", source_experiment_id=None):
    now = datetime.now(timezone.utc)
    item = ResearchRoadmapItem(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        title="Test roadmap item",
        description="Test description",
        lane=lane,
        status=status,
        priority_score=0.8,
        priority_rank=1,
        rationale="Test rationale",
        estimated_cost="low",
        estimated_information_gain="medium",
        source_approach_ids=json.dumps([]),
        source_experiment_id=source_experiment_id,
        source_device_id=None,
        generation_run_id=str(uuid.uuid4()),
        model_used="test-model",
        created_at=now,
        updated_at=now,
    )
    db.add(item)
    db.flush()
    return item


# --- POST /generate ---


def test_generate_returns_201(client, db_session):
    goal = _create_goal(client)
    _seed_approach(db_session, goal["id"])
    with patch("coscientist.services.roadmap._run_roadmap_agent", return_value=MOCK_ITEMS):
        resp = client.post(f"/co-scientist/goals/{goal['id']}/roadmap/generate", json={})
    assert resp.status_code == 201
    body = resp.json()
    assert body["total"] == 2
    assert len(body["items"]) == 2
    assert body["generation_run_id"] is not None


def test_generate_wrong_goal_returns_404(client):
    resp = client.post("/co-scientist/goals/nonexistent/roadmap/generate", json={})
    assert resp.status_code == 404


def test_generate_empty_returns_201_zero_items(client, db_session):
    goal = _create_goal(client)
    resp = client.post(f"/co-scientist/goals/{goal['id']}/roadmap/generate", json={})
    assert resp.status_code == 201
    assert resp.json()["total"] == 0


# --- GET / ---


def test_list_roadmap_returns_200(client, db_session):
    goal = _create_goal(client)
    _seed_roadmap_item(db_session, goal["id"])
    resp = client.get(f"/co-scientist/goals/{goal['id']}/roadmap")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1


def test_list_roadmap_empty_returns_200(client, db_session):
    goal = _create_goal(client)
    resp = client.get(f"/co-scientist/goals/{goal['id']}/roadmap")
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


def test_list_roadmap_lane_filter(client, db_session):
    goal = _create_goal(client)
    _seed_roadmap_item(db_session, goal["id"], lane="conservative")
    _seed_roadmap_item(db_session, goal["id"], lane="exploratory")
    resp = client.get(f"/co-scientist/goals/{goal['id']}/roadmap?lane=conservative")
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["lane"] == "conservative"


# --- GET /{item_id} ---


def test_get_roadmap_item_returns_200(client, db_session):
    goal = _create_goal(client)
    item = _seed_roadmap_item(db_session, goal["id"])
    resp = client.get(f"/co-scientist/goals/{goal['id']}/roadmap/{item.id}")
    assert resp.status_code == 200
    assert resp.json()["id"] == item.id


def test_get_roadmap_item_not_found_returns_404(client, db_session):
    goal = _create_goal(client)
    resp = client.get(f"/co-scientist/goals/{goal['id']}/roadmap/nonexistent-id")
    assert resp.status_code == 404


# --- POST /{item_id}/transition ---


def test_transition_item_returns_200(client, db_session):
    goal = _create_goal(client)
    item = _seed_roadmap_item(db_session, goal["id"], status="open")
    resp = client.post(
        f"/co-scientist/goals/{goal['id']}/roadmap/{item.id}/transition",
        json={"status": "completed"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"


def test_transition_invalid_returns_422(client, db_session):
    goal = _create_goal(client)
    item = _seed_roadmap_item(db_session, goal["id"], status="completed")
    resp = client.post(
        f"/co-scientist/goals/{goal['id']}/roadmap/{item.id}/transition",
        json={"status": "open"},
    )
    assert resp.status_code == 422


# --- Auto-retire integration ---


def test_experiment_completion_retires_roadmap_item(client, db_session):
    from coscientist.models.experiment import ExperimentCard
    from coscientist.schemas.roadmap import AgentRoadmapItem

    goal = _create_goal(client)
    now = datetime.now(timezone.utc)

    exp_id = str(uuid.uuid4())
    experiment = ExperimentCard(
        id=exp_id,
        workspace_id=goal["id"],
        name="Test Experiment",
        objective="Test objective",
        hypothesis_text="Test hypothesis",
        experiment_type="simulation",
        status="running",
        approach_ids=json.dumps([]),
        parameter_sweep_count=0,
        estimated_cost="low",
        generation_run_id="run-test",
        created_at=now,
        updated_at=now,
    )
    db_session.add(experiment)
    db_session.flush()

    item = _seed_roadmap_item(db_session, goal["id"], status="open", source_experiment_id=exp_id)
    db_session.commit()

    resp = client.post(
        f"/co-scientist/goals/{goal['id']}/experiments/{exp_id}/transition",
        json={"status": "completed"},
    )
    assert resp.status_code == 200

    db_session.refresh(item)
    assert item.status == "completed"
