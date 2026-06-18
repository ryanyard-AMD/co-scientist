import json
import uuid
from datetime import datetime, timezone

import pytest

from conftest import GOAL_PAYLOAD
from coscientist.models.evidence import EvidenceRecord
from coscientist.schemas.approval import (
    ApprovalDecisionCreate,
    ApprovalDecisionEnum,
    ResourceFlagEnum,
)
from coscientist.schemas.approach import ApproachGenerateRequest, ApproachStatusEnum
from coscientist.schemas.experiment import (
    ExperimentCardCreate,
    ExperimentStatusEnum,
)
from coscientist.services import approval as svc
from coscientist.services import approach as approach_svc
from coscientist.services import experiment as experiment_svc
from coscientist.services import goal as goal_svc
from coscientist.services import score as score_svc


def _create_goal(db):
    from coscientist.schemas.goal import GoalCreate
    return goal_svc.create(db, GoalCreate(**GOAL_PAYLOAD))


def _seed_evidence(db, workspace_id, method_family):
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


def _create_reviewed_experiment(db, goal_id, approach_id):
    exp = experiment_svc.create(db, goal_id, ExperimentCardCreate(
        name="Test Experiment",
        objective="Evaluate method",
        hypothesis_text="Method achieves target",
        approach_ids=[approach_id],
    ))
    experiment_svc.transition(db, exp.id, ExperimentStatusEnum.reviewed)
    return experiment_svc.get(db, exp.id)


# ---------------------------------------------------------------------------
# record_decision — approve
# ---------------------------------------------------------------------------

def test_approve_transitions_experiment_to_approved(db_session):
    goal = _create_goal(db_session)
    approach = _create_scored_approach(db_session, goal.id)
    exp = _create_reviewed_experiment(db_session, goal.id, approach.id)

    body = ApprovalDecisionCreate(decision=ApprovalDecisionEnum.approve)
    decision = svc.record_decision(db_session, exp.id, goal.id, body)

    assert decision.decision == ApprovalDecisionEnum.approve
    updated = experiment_svc.get(db_session, exp.id)
    assert updated.status == ExperimentStatusEnum.approved


def test_approve_stores_yaml_handoff_when_no_reason(db_session):
    goal = _create_goal(db_session)
    approach = _create_scored_approach(db_session, goal.id)
    exp = _create_reviewed_experiment(db_session, goal.id, approach.id)

    body = ApprovalDecisionCreate(decision=ApprovalDecisionEnum.approve)
    decision = svc.record_decision(db_session, exp.id, goal.id, body)

    assert decision.reason is not None
    assert "experiment_card" in decision.reason


def test_approve_preserves_explicit_reason(db_session):
    goal = _create_goal(db_session)
    approach = _create_scored_approach(db_session, goal.id)
    exp = _create_reviewed_experiment(db_session, goal.id, approach.id)

    body = ApprovalDecisionCreate(decision=ApprovalDecisionEnum.approve, reason="Looks good")
    decision = svc.record_decision(db_session, exp.id, goal.id, body)

    assert decision.reason == "Looks good"


def test_approve_uses_explicit_resource_flags(db_session):
    goal = _create_goal(db_session)
    approach = _create_scored_approach(db_session, goal.id)
    exp = _create_reviewed_experiment(db_session, goal.id, approach.id)

    body = ApprovalDecisionCreate(
        decision=ApprovalDecisionEnum.approve,
        resource_flags=[ResourceFlagEnum.gpu, ResourceFlagEnum.credentials],
    )
    decision = svc.record_decision(db_session, exp.id, goal.id, body)

    assert "gpu" in decision.resource_flags
    assert "credentials" in decision.resource_flags


def test_approve_records_reviewer_id(db_session):
    goal = _create_goal(db_session)
    approach = _create_scored_approach(db_session, goal.id)
    exp = _create_reviewed_experiment(db_session, goal.id, approach.id)

    body = ApprovalDecisionCreate(
        decision=ApprovalDecisionEnum.approve,
        reviewer_id="ryard",
    )
    decision = svc.record_decision(db_session, exp.id, goal.id, body)
    assert decision.reviewer_id == "ryard"


# ---------------------------------------------------------------------------
# record_decision — reject
# ---------------------------------------------------------------------------

