import json
import uuid
from datetime import datetime, timezone

import pytest

from conftest import GOAL_PAYLOAD
from coscientist.models.approach import ApproachCard
from coscientist.models.evidence import EvidenceRecord
from coscientist.schemas.approach import (
    ApproachCardCreate,
    ApproachGenerateRequest,
    ApproachStatusEnum,
)
from coscientist.schemas.score import RubricDimensionEnum, WeightProfileEnum
from coscientist.services import approach as approach_svc
from coscientist.services import goal as goal_svc
from coscientist.services import score as svc


def _create_goal(db):
    from coscientist.schemas.goal import GoalCreate
    data = GoalCreate(**GOAL_PAYLOAD)
    return goal_svc.create(db, data)


def _seed_evidence(db, workspace_id, method_families, metric_names=None,
                   hardware=None, failure_modes=None, text="test chunk text",
                   score=0.9, is_primary=True, strength="weak"):
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
        is_primary_method=is_primary,
        evidence_strength=strength,
        created_at=now,
    )
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return rec


def _create_and_review_approach(db, goal_id, method_family="beamforming", name="BF"):
    card = approach_svc.create(db, goal_id, ApproachCardCreate(
        name=name, method_family=method_family,
    ))
    approach_svc.transition(db, card.id, ApproachStatusEnum.reviewed)
    return approach_svc.get(db, card.id)


def _generate_and_review(db, goal_id):
    result = approach_svc.generate_approaches(db, goal_id, ApproachGenerateRequest())
    for a in result.approaches:
        approach_svc.transition(db, a.id, ApproachStatusEnum.reviewed)
    return result.approaches


def test_score_approach_returns_10_dimensions(db_session):
    goal = _create_goal(db_session)
    _seed_evidence(db_session, goal.id, ["beamforming"], metric_names=["acoustic_contrast_db"])
    _seed_evidence(db_session, goal.id, ["beamforming"], metric_names=["latency_ms"])
    approaches = _generate_and_review(db_session, goal.id)

    result = svc.score_approach(db_session, approaches[0].id)
    assert len(result.dimensions) == 10
    dims = {d.dimension for d in result.dimensions}
    for dim in RubricDimensionEnum:
        assert dim in dims


def test_score_approach_scores_in_range(db_session):
    goal = _create_goal(db_session)
    _seed_evidence(db_session, goal.id, ["beamforming"], metric_names=["acoustic_contrast_db"])
    _seed_evidence(db_session, goal.id, ["beamforming"])
    approaches = _generate_and_review(db_session, goal.id)

    result = svc.score_approach(db_session, approaches[0].id)
    for d in result.dimensions:
        assert 0.0 <= d.score <= 1.0
        assert 0.0 <= d.weight <= 1.0
        assert 0.0 <= d.weighted_score <= 1.0


def test_score_approach_total_equals_weighted_sum(db_session):
    goal = _create_goal(db_session)
    _seed_evidence(db_session, goal.id, ["beamforming"], metric_names=["acoustic_contrast_db"])
    _seed_evidence(db_session, goal.id, ["beamforming"])
    approaches = _generate_and_review(db_session, goal.id)

    result = svc.score_approach(db_session, approaches[0].id)
    expected_total = sum(d.weighted_score for d in result.dimensions)
    assert abs(result.total_score - round(expected_total, 4)) < 0.001


def test_score_approach_final_includes_risk_penalty(db_session):
    goal = _create_goal(db_session)
    _seed_evidence(db_session, goal.id, ["beamforming"],
                   failure_modes=["head_movement"])
    _seed_evidence(db_session, goal.id, ["beamforming"])
    approaches = _generate_and_review(db_session, goal.id)

    result = svc.score_approach(db_session, approaches[0].id)
    assert result.final_score == round(max(0.0, result.total_score - result.risk_penalty), 4)


