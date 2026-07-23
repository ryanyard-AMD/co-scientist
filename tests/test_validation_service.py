import json
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from conftest import GOAL_PAYLOAD
from coscientist.models.approach import ApproachCard
from coscientist.models.evidence import EvidenceRecord
from coscientist.models.experiment import ExperimentCard
from coscientist.schemas.approach import (
    ApproachGenerateRequest,
    ApproachMaturityEnum,
    ApproachStatusEnum,
)
from coscientist.schemas.experiment import (
    ExperimentCardCreate,
    ExperimentStatusEnum,
    ExperimentTypeEnum,
    ValidationCriteria,
)
from coscientist.schemas.validation import (
    AgentValidationOutput,
    CriterionResult,
    ExperimentResultSubmission,
    ReproductionStatusEnum,
    ValidationDecisionEnum,
)
from coscientist.services import approach as approach_svc
from coscientist.services import experiment as experiment_svc
from coscientist.services import goal as goal_svc
from coscientist.services import score as score_svc
from coscientist.services import validation as svc
from coscientist.services.validation import _advance_maturity


MOCK_VALIDATED = AgentValidationOutput(
    decision=ValidationDecisionEnum.validated,
    confidence=0.92,
    reasoning="All criteria passed.",
    criterion_results=[
        CriterionResult(name="acoustic_contrast", measured=18.5, target=15.0,
                        operator=">=", passed=True, unit="dB"),
        CriterionResult(name="latency", measured=8.2, target=10.0,
                        operator="<=", passed=True, unit="ms"),
    ],
    refinement_suggestions=[],
)

MOCK_REFUTED = AgentValidationOutput(
    decision=ValidationDecisionEnum.refuted,
    confidence=0.85,
    reasoning="Acoustic contrast criterion failed.",
    criterion_results=[
        CriterionResult(name="acoustic_contrast", measured=12.0, target=15.0,
                        operator=">=", passed=False, unit="dB"),
    ],
    refinement_suggestions=["Increase speaker count to 8", "Adjust filter design"],
)


def _create_goal(db):
    from coscientist.schemas.goal import GoalCreate
    return goal_svc.create(db, GoalCreate(**GOAL_PAYLOAD))


def _seed_evidence(db, workspace_id, method_family="beamforming"):
    now = datetime.now(timezone.utc)
    for _ in range(2):
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
            method_families=json.dumps([method_family]),
            metric_names=json.dumps([]),
            hardware_assumptions=json.dumps([]),
            failure_modes=json.dumps([]),
            is_primary_method=True,
            evidence_strength="strong",
            created_at=now,
        )
        db.add(rec)
    db.commit()


def _create_scored_approach(db, goal_id, method_family="beamforming"):
    _seed_evidence(db, goal_id, method_family)
    result = approach_svc.generate_approaches(db, goal_id, ApproachGenerateRequest(
        method_families=[method_family],
    ))
    card = result.approaches[0]
    approach_svc.transition(db, card.id, ApproachStatusEnum.reviewed)
    score_svc.score_approach(db, card.id)
    return approach_svc.get(db, card.id)


def _advance_to_experiment_proposed(db, approach_id):
    approach_svc.transition(db, approach_id, ApproachStatusEnum.experiment_proposed)


def _create_running_experiment(db, goal_id, approach_id,
                               experiment_type=ExperimentTypeEnum.simulation):
    exp = experiment_svc.create(db, goal_id, ExperimentCardCreate(
        name="Test Experiment",
        objective="Evaluate method",
        hypothesis_text="Method achieves target",
        approach_ids=[approach_id],
        validation=ValidationCriteria(
            pass_conditions={"acoustic_contrast_min": 15.0, "latency_max": 10.0},
        ),
        experiment_type=experiment_type,
    ))
    experiment_svc.transition(db, exp.id, ExperimentStatusEnum.reviewed)
    experiment_svc.transition(db, exp.id, ExperimentStatusEnum.approved)
    experiment_svc.transition(db, exp.id, ExperimentStatusEnum.running)
    return experiment_svc.get(db, exp.id)


