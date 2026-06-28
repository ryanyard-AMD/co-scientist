import json
import uuid

import pytest
from fastapi import HTTPException

from conftest import GOAL_PAYLOAD
from coscientist.models.approach import ApproachCard
from coscientist.models.experiment import ExperimentCard
from coscientist.services import evaluation as svc
from coscientist.services import goal as goal_svc
from coscientist.schemas.goal import GoalCreate


def _make_goal(db):
    goal = goal_svc.create(db, GoalCreate(**GOAL_PAYLOAD))
    return goal.id


def _approach(db, workspace_id, *, status="generated", evidence_links=None, **fields):
    defaults = dict(
        problem_fit="Maximizes contrast between zones.",
        mechanism_summary="Optimizes signals for contrast.",
        key_assumptions=json.dumps(["free-field"]),
        reported_metrics=json.dumps([]),
        hardware_requirements=json.dumps(["loudspeaker array"]),
        device_relevance="Headphone friendly.",
        risks_and_limitations=json.dumps([]),
    )
    defaults.update(fields)
    card = ApproachCard(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        name="ACC",
        method_family="acoustic_contrast_control",
        domain="personal_sound_zones",
        unresolved_questions=json.dumps([]),
        suggested_experiments=json.dumps([]),
        evidence_links=json.dumps(evidence_links if evidence_links is not None else []),
        status=status,
        maturity="theoretical",
        **defaults,
    )
    db.add(card)
    db.commit()
    return card


def _experiment(db, workspace_id, *, status="generated", validation=None):
    card = ExperimentCard(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        name="Sweep",
        objective="Measure contrast",
        hypothesis_text="Higher order increases contrast.",
        approach_ids=json.dumps([]),
        baseline_methods=json.dumps(["pressure_matching"]),
        independent_variables=json.dumps({"filter_order": [4, 8]}),
        fixed_assumptions=json.dumps({}),
        metrics=json.dumps(["acoustic_contrast"]),
        validation=validation if validation is not None else json.dumps(
            {"pass_conditions": {"acoustic_contrast": 20.0}}
        ),
        runtime=json.dumps({}),
        artifacts=json.dumps([]),
        estimated_cost="low",
        estimated_runtime="medium",
        experiment_type="simulation",
        parameter_sweep_count=2,
        status=status,
    )
    db.add(card)
    db.commit()
    return card


# --- CS-EVAL-001 approach usefulness ---


def test_usefulness_rate_by_status(db_session):
    gid = _make_goal(db_session)
    _approach(db_session, gid, status="reviewed")
    _approach(db_session, gid, status="validated")
    _approach(db_session, gid, status="superseded")
    _approach(db_session, gid, status="generated")
    m = svc.approach_usefulness(db_session, gid)
    assert m.total == 4
    assert m.useful_count == 2
    assert m.discarded_count == 1
    assert m.pending_count == 1
    assert m.usefulness_rate == pytest.approx(2 / 3)
    assert m.usefulness_meets_target is False


def test_traceability_counts_cards_with_links(db_session):
    gid = _make_goal(db_session)
    _approach(
        db_session,
        gid,
        evidence_links=[
            {"evidence_id": "e1", "evidence_type": "direct", "claim_field": "mechanism_summary"}
        ],
    )
    _approach(db_session, gid, evidence_links=[])
    m = svc.approach_usefulness(db_session, gid)
    assert m.traceable_count == 1
    assert m.traceability_rate == pytest.approx(0.5)
    assert m.traceability_meets_target is False


def test_usefulness_empty_goal_meets_target(db_session):
    gid = _make_goal(db_session)
    m = svc.approach_usefulness(db_session, gid)
    assert m.total == 0
    assert m.usefulness_rate == 0.0
    assert m.usefulness_meets_target is True
    assert m.traceability_meets_target is True


# --- CS-EVAL-002 evidence grounding ---


def test_grounding_classifies_claims(db_session):
    gid = _make_goal(db_session)
    # Counted claim fields: problem_fit, mechanism_summary, key_assumptions,
    # hardware_requirements = 4 (reported_metrics + risks empty; device_relevance
    # is not a literature claim and is excluded from grounding).
    _approach(
        db_session,
        gid,
        evidence_links=[
            {"evidence_id": "e1", "evidence_type": "direct", "claim_field": "mechanism_summary"},
            {"evidence_id": "e2", "evidence_type": "inferred", "claim_field": "problem_fit"},
        ],
    )
    m = svc.evidence_grounding(db_session, gid)
    assert m.total_claims == 4
    assert m.grounded == 1
    assert m.inferred == 1
    assert m.unsupported == 2
    assert m.grounding_rate == pytest.approx(2 / 4)
    assert m.unsupported_rate == pytest.approx(2 / 4)
    assert m.grounding_meets_target is False
    assert m.unsupported_meets_target is False
    fields = {c.claim_field for c in m.unsupported_claims}
    assert fields == {"key_assumptions", "hardware_requirements"}


def test_grounding_direct_beats_inferred(db_session):
    gid = _make_goal(db_session)
    _approach(
        db_session,
        gid,
        problem_fit="",
        key_assumptions=json.dumps([]),
        hardware_requirements=json.dumps([]),
        device_relevance="",
        evidence_links=[
            {"evidence_id": "e1", "evidence_type": "inferred", "claim_field": "mechanism_summary"},
            {"evidence_id": "e2", "evidence_type": "direct", "claim_field": "mechanism_summary"},
        ],
    )
    m = svc.evidence_grounding(db_session, gid)
    assert m.total_claims == 1
    assert m.grounded == 1
    assert m.inferred == 0


