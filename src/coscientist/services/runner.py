"""Real experiment runner: drives the repro API (:8003) and feeds the measured
metrics through the existing validation pipeline.

Flow for ``run_experiment``:
  1. resolve the experiment card + its primary approach's method family
  2. pick a repro simulator for that family (no fabrication if none registered)
  3. POST a spec to repro, poll the run to completion
  4. pull metrics.json, translate native keys → co-scientist canonical names
  5. transition the card approved → running and call validation.submit_results
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

from coscientist.clients.repro import ReproClient
from coscientist.config import settings
from coscientist.models.experiment import ExperimentCard
from coscientist.schemas.experiment import ExperimentStatusEnum
from coscientist.schemas.runner import RunnerResult
from coscientist.schemas.validation import ExperimentResultSubmission
from coscientist.services import approach as approach_svc
from coscientist.services import experiment as experiment_svc
from coscientist.services import goal as goal_svc
from coscientist.services import governance as governance_svc
from coscientist.services import validation as validation_svc


@dataclass(frozen=True)
class Simulator:
    """A repro reproduction and how to translate its metrics to canonical names.

    ``repro_paper_id`` is the retrieval paper id of the curated reproduction whose
    descriptor grounds the design-run command. The live repro workspace is resolved
    by matching this against ``workspace.retrieval_paper_id`` at run time, so we
    never hardcode environment-specific workspace UUIDs.
    """

    script: str
    metric_map: dict[str, str]
    repro_paper_id: str
    experiment_id: str | None = None
    extra_args: list[str] = field(default_factory=list)


# repro reproductions write runs/${RUN_ID}/metrics.json (token resolved by repro).
# Only top-level scalar keys can be translated; nested/non-numeric keys are dropped.
_VAST = Simulator(
    script="vast_simulate.py",
    repro_paper_id="786380fd-256b-46b6-b71e-af1b41adeb0b",
    metric_map={
        "oAC_best_dB": "acoustic_contrast_db",
        "nsde_achieved_dB": "bright_zone_error",
    },
)

# method_family → simulator. Families absent here have no auto-runner and fall back
# to manual `cs validation submit` (never fabricated metrics).
SIMULATOR_REGISTRY: dict[str, Simulator] = {
    "acoustic_contrast_control": _VAST,
    "beamforming": _VAST,
    "pressure_matching": _VAST,
    "null_steering": _VAST,
}

_TERMINAL_OK = "success"
_TERMINAL_BAD = {"failed", "cancelled"}


def _resolve_simulator(db: Session, approach_ids: list[str]) -> Simulator:
    """Pick the simulator for a single-approach experiment.

    Combination experiments (>1 approach) describe a method no single-paper
    reproduction runs; auto-running one ingredient and labelling it as the
    combination's result would fabricate a verdict. Refuse and route to the
    manual submission lane instead.
    """
    if len(approach_ids) > 1:
        raise HTTPException(
            status_code=422,
            detail=(
                "Experiment combines multiple approaches; no single-paper repro simulator "
                "can run the combination. Run it externally and use 'cs validation submit'."
            ),
        )

    family: str | None = None
    for aid in approach_ids:
        try:
            family = approach_svc.get(db, aid).method_family
            break
        except HTTPException:
            continue
    if family is None:
        raise HTTPException(
            status_code=422,
            detail="Experiment has no resolvable approach to determine a method family.",
        )

    sim = SIMULATOR_REGISTRY.get(family)
    if sim is None:
        raise HTTPException(
            status_code=422,
            detail=(
                f"No repro simulator registered for method family {family!r}. "
                "Run the experiment externally and use 'cs validation submit' instead."
            ),
        )
    return sim


def _translate(raw: dict, metric_map: dict[str, str]) -> dict[str, float]:
    out: dict[str, float] = {}
    for native, canonical in metric_map.items():
        val = raw.get(native)
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            out[canonical] = float(val)
    return out


def _resolve_workspace(client: ReproClient, sim: Simulator) -> str:
    """Find the live repro workspace whose paper matches the reproduction's paper.

    design-run is workspace-scoped; we match on ``retrieval_paper_id`` so the
    workspace UUID need not be hardcoded. Zero matches → 422 (route to manual lane).
    """
    try:
        workspaces = client.list_workspaces()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"repro API error listing workspaces: {exc}")
    matches = [w["id"] for w in workspaces if w.get("retrieval_paper_id") == sim.repro_paper_id]
    if not matches:
        raise HTTPException(
            status_code=422,
            detail=(
                f"No repro workspace found for reproduction paper {sim.repro_paper_id!r}. "
                "Create it (POST /workspaces/from-paper) or run externally and use "
                "'cs validation submit'."
            ),
        )
    return matches[0]


# Card validation.pass_conditions keys are suffixed with the comparison direction.
_PASS_SUFFIXES = (("_min", ">="), ("_max", "<="))


def _pass_conditions(pass_conditions: dict[str, float]) -> list[dict]:
    """Convert the card's pass_conditions dict into repro PassCondition list.

    ``{"acoustic_contrast_min": 15.0}`` → ``{metric, operator: ">=", value: 15.0}``.
    """
    out: list[dict] = []
    for key, value in (pass_conditions or {}).items():
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            continue
        metric, operator = key, ">="
        for suffix, op in _PASS_SUFFIXES:
            if key.endswith(suffix):
                metric, operator = key[: -len(suffix)], op
                break
        out.append({"metric": metric, "operator": operator, "value": float(value)})
    return out


def _build_proposal(card, sim: Simulator) -> dict:
    """Build a repro ExperimentProposal from the approved experiment card.

    ``card`` is an ``ExperimentCardResponse`` whose JSON columns are already parsed.
    """
    proposal = {
        "objective": card.objective,
        "hypothesis": card.hypothesis_text,
        "independent_variables": card.independent_variables,
        "metrics": card.metrics,
        "pass_conditions": _pass_conditions(card.validation.pass_conditions),
    }
    if sim.experiment_id is not None:
        proposal["experiment_id"] = sim.experiment_id
    return proposal


def _poll(client: ReproClient, run_id: str, timeout: float) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        meta = client.get_run(run_id)
        status = meta.get("status")
        if status == _TERMINAL_OK or status in _TERMINAL_BAD:
            return meta
        if time.monotonic() >= deadline:
            raise HTTPException(
                status_code=504,
                detail=f"repro run {run_id!r} did not finish within {timeout:.0f}s (last status {status!r})",
            )
        time.sleep(settings.repro_poll_interval)


def _record_design_provenance(
    db: Session,
    experiment_id: str,
    workspace_id: str,
    design: dict,
    run_id: str,
) -> None:
    """Persist the design-run's honored/dropped report + linkage onto the card."""
    row = db.get(ExperimentCard, experiment_id)
    if row is None:
        return
    run_request_ids = json.loads(row.run_request_ids) if row.run_request_ids else []
    if run_id not in run_request_ids:
        run_request_ids.append(run_id)
    row.run_request_ids = json.dumps(run_request_ids)
    row.batch_expansion = json.dumps(
        {
            "repro_workspace_id": workspace_id,
            "draft_id": design.get("draft_id"),
            "spec_status": design.get("spec_status"),
            "honored": design.get("honored", []),
            "dropped": design.get("dropped", []),
        }
    )
    row.updated_at = datetime.now(timezone.utc)
    db.commit()