# ---------------------------------------------------------------------------
# submit_results — error cases
# ---------------------------------------------------------------------------

@patch("coscientist.services.validation._run_validation_agent")
def test_submit_results_experiment_not_found(mock_agent, db_session):
    from fastapi import HTTPException
    mock_agent.return_value = MOCK_VALIDATED
    goal = _create_goal(db_session)
    with pytest.raises(HTTPException) as exc_info:
        svc.submit_results(db_session, "nonexistent", goal.id,
                           ExperimentResultSubmission(measured_metrics={}))
    assert exc_info.value.status_code == 404


@patch("coscientist.services.validation._run_validation_agent")
def test_submit_results_wrong_goal_returns_404(mock_agent, db_session):
    from fastapi import HTTPException
    mock_agent.return_value = MOCK_VALIDATED
    goal = _create_goal(db_session)
    approach = _create_scored_approach(db_session, goal.id)
    _advance_to_experiment_proposed(db_session, approach.id)
    exp = _create_running_experiment(db_session, goal.id, approach.id)
    with pytest.raises(HTTPException) as exc_info:
        svc.submit_results(db_session, exp.id, "wrong-goal",
                           ExperimentResultSubmission(measured_metrics={}))
    assert exc_info.value.status_code == 404


def test_submit_results_not_running_returns_409(db_session):
    from fastapi import HTTPException
    goal = _create_goal(db_session)
    approach = _create_scored_approach(db_session, goal.id)
    exp = experiment_svc.create(db_session, goal.id, ExperimentCardCreate(
        name="Not Running",
        objective="Test",
        hypothesis_text="Hypothesis",
        approach_ids=[approach.id],
    ))
    with pytest.raises(HTTPException) as exc_info:
        svc.submit_results(db_session, exp.id, goal.id,
                           ExperimentResultSubmission(measured_metrics={}))
    assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# submit_results — happy path (validated)
# ---------------------------------------------------------------------------

@patch("coscientist.services.validation._run_validation_agent")
def test_submit_results_creates_validation_result(mock_agent, db_session):
    mock_agent.return_value = MOCK_VALIDATED
    goal = _create_goal(db_session)
    approach = _create_scored_approach(db_session, goal.id)
    _advance_to_experiment_proposed(db_session, approach.id)
    exp = _create_running_experiment(db_session, goal.id, approach.id)
    submission = ExperimentResultSubmission(
        measured_metrics={"acoustic_contrast": 18.5, "latency": 8.2},
    )
    result = svc.submit_results(db_session, exp.id, goal.id, submission)
    assert result.decision == ValidationDecisionEnum.validated
    assert result.experiment_id == exp.id
    assert result.goal_id == goal.id
    assert result.confidence == 0.92


@patch("coscientist.services.validation._run_validation_agent")
def test_submit_results_stores_measured_metrics(mock_agent, db_session):
    mock_agent.return_value = MOCK_VALIDATED
    goal = _create_goal(db_session)
    approach = _create_scored_approach(db_session, goal.id)
    _advance_to_experiment_proposed(db_session, approach.id)
    exp = _create_running_experiment(db_session, goal.id, approach.id)
    submission = ExperimentResultSubmission(
        measured_metrics={"acoustic_contrast": 18.5, "latency": 8.2},
    )
    result = svc.submit_results(db_session, exp.id, goal.id, submission)
    assert result.measured_metrics == {"acoustic_contrast": 18.5, "latency": 8.2}


