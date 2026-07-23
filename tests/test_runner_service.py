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


def _experiment(db, workspace_id, approach_ids, *, status="approved", pass_conditions=None):
    now = datetime.now(timezone.utc)
    if pass_conditions is None:
        pass_conditions = {"acoustic_contrast_db_min": 20.0}
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
        validation=json.dumps({"pass_conditions": pass_conditions}),
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


_VAST_PAPER_ID = "786380fd-256b-46b6-b71e-af1b41adeb0b"
_VAST_EXPERIMENT_ID = "fast-generation-of-sound-zones-using-var-v1"
_VAST_FAMILIES = [
    "acoustic_contrast_control",
    "pressure_matching",
    "sound_zone_control",
    "variable_span_tradeoff",
]


def _vast_candidate(**overrides):
    cand = {
        "paper_id": _VAST_PAPER_ID,
        "title": "Fast Generation of Sound Zones",
        "score": 0.94,
        "rationale": "Method",
        "runnable": True,
        "experiment_ids": [_VAST_EXPERIMENT_ID],
        "method_families": list(_VAST_FAMILIES),
        "family_match": True,
    }
    cand.update(overrides)
    return cand


class _FakeReproClient:
    """Stand-in for ReproClient; records the recommend/design proposals, scripts responses."""

    instances: list["_FakeReproClient"] = []

    def __init__(
        self,
        run_status="success",
        metrics=None,
        exit_code=0,
        *,
        honored=None,
        dropped=None,
        workspaces=None,
        candidates=None,
        surface=None,
    ):
        self.run_status = run_status
        self.metrics = metrics if metrics is not None else {}
        self.exit_code = exit_code
        self.honored = honored if honored is not None else []
        self.dropped = dropped if dropped is not None else []
        self.workspaces = (
            workspaces
            if workspaces is not None
            else [{"id": "ws-vast", "retrieval_paper_id": _VAST_PAPER_ID}]
        )
        self.candidates = candidates if candidates is not None else [_vast_candidate()]
        self.surface = surface
        self.submitted_proposal = None
        self.recommend_proposal = None
        self.recommend_workspace_id = None
        self.design_workspace_id = None
        _FakeReproClient.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def list_workspaces(self):
        return self.workspaces

    def recommend_method(self, workspace_id, proposal, *, top_k=None, draft=False):
        self.recommend_workspace_id = workspace_id
        self.recommend_proposal = proposal
        return {
            "hypothesis": proposal.get("hypothesis"),
            "candidates": self.candidates,
            "draft_id": None,
            "drafted_experiment_id": None,
            "honored": [],
            "dropped": [],
            "method_family_supported": None,
        }

    def get_metrics_surface(self, workspace_id):
        if self.surface is not None:
            return self.surface
        return {"paper_id": _VAST_PAPER_ID, "reproductions": []}

    def design_run(self, workspace_id, proposal, *, auto_approve=True):
        self.design_workspace_id = workspace_id
        self.submitted_proposal = proposal
        return {
            "run_id": "run-123",
            "draft_id": "draft-1",
            "spec_status": "approved",
            "honored": self.honored,
            "dropped": self.dropped,
        }

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
    # simulator now names the repro reproduction repro recommended, not a local script
    assert result.simulator == _VAST_EXPERIMENT_ID
    assert result.measured_metrics == {"acoustic_contrast_db": 18.5, "bright_zone_error": -25.0}
    # non-numeric native keys are dropped from raw too
    assert "label" not in result.raw_metrics
    # validation received the translated metrics
    assert captured["submission"].measured_metrics == {"acoustic_contrast_db": 18.5, "bright_zone_error": -25.0}
    # recommendation provenance surfaced; no divergence (card family is in candidate families)
    assert result.recommendation["experiment_id"] == _VAST_EXPERIMENT_ID
    assert result.recommendation["diverged_from_card_family"] is False
    # card was transitioned to running before validation handoff
    db_session.refresh(exp)
    assert exp.status == ExperimentStatusEnum.running.value


