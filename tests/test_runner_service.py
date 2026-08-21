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
from coscientist.schemas.runner import RunnerResult
from coscientist.schemas.validation import (
    ReproductionStatusEnum,
    ValidationDecisionEnum,
    ValidationResultResponse,
)
from coscientist.services import experiment as experiment_svc
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


class _PreviewReproClient:
    """Fake for the new /api/v1/handoffs/preview path."""

    def __init__(self, report: dict):
        self.report = report
        self.payload = None
        self.top_k = None

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def preview_handoff(self, payload, *, top_k=None):
        self.payload = payload
        self.top_k = top_k
        return self.report


def _fake_validation(monkeypatch):
    return {}


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
        lambda: _FakeReproClient(metrics={"oAC_best_dB": 22.5, "nsde_achieved_dB": -25.0, "label": "x"}),
    )

    result = svc.run_experiment(db_session, exp.id, gid)

    assert result.run_id == "run-123"
    # simulator now names the repro reproduction repro recommended, not a local script
    assert result.simulator == _VAST_EXPERIMENT_ID
    assert result.measured_metrics == {"acoustic_contrast_db": 22.5, "bright_zone_error": -25.0}
    # non-numeric native keys are dropped from raw too
    assert "label" not in result.raw_metrics
    assert result.validation.decision == ValidationDecisionEnum.validated
    assert result.result_bundle.bundle.validation_status.value == "passed"
    assert result.result_bundle.aggregation.aggregate_status.value == "passed"
    # recommendation provenance surfaced; no divergence (card family is in candidate families)
    assert result.recommendation["experiment_id"] == _VAST_EXPERIMENT_ID
    assert result.recommendation["diverged_from_card_family"] is False
    db_session.refresh(exp)
    assert exp.status == ExperimentStatusEnum.completed.value
    assert exp.execution_status == "completed"


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
    # pass_conditions dict -> PassCondition list with parsed operator/metric
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


def test_preflight_resolves_execution_plan(db_session, monkeypatch):
    gid = _make_goal(db_session)
    ac = _approach(db_session, gid)
    exp = _experiment(db_session, gid, [ac.id])
    fake = _FakeReproClient(
        surface={
            "paper_id": _VAST_PAPER_ID,
            "reproductions": [
                {
                    "experiment_id": _VAST_EXPERIMENT_ID,
                    "method_families": list(_VAST_FAMILIES),
                    "metrics": ["oAC_best_dB", "nsde_achieved_dB"],
                }
            ],
        }
    )
    monkeypatch.setattr(svc, "ReproClient", lambda: fake)

    result = svc.preflight_experiment(db_session, exp.id, gid)

    assert result.runnable is True
    assert result.blocking_reasons == []
    assert result.selected_reproduction_id == _VAST_EXPERIMENT_ID
    assert result.repro_workspace_id == "ws-vast"
    assert result.method_family == "acoustic_contrast_control"
    assert result.pass_conditions == [
        {"metric": "acoustic_contrast_db", "operator": ">=", "value": 20.0}
    ]
    assert result.design_run_payload["experiment_id"] == _VAST_EXPERIMENT_ID
    assert result.metric_contract["native_to_canonical"]["oAC_best_dB"] == "acoustic_contrast_db"
    assert result.recommendation["family_match"] is True


def test_preflight_uses_repro_handoff_preview(db_session, monkeypatch):
    gid = _make_goal(db_session)
    ac = _approach(db_session, gid)
    exp = _experiment(db_session, gid, [ac.id])
    report = {
        "schema": "co_scientist.run_request.v1",
        "runnable": True,
        "blocking_reasons": [],
        "warnings": ["handoff preview warning"],
        "proposal": {
            "objective": "Measure contrast",
            "hypothesis": "Higher order increases contrast.",
            "independent_variables": {},
            "metrics": ["acoustic_contrast_db"],
            "pass_conditions": [
                {"metric": "acoustic_contrast_db", "operator": ">=", "value": 20.0}
            ],
            "method_family": "acoustic_contrast_control",
            "experiment_id": _VAST_EXPERIMENT_ID,
        },
        "selected_reproduction_id": _VAST_EXPERIMENT_ID,
        "selected_paper_id": _VAST_PAPER_ID,
        "selected_method_families": list(_VAST_FAMILIES),
        "honored": [{"proposal_name": "t60", "canonical": "reverb_t60_s"}],
        "dropped": [{"proposal_name": "speaker_count", "reason": "unsupported"}],
        "method_family_supported": True,
        "result_contract": {"expected_metrics": ["acoustic_contrast_db"]},
    }
    fake = _PreviewReproClient(report)
    monkeypatch.setattr(svc, "ReproClient", lambda: fake)

    result = svc.preflight_experiment(db_session, exp.id, gid)

    assert result.runnable is True
    assert result.selected_reproduction_id == _VAST_EXPERIMENT_ID
    assert result.metric_contract["native_to_canonical"]["oAC_best_dB"] == "acoustic_contrast_db"
    assert result.recommendation["source"] == "handoffs.preview"
    assert result.recommendation["honored"] == report["honored"]
    assert result.recommendation["dropped"] == report["dropped"]
    assert "handoff preview warning" in result.warnings
    assert fake.top_k is not None
    assert fake.payload["schema"] == "co_scientist.run_request.v1"
    assert fake.payload["experiment"]["method_family"] == "acoustic_contrast_control"
    assert fake.payload["co_scientist"]["experiment_id"] == exp.id
    assert fake.payload["result_contract"]["required_correlation"]["approach_ids"] == [ac.id]
    assert (
        fake.payload["result_contract"]["result_bundle_endpoint"]
        == "http://localhost:8001/co-scientist/result-bundles"
    )


