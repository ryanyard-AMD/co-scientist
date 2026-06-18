import json
import uuid
from datetime import datetime, timezone

import pytest

from conftest import GOAL_PAYLOAD
from coscientist.models.evidence import EvidenceRecord
from coscientist.schemas.approach import (
    ApproachGenerateRequest,
    ApproachStatusEnum,
)
from coscientist.schemas.experiment import (
    ExperimentCardCreate,
    ExperimentCardUpdate,
    ExperimentGenerateRequest,
    ExperimentStatusEnum,
    ExperimentTypeEnum,
    ValidationCriteria,
    RuntimeSpec,
)
from coscientist.services import approach as approach_svc
from coscientist.services import experiment as svc
from coscientist.services import goal as goal_svc
from coscientist.services import score as score_svc


def _create_goal(db):
    from coscientist.schemas.goal import GoalCreate
    data = GoalCreate(**GOAL_PAYLOAD)
    return goal_svc.create(db, data)


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


def _create_scored_approach(db, goal_id, method_family, hardware=None, strength="strong"):
    _seed_evidence(db, goal_id, [method_family], hardware=hardware, strength=strength)
    _seed_evidence(db, goal_id, [method_family], strength=strength)
    result = approach_svc.generate_approaches(db, goal_id, ApproachGenerateRequest(
        method_families=[method_family],
    ))
    card = result.approaches[0]
    approach_svc.transition(db, card.id, ApproachStatusEnum.reviewed)
    score_svc.score_approach(db, card.id)
    return approach_svc.get(db, card.id)


def _make_experiment_data(approach_ids):
    return ExperimentCardCreate(
        name="Test Experiment",
        objective="Evaluate method",
        hypothesis_text="Method will achieve target performance",
        approach_ids=approach_ids,
        baseline_methods=["delay_and_sum_beamforming"],
        independent_variables={"speaker_count": [4, 8]},
        fixed_assumptions={"room_geometry": "desktop"},
        metrics=["acoustic_contrast_db"],
        validation=ValidationCriteria(
            pass_conditions={"acoustic_contrast_db_min": 12.0},
            comparison={"baseline_improvement_required": True},
        ),
        runtime=RuntimeSpec(preferred="python_numerics_or_treble"),
        artifacts=["metrics_json", "plots"],
    )


# --- CRUD tests ---

def test_create_experiment_card(db_session):
    goal = _create_goal(db_session)
    approach = _create_scored_approach(db_session, goal.id, "beamforming")
    data = _make_experiment_data([approach.id])
    result = svc.create(db_session, goal.id, data)
    assert result.name == "Test Experiment"
    assert result.status == ExperimentStatusEnum.generated
    assert result.approach_ids == [approach.id]
    assert result.parameter_sweep_count == 2


def test_create_validates_goal_exists(db_session):
    with pytest.raises(Exception, match="not found"):
        svc.create(db_session, "nonexistent", _make_experiment_data(["fake"]))


def test_create_validates_approach_ids_exist(db_session):
    goal = _create_goal(db_session)
    with pytest.raises(Exception, match="not found"):
        svc.create(db_session, goal.id, _make_experiment_data(["nonexistent"]))


def test_get_experiment(db_session):
    goal = _create_goal(db_session)
    approach = _create_scored_approach(db_session, goal.id, "beamforming")
    created = svc.create(db_session, goal.id, _make_experiment_data([approach.id]))
    result = svc.get(db_session, created.id)
    assert result.id == created.id
    assert result.objective == "Evaluate method"


def test_get_experiment_not_found(db_session):
    with pytest.raises(Exception, match="not found"):
        svc.get(db_session, "nonexistent")


def test_list_experiments_empty(db_session):
    goal = _create_goal(db_session)
    items, total = svc.list_experiments(db_session, goal.id)
    assert total == 0
    assert items == []


def test_list_experiments_filter_status(db_session):
    goal = _create_goal(db_session)
    approach = _create_scored_approach(db_session, goal.id, "beamforming")
    svc.create(db_session, goal.id, _make_experiment_data([approach.id]))
    items, total = svc.list_experiments(db_session, goal.id, status=ExperimentStatusEnum.generated)
    assert total == 1
    items2, total2 = svc.list_experiments(db_session, goal.id, status=ExperimentStatusEnum.reviewed)
    assert total2 == 0


