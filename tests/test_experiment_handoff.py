"""CS-EPIC-EXPERIMENT — execution handoff schema, batch modes, execution lifecycle."""

import pytest

from conftest import GOAL_PAYLOAD
from coscientist.schemas.approach import ApproachGenerateRequest, ApproachStatusEnum
from coscientist.schemas.experiment import (
    ExecutionStatusEnum,
    ExperimentCardCreate,
    ExperimentCardUpdate,
    HandoffStatusEnum,
    RuntimeSpec,
    SubmissionModeEnum,
    ValidationCriteria,
)
from coscientist.schemas.goal import GoalCreate
from coscientist.services import approach as approach_svc
from coscientist.services import experiment as svc
from coscientist.services import goal as goal_svc
from coscientist.services import score as score_svc

from test_experiment_service import _seed_evidence


def _goal(db):
    return goal_svc.create(db, GoalCreate(**GOAL_PAYLOAD))


def _scored_approach(db, goal_id, method_family="beamforming"):
    _seed_evidence(db, goal_id, [method_family])
    _seed_evidence(db, goal_id, [method_family])
    result = approach_svc.generate_approaches(db, goal_id, ApproachGenerateRequest(method_families=[method_family]))
    card = result.approaches[0]
    approach_svc.transition(db, card.id, ApproachStatusEnum.reviewed)
    score_svc.score_approach(db, card.id)
    return approach_svc.get(db, card.id)


def _data(approach_ids, **overrides):
    base = dict(
        name="Test Experiment",
        objective="Evaluate method",
        hypothesis_text="Method will achieve target performance",
        approach_ids=approach_ids,
        baseline_methods=["delay_and_sum_beamforming"],
        independent_variables={"speaker_count": [4, 8]},
        fixed_assumptions={"room_geometry": "desktop"},
        metrics=["acoustic_contrast_db"],
        validation=ValidationCriteria(pass_conditions={"acoustic_contrast_db_min": 12.0}),
        runtime=RuntimeSpec(preferred="python_numerics_or_treble"),
        artifacts=["metrics_json"],
    )
    base.update(overrides)
    return ExperimentCardCreate(**base)


def test_new_card_has_default_handoff_state(db_session):
    goal = _goal(db_session)
    ac = _scored_approach(db_session, goal.id)
    card = svc.create(db_session, goal.id, _data([ac.id]))
    assert card.execution_status == ExecutionStatusEnum.not_submitted
    assert card.execution_handoff.handoff_status == HandoffStatusEnum.not_submitted
    assert card.execution_handoff.submission_mode == SubmissionModeEnum.single_run
    assert card.execution_handoff.run_request_ids == []
    assert card.execution_handoff.result_bundle_ids == []
    # capabilities derived from runtime when not supplied
    assert card.execution_handoff.required_capabilities == ["python_numerics"]


def test_create_accepts_handoff_config(db_session):
    goal = _goal(db_session)
    ac = _scored_approach(db_session, goal.id)
    card = svc.create(db_session, goal.id, _data(
        [ac.id],
        submission_mode=SubmissionModeEnum.sweep_batch,
        required_capabilities=["gpu", "treble_solver"],
        runner_pool_preference="gpu-pool",
        experiment_control_plane="http://exp-system/api",
    ))
    hb = card.execution_handoff
    assert hb.submission_mode == SubmissionModeEnum.sweep_batch
    assert hb.required_capabilities == ["gpu", "treble_solver"]
    assert hb.runner_pool_preference == "gpu-pool"
    assert hb.experiment_control_plane == "http://exp-system/api"
    # sweep of 2 => expected 2 runs
    assert hb.expected_run_count == 2


def test_update_handoff_config(db_session):
    goal = _goal(db_session)
    ac = _scored_approach(db_session, goal.id)
    card = svc.create(db_session, goal.id, _data([ac.id]))
    updated = svc.update(db_session, card.id, ExperimentCardUpdate(
        submission_mode=SubmissionModeEnum.run_request_batch,
        runner_pool_preference="cpu-pool",
    ))
    assert updated.execution_handoff.submission_mode == SubmissionModeEnum.run_request_batch
    assert updated.execution_handoff.runner_pool_preference == "cpu-pool"