def test_score_approach_auto_transitions_to_scored(db_session):
    goal = _create_goal(db_session)
    _seed_evidence(db_session, goal.id, ["beamforming"])
    _seed_evidence(db_session, goal.id, ["beamforming"])
    approaches = _generate_and_review(db_session, goal.id)

    svc.score_approach(db_session, approaches[0].id)
    updated = approach_svc.get(db_session, approaches[0].id)
    assert updated.status == ApproachStatusEnum.scored


def test_score_all_approaches(db_session):
    goal = _create_goal(db_session)
    _seed_evidence(db_session, goal.id, ["beamforming"], metric_names=["acoustic_contrast_db"])
    _seed_evidence(db_session, goal.id, ["beamforming"])
    _seed_evidence(db_session, goal.id, ["pressure_matching"])
    _seed_evidence(db_session, goal.id, ["pressure_matching"])
    _generate_and_review(db_session, goal.id)

    results = svc.score_all_approaches(db_session, goal.id)
    assert len(results) == 2
    names = {r.method_family for r in results}
    assert "beamforming" in names
    assert "pressure_matching" in names


def test_get_scores_after_scoring(db_session):
    goal = _create_goal(db_session)
    _seed_evidence(db_session, goal.id, ["beamforming"])
    _seed_evidence(db_session, goal.id, ["beamforming"])
    approaches = _generate_and_review(db_session, goal.id)

    svc.score_approach(db_session, approaches[0].id)
    result = svc.get_scores(db_session, approaches[0].id)
    assert len(result.dimensions) == 10
    assert result.approach_id == approaches[0].id


def test_get_scores_not_found(db_session):
    goal = _create_goal(db_session)
    card = approach_svc.create(db_session, goal.id, ApproachCardCreate(
        name="BF", method_family="beamforming",
    ))
    with pytest.raises(Exception) as exc_info:
        svc.get_scores(db_session, card.id)
    assert exc_info.value.status_code == 404


def test_weight_profile_changes_weights(db_session):
    goal = _create_goal(db_session)
    _seed_evidence(db_session, goal.id, ["beamforming"])
    _seed_evidence(db_session, goal.id, ["beamforming"])
    approaches = _generate_and_review(db_session, goal.id)

    default_result = svc.score_approach(db_session, approaches[0].id, WeightProfileEnum.default)
    default_weights = {d.dimension.value: d.weight for d in default_result.dimensions}

    novel_result = svc.score_approach(db_session, approaches[0].id, WeightProfileEnum.scientific_novelty)
    novel_weights = {d.dimension.value: d.weight for d in novel_result.dimensions}

    assert novel_weights["evidence_strength"] > default_weights["evidence_strength"]


def test_rescore_replaces_old_scores(db_session):
    goal = _create_goal(db_session)
    _seed_evidence(db_session, goal.id, ["beamforming"])
    _seed_evidence(db_session, goal.id, ["beamforming"])
    approaches = _generate_and_review(db_session, goal.id)

    r1 = svc.score_approach(db_session, approaches[0].id)
    r2 = svc.rescore(db_session, approaches[0].id)
    assert r2.scoring_run_id != r1.scoring_run_id

    current = svc.get_scores(db_session, approaches[0].id)
    assert current.scoring_run_id == r2.scoring_run_id


def test_low_confidence_flagged_no_evidence(db_session):
    goal = _create_goal(db_session)
    card = _create_and_review_approach(db_session, goal.id)

    result = svc.score_approach(db_session, card.id)
    ev_dim = next(d for d in result.dimensions if d.dimension == RubricDimensionEnum.evidence_strength)
    assert ev_dim.low_confidence is True