def test_list_experiments_filter_type(db_session):
    goal = _create_goal(db_session)
    approach = _create_scored_approach(db_session, goal.id, "beamforming")
    svc.create(db_session, goal.id, _make_experiment_data([approach.id]))
    items, total = svc.list_experiments(db_session, goal.id, experiment_type=ExperimentTypeEnum.simulation)
    assert total == 1
    items2, total2 = svc.list_experiments(db_session, goal.id, experiment_type=ExperimentTypeEnum.measurement)
    assert total2 == 0


def test_update_experiment(db_session):
    goal = _create_goal(db_session)
    approach = _create_scored_approach(db_session, goal.id, "beamforming")
    created = svc.create(db_session, goal.id, _make_experiment_data([approach.id]))
    result = svc.update(db_session, created.id, ExperimentCardUpdate(
        objective="Updated objective",
        metrics=["latency_ms", "acoustic_contrast_db"],
    ))
    assert result.objective == "Updated objective"
    assert "latency_ms" in result.metrics


def test_update_experiment_partial(db_session):
    goal = _create_goal(db_session)
    approach = _create_scored_approach(db_session, goal.id, "beamforming")
    created = svc.create(db_session, goal.id, _make_experiment_data([approach.id]))
    result = svc.update(db_session, created.id, ExperimentCardUpdate(name="New Name"))
    assert result.name == "New Name"
    assert result.objective == "Evaluate method"


# --- State machine tests ---

def test_transition_generated_to_reviewed(db_session):
    goal = _create_goal(db_session)
    approach = _create_scored_approach(db_session, goal.id, "beamforming")
    created = svc.create(db_session, goal.id, _make_experiment_data([approach.id]))
    result = svc.transition(db_session, created.id, ExperimentStatusEnum.reviewed)
    assert result.status == ExperimentStatusEnum.reviewed


def test_transition_reviewed_to_approved(db_session):
    goal = _create_goal(db_session)
    approach = _create_scored_approach(db_session, goal.id, "beamforming")
    created = svc.create(db_session, goal.id, _make_experiment_data([approach.id]))
    svc.transition(db_session, created.id, ExperimentStatusEnum.reviewed)
    result = svc.transition(db_session, created.id, ExperimentStatusEnum.approved)
    assert result.status == ExperimentStatusEnum.approved


def test_transition_approved_to_running(db_session):
    goal = _create_goal(db_session)
    approach = _create_scored_approach(db_session, goal.id, "beamforming")
    created = svc.create(db_session, goal.id, _make_experiment_data([approach.id]))
    svc.transition(db_session, created.id, ExperimentStatusEnum.reviewed)
    svc.transition(db_session, created.id, ExperimentStatusEnum.approved)
    result = svc.transition(db_session, created.id, ExperimentStatusEnum.running)
    assert result.status == ExperimentStatusEnum.running


def test_transition_running_to_completed(db_session):
    goal = _create_goal(db_session)
    approach = _create_scored_approach(db_session, goal.id, "beamforming")
    created = svc.create(db_session, goal.id, _make_experiment_data([approach.id]))
    svc.transition(db_session, created.id, ExperimentStatusEnum.reviewed)
    svc.transition(db_session, created.id, ExperimentStatusEnum.approved)
    svc.transition(db_session, created.id, ExperimentStatusEnum.running)
    result = svc.transition(db_session, created.id, ExperimentStatusEnum.completed)
    assert result.status == ExperimentStatusEnum.completed


def test_transition_running_to_failed(db_session):
    goal = _create_goal(db_session)
    approach = _create_scored_approach(db_session, goal.id, "beamforming")
    created = svc.create(db_session, goal.id, _make_experiment_data([approach.id]))
    svc.transition(db_session, created.id, ExperimentStatusEnum.reviewed)
    svc.transition(db_session, created.id, ExperimentStatusEnum.approved)
    svc.transition(db_session, created.id, ExperimentStatusEnum.running)
    result = svc.transition(db_session, created.id, ExperimentStatusEnum.failed)
    assert result.status == ExperimentStatusEnum.failed