@patch("coscientist.services.validation._run_validation_agent")
def test_submit_results_stores_artifact_paths(mock_agent, db_session):
    mock_agent.return_value = MOCK_VALIDATED
    goal = _create_goal(db_session)
    approach = _create_scored_approach(db_session, goal.id)
    _advance_to_experiment_proposed(db_session, approach.id)
    exp = _create_running_experiment(db_session, goal.id, approach.id)
    submission = ExperimentResultSubmission(
        measured_metrics={"acoustic_contrast": 18.5},
        artifact_paths={"metrics_json": "/results/metrics.json"},
    )
    result = svc.submit_results(db_session, exp.id, goal.id, submission)
    assert result.artifact_paths == {"metrics_json": "/results/metrics.json"}


@patch("coscientist.services.validation._run_validation_agent")
def test_submit_results_experiment_transitions_to_completed(mock_agent, db_session):
    mock_agent.return_value = MOCK_VALIDATED
    goal = _create_goal(db_session)
    approach = _create_scored_approach(db_session, goal.id)
    _advance_to_experiment_proposed(db_session, approach.id)
    exp = _create_running_experiment(db_session, goal.id, approach.id)
    svc.submit_results(db_session, exp.id, goal.id,
                       ExperimentResultSubmission(measured_metrics={}))
    updated = experiment_svc.get(db_session, exp.id)
    assert updated.status == ExperimentStatusEnum.completed


@patch("coscientist.services.validation._run_validation_agent")
def test_submit_results_approach_transitions_to_validated(mock_agent, db_session):
    mock_agent.return_value = MOCK_VALIDATED
    goal = _create_goal(db_session)
    approach = _create_scored_approach(db_session, goal.id)
    _advance_to_experiment_proposed(db_session, approach.id)
    exp = _create_running_experiment(db_session, goal.id, approach.id)
    svc.submit_results(db_session, exp.id, goal.id,
                       ExperimentResultSubmission(measured_metrics={}))
    updated = approach_svc.get(db_session, approach.id)
    assert updated.status == ApproachStatusEnum.validated


# ---------------------------------------------------------------------------
# submit_results — refuted path
# ---------------------------------------------------------------------------

@patch("coscientist.services.validation._run_validation_agent")
def test_submit_results_experiment_transitions_to_failed(mock_agent, db_session):
    mock_agent.return_value = MOCK_REFUTED
    goal = _create_goal(db_session)
    approach = _create_scored_approach(db_session, goal.id)
    _advance_to_experiment_proposed(db_session, approach.id)
    exp = _create_running_experiment(db_session, goal.id, approach.id)
    svc.submit_results(db_session, exp.id, goal.id,
                       ExperimentResultSubmission(measured_metrics={}))
    updated = experiment_svc.get(db_session, exp.id)
    assert updated.status == ExperimentStatusEnum.failed


@patch("coscientist.services.validation._run_validation_agent")
def test_submit_results_approach_transitions_to_refuted(mock_agent, db_session):
    mock_agent.return_value = MOCK_REFUTED
    goal = _create_goal(db_session)
    approach = _create_scored_approach(db_session, goal.id)
    _advance_to_experiment_proposed(db_session, approach.id)
    exp = _create_running_experiment(db_session, goal.id, approach.id)
    svc.submit_results(db_session, exp.id, goal.id,
                       ExperimentResultSubmission(measured_metrics={}))
    updated = approach_svc.get(db_session, approach.id)
    assert updated.status == ApproachStatusEnum.refuted


@patch("coscientist.services.validation._run_validation_agent")
def test_submit_results_refinement_suggestions_stored(mock_agent, db_session):
    mock_agent.return_value = MOCK_REFUTED
    goal = _create_goal(db_session)
    approach = _create_scored_approach(db_session, goal.id)
    _advance_to_experiment_proposed(db_session, approach.id)
    exp = _create_running_experiment(db_session, goal.id, approach.id)
    result = svc.submit_results(db_session, exp.id, goal.id,
                                ExperimentResultSubmission(measured_metrics={}))
    assert len(result.refinement_suggestions) == 2
    assert "speaker count" in result.refinement_suggestions[0]