def test_evidence_strength_higher_with_strong_evidence(db_session):
    goal = _create_goal(db_session)
    _seed_evidence(db_session, goal.id, ["beamforming"], strength="strong",
                   metric_names=["acoustic_contrast_db"])
    _seed_evidence(db_session, goal.id, ["beamforming"], strength="strong",
                   metric_names=["latency_ms"])
    approaches = _generate_and_review(db_session, goal.id)
    strong_result = svc.score_approach(db_session, approaches[0].id)

    goal2 = _create_goal(db_session)
    _seed_evidence(db_session, goal2.id, ["beamforming"], strength="weak",
                   metric_names=["acoustic_contrast_db"])
    _seed_evidence(db_session, goal2.id, ["beamforming"], strength="weak",
                   metric_names=["latency_ms"])
    approaches2 = _generate_and_review(db_session, goal2.id)
    weak_result = svc.score_approach(db_session, approaches2[0].id)

    strong_ev = next(d for d in strong_result.dimensions
                     if d.dimension == RubricDimensionEnum.evidence_strength)
    weak_ev = next(d for d in weak_result.dimensions
                   if d.dimension == RubricDimensionEnum.evidence_strength)
    assert strong_ev.score > weak_ev.score


def test_comparison_ranking_order(db_session):
    goal = _create_goal(db_session)
    _seed_evidence(db_session, goal.id, ["beamforming"], metric_names=["acoustic_contrast_db"],
                   strength="strong")
    _seed_evidence(db_session, goal.id, ["beamforming"], metric_names=["latency_ms"],
                   strength="strong")
    _seed_evidence(db_session, goal.id, ["pressure_matching"], strength="weak")
    _seed_evidence(db_session, goal.id, ["pressure_matching"], strength="weak")
    _generate_and_review(db_session, goal.id)
    svc.score_all_approaches(db_session, goal.id)

    comparison = svc.get_comparison(db_session, goal.id)
    assert len(comparison.approaches) == 2
    assert comparison.approaches[0].final_score >= comparison.approaches[1].final_score
    assert len(comparison.dimension_rankings) == 10


def test_pareto_single_approach_is_optimal(db_session):
    goal = _create_goal(db_session)
    _seed_evidence(db_session, goal.id, ["beamforming"])
    _seed_evidence(db_session, goal.id, ["beamforming"])
    _generate_and_review(db_session, goal.id)
    svc.score_all_approaches(db_session, goal.id)

    result = svc.get_pareto(db_session, goal.id)
    assert len(result.pareto_optimal) == 1
    assert len(result.dominated) == 0


def test_pareto_with_multiple_approaches(db_session):
    goal = _create_goal(db_session)
    _seed_evidence(db_session, goal.id, ["beamforming"], metric_names=["acoustic_contrast_db"],
                   strength="strong")
    _seed_evidence(db_session, goal.id, ["beamforming"], metric_names=["latency_ms"],
                   strength="strong")
    _seed_evidence(db_session, goal.id, ["pressure_matching"], strength="weak")
    _seed_evidence(db_session, goal.id, ["pressure_matching"], strength="weak")
    _generate_and_review(db_session, goal.id)
    svc.score_all_approaches(db_session, goal.id)

    result = svc.get_pareto(db_session, goal.id)
    total = len(result.pareto_optimal) + len(result.dominated)
    assert total == 2


def test_each_dimension_has_rationale(db_session):
    goal = _create_goal(db_session)
    _seed_evidence(db_session, goal.id, ["beamforming"])
    _seed_evidence(db_session, goal.id, ["beamforming"])
    approaches = _generate_and_review(db_session, goal.id)

    result = svc.score_approach(db_session, approaches[0].id)
    for d in result.dimensions:
        assert d.rationale
        assert isinstance(d.rationale, str)
        assert len(d.rationale) > 0


def test_risk_penalty_capped_at_02(db_session):
    goal = _create_goal(db_session)
    card = approach_svc.create(db_session, goal.id, ApproachCardCreate(
        name="Risky",
        method_family="beamforming",
        risks_and_limitations=[
            {"description": f"Risk {i}", "severity": "high"} for i in range(10)
        ],
    ))
    approach_svc.transition(db_session, card.id, ApproachStatusEnum.reviewed)

    result = svc.score_approach(db_session, card.id)
    assert result.risk_penalty == 0.2


def test_score_approach_not_found(db_session):
    with pytest.raises(Exception) as exc_info:
        svc.score_approach(db_session, "nonexistent")
    assert exc_info.value.status_code == 404