def test_preflight_uses_card_control_plane_for_preview(db_session, monkeypatch):
    gid = _make_goal(db_session)
    ac = _approach(db_session, gid)
    exp = _experiment(db_session, gid, [ac.id])
    exp.experiment_control_plane = "http://configured-runner"
    db_session.commit()
    report = {
        "schema": "co_scientist.run_request.v1",
        "runnable": True,
        "blocking_reasons": [],
        "warnings": [],
        "proposal": {"objective": "Measure contrast"},
        "selected_reproduction_id": _VAST_EXPERIMENT_ID,
        "selected_paper_id": _VAST_PAPER_ID,
        "selected_method_families": list(_VAST_FAMILIES),
        "method_family_supported": True,
    }
    fake = _PreviewReproClient(report)
    bases = []

    def _client(*, base_url=None):
        bases.append(base_url)
        return fake

    monkeypatch.setattr(svc, "ReproClient", _client)

    result = svc.preflight_experiment(db_session, exp.id, gid)

    assert result.runnable is True
    assert bases == ["http://configured-runner"]
    assert fake.payload["control_plane_uri"] == "http://configured-runner"


def test_preflight_uses_repro_declared_metric_aliases(db_session, monkeypatch):
    gid = _make_goal(db_session)
    ac = _approach(db_session, gid)
    exp = _experiment(db_session, gid, [ac.id])
    report = {
        "schema": "co_scientist.run_request.v1",
        "runnable": True,
        "blocking_reasons": [],
        "warnings": [],
        "proposal": {"objective": "Measure contrast"},
        "selected_reproduction_id": "new-repro-v1",
        "selected_paper_id": "paper-new",
        "selected_method_families": ["acoustic_contrast_control"],
        "method_family_supported": True,
        "metric_aliases": {"native_contrast": "acoustic_contrast_db"},
    }
    fake = _PreviewReproClient(report)
    monkeypatch.setattr(svc, "ReproClient", lambda: fake)

    result = svc.preflight_experiment(db_session, exp.id, gid)

    assert result.runnable is True
    assert result.blocking_reasons == []
    assert result.unmeasurable_conditions == []
    assert result.metric_contract["native_to_canonical"] == {
        "native_contrast": "acoustic_contrast_db"
    }
    assert "local metric map fallback" not in " ".join(result.warnings)


def test_preflight_reports_no_runnable_reproduction(db_session, monkeypatch):
    gid = _make_goal(db_session)
    ac = _approach(db_session, gid)
    exp = _experiment(db_session, gid, [ac.id])
    fake = _FakeReproClient(candidates=[_vast_candidate(runnable=False, experiment_ids=[])])
    monkeypatch.setattr(svc, "ReproClient", lambda: fake)

    result = svc.preflight_experiment(db_session, exp.id, gid)

    assert result.runnable is False
    assert result.selected_reproduction_id is None
    assert any("no runnable reproduction" in reason for reason in result.blocking_reasons)


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


