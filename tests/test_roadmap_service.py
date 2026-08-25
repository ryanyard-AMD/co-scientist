import json
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from conftest import GOAL_PAYLOAD
from coscientist.models.approach import ApproachCard
from coscientist.models.device import DeviceConceptCard
from coscientist.models.roadmap import ResearchRoadmapItem
from coscientist.schemas.roadmap import (
    AgentRoadmapItem,
    RoadmapLaneEnum,
    RoadmapStatusEnum,
)
from coscientist.services import goal as goal_svc
from coscientist.services import roadmap as svc


MOCK_ITEMS = [
    AgentRoadmapItem(
        title="Run simulation of beamforming baseline",
        description="Validate beamforming in simulation with headphone geometry.",
        lane=RoadmapLaneEnum.conservative,
        priority_score=0.9,
        rationale="Weakest evidence dimension is simulation; lowest cost path.",
        estimated_cost="low",
        estimated_information_gain="high",
        source_approach_ids=["approach-1"],
        source_experiment_id=None,
        source_device_id=None,
    ),
    AgentRoadmapItem(
        title="Explore pressure matching hybrid",
        description="Test pressure matching combined with adaptive filter for exploratory upside.",
        lane=RoadmapLaneEnum.exploratory,
        priority_score=0.7,
        rationale="High information gain if hypothesis validated.",
        estimated_cost="medium",
        estimated_information_gain="high",
        source_approach_ids=["approach-1", "approach-2"],
        source_experiment_id=None,
        source_device_id=None,
    ),
    AgentRoadmapItem(
        title="Build prototype speaker array",
        description="Construct 8-element linear array for device prototype testing.",
        lane=RoadmapLaneEnum.device_prototype,
        priority_score=0.5,
        rationale="Next step for device maturity after simulation validation.",
        estimated_cost="high",
        estimated_information_gain="medium",
        source_approach_ids=[],
        source_experiment_id=None,
        source_device_id="device-1",
    ),
]


def _create_goal(db):
    from coscientist.schemas.goal import GoalCreate
    return goal_svc.create(db, GoalCreate(**GOAL_PAYLOAD))


def _seed_approach(db, workspace_id, approach_id=None):
    now = datetime.now(timezone.utc)
    approach = ApproachCard(
        id=approach_id or str(uuid.uuid4()),
        workspace_id=workspace_id,
        name="Beamforming Baseline",
        method_family="beamforming",
        maturity="theoretical",
        status="reviewed",
        evidence_links=json.dumps([]),
        hardware_requirements=json.dumps([]),
        risks_and_limitations=json.dumps([]),
        device_relevance="Form factor: headphone; Speaker count: 2",
        generation_run_id="run-test",
        created_at=now,
        updated_at=now,
    )
    db.add(approach)
    db.flush()
    return approach


def _seed_roadmap_item(
    db,
    workspace_id,
    status="open",
    lane="conservative",
    source_experiment_id=None,
    priority_score=0.8,
    priority_rank=1,
    generation_run_id=None,
    created_at=None,
):
    now = created_at or datetime.now(timezone.utc)
    item = ResearchRoadmapItem(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        title="Test item",
        description="A test roadmap item",
        lane=lane,
        status=status,
        priority_score=priority_score,
        priority_rank=priority_rank,
        rationale="Testing",
        estimated_cost="low",
        estimated_information_gain="medium",
        source_approach_ids=json.dumps([]),
        source_experiment_id=source_experiment_id,
        source_device_id=None,
        generation_run_id=generation_run_id or str(uuid.uuid4()),
        model_used="test-model",
        created_at=now,
        updated_at=now,
    )
    db.add(item)
    db.flush()
    return item


# --- generate ---


def test_generate_creates_items(db_session):
    goal = _create_goal(db_session)
    _seed_approach(db_session, goal.id)
    with patch("coscientist.services.roadmap._run_roadmap_agent", return_value=MOCK_ITEMS):
        result = svc.generate(db_session, goal.id)
    assert result.total == 3
    assert len(result.items) == 3
    assert result.generation_run_id is not None