def test_reject_transitions_experiment_to_superseded(db_session):
    goal = _create_goal(db_session)
    approach = _create_scored_approach(db_session, goal.id)
    exp = _create_reviewed_experiment(db_session, goal.id, approach.id)

    body = ApprovalDecisionCreate(decision=ApprovalDecisionEnum.reject, reason="Not feasible")
    decision = svc.record_decision(db_session, exp.id, goal.id, body)

    assert decision.decision == ApprovalDecisionEnum.reject
    updated = experiment_svc.get(db_session, exp.id)
    assert updated.status == ExperimentStatusEnum.superseded


def test_reject_requires_reason():
    with pytest.raises(ValueError, match="reason is required"):
        ApprovalDecisionCreate(decision=ApprovalDecisionEnum.reject)


# ---------------------------------------------------------------------------
# record_decision — request_edit
# ---------------------------------------------------------------------------

def test_request_edit_transitions_experiment_to_generated(db_session):
    goal = _create_goal(db_session)
    approach = _create_scored_approach(db_session, goal.id)
    exp = _create_reviewed_experiment(db_session, goal.id, approach.id)

    body = ApprovalDecisionCreate(
        decision=ApprovalDecisionEnum.request_edit,
        reason="Needs more baselines",
    )
    decision = svc.record_decision(db_session, exp.id, goal.id, body)

    assert decision.decision == ApprovalDecisionEnum.request_edit
    updated = experiment_svc.get(db_session, exp.id)
    assert updated.status == ExperimentStatusEnum.generated


def test_request_edit_requires_reason():
    with pytest.raises(ValueError, match="reason is required"):
        ApprovalDecisionCreate(decision=ApprovalDecisionEnum.request_edit)


# ---------------------------------------------------------------------------
# record_decision — error cases
# ---------------------------------------------------------------------------

def test_record_decision_experiment_not_found(db_session):
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        body = ApprovalDecisionCreate(decision=ApprovalDecisionEnum.approve)
        svc.record_decision(db_session, "nonexistent", "nonexistent-goal", body)
    assert exc_info.value.status_code == 404


def test_record_decision_wrong_goal_returns_404(db_session):
    from fastapi import HTTPException
    goal = _create_goal(db_session)
    approach = _create_scored_approach(db_session, goal.id)
    exp = _create_reviewed_experiment(db_session, goal.id, approach.id)

    body = ApprovalDecisionCreate(decision=ApprovalDecisionEnum.approve)
    with pytest.raises(HTTPException) as exc_info:
        svc.record_decision(db_session, exp.id, "wrong-goal-id", body)
    assert exc_info.value.status_code == 404


def test_record_decision_wrong_status_returns_409(db_session):
    from fastapi import HTTPException
    goal = _create_goal(db_session)
    approach = _create_scored_approach(db_session, goal.id)
    # experiment is in "generated" status, not "reviewed"
    exp = experiment_svc.create(db_session, goal.id, ExperimentCardCreate(
        name="Not Reviewed",
        objective="Test",
        hypothesis_text="Hypothesis",
        approach_ids=[approach.id],
    ))

    body = ApprovalDecisionCreate(decision=ApprovalDecisionEnum.approve)
    with pytest.raises(HTTPException) as exc_info:
        svc.record_decision(db_session, exp.id, goal.id, body)
    assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# list_decisions
# ---------------------------------------------------------------------------

def test_list_decisions_returns_chronological_audit_log(db_session):
    goal = _create_goal(db_session)
    approach = _create_scored_approach(db_session, goal.id)
    exp = _create_reviewed_experiment(db_session, goal.id, approach.id)

    body = ApprovalDecisionCreate(
        decision=ApprovalDecisionEnum.request_edit,
        reason="Needs more baselines",
    )
    svc.record_decision(db_session, exp.id, goal.id, body)

    # Transition back to reviewed for second decision
    experiment_svc.transition(db_session, exp.id, ExperimentStatusEnum.reviewed)
    body2 = ApprovalDecisionCreate(decision=ApprovalDecisionEnum.approve)
    svc.record_decision(db_session, exp.id, goal.id, body2)

    result = svc.list_decisions(db_session, exp.id, goal.id)
    assert result.total == 2
    assert result.items[0].decision == ApprovalDecisionEnum.request_edit
    assert result.items[1].decision == ApprovalDecisionEnum.approve


def test_list_decisions_empty_for_new_experiment(db_session):
    goal = _create_goal(db_session)
    approach = _create_scored_approach(db_session, goal.id)
    exp = _create_reviewed_experiment(db_session, goal.id, approach.id)

    result = svc.list_decisions(db_session, exp.id, goal.id)
    assert result.total == 0
    assert result.items == []


# ---------------------------------------------------------------------------
# list_pending
# ---------------------------------------------------------------------------