def test_run_requires_family_match_when_requested(db_session, monkeypatch):
    gid = _make_goal(db_session)
    ac = _approach(db_session, gid, method_family="crosstalk_cancellation")
    exp = _experiment(db_session, gid, [ac.id])
    fake = _FakeReproClient(metrics={"oAC_best_dB": 18.5, "nsde_achieved_dB": -25.0})
    monkeypatch.setattr(svc, "ReproClient", lambda: fake)

    with pytest.raises(HTTPException) as exc:
        svc.run_experiment(db_session, exp.id, gid, require_family_match=True)

    assert exc.value.status_code == 422
    assert "does not support comparison child method_family" in exc.value.detail
    assert fake.submitted_proposal is None


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
    result = svc.run_experiment(db_session, exp.id, gid)
    assert "latency_ms" in result.recommendation["unmeasurable_pass_conditions"]
    assert "acoustic_contrast_db" not in result.recommendation["unmeasurable_pass_conditions"]
    assert "latency_ms" in result.result_bundle.bundle.provenance["unmeasurable_conditions"]
    latency = next(c for c in result.validation.criterion_results if c.name == "latency_ms")
    assert latency.measured is None


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


# ---------------------------------------------------------------------------
# Comparison run (task #49): a >1-approach card is decomposed into per-approach
# single-method children, each run through run_experiment (faked here), then compared.
# ---------------------------------------------------------------------------

def _fake_run_experiment(monkeypatch, metrics_by_approach, decision_by_approach=None):
    """Replace run_experiment with a stub that mimics the child's real transitions."""
    decisions = decision_by_approach or {}
    _final = {
        "validated": ExperimentStatusEnum.completed,
        "refuted": ExperimentStatusEnum.failed,
        "inconclusive": ExperimentStatusEnum.inconclusive,
    }

    def _run(db, experiment_id, goal_id, *, timeout=None, require_family_match=False):
        child = experiment_svc.get(db, experiment_id)
        aid = child.approach_ids[0]
        if aid not in metrics_by_approach:
            raise HTTPException(status_code=502, detail=f"no runnable reproduction for {aid[:8]}…")
        metrics = metrics_by_approach[aid]
        decision = decisions.get(aid, "validated")
        experiment_svc.transition(db, experiment_id, ExperimentStatusEnum.running)
        experiment_svc.transition(db, experiment_id, _final[decision])
        return RunnerResult(
            experiment_id=experiment_id,
            goal_id=goal_id,
            run_id="run-x",
            simulator="sim",
            repro_status="success",
            raw_metrics=metrics,
            measured_metrics=metrics,
            validation=ValidationResultResponse(
                id=str(uuid.uuid4()),
                experiment_id=experiment_id,
                goal_id=goal_id,
                approach_id=aid,
                decision=ValidationDecisionEnum(decision),
                reproduction_status=ReproductionStatusEnum.reproduced,
                confidence=0.9,
                reasoning="ok",
                criterion_results=[],
                refinement_suggestions=[],
                measured_metrics=metrics,
                artifact_paths=None,
                model_used="test",
                created_at=datetime.now(timezone.utc),
            ),
            recommendation={},
        )

    monkeypatch.setattr(svc, "run_experiment", _run)


def test_run_comparison_two_children_completes_and_picks_winner(db_session, monkeypatch):
    gid = _make_goal(db_session)
    a1 = _approach(db_session, gid, method_family="acoustic_contrast_control")
    a2 = _approach(db_session, gid, method_family="pressure_matching")
    exp = _experiment(
        db_session, gid, [a1.id, a2.id],
        pass_conditions={"acoustic_contrast_db_min": 20.0, "bright_zone_error_max": -20.0},
    )
    _fake_run_experiment(monkeypatch, {
        a1.id: {"acoustic_contrast_db": 25.0, "bright_zone_error": -40.0},
        a2.id: {"acoustic_contrast_db": 22.0, "bright_zone_error": -30.0},
    })

    result = svc.run_comparison(db_session, exp.id, gid)

    assert result.status == "completed"
    assert result.recommended_approach_id == a1.id
    mc = {c.metric: c for c in result.metric_comparisons}
    assert mc["acoustic_contrast_db"].direction == "higher_better"
    assert mc["acoustic_contrast_db"].best_approach_id == a1.id  # 25 > 22
    assert mc["bright_zone_error"].direction == "lower_better"
    assert mc["bright_zone_error"].best_approach_id == a1.id     # -40 < -30
    # parent transitioned approved → running → completed
    db_session.refresh(exp)
    assert exp.status == ExperimentStatusEnum.completed.value
    # comparison summary persisted on the parent
    comp = json.loads(exp.batch_expansion)["comparison"]
    assert comp["recommended_approach_id"] == a1.id
    assert set(comp["child_experiment_ids"].keys()) == {a1.id, a2.id}