def test_transition_superseded_is_terminal(db_session):
    goal = _create_goal(db_session)
    approach = _create_scored_approach(db_session, goal.id, "beamforming")
    created = svc.create(db_session, goal.id, _make_experiment_data([approach.id]))
    svc.transition(db_session, created.id, ExperimentStatusEnum.superseded)
    with pytest.raises(Exception, match="Cannot transition"):
        svc.transition(db_session, created.id, ExperimentStatusEnum.reviewed)


def test_transition_invalid_raises_422(db_session):
    goal = _create_goal(db_session)
    approach = _create_scored_approach(db_session, goal.id, "beamforming")
    created = svc.create(db_session, goal.id, _make_experiment_data([approach.id]))
    with pytest.raises(Exception, match="Cannot transition"):
        svc.transition(db_session, created.id, ExperimentStatusEnum.approved)


def test_delete_generated_experiment(db_session):
    goal = _create_goal(db_session)
    approach = _create_scored_approach(db_session, goal.id, "beamforming")
    created = svc.create(db_session, goal.id, _make_experiment_data([approach.id]))
    svc.delete(db_session, created.id)
    with pytest.raises(Exception, match="not found"):
        svc.get(db_session, created.id)


def test_delete_reviewed_raises_409(db_session):
    goal = _create_goal(db_session)
    approach = _create_scored_approach(db_session, goal.id, "beamforming")
    created = svc.create(db_session, goal.id, _make_experiment_data([approach.id]))
    svc.transition(db_session, created.id, ExperimentStatusEnum.reviewed)
    with pytest.raises(Exception, match="Only generated"):
        svc.delete(db_session, created.id)


# --- Generation tests ---

def test_generate_experiments_from_approaches(db_session):
    goal = _create_goal(db_session)
    a1 = _create_scored_approach(db_session, goal.id, "beamforming")
    a2 = _create_scored_approach(db_session, goal.id, "pressure_matching")
    result = svc.generate_experiments(db_session, goal.id, ExperimentGenerateRequest())
    assert result.experiments_created >= 1
    for exp in result.experiments:
        assert exp.objective
        assert exp.hypothesis_text
        assert exp.baseline_methods
        assert exp.independent_variables
        assert exp.metrics
        assert exp.artifacts


def test_generate_experiments_from_specific_approaches(db_session):
    goal = _create_goal(db_session)
    a1 = _create_scored_approach(db_session, goal.id, "beamforming")
    result = svc.generate_experiments(db_session, goal.id, ExperimentGenerateRequest(
        approach_ids=[a1.id],
    ))
    assert result.experiments_created == 1
    assert a1.id in result.experiments[0].approach_ids


def test_generate_needs_approaches(db_session):
    goal = _create_goal(db_session)
    result = svc.generate_experiments(db_session, goal.id, ExperimentGenerateRequest())
    assert result.experiments_created == 0


def test_generate_skips_duplicate_approach_sets(db_session):
    goal = _create_goal(db_session)
    a1 = _create_scored_approach(db_session, goal.id, "beamforming")
    result1 = svc.generate_experiments(db_session, goal.id, ExperimentGenerateRequest(
        approach_ids=[a1.id],
    ))
    assert result1.experiments_created == 1
    result2 = svc.generate_experiments(db_session, goal.id, ExperimentGenerateRequest(
        approach_ids=[a1.id],
    ))
    assert result2.experiments_created == 0
    assert result2.experiments_skipped_duplicate == 1


def test_generate_respects_max_experiments(db_session):
    goal = _create_goal(db_session)
    _create_scored_approach(db_session, goal.id, "beamforming")
    _create_scored_approach(db_session, goal.id, "pressure_matching")
    _create_scored_approach(db_session, goal.id, "acoustic_contrast_control")
    result = svc.generate_experiments(db_session, goal.id, ExperimentGenerateRequest(
        max_experiments=2,
    ))
    assert result.experiments_created == 2


def test_generate_includes_baselines(db_session):
    goal = _create_goal(db_session)
    a1 = _create_scored_approach(db_session, goal.id, "beamforming")
    result = svc.generate_experiments(db_session, goal.id, ExperimentGenerateRequest(
        approach_ids=[a1.id],
    ))
    exp = result.experiments[0]
    assert "delay_and_sum_beamforming" in exp.baseline_methods


