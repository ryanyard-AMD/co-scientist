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

import time
from dataclasses import dataclass, field

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

from coscientist.clients.repro import ReproClient
from coscientist.config import settings
from coscientist.schemas.experiment import ExperimentStatusEnum
from coscientist.schemas.runner import RunnerResult
from coscientist.schemas.validation import ExperimentResultSubmission
from coscientist.services import approach as approach_svc
from coscientist.services import experiment as experiment_svc
from coscientist.services import goal as goal_svc
from coscientist.services import validation as validation_svc


@dataclass(frozen=True)
class Simulator:
    """A repro simulator and how to translate its metrics to canonical names."""

    script: str
    metric_map: dict[str, str]
    extra_args: list[str] = field(default_factory=list)


# repro PSZ simulators write runs/${RUN_ID}/metrics.json (token resolved by repro).
# Only top-level scalar keys can be translated; nested/non-numeric keys are dropped.
_VAST = Simulator(
    script="vast_simulate.py",
    extra_args=["--t60", "0.3"],
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


def _primary_method_family(db: Session, approach_ids: list[str]) -> str | None:
    for aid in approach_ids:
        try:
            return approach_svc.get(db, aid).method_family
        except HTTPException:
            continue
    return None


def _translate(raw: dict, metric_map: dict[str, str]) -> dict[str, float]:
    out: dict[str, float] = {}
    for native, canonical in metric_map.items():
        val = raw.get(native)
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            out[canonical] = float(val)
    return out


def _build_spec(card, sim: Simulator) -> dict:
    return {
        "experiment_id": card.id,
        "description": card.objective[:200],
        "command": [".venv/bin/python3", sim.script, "--output-dir", "runs/${RUN_ID}", *sim.extra_args],
        "seeds": [42],
    }


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


def run_experiment(
    db: Session,
    experiment_id: str,
    goal_id: str,
    *,
    timeout: float | None = None,
) -> RunnerResult:
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

    family = _primary_method_family(db, card.approach_ids)
    sim = SIMULATOR_REGISTRY.get(family) if family else None
    if sim is None:
        raise HTTPException(
            status_code=422,
            detail=(
                f"No repro simulator registered for method family {family!r}. "
                "Run the experiment externally and use 'cs validation submit' instead."
            ),
        )

    timeout = timeout if timeout is not None else settings.repro_run_timeout
    spec = _build_spec(card, sim)

    try:
        with ReproClient() as client:
            accepted = client.submit_run(spec)
            run_id = accepted["run_id"]
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

    measured = _translate(raw_metrics, sim.metric_map)
    if not measured:
        raise HTTPException(
            status_code=502,
            detail=(
                f"repro run {run_id!r} produced no translatable metrics for {family!r}; "
                "refusing to fabricate. Experiment left 'approved'."
            ),
        )

    experiment_svc.transition(db, experiment_id, ExperimentStatusEnum.running)
    submission = ExperimentResultSubmission(
        measured_metrics=measured,
        artifact_paths={"metrics_json": f"runs/{run_id}/metrics.json"},
        notes=f"Auto-run via repro simulator {sim.script} (run {run_id}).",
    )
    result = validation_svc.submit_results(db, experiment_id, goal_id, submission)

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
