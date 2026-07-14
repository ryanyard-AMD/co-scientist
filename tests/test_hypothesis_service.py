import json
import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from conftest import GOAL_PAYLOAD
from coscientist.config import settings
from coscientist.models.evidence import EvidenceRecord
from coscientist.models.governance import AgentActionLog
from coscientist.schemas.approach import (
    ApproachCardCreate,
    ApproachGenerateRequest,
    ApproachStatusEnum,
)
from coscientist.schemas.hypothesis import (
    AgentHypothesisOutput,
    CompatibilityNote,
    HypothesisCardCreate,
    HypothesisCardUpdate,
    HypothesisGenerateRequest,
    HypothesisStatusEnum,
    HypothesisTypeEnum,
)
from coscientist.schemas.score import WeightProfileEnum
from coscientist.services import approach as approach_svc
from coscientist.services import goal as goal_svc
from coscientist.services import hypothesis as svc
from coscientist.services import score as score_svc
from sqlalchemy import select


def _create_goal(db):
    from coscientist.schemas.goal import GoalCreate
    data = GoalCreate(**GOAL_PAYLOAD)
    return goal_svc.create(db, data)


def _seed_evidence(db, workspace_id, method_families, metric_names=None,
                   hardware=None, failure_modes=None, text="test chunk text",
                   score=0.9, strength="weak"):
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
        metric_names=json.dumps(metric_names or []),
        hardware_assumptions=json.dumps(hardware or []),
        failure_modes=json.dumps(failure_modes or []),
        is_primary_method=True,
        evidence_strength=strength,
        created_at=now,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


def _create_scored_approach(db, goal_id, method_family, metric_names=None,
                            hardware=None, failure_modes=None, strength="strong"):
    _seed_evidence(db, goal_id, [method_family], metric_names=metric_names,
                   hardware=hardware, failure_modes=failure_modes, strength=strength)
    _seed_evidence(db, goal_id, [method_family], strength=strength)
    result = approach_svc.generate_approaches(db, goal_id, ApproachGenerateRequest(
        method_families=[method_family],
    ))
    card = result.approaches[0]
    approach_svc.transition(db, card.id, ApproachStatusEnum.reviewed)
    score_svc.score_approach(db, card.id)
    return approach_svc.get(db, card.id)


# --- CRUD tests ---

def test_create_hypothesis_card(db_session):
    goal = _create_goal(db_session)
    a1 = _create_scored_approach(db_session, goal.id, "beamforming",
                                 metric_names=["acoustic_contrast_db"])
    a2 = _create_scored_approach(db_session, goal.id, "pressure_matching")

    data = HypothesisCardCreate(
        name="BF + PM",
        text="Combine beamforming with pressure matching",
        rationale="Complementary methods",
        approach_ids=[a1.id, a2.id],
    )
    result = svc.create(db_session, goal.id, data)
    assert result.name == "BF + PM"
    assert result.status == HypothesisStatusEnum.generated
    assert len(result.approach_ids) == 2


def test_create_validates_goal_exists(db_session):
    data = HypothesisCardCreate(
        name="X", text="x", rationale="x",
        approach_ids=["a", "b"],
    )
    with pytest.raises(Exception) as exc_info:
        svc.create(db_session, "nonexistent", data)
    assert exc_info.value.status_code == 404


def test_create_validates_approach_ids_exist(db_session):
    goal = _create_goal(db_session)
    data = HypothesisCardCreate(
        name="X", text="x", rationale="x",
        approach_ids=["nonexistent1", "nonexistent2"],
    )
    with pytest.raises(Exception) as exc_info:
        svc.create(db_session, goal.id, data)
    assert exc_info.value.status_code == 404


def test_get_hypothesis(db_session):
    goal = _create_goal(db_session)
    a1 = _create_scored_approach(db_session, goal.id, "beamforming")
    a2 = _create_scored_approach(db_session, goal.id, "pressure_matching")
    created = svc.create(db_session, goal.id, HypothesisCardCreate(
        name="H", text="t", rationale="r", approach_ids=[a1.id, a2.id],
    ))
    result = svc.get(db_session, created.id)
    assert result.id == created.id


def test_get_hypothesis_not_found(db_session):
    with pytest.raises(Exception) as exc_info:
        svc.get(db_session, "nonexistent")
    assert exc_info.value.status_code == 404


def test_list_hypotheses_empty(db_session):
    goal = _create_goal(db_session)
    items, total = svc.list_hypotheses(db_session, goal.id)
    assert total == 0
    assert items == []