def test_generate_includes_parameter_sweeps(db_session):
    goal = _create_goal(db_session)
    a1 = _create_scored_approach(db_session, goal.id, "beamforming")
    result = svc.generate_experiments(db_session, goal.id, ExperimentGenerateRequest(
        approach_ids=[a1.id],
    ))
    exp = result.experiments[0]
    assert "speaker_count" in exp.independent_variables
    assert "listener_shift_cm" in exp.independent_variables
    assert "frequency_band_hz" in exp.independent_variables


def test_generate_derives_metrics_from_goal(db_session):
    goal = _create_goal(db_session)
    a1 = _create_scored_approach(db_session, goal.id, "beamforming")
    result = svc.generate_experiments(db_session, goal.id, ExperimentGenerateRequest(
        approach_ids=[a1.id],
    ))
    exp = result.experiments[0]
    assert "acoustic_contrast_db" in exp.metrics
    assert "latency_ms" in exp.metrics


def test_generate_derives_validation_from_goal(db_session):
    goal = _create_goal(db_session)
    a1 = _create_scored_approach(db_session, goal.id, "beamforming")
    result = svc.generate_experiments(db_session, goal.id, ExperimentGenerateRequest(
        approach_ids=[a1.id],
    ))
    exp = result.experiments[0]
    assert "acoustic_contrast_min" in exp.validation.pass_conditions
    assert "latency_max" in exp.validation.pass_conditions


def test_generate_estimates_cost(db_session):
    goal = _create_goal(db_session)
    a1 = _create_scored_approach(db_session, goal.id, "beamforming")
    result = svc.generate_experiments(db_session, goal.id, ExperimentGenerateRequest(
        approach_ids=[a1.id],
    ))
    exp = result.experiments[0]
    assert exp.estimated_cost in ("low", "medium", "high")
    assert exp.estimated_runtime in ("low", "medium", "high")
    assert exp.parameter_sweep_count > 0


def test_generate_comparative_experiment(db_session):
    goal = _create_goal(db_session)
    a1 = _create_scored_approach(db_session, goal.id, "beamforming")
    a2 = _create_scored_approach(db_session, goal.id, "pressure_matching")
    result = svc.generate_experiments(db_session, goal.id, ExperimentGenerateRequest())
    comparative = [e for e in result.experiments if len(e.approach_ids) == 2]
    assert len(comparative) >= 1
    comp = comparative[0]
    assert "vs" in comp.name


# --- Export tests ---

def test_export_yaml_format(db_session):
    goal = _create_goal(db_session)
    approach = _create_scored_approach(db_session, goal.id, "beamforming")
    created = svc.create(db_session, goal.id, _make_experiment_data([approach.id]))
    result = svc.export_experiment(db_session, created.id, "yaml")
    assert result.format == "yaml"
    assert "experiment_card" in result.content
    assert "objective" in result.content


def test_export_python_format(db_session):
    goal = _create_goal(db_session)
    approach = _create_scored_approach(db_session, goal.id, "beamforming")
    created = svc.create(db_session, goal.id, _make_experiment_data([approach.id]))
    result = svc.export_experiment(db_session, created.id, "python")
    assert result.format == "python"
    assert "experiment_card" in result.content


def test_export_invalid_format_422(db_session):
    goal = _create_goal(db_session)
    approach = _create_scored_approach(db_session, goal.id, "beamforming")
    created = svc.create(db_session, goal.id, _make_experiment_data([approach.id]))
    with pytest.raises(Exception, match="Unsupported"):
        svc.export_experiment(db_session, created.id, "csv")


# --- Scoring tests ---

def test_score_experiment_returns_all_dimensions(db_session):
    goal = _create_goal(db_session)
    approach = _create_scored_approach(db_session, goal.id, "beamforming")
    created = svc.create(db_session, goal.id, _make_experiment_data([approach.id]))
    result = svc.score_experiment(db_session, created.id, goal.id)
    assert len(result.dimensions) == 10
    assert result.total_score > 0


def test_score_experiment_weights_sum_to_1(db_session):
    total_weight = sum(svc.EXPERIMENT_WEIGHTS.values())
    assert abs(total_weight - 1.0) < 0.001