def test_grounding_empty_goal_meets_target(db_session):
    gid = _make_goal(db_session)
    m = svc.evidence_grounding(db_session, gid)
    assert m.total_claims == 0
    assert m.grounding_meets_target is True
    assert m.unsupported_meets_target is True


# --- CS-EVAL-003 experiment quality ---


def test_acceptance_rate_by_status(db_session):
    gid = _make_goal(db_session)
    _experiment(db_session, gid, status="approved")
    _experiment(db_session, gid, status="completed")
    _experiment(db_session, gid, status="superseded")
    _experiment(db_session, gid, status="failed")
    _experiment(db_session, gid, status="generated")
    m = svc.experiment_quality(db_session, gid)
    assert m.total == 5
    assert m.accepted_count == 2
    assert m.discarded_count == 1
    assert m.failed_count == 1
    assert m.pending_count == 1
    assert m.acceptance_rate == pytest.approx(2 / 3)
    assert m.acceptance_meets_target is False


def test_spec_validity_flags_broken_experiment(db_session):
    gid = _make_goal(db_session)
    _experiment(db_session, gid, status="approved")
    broken = _experiment(
        db_session, gid, status="approved", validation=json.dumps({"pass_conditions": "nope"})
    )
    m = svc.experiment_quality(db_session, gid)
    assert m.total == 2
    assert m.valid_count == 1
    assert m.invalid_experiment_ids == [broken.id]
    assert m.validity_rate == pytest.approx(0.5)
    assert m.validity_meets_target is False


def test_experiment_empty_goal_meets_target(db_session):
    gid = _make_goal(db_session)
    m = svc.experiment_quality(db_session, gid)
    assert m.total == 0
    assert m.acceptance_meets_target is True
    assert m.validity_meets_target is True


# --- report + unknown goal ---


def test_get_report_combines_blocks(db_session):
    gid = _make_goal(db_session)
    _approach(db_session, gid, status="reviewed")
    _experiment(db_session, gid, status="approved")
    report = svc.get_report(db_session, gid)
    assert report.goal_id == gid
    assert report.approach_usefulness.total == 1
    assert report.experiment_quality.total == 1
    assert report.evidence_grounding.total_claims >= 1


def test_unknown_goal_raises_404(db_session):
    with pytest.raises(HTTPException) as exc:
        svc.approach_usefulness(db_session, "does-not-exist")
    assert exc.value.status_code == 404


# --- CS-EVAL-005 productivity ---


def _log_agent_call(db, workspace_id, *, error=None):
    from coscientist.models.governance import AgentActionLog

    db.add(
        AgentActionLog(
            id=str(uuid.uuid4()),
            workspace_id=workspace_id,
            service="approach",
            action="generate",
            model_used="test-model",
            error=error,
        )
    )
    db.commit()


def _feedback(db, workspace_id, *, is_positive):
    from coscientist.schemas.feedback import FeedbackCreate, FeedbackTargetEnum
    from coscientist.services import feedback as feedback_svc

    feedback_svc.create(
        db,
        workspace_id,
        FeedbackCreate(
            target_type=FeedbackTargetEnum.approach,
            target_id="approach-1",
            is_positive=is_positive,
        ),
    )


def test_productivity_counts_successful_agent_actions(db_session):
    from coscientist.config import settings

    gid = _make_goal(db_session)
    _log_agent_call(db_session, gid)
    _log_agent_call(db_session, gid)
    _log_agent_call(db_session, gid, error="boom")  # failed calls excluded
    m = svc.productivity(db_session, gid)
    assert m.agent_action_count == 2
    assert m.minutes_per_agent_action == settings.eval_minutes_per_agent_action
    assert m.estimated_time_saved_minutes == 2 * settings.eval_minutes_per_agent_action
    assert m.estimated_time_saved_hours == pytest.approx(
        round(2 * settings.eval_minutes_per_agent_action / 60, 2)
    )


def test_productivity_satisfaction_from_feedback(db_session):
    gid = _make_goal(db_session)
    _feedback(db_session, gid, is_positive=True)
    _feedback(db_session, gid, is_positive=True)
    _feedback(db_session, gid, is_positive=False)
    m = svc.productivity(db_session, gid)
    assert m.positive_feedback == 2
    assert m.total_feedback == 3
    assert m.satisfaction_rate == pytest.approx(2 / 3)


def test_productivity_no_feedback_rate_is_none(db_session):
    gid = _make_goal(db_session)
    m = svc.productivity(db_session, gid)
    assert m.total_feedback == 0
    assert m.satisfaction_rate is None


def test_productivity_unknown_goal_404(db_session):
    with pytest.raises(HTTPException) as exc:
        svc.productivity(db_session, "does-not-exist")
    assert exc.value.status_code == 404


def test_get_report_includes_productivity(db_session):
    gid = _make_goal(db_session)
    _log_agent_call(db_session, gid)
    report = svc.get_report(db_session, gid)
    assert report.productivity.agent_action_count == 1