def test_run_builds_proposal_and_records_provenance(db_session, monkeypatch):
    gid = _make_goal(db_session)
    ac = _approach(db_session, gid)
    exp = _experiment(db_session, gid, [ac.id])

    honored = [{"proposal_name": "reverb_t60_s", "canonical": "reverb_t60_s", "flag": "--t60", "value": [0.3], "kind": "scalar"}]
    dropped = [{"proposal_name": "speaker_count", "reason": "unsupported"}]
    fake = _FakeReproClient(
        metrics={"oAC_best_dB": 18.5, "nsde_achieved_dB": -25.0},
        honored=honored,
        dropped=dropped,
    )
    monkeypatch.setattr(svc, "ReproClient", lambda: fake)
    _fake_validation(monkeypatch)

    svc.run_experiment(db_session, exp.id, gid)

    # design-run targeted the workspace resolved from the recommended candidate's paper
    assert fake.design_workspace_id == "ws-vast"
    # recommend-method received the card's hypothesis + method_family (P5: repro
    # ranks by declared capability, keyed on method_family — without it the runnable
    # reproduction for the card's method is never surfaced)
    assert fake.recommend_proposal["hypothesis"] == "Higher order increases contrast."
    assert fake.recommend_proposal["method_family"] == "acoustic_contrast_control"
    # proposal carried the card's scientific fields + the chosen reproduction id
    prop = fake.submitted_proposal
    assert prop["objective"] == "Measure contrast"
    assert prop["hypothesis"] == "Higher order increases contrast."
    assert prop["metrics"] == ["acoustic_contrast_db"]
    assert prop["experiment_id"] == _VAST_EXPERIMENT_ID
    # pass_conditions dict → PassCondition list with parsed operator/metric
    assert prop["pass_conditions"] == [
        {"metric": "acoustic_contrast_db", "operator": ">=", "value": 20.0}
    ]
    # honored/dropped + recommendation provenance persisted on the card
    db_session.refresh(exp)
    assert "run-123" in json.loads(exp.run_request_ids)
    batch = json.loads(exp.batch_expansion)
    assert batch["repro_workspace_id"] == "ws-vast"
    assert batch["dropped"] == dropped
    assert batch["honored"] == honored
    assert batch["recommendation"]["experiment_id"] == _VAST_EXPERIMENT_ID
    assert batch["recommendation"]["card_method_family"] == "acoustic_contrast_control"


def test_run_records_divergence_when_family_differs(db_session, monkeypatch):
    # The card committed to a family the recommended reproduction does not implement;
    # the runner runs repro's recommendation but records the divergence.
    gid = _make_goal(db_session)
    ac = _approach(db_session, gid, method_family="crosstalk_cancellation")
    exp = _experiment(db_session, gid, [ac.id])

    monkeypatch.setattr(
        svc, "ReproClient",
        lambda: _FakeReproClient(metrics={"oAC_best_dB": 18.5, "nsde_achieved_dB": -25.0}),
    )
    _fake_validation(monkeypatch)

    result = svc.run_experiment(db_session, exp.id, gid)

    assert result.recommendation["diverged_from_card_family"] is True
    assert result.recommendation["card_method_family"] == "crosstalk_cancellation"
    db_session.refresh(exp)
    batch = json.loads(exp.batch_expansion)
    assert batch["recommendation"]["diverged_from_card_family"] is True