def test_list_hypotheses_filter_status(db_session):
    goal = _create_goal(db_session)
    a1 = _create_scored_approach(db_session, goal.id, "beamforming")
    a2 = _create_scored_approach(db_session, goal.id, "pressure_matching")
    svc.create(db_session, goal.id, HypothesisCardCreate(
        name="H", text="t", rationale="r", approach_ids=[a1.id, a2.id],
    ))
    items, total = svc.list_hypotheses(db_session, goal.id, status=HypothesisStatusEnum.generated)
    assert total == 1
    items, total = svc.list_hypotheses(db_session, goal.id, status=HypothesisStatusEnum.reviewed)
    assert total == 0


def test_list_hypotheses_filter_type(db_session):
    goal = _create_goal(db_session)
    a1 = _create_scored_approach(db_session, goal.id, "beamforming")
    a2 = _create_scored_approach(db_session, goal.id, "pressure_matching")
    svc.create(db_session, goal.id, HypothesisCardCreate(
        name="C", text="t", rationale="r", approach_ids=[a1.id, a2.id],
        hypothesis_type=HypothesisTypeEnum.conservative,
    ))
    svc.create(db_session, goal.id, HypothesisCardCreate(
        name="E", text="t", rationale="r", approach_ids=[a1.id, a2.id],
        hypothesis_type=HypothesisTypeEnum.exploratory,
    ))
    items, total = svc.list_hypotheses(db_session, goal.id,
                                       hypothesis_type=HypothesisTypeEnum.conservative)
    assert total == 1
    assert items[0].hypothesis_type == HypothesisTypeEnum.conservative


def test_update_hypothesis(db_session):
    goal = _create_goal(db_session)
    a1 = _create_scored_approach(db_session, goal.id, "beamforming")
    a2 = _create_scored_approach(db_session, goal.id, "pressure_matching")
    created = svc.create(db_session, goal.id, HypothesisCardCreate(
        name="H", text="t", rationale="r", approach_ids=[a1.id, a2.id],
    ))
    result = svc.update(db_session, created.id, HypothesisCardUpdate(name="Updated H"))
    assert result.name == "Updated H"


# --- State machine tests ---

def test_transition_generated_to_reviewed(db_session):
    goal = _create_goal(db_session)
    a1 = _create_scored_approach(db_session, goal.id, "beamforming")
    a2 = _create_scored_approach(db_session, goal.id, "pressure_matching")
    created = svc.create(db_session, goal.id, HypothesisCardCreate(
        name="H", text="t", rationale="r", approach_ids=[a1.id, a2.id],
    ))
    result = svc.transition(db_session, created.id, HypothesisStatusEnum.reviewed)
    assert result.status == HypothesisStatusEnum.reviewed


def test_transition_reviewed_to_experiment_proposed(db_session):
    goal = _create_goal(db_session)
    a1 = _create_scored_approach(db_session, goal.id, "beamforming")
    a2 = _create_scored_approach(db_session, goal.id, "pressure_matching")
    created = svc.create(db_session, goal.id, HypothesisCardCreate(
        name="H", text="t", rationale="r", approach_ids=[a1.id, a2.id],
    ))
    svc.transition(db_session, created.id, HypothesisStatusEnum.reviewed)
    result = svc.transition(db_session, created.id, HypothesisStatusEnum.experiment_proposed)
    assert result.status == HypothesisStatusEnum.experiment_proposed


def test_transition_superseded_is_terminal(db_session):
    goal = _create_goal(db_session)
    a1 = _create_scored_approach(db_session, goal.id, "beamforming")
    a2 = _create_scored_approach(db_session, goal.id, "pressure_matching")
    created = svc.create(db_session, goal.id, HypothesisCardCreate(
        name="H", text="t", rationale="r", approach_ids=[a1.id, a2.id],
    ))
    svc.transition(db_session, created.id, HypothesisStatusEnum.superseded)
    with pytest.raises(Exception) as exc_info:
        svc.transition(db_session, created.id, HypothesisStatusEnum.reviewed)
    assert exc_info.value.status_code == 422


def test_transition_invalid_raises_422(db_session):
    goal = _create_goal(db_session)
    a1 = _create_scored_approach(db_session, goal.id, "beamforming")
    a2 = _create_scored_approach(db_session, goal.id, "pressure_matching")
    created = svc.create(db_session, goal.id, HypothesisCardCreate(
        name="H", text="t", rationale="r", approach_ids=[a1.id, a2.id],
    ))
    with pytest.raises(Exception) as exc_info:
        svc.transition(db_session, created.id, HypothesisStatusEnum.experiment_proposed)
    assert exc_info.value.status_code == 422