def test_run_comparison_one_child_errors_is_inconclusive(db_session, monkeypatch):
    gid = _make_goal(db_session)
    a1 = _approach(db_session, gid, method_family="acoustic_contrast_control")
    a2 = _approach(db_session, gid, method_family="pressure_matching")
    exp = _experiment(db_session, gid, [a1.id, a2.id])
    # only a1 produces metrics; a2's child run raises → recorded as an error
    _fake_run_experiment(monkeypatch, {a1.id: {"acoustic_contrast_db": 25.0}})

    result = svc.run_comparison(db_session, exp.id, gid)

    assert result.status == "inconclusive"
    assert result.recommended_approach_id is None
    errored = [r for r in result.approach_runs if r.error]
    assert len(errored) == 1 and errored[0].approach_id == a2.id
    db_session.refresh(exp)
    assert exp.status == ExperimentStatusEnum.inconclusive.value


def test_run_comparison_all_error_leaves_approved(db_session, monkeypatch):
    gid = _make_goal(db_session)
    a1 = _approach(db_session, gid, method_family="acoustic_contrast_control")
    a2 = _approach(db_session, gid, method_family="pressure_matching")
    exp = _experiment(db_session, gid, [a1.id, a2.id])
    _fake_run_experiment(monkeypatch, {})  # no approach produces metrics

    with pytest.raises(HTTPException) as exc:
        svc.run_comparison(db_session, exp.id, gid)
    assert exc.value.status_code == 502
    db_session.refresh(exp)
    assert exp.status == ExperimentStatusEnum.approved.value


def test_run_comparison_single_approach_refuses(db_session, monkeypatch):
    gid = _make_goal(db_session)
    a1 = _approach(db_session, gid, method_family="acoustic_contrast_control")
    exp = _experiment(db_session, gid, [a1.id])

    with pytest.raises(HTTPException) as exc:
        svc.run_comparison(db_session, exp.id, gid)
    assert exc.value.status_code == 422
    assert "comparison card" in exc.value.detail


def test_run_comparison_tie_has_no_winner(db_session, monkeypatch):
    gid = _make_goal(db_session)
    a1 = _approach(db_session, gid, method_family="acoustic_contrast_control")
    a2 = _approach(db_session, gid, method_family="pressure_matching")
    exp = _experiment(
        db_session, gid, [a1.id, a2.id],
        pass_conditions={"acoustic_contrast_db_min": 20.0, "bright_zone_error_max": -20.0},
    )
    # a1 wins contrast, a2 wins error → 1-1 tie; both validated so no tiebreak
    _fake_run_experiment(monkeypatch, {
        a1.id: {"acoustic_contrast_db": 25.0, "bright_zone_error": -30.0},
        a2.id: {"acoustic_contrast_db": 22.0, "bright_zone_error": -40.0},
    })

    result = svc.run_comparison(db_session, exp.id, gid)

    assert result.status == "completed"
    assert result.recommended_approach_id is None
    assert "clear winner" in result.rationale.lower() or "tie" in result.rationale.lower()


def test_run_comparison_equal_metric_values_has_no_winner(db_session, monkeypatch):
    gid = _make_goal(db_session)
    a1 = _approach(db_session, gid, method_family="acoustic_contrast_control")
    a2 = _approach(db_session, gid, method_family="pressure_matching")
    exp = _experiment(
        db_session, gid, [a1.id, a2.id],
        pass_conditions={"acoustic_contrast_db_min": 20.0},
    )
    _fake_run_experiment(monkeypatch, {
        a1.id: {"acoustic_contrast_db": 23.0},
        a2.id: {"acoustic_contrast_db": 23.0},
    })

    result = svc.run_comparison(db_session, exp.id, gid)

    assert result.status == "completed"
    assert result.recommended_approach_id is None
    assert result.metric_comparisons[0].best_approach_id is None
    assert "tied" in result.rationale.lower()


def test_result_bundle_error_rolls_back_to_approved(db_session, monkeypatch):
    # If bundle ingestion raises after the card is moved to 'running', the runner
    # rolls it back to 'approved' so it stays re-runnable.
    gid = _make_goal(db_session)
    ac = _approach(db_session, gid)
    exp = _experiment(db_session, gid, [ac.id])

    monkeypatch.setattr(
        svc, "ReproClient",
        lambda: _FakeReproClient(metrics={"oAC_best_dB": 18.5, "nsde_achieved_dB": -25.0}),
    )

    def _boom(db, body):
        raise HTTPException(status_code=502, detail="bundle sink unavailable")

    monkeypatch.setattr(svc.result_bundle_svc, "ingest_result_bundle", _boom)

    with pytest.raises(HTTPException) as exc:
        svc.run_experiment(db_session, exp.id, gid)
    assert exc.value.status_code == 502
    db_session.refresh(exp)
    assert exp.status == ExperimentStatusEnum.approved.value