def run_experiment(
    db: Session,
    experiment_id: str,
    goal_id: str,
    *,
    timeout: float | None = None,
) -> RunnerResult:
    governance_svc.assert_execution_boundary("run experiments")
    goal_svc.raise_if_restricted(db, goal_id)
    card = experiment_svc.get(db, experiment_id)
    if card.workspace_id != goal_id:
        raise HTTPException(
            status_code=404,
            detail=f"Experiment {experiment_id!r} not found in goal {goal_id!r}",
        )
    if card.status != ExperimentStatusEnum.approved:
        raise HTTPException(
            status_code=409,
            detail=f"Experiment must be 'approved' to run, got {card.status.value!r}",
        )

    sim = _resolve_simulator(db, card.approach_ids)

    timeout = timeout if timeout is not None else settings.repro_run_timeout
    proposal = _build_proposal(card, sim)

    try:
        with ReproClient() as client:
            workspace_id = _resolve_workspace(client, sim)
            design = client.design_run(workspace_id, proposal, auto_approve=True)
            run_id = design["run_id"]
            meta = _poll(client, run_id, timeout)
            if meta.get("status") != _TERMINAL_OK:
                raise HTTPException(
                    status_code=502,
                    detail=(
                        f"repro run {run_id!r} ended with status {meta.get('status')!r} "
                        f"(exit_code {meta.get('exit_code')}). Experiment left 'approved'."
                    ),
                )
            raw_metrics = client.get_run_metrics(run_id)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"repro API error: {exc}")

    # Record the design-run provenance on the card: which workspace/draft grounded
    # the run, and which proposal variables the descriptor honored vs. dropped. This
    # makes the arg-surface gap (e.g. speaker_count sweep dropped) auditable rather
    # than a silent collapse.
    honored = design.get("honored", [])
    dropped = design.get("dropped", [])
    _record_design_provenance(db, experiment_id, workspace_id, design, run_id)

    measured = _translate(raw_metrics, sim.metric_map)
    if not measured:
        raise HTTPException(
            status_code=502,
            detail=(
                f"repro run {run_id!r} produced no translatable metrics for {sim.script!r}; "
                "refusing to fabricate. Experiment left 'approved'."
            ),
        )

    # The run succeeded and produced metrics. Transition to 'running' and hand off to
    # validation. If validation raises (infra error, not a refuted verdict), roll the
    # card back to 'approved' so it stays re-runnable — the state machine has no
    # running→approved edge, so this compensating write is the runner's responsibility.
    experiment_svc.transition(db, experiment_id, ExperimentStatusEnum.running)
    submission = ExperimentResultSubmission(
        measured_metrics=measured,
        artifact_paths={"metrics_json": f"runs/{run_id}/metrics.json"},
        notes=(
            f"Auto-run via repro design-run ({sim.script}, run {run_id}); "
            f"honored={len(honored)} dropped={len(dropped)}."
        ),
    )
    try:
        result = validation_svc.submit_results(db, experiment_id, goal_id, submission)
    except Exception:
        card_row = db.get(ExperimentCard, experiment_id)
        if card_row is not None and card_row.status == ExperimentStatusEnum.running.value:
            card_row.status = ExperimentStatusEnum.approved.value
            card_row.updated_at = datetime.now(timezone.utc)
            db.commit()
        raise

    return RunnerResult(
        experiment_id=experiment_id,
        goal_id=goal_id,
        run_id=run_id,
        simulator=sim.script,
        repro_status=_TERMINAL_OK,
        raw_metrics={k: float(v) for k, v in raw_metrics.items() if isinstance(v, (int, float)) and not isinstance(v, bool)},
        measured_metrics=measured,
        validation=result,
    )