def test_list_pending_returns_reviewed_experiments(db_session):
    goal = _create_goal(db_session)
    approach = _create_scored_approach(db_session, goal.id)
    _create_reviewed_experiment(db_session, goal.id, approach.id)

    pending = svc.list_pending(db_session)
    assert len(pending) >= 1
    assert all(e.status == ExperimentStatusEnum.reviewed for e in pending)


def test_list_pending_filtered_by_goal(db_session):
    goal = _create_goal(db_session)
    approach = _create_scored_approach(db_session, goal.id)
    _create_reviewed_experiment(db_session, goal.id, approach.id)

    pending = svc.list_pending(db_session, goal_id=goal.id)
    assert len(pending) >= 1
    assert all(e.workspace_id == goal.id for e in pending)


def test_list_pending_empty_when_no_reviewed(db_session):
    goal = _create_goal(db_session)
    approach = _create_scored_approach(db_session, goal.id)
    # Create experiment but don't transition to reviewed
    experiment_svc.create(db_session, goal.id, ExperimentCardCreate(
        name="Not Reviewed",
        objective="Test",
        hypothesis_text="Hypothesis",
        approach_ids=[approach.id],
    ))
    pending = svc.list_pending(db_session, goal_id=goal.id)
    assert pending == []


# ---------------------------------------------------------------------------
# duplicate_experiment
# ---------------------------------------------------------------------------

def test_duplicate_creates_new_card_with_generated_status(db_session):
    goal = _create_goal(db_session)
    approach = _create_scored_approach(db_session, goal.id)
    exp = _create_reviewed_experiment(db_session, goal.id, approach.id)

    result = svc.duplicate_experiment(db_session, exp.id, goal.id)

    assert result.original_id == exp.id
    assert result.new_id != exp.id
    assert result.new_experiment.status == ExperimentStatusEnum.generated
    assert "(copy)" in result.new_experiment.name
    assert result.new_experiment.workspace_id == exp.workspace_id


def test_duplicate_copies_fields(db_session):
    goal = _create_goal(db_session)
    approach = _create_scored_approach(db_session, goal.id)
    exp = _create_reviewed_experiment(db_session, goal.id, approach.id)

    result = svc.duplicate_experiment(db_session, exp.id, goal.id)
    dup = result.new_experiment

    assert dup.objective == exp.objective
    assert dup.hypothesis_text == exp.hypothesis_text
    assert dup.approach_ids == exp.approach_ids


def test_duplicate_has_no_decisions(db_session):
    goal = _create_goal(db_session)
    approach = _create_scored_approach(db_session, goal.id)
    exp = _create_reviewed_experiment(db_session, goal.id, approach.id)

    result = svc.duplicate_experiment(db_session, exp.id, goal.id)
    decisions = svc.list_decisions(db_session, result.new_id, goal.id)
    assert decisions.total == 0


def test_duplicate_not_found_returns_404(db_session):
    from fastapi import HTTPException
    goal = _create_goal(db_session)
    with pytest.raises(HTTPException) as exc_info:
        svc.duplicate_experiment(db_session, "nonexistent", goal.id)
    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# _classify_resource_flags
# ---------------------------------------------------------------------------

def test_classify_flags_infers_high_cost(db_session):
    from coscientist.models.experiment import ExperimentCard
    from coscientist.services.approval import _classify_resource_flags
    card = ExperimentCard(estimated_cost="high", estimated_compute=None, experiment_type="simulation")
    flags = _classify_resource_flags(card)
    assert "high_cost" in flags


def test_classify_flags_infers_gpu_from_compute(db_session):
    from coscientist.models.experiment import ExperimentCard
    from coscientist.services.approval import _classify_resource_flags
    card = ExperimentCard(estimated_cost="low", estimated_compute="requires GPU cluster", experiment_type="simulation")
    flags = _classify_resource_flags(card)
    assert "gpu" in flags


def test_classify_flags_infers_treble_from_compute(db_session):
    from coscientist.models.experiment import ExperimentCard
    from coscientist.services.approval import _classify_resource_flags
    card = ExperimentCard(estimated_cost="low", estimated_compute="run via treble", experiment_type="simulation")
    flags = _classify_resource_flags(card)
    assert "treble" in flags


def test_classify_flags_empty_for_low_cost_no_compute(db_session):
    from coscientist.models.experiment import ExperimentCard
    from coscientist.services.approval import _classify_resource_flags
    card = ExperimentCard(estimated_cost="low", estimated_compute=None, experiment_type="simulation")
    flags = _classify_resource_flags(card)
    assert flags == []