# ---------------------------------------------------------------------------
# submit_results — maturity advancement
# ---------------------------------------------------------------------------

@patch("coscientist.services.validation._run_validation_agent")
def test_maturity_advanced_to_simulated_for_simulation(mock_agent, db_session):
    mock_agent.return_value = MOCK_VALIDATED
    goal = _create_goal(db_session)
    approach = _create_scored_approach(db_session, goal.id)
    _advance_to_experiment_proposed(db_session, approach.id)
    exp = _create_running_experiment(db_session, goal.id, approach.id,
                                     experiment_type=ExperimentTypeEnum.simulation)
    svc.submit_results(db_session, exp.id, goal.id,
                       ExperimentResultSubmission(measured_metrics={}))
    updated = approach_svc.get(db_session, approach.id)
    assert updated.maturity == ApproachMaturityEnum.simulated


@patch("coscientist.services.validation._run_validation_agent")
def test_maturity_advanced_to_measured_for_measurement(mock_agent, db_session):
    mock_agent.return_value = MOCK_VALIDATED
    goal = _create_goal(db_session)
    approach = _create_scored_approach(db_session, goal.id)
    _advance_to_experiment_proposed(db_session, approach.id)
    exp = _create_running_experiment(db_session, goal.id, approach.id,
                                     experiment_type=ExperimentTypeEnum.measurement)
    svc.submit_results(db_session, exp.id, goal.id,
                       ExperimentResultSubmission(measured_metrics={}))
    updated = approach_svc.get(db_session, approach.id)
    assert updated.maturity == ApproachMaturityEnum.measured


# ---------------------------------------------------------------------------
# submit_results — approach already in tested state
# ---------------------------------------------------------------------------

@patch("coscientist.services.validation._run_validation_agent")
def test_approach_already_tested_still_transitions(mock_agent, db_session):
    mock_agent.return_value = MOCK_VALIDATED
    goal = _create_goal(db_session)
    approach = _create_scored_approach(db_session, goal.id)
    # Manually set approach to tested (skipping experiment_proposed)
    approach_svc.transition(db_session, approach.id, ApproachStatusEnum.experiment_proposed)
    approach_svc.transition(db_session, approach.id, ApproachStatusEnum.tested)
    exp = _create_running_experiment(db_session, goal.id, approach.id)
    svc.submit_results(db_session, exp.id, goal.id,
                       ExperimentResultSubmission(measured_metrics={}))
    updated = approach_svc.get(db_session, approach.id)
    assert updated.status == ApproachStatusEnum.validated


# ---------------------------------------------------------------------------
# get_result
# ---------------------------------------------------------------------------

@patch("coscientist.services.validation._run_validation_agent")
def test_get_result_returns_response(mock_agent, db_session):
    mock_agent.return_value = MOCK_VALIDATED
    goal = _create_goal(db_session)
    approach = _create_scored_approach(db_session, goal.id)
    _advance_to_experiment_proposed(db_session, approach.id)
    exp = _create_running_experiment(db_session, goal.id, approach.id)
    svc.submit_results(db_session, exp.id, goal.id,
                       ExperimentResultSubmission(measured_metrics={}))
    result = svc.get_result(db_session, exp.id, goal.id)
    assert result is not None
    assert result.experiment_id == exp.id


def test_get_result_returns_none_when_no_result(db_session):
    goal = _create_goal(db_session)
    approach = _create_scored_approach(db_session, goal.id)
    _advance_to_experiment_proposed(db_session, approach.id)
    exp = _create_running_experiment(db_session, goal.id, approach.id)
    result = svc.get_result(db_session, exp.id, goal.id)
    assert result is None


# ---------------------------------------------------------------------------
# list_results
# ---------------------------------------------------------------------------

