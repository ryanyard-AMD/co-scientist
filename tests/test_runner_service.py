import json
import uuid
from datetime import datetime, timezone

import pytest
from fastapi import HTTPException

from conftest import GOAL_PAYLOAD
from coscientist.models.approach import ApproachCard
from coscientist.models.experiment import ExperimentCard
from coscientist.schemas.experiment import ExperimentStatusEnum
from coscientist.schemas.goal import GoalCreate
from coscientist.schemas.validation import (
    ReproductionStatusEnum,
    ValidationDecisionEnum,
    ValidationResultResponse,
)
from coscientist.services import goal as goal_svc
from coscientist.services import runner as svc


def _make_goal(db):
    return goal_svc.create(db, GoalCreate(**GOAL_PAYLOAD)).id


def _approach(db, workspace_id, *, method_family="acoustic_contrast_control"):
    card = ApproachCard(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        name="ACC",
        method_family=method_family,
        domain="personal_sound_zones",
        problem_fit="x",
        mechanism_summary="x",
        key_assumptions=json.dumps([]),
        reported_metrics=json.dumps([]),
        hardware_requirements=json.dumps([]),
        device_relevance="x",
        risks_and_limitations=json.dumps([]),
        unresolved_questions=json.dumps([]),
        suggested_experiments=json.dumps([]),
        evidence_links=json.dumps([]),
        status="scored",
        maturity="theoretical",
    )
    db.add(card)
    db.commit()
    return card


def _experiment(db, workspace_id, approach_ids, *, status="approved"):
    now = datetime.now(timezone.utc)
    card = ExperimentCard(
        id=str(uuid.uuid4()),
        workspace_id=workspace_id,
        name="Sweep",
        objective="Measure contrast",
        hypothesis_text="Higher order increases contrast.",
        approach_ids=json.dumps(approach_ids),
        baseline_methods=json.dumps([]),
        independent_variables=json.dumps({}),
        fixed_assumptions=json.dumps({}),
        metrics=json.dumps(["acoustic_contrast_db"]),
        validation=json.dumps({"pass_conditions": {"acoustic_contrast_db_min": 20.0}}),
        runtime=json.dumps({}),
        artifacts=json.dumps([]),
        estimated_cost="low",
        estimated_runtime="medium",
        experiment_type="simulation",
        parameter_sweep_count=0,
        status=status,
        created_at=now,
        updated_at=now,
    )
    db.add(card)
    db.commit()
    return card


class _FakeReproClient:
    """Stand-in for ReproClient; records the submitted spec, scripts the responses."""

    instances: list["_FakeReproClient"] = []

    def __init__(self, run_status="success", metrics=None, exit_code=0):
        self.run_status = run_status
        self.metrics = metrics if metrics is not None else {}
        self.exit_code = exit_code
        self.submitted_spec = None
        _FakeReproClient.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def submit_run(self, spec, *, unsafe_draft=False):
        self.submitted_spec = spec
        return {"run_id": "run-123", "status": "pending", "poll": "/x"}

    def get_run(self, run_id):
        return {"status": self.run_status, "exit_code": self.exit_code}

    def get_run_metrics(self, run_id):
        return self.metrics


def _fake_validation(monkeypatch):
    captured = {}

    def _submit(db, experiment_id, goal_id, submission):
        captured["submission"] = submission
        return ValidationResultResponse(
            id=str(uuid.uuid4()),
            experiment_id=experiment_id,
            goal_id=goal_id,
            approach_id="",
            decision=ValidationDecisionEnum.validated,
            reproduction_status=ReproductionStatusEnum.reproduced,
            confidence=0.9,
            reasoning="ok",
            criterion_results=[],
            refinement_suggestions=[],
            measured_metrics=submission.measured_metrics,
            artifact_paths=submission.artifact_paths,
            model_used="test",
            created_at=datetime.now(timezone.utc),
        )

    monkeypatch.setattr(svc.validation_svc, "submit_results", _submit)
    return captured


@pytest.fixture(autouse=True)
def _reset_fake():
    _FakeReproClient.instances.clear()
    yield
    _FakeReproClient.instances.clear()


def test_run_success_translates_and_validates(db_session, monkeypatch):
    gid = _make_goal(db_session)
    ac = _approach(db_session, gid)
    exp = _experiment(db_session, gid, [ac.id])

    monkeypatch.setattr(
        svc, "ReproClient",
        lambda: _FakeReproClient(metrics={"oAC_best_dB": 18.5, "nsde_achieved_dB": -25.0, "label": "x"}),
    )
    captured = _fake_validation(monkeypatch)

    result = svc.run_experiment(db_session, exp.id, gid)

    assert result.run_id == "run-123"
    assert result.simulator == "vast_simulate.py"
    assert result.measured_metrics == {"acoustic_contrast_db": 18.5, "bright_zone_error": -25.0}
    # non-numeric native keys are dropped from raw too
    assert "label" not in result.raw_metrics
    # validation received the translated metrics
    assert captured["submission"].measured_metrics == {"acoustic_contrast_db": 18.5, "bright_zone_error": -25.0}
    # card was transitioned to running before validation handoff
    db_session.refresh(exp)
    assert exp.status == ExperimentStatusEnum.running.value


def test_run_failure_does_not_fabricate(db_session, monkeypatch):
    gid = _make_goal(db_session)
    ac = _approach(db_session, gid)
    exp = _experiment(db_session, gid, [ac.id])

    monkeypatch.setattr(svc, "ReproClient", lambda: _FakeReproClient(run_status="failed", exit_code=1))
    captured = _fake_validation(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        svc.run_experiment(db_session, exp.id, gid)
    assert exc.value.status_code == 502
    assert "submission" not in captured
    db_session.refresh(exp)
    assert exp.status == ExperimentStatusEnum.approved.value


def test_run_empty_metrics_refuses(db_session, monkeypatch):
    gid = _make_goal(db_session)
    ac = _approach(db_session, gid)
    exp = _experiment(db_session, gid, [ac.id])

    monkeypatch.setattr(svc, "ReproClient", lambda: _FakeReproClient(metrics={"unrelated": 1.0}))
    captured = _fake_validation(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        svc.run_experiment(db_session, exp.id, gid)
    assert exc.value.status_code == 502
    assert "submission" not in captured
    db_session.refresh(exp)
    assert exp.status == ExperimentStatusEnum.approved.value


def test_run_no_simulator_for_family(db_session, monkeypatch):
    gid = _make_goal(db_session)
    ac = _approach(db_session, gid, method_family="crosstalk_cancellation")
    exp = _experiment(db_session, gid, [ac.id])

    monkeypatch.setattr(svc, "ReproClient", lambda: _FakeReproClient())

    with pytest.raises(HTTPException) as exc:
        svc.run_experiment(db_session, exp.id, gid)
    assert exc.value.status_code == 422
    assert "crosstalk_cancellation" in exc.value.detail


def test_run_requires_approved_status(db_session, monkeypatch):
    gid = _make_goal(db_session)
    ac = _approach(db_session, gid)
    exp = _experiment(db_session, gid, [ac.id], status="generated")

    monkeypatch.setattr(svc, "ReproClient", lambda: _FakeReproClient())

    with pytest.raises(HTTPException) as exc:
        svc.run_experiment(db_session, exp.id, gid)
    assert exc.value.status_code == 409


def test_run_unknown_experiment_404(db_session, monkeypatch):
    gid = _make_goal(db_session)
    with pytest.raises(HTTPException) as exc:
        svc.run_experiment(db_session, "nope", gid)
    assert exc.value.status_code == 404
