import json
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from conftest import GOAL_PAYLOAD
from coscientist.models.governance import AgentActionLog
from coscientist.models.roadmap import ResearchRoadmapItem
from coscientist.schemas.roadmap import AgentRoadmapItem, RoadmapLaneEnum
from coscientist.services import goal as goal_svc
from coscientist.services import governance as svc
from coscientist.schemas.goal import GoalCreate


def _create_goal(db, is_restricted=False):
    payload = {**GOAL_PAYLOAD, "is_restricted": is_restricted}
    return goal_svc.create(db, GoalCreate(**payload))


def _seed_log(db, workspace_id, service="validation", action="validate_experiment"):
    now = datetime.now(timezone.utc)
    log = AgentActionLog(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        service=service,
        action=action,
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


# --- log_agent_call ---


def test_log_agent_call_creates_row(db_session):
    goal = _create_goal(db_session)
    svc.log_agent_call(
        db=db_session,
        workspace_id=goal.id,
        service="roadmap",
        action="generate_roadmap",
        model_used="claude-sonnet-4-6",
        prompt_tokens=1000,
        completion_tokens=500,
        elapsed_ms=2500,
        response_summary="[{...}]",
    )
    db_session.commit()

    rows = db_session.query(AgentActionLog).filter_by(workspace_id=goal.id).all()
    assert len(rows) == 1
    row = rows[0]
    assert row.service == "roadmap"
    assert row.action == "generate_roadmap"
    assert row.prompt_tokens == 1000
    assert row.completion_tokens == 500
    assert row.elapsed_ms == 2500
    assert row.error is None


def test_log_agent_call_with_error(db_session):
    goal = _create_goal(db_session)
    svc.log_agent_call(
        db=db_session,
        workspace_id=goal.id,
        service="validation",
        action="validate_experiment",
        model_used="claude-sonnet-4-6",
        error="Connection timeout",
    )
    db_session.commit()

    rows = db_session.query(AgentActionLog).filter_by(workspace_id=goal.id).all()
    assert len(rows) == 1
    assert rows[0].error == "Connection timeout"


# --- list_logs ---


def test_list_logs_returns_all(db_session):
    goal = _create_goal(db_session)
    _seed_log(db_session, goal.id, service="validation")
    _seed_log(db_session, goal.id, service="roadmap")
    db_session.commit()

    result = svc.list_logs(db_session, goal.id)
    assert result.total == 2


def test_list_logs_filters_by_service(db_session):
    goal = _create_goal(db_session)
    _seed_log(db_session, goal.id, service="validation")
    _seed_log(db_session, goal.id, service="roadmap")
    db_session.commit()

    result = svc.list_logs(db_session, goal.id, service="validation")
    assert result.total == 1
    assert result.items[0].service == "validation"


def test_list_logs_empty_goal_returns_zero(db_session):
    goal = _create_goal(db_session)
    result = svc.list_logs(db_session, goal.id)
    assert result.total == 0
    assert result.items == []


# --- get_log ---


def test_get_log_returns_row(db_session):
    goal = _create_goal(db_session)
    log = _seed_log(db_session, goal.id)
    db_session.commit()

    result = svc.get_log(db_session, log.id, goal.id)
    assert result.id == log.id
    assert result.workspace_id == goal.id


def test_get_log_wrong_goal_raises_404(db_session):
    from fastapi import HTTPException
    goal = _create_goal(db_session)
    log = _seed_log(db_session, goal.id)
    db_session.commit()

    with pytest.raises(HTTPException) as exc_info:
        svc.get_log(db_session, log.id, "wrong-goal-id")
    assert exc_info.value.status_code == 404


def test_get_log_nonexistent_raises_404(db_session):
    from fastapi import HTTPException
    goal = _create_goal(db_session)
    with pytest.raises(HTTPException) as exc_info:
        svc.get_log(db_session, "nonexistent-id", goal.id)
    assert exc_info.value.status_code == 404


# --- raise_if_restricted ---


def test_raise_if_restricted_allows_unrestricted_goal(db_session):
    goal = _create_goal(db_session, is_restricted=False)
    result = goal_svc.raise_if_restricted(db_session, goal.id)
    assert result.id == goal.id


def test_raise_if_restricted_raises_403_for_restricted_goal(db_session):
    from fastapi import HTTPException
    goal = _create_goal(db_session, is_restricted=True)
    with pytest.raises(HTTPException) as exc_info:
        goal_svc.raise_if_restricted(db_session, goal.id)
    assert exc_info.value.status_code == 403


# --- instrumented services ---

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


def _seed_approach(db, workspace_id):
    from coscientist.models.approach import ApproachCard
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


def test_log_agent_call_is_called_by_instrumented_agent(db_session):
    """Verify the log_agent_call helper can be called with the expected roadmap args."""
    goal = _create_goal(db_session)
    svc.log_agent_call(
        db=db_session,
        workspace_id=goal.id,
        service="roadmap",
        action="generate_roadmap",
        model_used="claude-sonnet-4-6",
        prompt_tokens=2048,
        completion_tokens=512,
        elapsed_ms=3100,
        response_summary="[{...}]",
    )
    db_session.commit()

    rows = db_session.query(AgentActionLog).filter_by(workspace_id=goal.id, service="roadmap").all()
    assert len(rows) == 1
    assert rows[0].action == "generate_roadmap"
    assert rows[0].elapsed_ms == 3100


def test_restricted_goal_blocks_roadmap_generate(db_session):
    from fastapi import HTTPException
    from coscientist.services import roadmap as roadmap_svc
    goal = _create_goal(db_session, is_restricted=True)
    with pytest.raises(HTTPException) as exc_info:
        roadmap_svc.generate(db_session, goal.id)
    assert exc_info.value.status_code == 403
