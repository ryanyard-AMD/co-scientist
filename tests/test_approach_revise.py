import json
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from conftest import GOAL_PAYLOAD
from coscientist.config import settings
from coscientist.models.approach import ApproachCard
from coscientist.models.evidence import EvidenceRecord
from coscientist.schemas.approach import (
    AgentRevisionOutput,
    ApproachGenerateRequest,
    ApproachMaturityEnum,
    ApproachReviseRequest,
    ApproachStatusEnum,
    ReportedMetric,
    RiskItem,
)
from coscientist.schemas.critic import AgentCritiqueOutput, ApproachCritiqueRequest, CriticVerdictEnum
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


def _critique(db, goal, verdict=CriticVerdictEnum.revise):
    """Create a real critique row (via the critic service with a stubbed agent)."""
    def _inner(db_, goal_, card_, evidence_):
        real_id = evidence_[0].id if evidence_ else "none"
        return AgentCritiqueOutput(
            verdict=verdict,
            summary="Device fit and grounding issues.",
            grounding_issues=["metric overclaimed"],
            device_fit_issues=["inherits generic loudspeaker array"],
            maturity_issues=["labeled validated but simulation only"],
            strengths=[],
            cited_evidence_ids=[real_id],
            confidence=0.7,
        )
    with patch.object(critic_svc, "_run_critic_agent", side_effect=_inner):
        critic_svc.critique_approaches(db, goal.id, ApproachCritiqueRequest())


def _fake_revision():
    def _inner(db, goal, card, critique, evidence):
        real_id = evidence[0].id if evidence else "none"
        return AgentRevisionOutput(
            name=card.name,
            problem_fit="Revised problem fit",
            mechanism_summary="Revised mechanism grounded in evidence",
            device_relevance="Maps onto the PAL ultrasonic element array",
            maturity=ApproachMaturityEnum.simulated,
            key_assumptions=["assumes steerable element array"],
            hardware_requirements=["ultrasonic transducer array"],
            unresolved_questions=["how does demodulation affect the ATF"],
            suggested_experiments=["bench contrast measurement"],
            reported_metrics=[
                ReportedMetric(metric_name="contrast", value="20", unit="dB", source_evidence_id=real_id),
            ],
            risks_and_limitations=[
                RiskItem(description="nonlinear distortion", failure_mode="distortion", evidence_id=real_id),
            ],
            cited_evidence_ids=[real_id, "invented-id"],
            revision_summary="Reframed hardware to the PAL; softened claims; maturity to simulated.",
        )
    return _inner


def _card_count(db, goal_id):
    return len(db.scalars(select(ApproachCard).where(ApproachCard.workspace_id == goal_id)).all())