@patch("coscientist.services.validation._run_validation_agent")
def test_list_results_returns_all_for_goal(mock_agent, db_session):
    mock_agent.return_value = MOCK_VALIDATED
    goal = _create_goal(db_session)
    approach = _create_scored_approach(db_session, goal.id)
    _advance_to_experiment_proposed(db_session, approach.id)
    exp = _create_running_experiment(db_session, goal.id, approach.id)
    svc.submit_results(db_session, exp.id, goal.id,
                       ExperimentResultSubmission(measured_metrics={}))
    result = svc.list_results(db_session, goal.id)
    assert result.total == 1
    assert result.items[0].experiment_id == exp.id


def test_list_results_empty_for_goal_with_no_runs(db_session):
    goal = _create_goal(db_session)
    result = svc.list_results(db_session, goal.id)
    assert result.total == 0
    assert result.items == []


# ---------------------------------------------------------------------------
# _advance_maturity unit tests
# ---------------------------------------------------------------------------

def test_advance_maturity_theoretical_to_simulated():
    card = ApproachCard(maturity=ApproachMaturityEnum.theoretical.value)
    assert _advance_maturity(card, ExperimentTypeEnum.simulation.value) == ApproachMaturityEnum.simulated.value


def test_advance_maturity_theoretical_to_measured():
    card = ApproachCard(maturity=ApproachMaturityEnum.theoretical.value)
    assert _advance_maturity(card, ExperimentTypeEnum.measurement.value) == ApproachMaturityEnum.measured.value


def test_advance_maturity_simulated_to_measured():
    card = ApproachCard(maturity=ApproachMaturityEnum.simulated.value)
    assert _advance_maturity(card, ExperimentTypeEnum.measurement.value) == ApproachMaturityEnum.measured.value


def test_advance_maturity_does_not_downgrade_measured():
    card = ApproachCard(maturity=ApproachMaturityEnum.measured.value)
    assert _advance_maturity(card, ExperimentTypeEnum.simulation.value) == ApproachMaturityEnum.measured.value


def test_advance_maturity_does_not_downgrade_validated():
    card = ApproachCard(maturity=ApproachMaturityEnum.validated.value)
    assert _advance_maturity(card, ExperimentTypeEnum.measurement.value) == ApproachMaturityEnum.validated.value


# ---------------------------------------------------------------------------
# _run_validation_agent — mock anthropic client
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# reproduction_status derivation (CS-VALIDATION-005)
# ---------------------------------------------------------------------------

from coscientist.services.validation import _derive_reproduction_status


def _cr(passed, measured=10.0):
    return CriterionResult(name="m", measured=measured, target=5.0,
                           operator=">=", passed=passed, unit="dB")


def test_derive_reproduction_blocked_when_nothing_measurable():
    assert _derive_reproduction_status([]) == ReproductionStatusEnum.blocked
    assert _derive_reproduction_status(
        [CriterionResult(name="m", measured=None, target=5.0, operator=">=", passed=False, unit="")]
    ) == ReproductionStatusEnum.blocked


def test_derive_reproduction_reproduced_when_all_pass():
    assert _derive_reproduction_status([_cr(True), _cr(True)]) == ReproductionStatusEnum.reproduced


def test_derive_reproduction_failed_when_none_pass():
    assert _derive_reproduction_status([_cr(False), _cr(False)]) == ReproductionStatusEnum.failed


def test_derive_reproduction_partial_when_some_pass():
    assert _derive_reproduction_status([_cr(True), _cr(False)]) == ReproductionStatusEnum.partially_reproduced


@patch("coscientist.services.validation._run_validation_agent")
def test_submit_sets_reproduction_status_reproduced(mock_agent, db_session):
    mock_agent.return_value = MOCK_VALIDATED
    goal = _create_goal(db_session)
    approach = _create_scored_approach(db_session, goal.id)
    _advance_to_experiment_proposed(db_session, approach.id)
    exp = _create_running_experiment(db_session, goal.id, approach.id)
    result = svc.submit_results(db_session, exp.id, goal.id,
                                ExperimentResultSubmission(measured_metrics={}))
    assert result.reproduction_status == ReproductionStatusEnum.reproduced