def test_delete_generated_hypothesis(db_session):
    goal = _create_goal(db_session)
    a1 = _create_scored_approach(db_session, goal.id, "beamforming")
    a2 = _create_scored_approach(db_session, goal.id, "pressure_matching")
    created = svc.create(db_session, goal.id, HypothesisCardCreate(
        name="H", text="t", rationale="r", approach_ids=[a1.id, a2.id],
    ))
    svc.delete(db_session, created.id)
    with pytest.raises(Exception) as exc_info:
        svc.get(db_session, created.id)
    assert exc_info.value.status_code == 404


def test_delete_reviewed_raises_409(db_session):
    goal = _create_goal(db_session)
    a1 = _create_scored_approach(db_session, goal.id, "beamforming")
    a2 = _create_scored_approach(db_session, goal.id, "pressure_matching")
    created = svc.create(db_session, goal.id, HypothesisCardCreate(
        name="H", text="t", rationale="r", approach_ids=[a1.id, a2.id],
    ))
    svc.transition(db_session, created.id, HypothesisStatusEnum.reviewed)
    with pytest.raises(Exception) as exc_info:
        svc.delete(db_session, created.id)
    assert exc_info.value.status_code == 409


# --- Generation tests ---

def test_generate_hypotheses_from_scored_approaches(db_session):
    goal = _create_goal(db_session)
    _create_scored_approach(db_session, goal.id, "beamforming",
                            metric_names=["acoustic_contrast_db"],
                            hardware=["loudspeaker_array"])
    _create_scored_approach(db_session, goal.id, "pressure_matching",
                            metric_names=["latency_ms"],
                            hardware=["loudspeaker_array"])

    result = svc.generate_hypotheses(db_session, goal.id, HypothesisGenerateRequest())
    assert result.hypotheses_created >= 1
    assert len(result.hypotheses) >= 1
    assert all(len(h.approach_ids) >= 2 for h in result.hypotheses)


def test_generate_hypotheses_needs_min_approaches(db_session):
    goal = _create_goal(db_session)
    _create_scored_approach(db_session, goal.id, "beamforming")

    result = svc.generate_hypotheses(db_session, goal.id, HypothesisGenerateRequest())
    assert result.hypotheses_created == 0


def test_generate_hypothesis_rationale_populated(db_session):
    goal = _create_goal(db_session)
    _create_scored_approach(db_session, goal.id, "beamforming",
                            hardware=["loudspeaker_array"])
    _create_scored_approach(db_session, goal.id, "pressure_matching",
                            hardware=["loudspeaker_array"])

    result = svc.generate_hypotheses(db_session, goal.id, HypothesisGenerateRequest())
    assert result.hypotheses_created >= 1
    for h in result.hypotheses:
        assert h.rationale
        assert len(h.rationale) > 0


def test_generate_hypothesis_has_assumptions(db_session):
    goal = _create_goal(db_session)
    _create_scored_approach(db_session, goal.id, "beamforming",
                            hardware=["loudspeaker_array", "microphone_array"])
    _create_scored_approach(db_session, goal.id, "pressure_matching",
                            hardware=["loudspeaker_array"])

    result = svc.generate_hypotheses(db_session, goal.id, HypothesisGenerateRequest())
    if result.hypotheses_created > 0:
        h = result.hypotheses[0]
        assert isinstance(h.assumptions, list)


def test_generate_hypothesis_has_failure_modes(db_session):
    goal = _create_goal(db_session)
    _create_scored_approach(db_session, goal.id, "beamforming",
                            failure_modes=["head_movement"])
    _create_scored_approach(db_session, goal.id, "pressure_matching",
                            failure_modes=["room_reverberation"])

    result = svc.generate_hypotheses(db_session, goal.id, HypothesisGenerateRequest())
    if result.hypotheses_created > 0:
        h = result.hypotheses[0]
        assert len(h.failure_modes) >= 1


def test_generate_hypothesis_has_required_experiments(db_session):
    goal = _create_goal(db_session)
    _create_scored_approach(db_session, goal.id, "beamforming")
    _create_scored_approach(db_session, goal.id, "pressure_matching")

    result = svc.generate_hypotheses(db_session, goal.id, HypothesisGenerateRequest())
    if result.hypotheses_created > 0:
        h = result.hypotheses[0]
        assert len(h.required_experiments) >= 1


def test_generate_skips_duplicate_combinations(db_session):
    goal = _create_goal(db_session)
    _create_scored_approach(db_session, goal.id, "beamforming",
                            hardware=["loudspeaker_array"])
    _create_scored_approach(db_session, goal.id, "pressure_matching",
                            hardware=["loudspeaker_array"])

    r1 = svc.generate_hypotheses(db_session, goal.id, HypothesisGenerateRequest())
    created_first = r1.hypotheses_created

    r2 = svc.generate_hypotheses(db_session, goal.id, HypothesisGenerateRequest())
    assert r2.hypotheses_created == 0
    assert r2.hypotheses_skipped_duplicate == created_first