def test_generate_assigns_priority_rank(db_session):
    goal = _create_goal(db_session)
    _seed_approach(db_session, goal.id)
    with patch("coscientist.services.roadmap._run_roadmap_agent", return_value=MOCK_ITEMS):
        result = svc.generate(db_session, goal.id)
    ranks = [i.priority_rank for i in result.items]
    assert ranks == [1, 2, 3]
    scores = [i.priority_score for i in result.items]
    assert scores == sorted(scores, reverse=True)


def test_generate_covers_all_lanes(db_session):
    goal = _create_goal(db_session)
    _seed_approach(db_session, goal.id)
    with patch("coscientist.services.roadmap._run_roadmap_agent", return_value=MOCK_ITEMS):
        result = svc.generate(db_session, goal.id)
    lanes = {i.lane for i in result.items}
    assert RoadmapLaneEnum.conservative in lanes
    assert RoadmapLaneEnum.exploratory in lanes
    assert RoadmapLaneEnum.device_prototype in lanes


def test_generate_empty_returns_no_items(db_session):
    goal = _create_goal(db_session)
    result = svc.generate(db_session, goal.id)
    assert result.total == 0
    assert result.items == []
    assert result.generation_run_id is None


def test_generate_goal_not_found_raises_404(db_session):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        svc.generate(db_session, "nonexistent-goal-id")
    assert exc_info.value.status_code == 404


def test_generate_sets_generation_run_id_on_all_items(db_session):
    goal = _create_goal(db_session)
    _seed_approach(db_session, goal.id)
    with patch("coscientist.services.roadmap._run_roadmap_agent", return_value=MOCK_ITEMS):
        result = svc.generate(db_session, goal.id)
    run_ids = {i.generation_run_id for i in result.items}
    assert len(run_ids) == 1
    assert result.generation_run_id in run_ids


def test_run_agent_truncated_response_raises_clear_error(db_session):
    """A max_tokens-truncated completion must fail with an actionable 502, not an
    opaque JSONDecodeError on the incomplete array."""
    from types import SimpleNamespace

    from fastapi import HTTPException

    goal = _create_goal(db_session)
    _seed_approach(db_session, goal.id)

    fake_message = SimpleNamespace(
        content=[SimpleNamespace(text='[{"title": "Do a thing", "descrip')],
        usage=SimpleNamespace(input_tokens=100, output_tokens=8192),
        stop_reason="max_tokens",
    )
    fake_client = SimpleNamespace(
        messages=SimpleNamespace(create=lambda **kw: fake_message)
    )
    with patch("coscientist.services.roadmap.anthropic_client", return_value=fake_client):
        with pytest.raises(HTTPException) as exc_info:
            svc.generate(db_session, goal.id)
    assert exc_info.value.status_code == 502
    assert "truncated" in exc_info.value.detail.lower()


# --- get_roadmap ---


def test_get_roadmap_returns_all_items(db_session):
    goal = _create_goal(db_session)
    _seed_roadmap_item(db_session, goal.id, lane="conservative")
    _seed_roadmap_item(db_session, goal.id, lane="exploratory", priority_score=0.5, priority_rank=2)
    result = svc.get_roadmap(db_session, goal.id)
    assert result.total == 2


def test_get_roadmap_filters_by_lane(db_session):
    goal = _create_goal(db_session)
    _seed_roadmap_item(db_session, goal.id, lane="conservative")
    _seed_roadmap_item(db_session, goal.id, lane="exploratory", priority_score=0.5, priority_rank=2)
    result = svc.get_roadmap(db_session, goal.id, lane=RoadmapLaneEnum.conservative)
    assert result.total == 1
    assert result.items[0].lane == RoadmapLaneEnum.conservative


def test_get_roadmap_filters_by_status(db_session):
    goal = _create_goal(db_session)
    _seed_roadmap_item(db_session, goal.id, status="open")
    _seed_roadmap_item(db_session, goal.id, status="completed", priority_score=0.5, priority_rank=2)
    result = svc.get_roadmap(db_session, goal.id, status=RoadmapStatusEnum.open)
    assert result.total == 1
    assert result.items[0].status == RoadmapStatusEnum.open