@patch("coscientist.services.validation._run_validation_agent")
def test_resubmit_supersedes_prior_result(mock_agent, db_session):
    from coscientist.models.validation import ValidationResult
    from coscientist.schemas.experiment import ExperimentStatusEnum

    mock_agent.return_value = MOCK_VALIDATED
    goal = _create_goal(db_session)
    approach = _create_scored_approach(db_session, goal.id)
    _advance_to_experiment_proposed(db_session, approach.id)
    exp = _create_running_experiment(db_session, goal.id, approach.id)
    first = svc.submit_results(db_session, exp.id, goal.id,
                              ExperimentResultSubmission(measured_metrics={}))
    # Force the card back to running to exercise the re-run supersede branch
    # (the normal lifecycle has no completed->running path).
    card = db_session.get(ExperimentCard, exp.id)
    card.status = ExperimentStatusEnum.running.value
    db_session.commit()
    svc.submit_results(db_session, exp.id, goal.id,
                       ExperimentResultSubmission(measured_metrics={}))
    prior = db_session.get(ValidationResult, first.id)
    assert prior.reproduction_status == ReproductionStatusEnum.superseded.value


@patch("coscientist.services.validation._run_validation_agent")
def test_submit_retires_linked_roadmap_item(mock_agent, db_session):
    from coscientist.models.roadmap import ResearchRoadmapItem
    from coscientist.services import roadmap as roadmap_svc

    mock_agent.return_value = MOCK_VALIDATED
    goal = _create_goal(db_session)
    approach = _create_scored_approach(db_session, goal.id)
    _advance_to_experiment_proposed(db_session, approach.id)
    exp = _create_running_experiment(db_session, goal.id, approach.id)

    now = datetime.now(timezone.utc)
    item = ResearchRoadmapItem(
        id=str(uuid.uuid4()),
        workspace_id=goal.id,
        title="Follow up on experiment",
        description="x",
        lane="conservative",
        status="open",
        priority_score=0.8,
        priority_rank=1,
        rationale="x",
        estimated_cost="low",
        estimated_information_gain="medium",
        source_approach_ids=json.dumps([]),
        source_experiment_id=exp.id,
        source_device_id=None,
        generation_run_id=str(uuid.uuid4()),
        model_used="test",
        created_at=now,
        updated_at=now,
    )
    db_session.add(item)
    db_session.commit()

    svc.submit_results(db_session, exp.id, goal.id,
                       ExperimentResultSubmission(measured_metrics={}))
    refreshed = roadmap_svc.get_item(db_session, item.id, goal.id)
    assert refreshed.status.value == "completed"


def test_run_validation_agent_sends_correct_context(db_session):
    from unittest.mock import MagicMock, patch as mock_patch
    from coscientist.services.validation import _run_validation_agent
    from coscientist.models.experiment import ExperimentCard

    goal = _create_goal(db_session)
    approach = _create_scored_approach(db_session, goal.id)
    _advance_to_experiment_proposed(db_session, approach.id)
    exp_resp = _create_running_experiment(db_session, goal.id, approach.id)
    exp_card = db_session.get(ExperimentCard, exp_resp.id)
    approach_card = db_session.get(ApproachCard, approach.id)

    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.input = {
        "decision": "validated",
        "confidence": 0.9,
        "reasoning": "All good.",
        "criterion_results": [],
        "refinement_suggestions": [],
    }
    mock_message = MagicMock()
    mock_message.content = [tool_block]
    mock_message.usage.input_tokens = 100
    mock_message.usage.output_tokens = 50

    with mock_patch("coscientist.services.validation.anthropic.Anthropic") as MockAnthropic:
        MockAnthropic.return_value.messages.create.return_value = mock_message
        goal_resp = goal_svc.get(db_session, goal.id)
        submission = ExperimentResultSubmission(
            measured_metrics={"acoustic_contrast": 18.5, "latency": 8.2},
        )
        output = _run_validation_agent(db_session, goal.id, exp_card, goal_resp, approach_card, submission)

        call_kwargs = MockAnthropic.return_value.messages.create.call_args.kwargs
        user_content = call_kwargs["messages"][0]["content"]
        assert "Pass Conditions" in user_content
        assert "acoustic_contrast" in user_content
        assert "18.5" in user_content
        assert output.decision == ValidationDecisionEnum.validated


