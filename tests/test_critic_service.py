import json
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from conftest import GOAL_PAYLOAD
from coscientist.config import settings
from coscientist.models.evidence import EvidenceRecord
from coscientist.schemas.approach import ApproachGenerateRequest, ApproachStatusEnum
from coscientist.schemas.critic import (
    AgentCritiqueOutput,
    ApproachCritiqueRequest,
    CriticVerdictEnum,
)
from coscientist.schemas.goal import GoalCreate
from coscientist.services import approach as approach_svc
from coscientist.services import critic as critic_svc
from coscientist.services import goal as goal_svc


def _create_goal(db):
    return goal_svc.create(db, GoalCreate(**GOAL_PAYLOAD))


def _seed_evidence(db, workspace_id, method_families, text="beamforming method chunk", score=0.9):
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
        chunk_text=text,
        score=score,
        method_families=json.dumps(method_families),
        metric_names=json.dumps([]),
        hardware_assumptions=json.dumps([]),
        failure_modes=json.dumps([]),
        is_primary_method=True,
        evidence_strength="weak",
        created_at=now,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


def _generate_card(db, goal, method="beamforming"):
    _seed_evidence(db, goal.id, [method])
    _seed_evidence(db, goal.id, [method])
    result = approach_svc.generate_approaches(db, goal.id, ApproachGenerateRequest())
    return result.approaches[0]


def _fake_critique(verdict=CriticVerdictEnum.advance):
    def _inner(db, goal, card, evidence):
        real_id = evidence[0].id if evidence else "none"
        return AgentCritiqueOutput(
            verdict=verdict,
            summary=f"Critique of {card.name}.",
            grounding_issues=["one claim is unsupported"],
            device_fit_issues=[],
            maturity_issues=[],
            strengths=["clear mechanism"],
            cited_evidence_ids=[real_id, "invented-id"],
            confidence=0.8,
        )
    return _inner


def test_critique_persists_and_returns(db_session, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    goal = _create_goal(db_session)
    _generate_card(db_session, goal)
    with patch.object(critic_svc, "_run_critic_agent", side_effect=_fake_critique()):
        result = critic_svc.critique_approaches(db_session, goal.id, ApproachCritiqueRequest())
    assert result.critiqued_count == 1
    assert result.advance_count == 1
    fetched = critic_svc.get_critiques(db_session, goal.id)
    assert len(fetched) == 1
    assert fetched[0].summary.startswith("Critique of")


def test_critique_strips_invented_citations(db_session, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    goal = _create_goal(db_session)
    _generate_card(db_session, goal)
    with patch.object(critic_svc, "_run_critic_agent", side_effect=_fake_critique()):
        result = critic_svc.critique_approaches(db_session, goal.id, ApproachCritiqueRequest())
    assert "invented-id" not in result.critiques[0].cited_evidence_ids


def test_apply_false_does_not_transition(db_session, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    goal = _create_goal(db_session)
    card = _generate_card(db_session, goal)
    with patch.object(critic_svc, "_run_critic_agent", side_effect=_fake_critique()):
        result = critic_svc.critique_approaches(db_session, goal.id, ApproachCritiqueRequest(apply=False))
    assert result.applied_count == 0
    assert result.critiques[0].applied is False
    assert approach_svc.get(db_session, card.id).status == ApproachStatusEnum.generated


def test_apply_true_advance_transitions_to_reviewed(db_session, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    goal = _create_goal(db_session)
    card = _generate_card(db_session, goal)
    with patch.object(critic_svc, "_run_critic_agent", side_effect=_fake_critique(CriticVerdictEnum.advance)):
        result = critic_svc.critique_approaches(db_session, goal.id, ApproachCritiqueRequest(apply=True))
    assert result.applied_count == 1
    assert approach_svc.get(db_session, card.id).status == ApproachStatusEnum.reviewed


def test_apply_true_refute_transitions_to_refuted(db_session, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    goal = _create_goal(db_session)
    card = _generate_card(db_session, goal)
    with patch.object(critic_svc, "_run_critic_agent", side_effect=_fake_critique(CriticVerdictEnum.refute)):
        result = critic_svc.critique_approaches(db_session, goal.id, ApproachCritiqueRequest(apply=True))
    assert result.applied_count == 1
    assert approach_svc.get(db_session, card.id).status == ApproachStatusEnum.refuted


def test_apply_true_revise_does_not_transition(db_session, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    goal = _create_goal(db_session)
    card = _generate_card(db_session, goal)
    with patch.object(critic_svc, "_run_critic_agent", side_effect=_fake_critique(CriticVerdictEnum.revise)):
        result = critic_svc.critique_approaches(db_session, goal.id, ApproachCritiqueRequest(apply=True))
    assert result.applied_count == 0
    assert result.critiques[0].applied is False
    assert approach_svc.get(db_session, card.id).status == ApproachStatusEnum.generated


def test_critique_without_api_key_raises(db_session, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", None)
    goal = _create_goal(db_session)
    _generate_card(db_session, goal)
    with pytest.raises(HTTPException) as exc:
        critic_svc.critique_approaches(db_session, goal.id, ApproachCritiqueRequest())
    assert exc.value.status_code == 422


def test_critique_goal_not_found(db_session, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    with pytest.raises(HTTPException) as exc:
        critic_svc.critique_approaches(db_session, "nonexistent", ApproachCritiqueRequest())
    assert exc.value.status_code == 404


def test_critique_no_generated_cards_is_noop(db_session, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    goal = _create_goal(db_session)
    with patch.object(critic_svc, "_run_critic_agent", side_effect=_fake_critique()) as agent:
        result = critic_svc.critique_approaches(db_session, goal.id, ApproachCritiqueRequest())
    assert result.critiqued_count == 0
    assert agent.call_count == 0