def test_get_roadmap_empty_goal_returns_zero(db_session):
    goal = _create_goal(db_session)
    result = svc.get_roadmap(db_session, goal.id)
    assert result.total == 0
    assert result.items == []


# --- get_item ---


def test_get_item_returns_item(db_session):
    goal = _create_goal(db_session)
    item = _seed_roadmap_item(db_session, goal.id)
    result = svc.get_item(db_session, item.id, goal.id)
    assert result.id == item.id
    assert result.workspace_id == goal.id


def test_get_item_wrong_goal_raises_404(db_session):
    from fastapi import HTTPException
    goal = _create_goal(db_session)
    item = _seed_roadmap_item(db_session, goal.id)
    with pytest.raises(HTTPException) as exc_info:
        svc.get_item(db_session, item.id, "wrong-goal-id")
    assert exc_info.value.status_code == 404


def test_get_item_nonexistent_raises_404(db_session):
    from fastapi import HTTPException
    goal = _create_goal(db_session)
    with pytest.raises(HTTPException) as exc_info:
        svc.get_item(db_session, "nonexistent-item-id", goal.id)
    assert exc_info.value.status_code == 404


# --- transition_item ---


def test_transition_open_to_completed(db_session):
    goal = _create_goal(db_session)
    item = _seed_roadmap_item(db_session, goal.id, status="open")
    result = svc.transition_item(db_session, item.id, goal.id, RoadmapStatusEnum.completed)
    assert result.status == RoadmapStatusEnum.completed


def test_transition_open_to_superseded(db_session):
    goal = _create_goal(db_session)
    item = _seed_roadmap_item(db_session, goal.id, status="open")
    result = svc.transition_item(db_session, item.id, goal.id, RoadmapStatusEnum.superseded)
    assert result.status == RoadmapStatusEnum.superseded


def test_transition_completed_is_terminal(db_session):
    from fastapi import HTTPException
    goal = _create_goal(db_session)
    item = _seed_roadmap_item(db_session, goal.id, status="completed")
    with pytest.raises(HTTPException) as exc_info:
        svc.transition_item(db_session, item.id, goal.id, RoadmapStatusEnum.open)
    assert exc_info.value.status_code == 422


def test_transition_superseded_is_terminal(db_session):
    from fastapi import HTTPException
    goal = _create_goal(db_session)
    item = _seed_roadmap_item(db_session, goal.id, status="superseded")
    with pytest.raises(HTTPException) as exc_info:
        svc.transition_item(db_session, item.id, goal.id, RoadmapStatusEnum.completed)
    assert exc_info.value.status_code == 422


def test_supersede_older_generations_keeps_latest_open_generation(db_session):
    goal = _create_goal(db_session)
    now = datetime.now(timezone.utc)
    old_gen = "old-generation"
    new_gen = "new-generation"
    old_a = _seed_roadmap_item(
        db_session, goal.id, status="open", generation_run_id=old_gen, created_at=now
    )
    old_b = _seed_roadmap_item(
        db_session, goal.id, status="open", generation_run_id=old_gen, created_at=now
    )
    new_item = _seed_roadmap_item(
        db_session,
        goal.id,
        status="open",
        generation_run_id=new_gen,
        created_at=now + timedelta(minutes=1),
    )
    completed = _seed_roadmap_item(
        db_session, goal.id, status="completed", generation_run_id=old_gen, created_at=now
    )

    result = svc.supersede_older_generations(db_session, goal.id)

    assert result.kept_generation_run_id == new_gen
    assert result.superseded_count == 2
    db_session.refresh(old_a)
    db_session.refresh(old_b)
    db_session.refresh(new_item)
    db_session.refresh(completed)
    assert old_a.status == "superseded"
    assert old_b.status == "superseded"
    assert new_item.status == "open"
    assert completed.status == "completed"