# ---------------------------------------------------------------------------
# Finding 2: unmeasured != failed — reconcile + derive verdict
# ---------------------------------------------------------------------------

from coscientist.services.validation import _derive_decision, _reconcile_unmeasurable


def test_reconcile_unmeasurable_nulls_matching_criteria():
    # A suffixed, non-canonical criterion name still matches a bare canonical
    # unmeasurable entry (strip _min/_max + canonicalize_metric).
    crs = [
        CriterionResult(name="acoustic_contrast_db_min", measured=23.0, target=15.0,
                        operator=">=", passed=True, unit="dB"),
        CriterionResult(name="dark_zone_attenuation_min", measured=0.0, target=20.0,
                        operator=">=", passed=False, unit="dB"),
    ]
    out = _reconcile_unmeasurable(crs, ["dark_zone_attenuation"])
    assert out[0].measured == 23.0 and out[0].passed is True
    assert out[1].measured is None and out[1].passed is False


def test_reconcile_unmeasurable_noop_when_empty():
    crs = [_cr(False)]
    assert _reconcile_unmeasurable(crs, []) == crs


def test_derive_decision_refuted_on_measurable_failure():
    assert _derive_decision([_cr(True), _cr(False)]) == ValidationDecisionEnum.refuted


def test_derive_decision_validated_when_measurable_pass_despite_unmeasurable():
    crs = [
        _cr(True),
        CriterionResult(name="x", measured=None, target=5.0, operator=">=", passed=False, unit=""),
    ]
    assert _derive_decision(crs) == ValidationDecisionEnum.validated


def test_derive_decision_inconclusive_when_nothing_measurable():
    crs = [CriterionResult(name="x", measured=None, target=5.0, operator=">=", passed=False, unit="")]
    assert _derive_decision(crs) == ValidationDecisionEnum.inconclusive
    assert _derive_decision([]) == ValidationDecisionEnum.inconclusive


def test_derive_reproduction_partial_when_untested_criterion_present():
    # All measurable passed, but an untested criterion means only partial coverage.
    crs = [
        _cr(True),
        CriterionResult(name="x", measured=None, target=5.0, operator=">=", passed=False, unit=""),
    ]
    assert _derive_reproduction_status(crs) == ReproductionStatusEnum.partially_reproduced


# VAST-shape agent output: one measurable pass + one condition the repro can't measure
# (the LLM naively scored it failed; reconciliation should null it out).
MOCK_VAST_SHAPE = AgentValidationOutput(
    decision=ValidationDecisionEnum.refuted,
    confidence=0.8,
    reasoning="Contrast passed; dark-zone attenuation not achieved.",
    criterion_results=[
        CriterionResult(name="acoustic_contrast_db_min", measured=23.05, target=15.0,
                        operator=">=", passed=True, unit="dB"),
        CriterionResult(name="dark_zone_attenuation_min", measured=0.0, target=20.0,
                        operator=">=", passed=False, unit="dB"),
    ],
    refinement_suggestions=["fix"],
)

MOCK_ALL_UNMEASURABLE = AgentValidationOutput(
    decision=ValidationDecisionEnum.refuted,
    confidence=0.8,
    reasoning="Nothing measurable.",
    criterion_results=[
        CriterionResult(name="dark_zone_attenuation_min", measured=0.0, target=20.0,
                        operator=">=", passed=False, unit="dB"),
    ],
    refinement_suggestions=["fix"],
)