def test_generate_respects_max_hypotheses(db_session):
    goal = _create_goal(db_session)
    _create_scored_approach(db_session, goal.id, "beamforming",
                            hardware=["loudspeaker_array"])
    _create_scored_approach(db_session, goal.id, "pressure_matching",
                            hardware=["loudspeaker_array"])
    _create_scored_approach(db_session, goal.id, "acoustic_contrast_control",
                            hardware=["loudspeaker_array"])

    result = svc.generate_hypotheses(db_session, goal.id,
                                     HypothesisGenerateRequest(max_hypotheses=1))
    assert result.hypotheses_created <= 1


def test_generate_no_exploratory_when_disabled(db_session):
    goal = _create_goal(db_session)
    _create_scored_approach(db_session, goal.id, "beamforming",
                            strength="strong", hardware=["loudspeaker_array"])
    _create_scored_approach(db_session, goal.id, "pressure_matching",
                            strength="weak", hardware=["microphone_array"])

    result = svc.generate_hypotheses(db_session, goal.id,
                                     HypothesisGenerateRequest(include_exploratory=False))
    assert result.exploratory_count == 0


def test_compatibility_shared_hardware(db_session):
    goal = _create_goal(db_session)
    a1 = _create_scored_approach(db_session, goal.id, "beamforming",
                                 hardware=["loudspeaker_array", "microphone_array"])
    a2 = _create_scored_approach(db_session, goal.id, "pressure_matching",
                                 hardware=["loudspeaker_array"])

    s1 = score_svc.get_scores(db_session, a1.id)
    s2 = score_svc.get_scores(db_session, a2.id)

    note = svc._check_compatibility(a1, a2, s1, s2, db_session)
    assert "loudspeaker array" in note.shared_hardware
    assert note.compatible is True


def test_compatibility_conflicting_assumptions(db_session):
    conflicts = svc._find_assumption_conflicts(
        ["Requires loudspeaker array", "Requires anechoic room"],
        ["Does not require loudspeaker array"],
    )
    assert len(conflicts) > 0


def test_complementary_dimensions_detected(db_session):
    from coscientist.schemas.score import DimensionScoreResponse, RubricDimensionEnum

    dims_a = [
        DimensionScoreResponse(
            dimension=RubricDimensionEnum.evidence_strength, score=0.8,
            weight=0.15, weighted_score=0.12, confidence=None,
            rationale="", evidence_ids=[], low_confidence=False,
        ),
        DimensionScoreResponse(
            dimension=RubricDimensionEnum.robustness, score=0.2,
            weight=0.12, weighted_score=0.024, confidence=None,
            rationale="", evidence_ids=[], low_confidence=True,
        ),
    ]
    dims_b = [
        DimensionScoreResponse(
            dimension=RubricDimensionEnum.evidence_strength, score=0.3,
            weight=0.15, weighted_score=0.045, confidence=None,
            rationale="", evidence_ids=[], low_confidence=True,
        ),
        DimensionScoreResponse(
            dimension=RubricDimensionEnum.robustness, score=0.7,
            weight=0.12, weighted_score=0.084, confidence=None,
            rationale="", evidence_ids=[], low_confidence=False,
        ),
    ]

    from coscientist.schemas.score import ApproachScoreResponse
    sa = ApproachScoreResponse(
        approach_id="a", approach_name="A", method_family="bf",
        dimensions=dims_a, total_score=0.5, risk_penalty=0.0,
        final_score=0.5, scoring_run_id="sr1",
    )
    sb = ApproachScoreResponse(
        approach_id="b", approach_name="B", method_family="pm",
        dimensions=dims_b, total_score=0.5, risk_penalty=0.0,
        final_score=0.5, scoring_run_id="sr2",
    )

    complementary = svc._find_complementary_dimensions(sa, sb)
    assert "evidence_strength" in complementary
    assert "robustness" in complementary


# --- LLM synthesis tests ---

def _seed_pair(db, goal_id):
    _create_scored_approach(db, goal_id, "beamforming",
                            hardware=["loudspeaker_array"],
                            failure_modes=["head_movement"])
    _create_scored_approach(db, goal_id, "pressure_matching",
                            hardware=["loudspeaker_array"],
                            failure_modes=["room_reverberation"])