def test_supersede_older_generations_honors_explicit_keep(db_session):
    goal = _create_goal(db_session)
    now = datetime.now(timezone.utc)
    keep = "manual-keep"
    other = "other-generation"
    keep_item = _seed_roadmap_item(
        db_session, goal.id, status="open", generation_run_id=keep, created_at=now
    )
    other_item = _seed_roadmap_item(
        db_session,
        goal.id,
        status="open",
        generation_run_id=other,
        created_at=now + timedelta(minutes=1),
    )

    result = svc.supersede_older_generations(
        db_session, goal.id, keep_generation_run_id=keep
    )

    assert result.kept_generation_run_id == keep
    assert result.superseded_count == 1
    db_session.refresh(keep_item)
    db_session.refresh(other_item)
    assert keep_item.status == "open"
    assert other_item.status == "superseded"


def test_supersede_older_generations_unknown_generation_404(db_session):
    from fastapi import HTTPException

    goal = _create_goal(db_session)
    _seed_roadmap_item(db_session, goal.id)

    with pytest.raises(HTTPException) as exc:
        svc.supersede_older_generations(
            db_session, goal.id, keep_generation_run_id="missing-generation"
        )
    assert exc.value.status_code == 404


# --- retire_for_experiment ---


def test_retire_for_experiment_retires_linked_open_items(db_session):
    goal = _create_goal(db_session)
    exp_id = str(uuid.uuid4())
    item = _seed_roadmap_item(db_session, goal.id, status="open", source_experiment_id=exp_id)
    svc.retire_for_experiment(db_session, exp_id, goal.id)
    db_session.refresh(item)
    assert item.status == "completed"


def test_retire_for_experiment_noop_if_no_match(db_session):
    goal = _create_goal(db_session)
    item = _seed_roadmap_item(db_session, goal.id, status="open")
    svc.retire_for_experiment(db_session, "nonexistent-exp-id", goal.id)
    db_session.refresh(item)
    assert item.status == "open"


def test_retire_for_experiment_does_not_re_retire_completed(db_session):
    goal = _create_goal(db_session)
    exp_id = str(uuid.uuid4())
    item = _seed_roadmap_item(db_session, goal.id, status="completed", source_experiment_id=exp_id)
    svc.retire_for_experiment(db_session, exp_id, goal.id)
    db_session.refresh(item)
    assert item.status == "completed"


# --- identify_evidence_gaps (CS-ROADMAP-003) ---


def _seed_score(db, approach_id, workspace_id, *, dimension, score, low_confidence=False):
    from coscientist.models.score import RubricScore

    db.add(
        RubricScore(
            id=str(uuid.uuid4()),
            approach_id=approach_id,
            workspace_id=workspace_id,
            dimension=dimension,
            score=score,
            weight=1.0,
            weighted_score=score,
            confidence=0.9,
            rationale="x",
            evidence_ids=json.dumps([]),
            low_confidence=low_confidence,
            scoring_run_id="run-test",
        )
    )
    db.flush()


def test_evidence_gaps_flags_unscored_approach(db_session):
    goal = _create_goal(db_session)
    _seed_approach(db_session, goal.id)
    db_session.commit()
    resp = svc.identify_evidence_gaps(db_session, goal.id)
    assert resp.total == 1
    assert resp.gaps[0].unscored is True


def test_evidence_gaps_flags_weak_dimension(db_session):
    goal = _create_goal(db_session)
    approach = _seed_approach(db_session, goal.id)
    _seed_score(db_session, approach.id, goal.id, dimension="feasibility", score=0.2)
    _seed_score(db_session, approach.id, goal.id, dimension="novelty", score=0.9)
    db_session.commit()
    resp = svc.identify_evidence_gaps(db_session, goal.id)
    assert resp.total == 1
    assert resp.gaps[0].weak_dimensions == ["feasibility"]
    assert resp.gaps[0].unscored is False


def test_evidence_gaps_flags_low_confidence_dimension(db_session):
    goal = _create_goal(db_session)
    approach = _seed_approach(db_session, goal.id)
    _seed_score(db_session, approach.id, goal.id, dimension="impact", score=0.9, low_confidence=True)
    db_session.commit()
    resp = svc.identify_evidence_gaps(db_session, goal.id)
    assert "impact" in resp.gaps[0].weak_dimensions