def test_dry_run_persists_nothing(db_session, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    goal = _create_goal(db_session)
    card = _generate_card(db_session, goal)
    _critique(db_session, goal)
    before = _card_count(db_session, goal.id)

    with patch.object(approach_svc, "_run_revise_agent", side_effect=_fake_revision()):
        result = approach_svc.revise_approaches(db_session, goal.id, ApproachReviseRequest(apply=False))

    assert result.revised_count == 1
    assert result.applied_count == 0
    rev = result.revisions[0]
    assert rev.applied is False
    assert rev.revised_approach_id is None
    # Proposed card is returned but not persisted; still carries provenance.
    assert rev.revised_card is not None
    assert rev.revised_card.revised_from_id == card.id
    assert _card_count(db_session, goal.id) == before
    assert approach_svc.get(db_session, card.id).status == ApproachStatusEnum.generated


def test_apply_supersedes_and_creates_revision(db_session, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    goal = _create_goal(db_session)
    card = _generate_card(db_session, goal)
    _critique(db_session, goal)

    with patch.object(approach_svc, "_run_revise_agent", side_effect=_fake_revision()):
        result = approach_svc.revise_approaches(db_session, goal.id, ApproachReviseRequest(apply=True))

    assert result.applied_count == 1
    rev = result.revisions[0]
    assert rev.applied is True
    new_id = rev.revised_approach_id
    assert new_id is not None

    source = approach_svc.get(db_session, card.id)
    assert source.status == ApproachStatusEnum.superseded
    assert source.merged_into_id == new_id

    revised = approach_svc.get(db_session, new_id)
    assert revised.status == ApproachStatusEnum.generated
    assert revised.revised_from_id == card.id
    assert revised.maturity == ApproachMaturityEnum.simulated
    assert rev.maturity_after == "simulated"


def test_apply_strips_invented_citations(db_session, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    goal = _create_goal(db_session)
    _generate_card(db_session, goal)
    _critique(db_session, goal)

    with patch.object(approach_svc, "_run_revise_agent", side_effect=_fake_revision()):
        result = approach_svc.revise_approaches(db_session, goal.id, ApproachReviseRequest(apply=True))

    revised = approach_svc.get(db_session, result.revisions[0].revised_approach_id)
    linked_ids = {el.evidence_id for el in revised.evidence_links}
    assert "invented-id" not in linked_ids
    assert linked_ids  # at least the real citation survived


def _fake_revision_no_citations():
    # Cites only invalid ids: every citation is stripped, so the built card ends
    # up with zero evidence_links.
    def _inner(db, goal, card, critique, evidence):
        return AgentRevisionOutput(
            name=card.name,
            problem_fit="Revised prose citing ids only inline (bad)",
            mechanism_summary="Revised mechanism",
            device_relevance="Maps onto the PAL",
            maturity=ApproachMaturityEnum.simulated,
            key_assumptions=["a"],
            hardware_requirements=["hw"],
            unresolved_questions=["q"],
            suggested_experiments=["e"],
            reported_metrics=[],
            risks_and_limitations=[],
            cited_evidence_ids=["invented-only"],
            revision_summary="Softened claims but returned no valid citations.",
        )
    return _inner


def test_apply_skips_revision_with_no_valid_citations(db_session, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    goal = _create_goal(db_session)
    card = _generate_card(db_session, goal)
    _critique(db_session, goal)
    before = _card_count(db_session, goal.id)

    with patch.object(approach_svc, "_run_revise_agent", side_effect=_fake_revision_no_citations()):
        result = approach_svc.revise_approaches(db_session, goal.id, ApproachReviseRequest(apply=True))

    rev = result.revisions[0]
    assert rev.skipped_reason is not None
    assert rev.applied is False
    assert rev.revised_approach_id is None
    assert rev.revised_card is None
    assert result.applied_count == 0
    # Nothing persisted; the source stays generated so a re-run can retry it.
    assert _card_count(db_session, goal.id) == before
    assert approach_svc.get(db_session, card.id).status == ApproachStatusEnum.generated


def test_non_revise_verdict_is_skipped(db_session, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    goal = _create_goal(db_session)
    _generate_card(db_session, goal)
    _critique(db_session, goal, verdict=CriticVerdictEnum.advance)

    with patch.object(approach_svc, "_run_revise_agent", side_effect=_fake_revision()) as agent:
        result = approach_svc.revise_approaches(db_session, goal.id, ApproachReviseRequest(apply=True))

    assert result.revised_count == 0
    assert agent.call_count == 0


def test_no_critique_is_skipped(db_session, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    goal = _create_goal(db_session)
    _generate_card(db_session, goal)

    with patch.object(approach_svc, "_run_revise_agent", side_effect=_fake_revision()) as agent:
        result = approach_svc.revise_approaches(db_session, goal.id, ApproachReviseRequest())

    assert result.revised_count == 0
    assert agent.call_count == 0


def test_revise_without_api_key_raises(db_session, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", None)
    goal = _create_goal(db_session)
    with pytest.raises(HTTPException) as exc:
        approach_svc.revise_approaches(db_session, goal.id, ApproachReviseRequest())
    assert exc.value.status_code == 422


def test_str_list_fields_coerce_dict_items():
    # The model sometimes wraps string-list items as {"type": "string", "value": ...}.
    out = AgentRevisionOutput(
        name="X",
        maturity="simulated",
        key_assumptions=[
            {"type": "string", "value": "assumption one"},
            {"item": "assumption two"},
            "assumption three",
        ],
        hardware_requirements=[{"type": "string", "value": "mic array"}],
        cited_evidence_ids=[{"item": "abc"}, "def"],
        revision_summary="ok",
    )
    assert out.key_assumptions == [
        "assumption one",
        "assumption two",
        "assumption three",
    ]
    assert out.hardware_requirements == ["mic array"]
    assert out.cited_evidence_ids == ["abc", "def"]