@patch("coscientist.services.validation._run_validation_agent")
def test_submit_vast_shape_validates_and_partially_reproduces(mock_agent, db_session):
    mock_agent.return_value = MOCK_VAST_SHAPE
    goal = _create_goal(db_session)
    approach = _create_scored_approach(db_session, goal.id)
    _advance_to_experiment_proposed(db_session, approach.id)
    exp = _create_running_experiment(db_session, goal.id, approach.id)
    result = svc.submit_results(db_session, exp.id, goal.id, ExperimentResultSubmission(
        measured_metrics={"acoustic_contrast_db": 23.05},
        unmeasurable_conditions=["dark_zone_attenuation"],
    ))
    assert result.decision == ValidationDecisionEnum.validated
    assert result.reproduction_status == ReproductionStatusEnum.partially_reproduced
    card = db_session.get(ExperimentCard, exp.id)
    assert card.status == ExperimentStatusEnum.completed.value
    approach_card = db_session.get(ApproachCard, approach.id)
    assert approach_card.status == ApproachStatusEnum.validated.value


@patch("coscientist.services.validation._run_validation_agent")
def test_submit_all_unmeasurable_is_inconclusive(mock_agent, db_session):
    mock_agent.return_value = MOCK_ALL_UNMEASURABLE
    goal = _create_goal(db_session)
    approach = _create_scored_approach(db_session, goal.id)
    _advance_to_experiment_proposed(db_session, approach.id)
    exp = _create_running_experiment(db_session, goal.id, approach.id)
    result = svc.submit_results(db_session, exp.id, goal.id, ExperimentResultSubmission(
        measured_metrics={},
        unmeasurable_conditions=["dark_zone_attenuation"],
    ))
    assert result.decision == ValidationDecisionEnum.inconclusive
    assert result.reproduction_status == ReproductionStatusEnum.blocked
    card = db_session.get(ExperimentCard, exp.id)
    assert card.status == ExperimentStatusEnum.inconclusive.value
    # Inconclusive must not declare the approach refuted — it stays tested.
    approach_card = db_session.get(ApproachCard, approach.id)
    assert approach_card.status == ApproachStatusEnum.tested.value


def test_run_validation_agent_includes_unmeasurable_block(db_session):
    from unittest.mock import MagicMock, patch as mock_patch
    from coscientist.services.validation import _run_validation_agent

    goal = _create_goal(db_session)
    approach = _create_scored_approach(db_session, goal.id)
    _advance_to_experiment_proposed(db_session, approach.id)
    exp_resp = _create_running_experiment(db_session, goal.id, approach.id)
    exp_card = db_session.get(ExperimentCard, exp_resp.id)
    approach_card = db_session.get(ApproachCard, approach.id)

    tool_block = MagicMock()
    tool_block.type = "tool_use"
    tool_block.input = {
        "decision": "validated", "confidence": 0.9, "reasoning": "ok",
        "criterion_results": [], "refinement_suggestions": [],
    }
    mock_message = MagicMock()
    mock_message.content = [tool_block]
    mock_message.usage.input_tokens = 100
    mock_message.usage.output_tokens = 50

    with mock_patch("coscientist.services.validation.anthropic.Anthropic") as MockAnthropic:
        MockAnthropic.return_value.messages.create.return_value = mock_message
        goal_resp = goal_svc.get(db_session, goal.id)
        submission = ExperimentResultSubmission(
            measured_metrics={"acoustic_contrast_db": 23.05},
            unmeasurable_conditions=["dark_zone_attenuation"],
        )
        _run_validation_agent(db_session, goal.id, exp_card, goal_resp, approach_card, submission)
        user_content = MockAnthropic.return_value.messages.create.call_args.kwargs["messages"][0]["content"]
        assert "Unmeasurable Conditions" in user_content
        assert "dark_zone_attenuation" in user_content