def test_execution_status_transition_valid(db_session):
    goal = _goal(db_session)
    ac = _scored_approach(db_session, goal.id)
    card = svc.create(db_session, goal.id, _data([ac.id]))
    svc.set_execution_status(db_session, card.id, ExecutionStatusEnum.submitted)
    svc.set_execution_status(db_session, card.id, ExecutionStatusEnum.queued)
    running = svc.set_execution_status(db_session, card.id, ExecutionStatusEnum.running)
    assert running.execution_status == ExecutionStatusEnum.running
    # approval lifecycle is untouched by execution updates
    assert running.status.value == "generated"


def test_execution_status_transition_invalid(db_session):
    goal = _goal(db_session)
    ac = _scored_approach(db_session, goal.id)
    card = svc.create(db_session, goal.id, _data([ac.id]))
    with pytest.raises(Exception, match="Cannot transition execution status"):
        svc.set_execution_status(db_session, card.id, ExecutionStatusEnum.completed)


def test_execution_status_idempotent_force(db_session):
    goal = _goal(db_session)
    ac = _scored_approach(db_session, goal.id)
    card = svc.create(db_session, goal.id, _data([ac.id]))
    svc.set_execution_status(db_session, card.id, ExecutionStatusEnum.submitted)
    svc.set_execution_status(db_session, card.id, ExecutionStatusEnum.completed, force=True)
    # replaying the same terminal status is a no-op, not an error
    again = svc.set_execution_status(db_session, card.id, ExecutionStatusEnum.completed, force=True)
    assert again.execution_status == ExecutionStatusEnum.completed


def test_new_lifecycle_states(db_session):
    goal = _goal(db_session)
    ac = _scored_approach(db_session, goal.id)
    card = svc.create(db_session, goal.id, _data([ac.id]))
    from coscientist.schemas.experiment import ExperimentStatusEnum
    nr = svc.transition(db_session, card.id, ExperimentStatusEnum.needs_review)
    assert nr.status == ExperimentStatusEnum.needs_review
    rej = svc.transition(db_session, card.id, ExperimentStatusEnum.rejected)
    assert rej.status == ExperimentStatusEnum.rejected
    arch = svc.transition(db_session, card.id, ExperimentStatusEnum.archived)
    assert arch.status == ExperimentStatusEnum.archived


def test_preview_run_requests_sweep(db_session):
    goal = _goal(db_session)
    ac = _scored_approach(db_session, goal.id)
    card = svc.create(db_session, goal.id, _data(
        [ac.id],
        submission_mode=SubmissionModeEnum.sweep_batch,
        independent_variables={"speaker_count": [4, 8], "listener_shift_cm": [0, 5, 10]},
    ))
    preview = svc.preview_run_requests(db_session, card.id)
    assert preview.submission_mode == SubmissionModeEnum.sweep_batch
    assert preview.expanded_run_count == 6
    assert len(preview.runs) == 6
    assert preview.truncated is False
    assert preview.requires_human_approval is True
    assert {"speaker_count", "listener_shift_cm"} == set(preview.runs[0].parameters)


def test_preview_run_requests_single(db_session):
    goal = _goal(db_session)
    ac = _scored_approach(db_session, goal.id)
    card = svc.create(db_session, goal.id, _data([ac.id]))
    preview = svc.preview_run_requests(db_session, card.id)
    assert preview.submission_mode == SubmissionModeEnum.single_run
    assert preview.expanded_run_count == 1
    assert len(preview.runs) == 1


def test_preview_truncates_large_sweep(db_session):
    goal = _goal(db_session)
    ac = _scored_approach(db_session, goal.id)
    card = svc.create(db_session, goal.id, _data(
        [ac.id],
        submission_mode=SubmissionModeEnum.sweep_batch,
        independent_variables={"a": list(range(10)), "b": list(range(10))},
    ))
    preview = svc.preview_run_requests(db_session, card.id, cap=25)
    assert preview.truncated is True
    assert len(preview.runs) == 25
    assert preview.expanded_run_count == 100