def test_evidence_gaps_skips_non_promising_status(db_session):
    goal = _create_goal(db_session)
    approach = _seed_approach(db_session, goal.id)
    approach.status = "refuted"
    db_session.commit()
    resp = svc.identify_evidence_gaps(db_session, goal.id)
    assert resp.total == 0


def test_evidence_gaps_clean_scored_approach_excluded(db_session):
    goal = _create_goal(db_session)
    approach = _seed_approach(db_session, goal.id)
    # mechanism_summary etc. are empty in the seed, so no missing-claim gaps;
    # give it a strong score so it is fully grounded + scored.
    _seed_score(db_session, approach.id, goal.id, dimension="feasibility", score=0.9)
    db_session.commit()
    resp = svc.identify_evidence_gaps(db_session, goal.id)
    assert resp.total == 0


def test_evidence_gaps_unknown_goal_404(db_session):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        svc.identify_evidence_gaps(db_session, "nope")
    assert exc.value.status_code == 404


# --- device simulation feeds the roadmap context ---


def _seed_device(db, workspace_id, *, simulation="{}"):
    now = datetime.now(timezone.utc)
    card = DeviceConceptCard(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        name="Tabletop PAL unit",
        simulation=simulation,
        created_at=now,
        updated_at=now,
    )
    db.add(card)
    db.flush()
    return card


def test_sim_summary_none_when_never_simulated():
    assert svc._sim_summary(None) is None
    assert svc._sim_summary("{}") is None
    # simulated record but missing the contrast is treated as no usable prediction
    assert svc._sim_summary(json.dumps({"resolved_geometry": {"layout": "cap"}})) is None


def test_sim_summary_extracts_prediction():
    summary = svc._sim_summary(json.dumps({
        "acoustic_contrast_db": 28.33,
        "target_contrast_db": 15.0,
        "meets_target": True,
        "resolved_geometry": {"layout": "cap", "n_elements": 8, "cap_radius_m": 0.12},
    }))
    assert summary == {
        "predicted_contrast_db": 28.33,
        "target_contrast_db": 15.0,
        "meets_target": True,
        "layout": "cap",
        "n_elements": 8,
    }


def test_sim_summary_extracts_reproduction_quality():
    summary = svc._sim_summary(json.dumps({
        "mode": "sound_field_reproduction",
        "solver": "pressure_matching",
        "target": {"kind": "plane_wave"},
        "normalized_reproduction_error": 0.2175,
        "spatial_correlation": 0.9412,
        "mean_spl_error_db": 1.88,
        "max_spl_error_db": 4.73,
        "array_effort": 2.41,
        "acoustic_contrast_db": 18.6,
        "resolved_geometry": {"layout": "cap", "n_elements": 16},
    }))
    assert summary == {
        "predicted_contrast_db": 18.6,
        "target_contrast_db": None,
        "meets_target": None,
        "layout": "cap",
        "n_elements": 16,
        "mode": "sound_field_reproduction",
        "solver": "pressure_matching",
        "target": {"kind": "plane_wave"},
        "normalized_reproduction_error": 0.2175,
        "spatial_correlation": 0.9412,
        "mean_spl_error_db": 1.88,
        "max_spl_error_db": 4.73,
        "array_effort": 2.41,
    }


def test_build_context_includes_device_simulation(db_session):
    goal = _create_goal(db_session)
    _seed_device(db_session, goal.id, simulation=json.dumps({
        "acoustic_contrast_db": 35.77,
        "target_contrast_db": 15.0,
        "meets_target": True,
        "resolved_geometry": {"layout": "cap", "n_elements": 16},
    }))
    _seed_device(db_session, goal.id)  # unsimulated → simulation is None
    db_session.commit()

    ctx = svc._build_context(db_session, goal.id)
    sims = {
        (d["simulation"] or {}).get("predicted_contrast_db")
        for d in ctx["device_concepts"]
    }
    assert 35.77 in sims          # simulated card's prediction reaches the context
    assert None in sims           # unsimulated card carries simulation=None