def test_run_translation_keyed_by_experiment_id(db_session, monkeypatch):
    # A reproduction with no native→canonical map entry yields no translatable
    # metrics even though the run emitted numeric keys → refuse, don't fabricate.
    gid = _make_goal(db_session)
    ac = _approach(db_session, gid)
    exp = _experiment(db_session, gid, [ac.id])

    unknown = _vast_candidate(experiment_ids=["some-unmapped-repro-v1"])
    monkeypatch.setattr(
        svc, "ReproClient",
        lambda: _FakeReproClient(
            metrics={"oAC_best_dB": 18.5, "nsde_achieved_dB": -25.0},
            candidates=[unknown],
        ),
    )
    captured = _fake_validation(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        svc.run_experiment(db_session, exp.id, gid)
    assert exc.value.status_code == 502
    assert "submission" not in captured
    db_session.refresh(exp)
    assert exp.status == ExperimentStatusEnum.approved.value


def test_run_records_unmeasurable_pass_conditions(db_session, monkeypatch):
    # A pass condition on a metric the reproduction can't produce is recorded (not
    # dropped) so an inevitable refutation is auditable.
    gid = _make_goal(db_session)
    ac = _approach(db_session, gid)
    exp = _experiment(
        db_session, gid, [ac.id],
        pass_conditions={"acoustic_contrast_db_min": 20.0, "latency_ms_max": 10.0},
    )

    monkeypatch.setattr(
        svc, "ReproClient",
        lambda: _FakeReproClient(metrics={"oAC_best_dB": 18.5, "nsde_achieved_dB": -25.0}),
    )
    _fake_validation(monkeypatch)

    result = svc.run_experiment(db_session, exp.id, gid)
    assert "latency_ms" in result.recommendation["unmeasurable_pass_conditions"]
    assert "acoustic_contrast_db" not in result.recommendation["unmeasurable_pass_conditions"]


def test_pass_conditions_canonicalizes_metric_name():
    # A card written with the non-canonical metric name reconciles onto the
    # canonical METRIC_NAMES vocabulary the runner emits.
    out = svc._pass_conditions({"acoustic_contrast_min": 15.0})
    assert out == [{"metric": "acoustic_contrast_db", "operator": ">=", "value": 15.0}]


def test_unmeasurable_conditions_reconciles_non_canonical_name():
    # 'acoustic_contrast' (non-canonical) must NOT be flagged unmeasurable for VAST,
    # since it canonicalizes to acoustic_contrast_db which VAST emits; a genuinely
    # absent metric still is.
    conds = svc._pass_conditions(
        {"acoustic_contrast_min": 15.0, "steering_loop_latency_max": 50.0}
    )
    unmeasurable = svc._unmeasurable_conditions(conds, _VAST_EXPERIMENT_ID)
    assert "acoustic_contrast_db" not in unmeasurable
    assert "steering_loop_latency" in unmeasurable


def test_run_no_runnable_candidate_refuses(db_session, monkeypatch):
    gid = _make_goal(db_session)
    ac = _approach(db_session, gid)
    exp = _experiment(db_session, gid, [ac.id])

    not_runnable = _vast_candidate(runnable=False, experiment_ids=[])
    monkeypatch.setattr(
        svc, "ReproClient",
        lambda: _FakeReproClient(candidates=[not_runnable]),
    )
    captured = _fake_validation(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        svc.run_experiment(db_session, exp.id, gid)
    assert exc.value.status_code == 422
    assert "no runnable reproduction" in exc.value.detail
    assert "submission" not in captured
    db_session.refresh(exp)
    assert exp.status == ExperimentStatusEnum.approved.value


def test_run_no_workspace_for_candidate_refuses(db_session, monkeypatch):
    # recommend-method chose a paper no repro workspace is bound to.
    gid = _make_goal(db_session)
    ac = _approach(db_session, gid)
    exp = _experiment(db_session, gid, [ac.id])

    orphan = _vast_candidate(paper_id="orphan-paper")
    monkeypatch.setattr(
        svc, "ReproClient",
        lambda: _FakeReproClient(candidates=[orphan]),
    )
    captured = _fake_validation(monkeypatch)

    with pytest.raises(HTTPException) as exc:
        svc.run_experiment(db_session, exp.id, gid)
    assert exc.value.status_code == 422
    assert "submission" not in captured
    db_session.refresh(exp)
    assert exp.status == ExperimentStatusEnum.approved.value


def test_run_no_workspace_at_all_refuses(db_session, monkeypatch):
    # repro has no workspace with a bound paper to query recommend-method against.
    gid = _make_goal(db_session)
    ac = _approach(db_session, gid)
    exp = _experiment(db_session, gid, [ac.id])

    monkeypatch.setattr(
        svc, "ReproClient",
        lambda: _FakeReproClient(workspaces=[{"id": "smoke", "retrieval_paper_id": None}]),
    )

    with pytest.raises(HTTPException) as exc:
        svc.run_experiment(db_session, exp.id, gid)
    assert exc.value.status_code == 422
    db_session.refresh(exp)
    assert exp.status == ExperimentStatusEnum.approved.value


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


def test_run_combination_refuses(db_session, monkeypatch):
    # A combination experiment (>1 approach) has no single-paper repro; auto-running one
    # ingredient would fabricate a verdict, so refuse and route to the manual lane.
    gid = _make_goal(db_session)
    a1 = _approach(db_session, gid, method_family="acoustic_contrast_control")
    a2 = _approach(db_session, gid, method_family="pressure_matching")
    exp = _experiment(db_session, gid, [a1.id, a2.id])

    monkeypatch.setattr(svc, "ReproClient", lambda: _FakeReproClient())

    with pytest.raises(HTTPException) as exc:
        svc.run_experiment(db_session, exp.id, gid)
    assert exc.value.status_code == 422
    assert "cs validation submit" in exc.value.detail
    # never touched repro, card left runnable
    assert _FakeReproClient.instances == []
    db_session.refresh(exp)
    assert exp.status == ExperimentStatusEnum.approved.value


def test_validation_error_rolls_back_to_approved(db_session, monkeypatch):
    # If validation raises (infra error, not a refuted verdict) after the card is moved to
    # 'running', the runner rolls it back to 'approved' so it stays re-runnable.
    gid = _make_goal(db_session)
    ac = _approach(db_session, gid)
    exp = _experiment(db_session, gid, [ac.id])

    monkeypatch.setattr(
        svc, "ReproClient",
        lambda: _FakeReproClient(metrics={"oAC_best_dB": 18.5, "nsde_achieved_dB": -25.0}),
    )

    def _boom(db, experiment_id, goal_id, submission):
        raise HTTPException(status_code=502, detail="validation agent unavailable")

    monkeypatch.setattr(svc.validation_svc, "submit_results", _boom)

    with pytest.raises(HTTPException) as exc:
        svc.run_experiment(db_session, exp.id, gid)
    assert exc.value.status_code == 502
    db_session.refresh(exp)
    assert exp.status == ExperimentStatusEnum.approved.value