def test_generate_uses_llm_agent_when_enabled(db_session, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(settings, "hypothesis_use_llm", True)
    goal = _create_goal(db_session)
    _seed_pair(db_session, goal.id)

    agent_out = AgentHypothesisOutput(
        name="Adaptive Contrast-Steered Zone Control",
        text="Fuse beamforming steering with pressure-matching error control.",
        rationale="The two mechanisms address orthogonal error sources.",
        expected_benefits=["higher contrast", "lower leakage"],
        assumptions=["quasi-static listener"],
        failure_modes=["coupling instability at high SPL"],
        required_experiments=["swept-tone contrast sweep"],
    )
    with patch.object(svc, "_run_hypothesis_agent", return_value=agent_out) as agent:
        result = svc.generate_hypotheses(db_session, goal.id, HypothesisGenerateRequest())

    assert agent.called
    assert result.hypotheses_created >= 1
    h = result.hypotheses[0]
    assert h.name == "Adaptive Contrast-Steered Zone Control"
    assert h.text == "Fuse beamforming steering with pressure-matching error control."
    assert h.rationale == "The two mechanisms address orthogonal error sources."
    assert h.expected_benefits == ["higher contrast", "lower leakage"]
    assert h.assumptions == ["quasi-static listener"]
    assert h.failure_modes == ["coupling instability at high SPL"]
    assert h.required_experiments == ["swept-tone contrast sweep"]


def test_generate_deterministic_when_no_api_key(db_session, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", None)
    monkeypatch.setattr(settings, "hypothesis_use_llm", True)
    goal = _create_goal(db_session)
    _seed_pair(db_session, goal.id)

    with patch.object(svc, "_run_hypothesis_agent") as agent:
        result = svc.generate_hypotheses(db_session, goal.id, HypothesisGenerateRequest())

    agent.assert_not_called()
    assert result.hypotheses_created >= 1
    h = result.hypotheses[0]
    # Deterministic name is the templated "Method A + Method B".
    assert " + " in h.name


def test_generate_deterministic_when_llm_disabled(db_session, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(settings, "hypothesis_use_llm", False)
    goal = _create_goal(db_session)
    _seed_pair(db_session, goal.id)

    with patch.object(svc, "_run_hypothesis_agent") as agent:
        result = svc.generate_hypotheses(db_session, goal.id, HypothesisGenerateRequest())

    agent.assert_not_called()
    assert result.hypotheses_created >= 1


def test_llm_empty_lists_backfill_from_deterministic(db_session, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(settings, "hypothesis_use_llm", True)
    goal = _create_goal(db_session)
    _seed_pair(db_session, goal.id)

    # Agent returns narrative fields but empty lists — must backfill from cards.
    agent_out = AgentHypothesisOutput(
        name="Fused Zone Control",
        text="A fused mechanism.",
        rationale="Because reasons.",
        expected_benefits=[],
        assumptions=[],
        failure_modes=[],
        required_experiments=[],
    )
    with patch.object(svc, "_run_hypothesis_agent", return_value=agent_out):
        result = svc.generate_hypotheses(db_session, goal.id, HypothesisGenerateRequest())

    h = result.hypotheses[0]
    # Grounded failure modes / experiments from source cards are never silently emptied.
    assert len(h.failure_modes) >= 1
    assert len(h.required_experiments) >= 1


def test_hypothesis_agent_writes_governance_row(db_session, monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr(settings, "hypothesis_use_llm", True)
    goal = _create_goal(db_session)
    _seed_pair(db_session, goal.id)

    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.input = {
        "name": "Fused Zone Control",
        "text": "A fused mechanism.",
        "rationale": "Because reasons.",
        "expected_benefits": ["b1"],
        "assumptions": ["a1"],
        "failure_modes": ["f1"],
        "required_experiments": ["e1"],
    }
    fake_message = MagicMock()
    fake_message.content = [tool_block]
    fake_message.usage.input_tokens = 123
    fake_message.usage.output_tokens = 45
    fake_client = MagicMock()
    fake_client.messages.create.return_value = fake_message

    with patch.object(svc.anthropic, "Anthropic", return_value=fake_client):
        result = svc.generate_hypotheses(db_session, goal.id, HypothesisGenerateRequest())

    assert result.hypotheses_created >= 1
    rows = db_session.scalars(
        select(AgentActionLog).where(
            AgentActionLog.workspace_id == goal.id,
            AgentActionLog.service == "hypothesis",
            AgentActionLog.action == "synthesize_hypothesis",
        )
    ).all()
    assert len(rows) >= 1
    assert rows[0].model_used == settings.validation_model
    assert rows[0].prompt_tokens == 123
    assert rows[0].completion_tokens == 45
