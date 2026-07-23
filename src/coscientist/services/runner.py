"""Real experiment runner: drives the repro API (:8003) and feeds the measured
metrics through the existing validation pipeline.

Flow for ``run_experiment`` (P4 recommend-method):
  1. resolve the experiment card + its primary approach (family + evidence papers)
  2. ask repro's recommend-method to rank runnable reproductions for the card's
     hypothesis; run the top runnable candidate (no local method→simulator dict)
  3. design-run that reproduction, poll to completion
  4. pull metrics.json, translate native keys → co-scientist canonical names
     (keyed by the reproduction's stable experiment_id)
  5. transition the card approved → running and call validation.submit_results

The reproduction is chosen by repro, not a local registry: ``method_family`` is a
bias hint into ranking, and divergence between the card's committed family and the
reproduction repro actually recommends is recorded as provenance, never silent.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone

import httpx
from fastapi import HTTPException
from sqlalchemy.orm import Session

from coscientist.clients.repro import ReproClient
from coscientist.config import settings
from coscientist.domain import canonicalize_metric
from coscientist.models.evidence import EvidenceRecord
from coscientist.models.experiment import ExperimentCard
from coscientist.schemas.experiment import ExperimentStatusEnum
from coscientist.schemas.runner import (
    ApproachRunSummary,
    ComparisonResult,
    MetricComparison,
    RunnerResult,
)
from coscientist.schemas.validation import ExperimentResultSubmission
from coscientist.services import approach as approach_svc
from coscientist.services import experiment as experiment_svc
from coscientist.services import goal as goal_svc
from coscientist.services import governance as governance_svc
from coscientist.services import roadmap as roadmap_svc
from coscientist.services import validation as validation_svc


# repro experiment_id → {native metrics.json key: canonical co-scientist name}.
# Native→canonical translation is co-scientist domain knowledge (metrics-surface
# reports native names only), keyed by the reproduction's stable experiment_id
# (which is only known after recommend-method picks a candidate). Reproductions
# absent here (or that emit no top-level scalar metrics.json) yield no translatable
# metrics → the runner refuses rather than fabricate a verdict. Add entries as a
# reproduction's emitted native keys are confirmed from a sample run.
EXPERIMENT_METRIC_MAP: dict[str, dict[str, str]] = {
    "fast-generation-of-sound-zones-using-var-v1": {
        "oAC_best_dB": "acoustic_contrast_db",
        "nsde_achieved_dB": "bright_zone_error",
    },
}

_TERMINAL_OK = "success"
_TERMINAL_BAD = {"failed", "cancelled"}


def _primary_approach(db: Session, approach_ids: list[str]) -> tuple[str, list[str]]:
    """Resolve the single approach's ``method_family`` and its evidence paper ids.

    Combination experiments (>1 approach) describe a method no single-paper
    reproduction runs; auto-running one ingredient and labelling it as the
    combination's result would fabricate a verdict. Refuse and route to the
    manual submission lane instead.
    """
    if len(approach_ids) > 1:
        raise HTTPException(
            status_code=422,
            detail=(
                "Experiment has multiple approaches; run it as a comparison "
                "('cs experiment run' dispatches comparison cards to the per-approach runner) "
                "or submit externally with 'cs validation submit'."
            ),
        )

    family: str | None = None
    evidence_ids: list[str] = []
    for aid in approach_ids:
        try:
            approach = approach_svc.get(db, aid)
        except HTTPException:
            continue
        family = approach.method_family
        evidence_ids = [link.evidence_id for link in approach.evidence_links]
        break
    if family is None:
        raise HTTPException(
            status_code=422,
            detail="Experiment has no resolvable approach to determine a method family.",
        )

    paper_ids: list[str] = []
    if evidence_ids:
        rows = (
            db.query(EvidenceRecord.paper_id)
            .filter(EvidenceRecord.id.in_(evidence_ids))
            .all()
        )
        seen: set[str] = set()
        for (pid,) in rows:
            if pid and pid not in seen:
                seen.add(pid)
                paper_ids.append(pid)
    return family, paper_ids


def _translate(raw: dict, metric_map: dict[str, str]) -> dict[str, float]:
    out: dict[str, float] = {}
    for native, canonical in metric_map.items():
        val = raw.get(native)
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            out[canonical] = float(val)
    return out


def _list_workspaces(client: ReproClient) -> list[dict]:
    try:
        return client.list_workspaces()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"repro API error listing workspaces: {exc}")


def _home_workspace(workspaces: list[dict], paper_ids: list[str]) -> str:
    """Pick a workspace to call recommend-method against.

    recommend-method is corpus-wide, so the URL workspace is just a valid handle;
    prefer one bound to the card's approach paper, else the first workspace with a
    retrieval paper. 422 if repro has no usable workspace.
    """
    by_paper = {w.get("retrieval_paper_id"): w["id"] for w in workspaces if w.get("retrieval_paper_id")}
    for pid in paper_ids:
        if pid in by_paper:
            return by_paper[pid]
    if by_paper:
        return next(iter(by_paper.values()))
    raise HTTPException(
        status_code=422,
        detail=(
            "No repro workspace with a bound paper is available to query recommend-method. "
            "Run the experiment externally and use 'cs validation submit'."
        ),
    )


def _select_candidate(rec: dict) -> dict:
    """Take the top-ranked runnable candidate with a concrete experiment id.

    Candidates are returned in rank order; the first with ``runnable`` and a
    non-empty ``experiment_ids`` is the reproduction repro recommends running.
    422 if none is runnable (route to the manual submission lane).
    """
    for cand in rec.get("candidates", []):
        if cand.get("runnable") and cand.get("experiment_ids"):
            return cand
    raise HTTPException(
        status_code=422,
        detail=(
            "recommend-method returned no runnable reproduction for this hypothesis. "
            "Run the experiment externally and use 'cs validation submit'."
        ),
    )


def _workspace_for_paper(workspaces: list[dict], paper_id: str) -> str:
    matches = [w["id"] for w in workspaces if w.get("retrieval_paper_id") == paper_id]
    if not matches:
        raise HTTPException(
            status_code=422,
            detail=(
                f"recommend-method chose reproduction paper {paper_id!r} but no repro workspace "
                "is bound to it. Create it (POST /workspaces/from-paper) or run externally and "
                "use 'cs validation submit'."
            ),
        )
    return matches[0]


# Card validation.pass_conditions keys are suffixed with the comparison direction.
_PASS_SUFFIXES = (("_min", ">="), ("_max", "<="))


def _pass_conditions(pass_conditions: dict[str, float]) -> list[dict]:
    """Convert the card's pass_conditions dict into repro PassCondition list.

    ``{"acoustic_contrast_min": 15.0}`` → ``{metric: "acoustic_contrast_db",
    operator: ">=", value: 15.0}``. The bare metric name is canonicalized onto the
    METRIC_NAMES vocabulary so it reconciles with the canonical names the runner
    emits (``_translate``) — otherwise a measured metric is falsely flagged
    unmeasurable.
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
        out.append(
            {"metric": canonicalize_metric(metric), "operator": operator, "value": float(value)}
        )
    return out


def _unmeasurable_conditions(pass_conditions: list[dict], experiment_id: str) -> list[str]:
    """Card pass-condition metrics the chosen reproduction cannot produce.

    A canonical metric absent from the reproduction's translatable outputs can
    never be satisfied → the verdict is refuted for a metric it could never
    measure. We do NOT drop the criterion (that could fabricate a pass); we record
    it so the mismatch is auditable — the P4-origin always-refuted symptom.
    """
    measurable = set(EXPERIMENT_METRIC_MAP.get(experiment_id, {}).values())
    if not measurable:
        return []
    return [c["metric"] for c in pass_conditions if c["metric"] not in measurable]


def _build_proposal(card, method_family: str | None) -> dict:
    """Build a repro ExperimentProposal from the approved experiment card.

    ``card`` is an ``ExperimentCardResponse`` whose JSON columns are already parsed.
    ``method_family`` is the card's resolved approach family; repro uses it as the
    key for capability-aware ranking (P5) — a runnable reproduction that declares
    support for this family surfaces as a candidate even when its source paper is
    not textually about the method. Without it, recommend-method ranks by paper
    text alone and never surfaces the runnable reproduction for the card's method.
    """
    proposal: dict = {
        "objective": card.objective,
        "hypothesis": card.hypothesis_text,
        "independent_variables": card.independent_variables,
        "metrics": card.metrics,
        "pass_conditions": _pass_conditions(card.validation.pass_conditions),
    }
    if method_family:
        proposal["method_family"] = method_family
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


def _record_run_provenance(
    db: Session,
    experiment_id: str,
    workspace_id: str,
    design: dict,
    run_id: str,
    recommendation: dict,
) -> None:
    """Persist the run's design-run report + recommendation provenance on the card."""
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
            "recommendation": recommendation,
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

    card_family, paper_ids = _primary_approach(db, card.approach_ids)
    timeout = timeout if timeout is not None else settings.repro_run_timeout
    proposal = _build_proposal(card, card_family)

    try:
        with ReproClient() as client:
            workspaces = _list_workspaces(client)
            home_ws = _home_workspace(workspaces, paper_ids)
            rec = client.recommend_method(
                home_ws, proposal, top_k=settings.runner_recommend_top_k, draft=False
            )
            candidate = _select_candidate(rec)
            experiment_id_repro = candidate["experiment_ids"][0]
            candidate_ws = _workspace_for_paper(workspaces, candidate["paper_id"])

            proposal["experiment_id"] = experiment_id_repro
            design = client.design_run(candidate_ws, proposal, auto_approve=True)
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

    cand_families = candidate.get("method_families", [])
    diverged = bool(card_family) and card_family not in cand_families
    unmeasurable = (
        _unmeasurable_conditions(_pass_conditions(card.validation.pass_conditions), experiment_id_repro)
        if settings.runner_align_pass_conditions
        else []
    )
    recommendation = {
        "candidate_paper_id": candidate.get("paper_id"),
        "title": candidate.get("title"),
        "score": candidate.get("score"),
        "experiment_id": experiment_id_repro,
        "method_families": cand_families,
        "family_match": candidate.get("family_match"),
        "card_method_family": card_family,
        "diverged_from_card_family": diverged,
        "unmeasurable_pass_conditions": unmeasurable,
    }
    honored = design.get("honored", [])
    dropped = design.get("dropped", [])
    _record_run_provenance(db, experiment_id, candidate_ws, design, run_id, recommendation)

    measured = _translate(raw_metrics, EXPERIMENT_METRIC_MAP.get(experiment_id_repro, {}))
    if not measured:
        raise HTTPException(
            status_code=502,
            detail=(
                f"repro run {run_id!r} produced no translatable metrics for reproduction "
                f"{experiment_id_repro!r}; refusing to fabricate. Experiment left 'approved'."
            ),
        )

    # The run succeeded and produced metrics. Transition to 'running' and hand off to
    # validation. If validation raises (infra error, not a refuted verdict), roll the
    # card back to 'approved' so it stays re-runnable — the state machine has no
    # running→approved edge, so this compensating write is the runner's responsibility.
    experiment_svc.transition(db, experiment_id, ExperimentStatusEnum.running)
    diverge_note = (
        f" recommended method diverges from card family {card_family!r} "
        f"(ran {cand_families})."
        if diverged
        else ""
    )
    submission = ExperimentResultSubmission(
        measured_metrics=measured,
        artifact_paths={"metrics_json": f"runs/{run_id}/metrics.json"},
        notes=(
            f"Auto-run via repro recommend-method ({experiment_id_repro}, run {run_id}); "
            f"honored={len(honored)} dropped={len(dropped)}.{diverge_note}"
        ),
        unmeasurable_conditions=unmeasurable,
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
        simulator=experiment_id_repro,
        repro_status=_TERMINAL_OK,
        raw_metrics={k: float(v) for k, v in raw_metrics.items() if isinstance(v, (int, float)) and not isinstance(v, bool)},
        measured_metrics=measured,
        validation=result,
        recommendation=recommendation,
    )


# ---------------------------------------------------------------------------
# Comparison run (task #49): decompose a >1-approach card into per-approach
# single-method child runs, then compare on shared metrics. repro is strictly
# single-method, so the fan-out is orchestrated here; each child goes through
# ``run_experiment`` unchanged.
# ---------------------------------------------------------------------------

def _metric_directions(pass_conditions: dict[str, float]) -> dict[str, str]:
    """Map each canonical pass-condition metric to a comparison direction.

    ``_min`` (>=) means higher is better; ``_max`` (<=) means lower is better.
    Equality/target conditions have no better/worse direction → omitted, so they
    never drive a winner.
    """
    directions: dict[str, str] = {}
    for key in (pass_conditions or {}):
        for suffix, _ in _PASS_SUFFIXES:
            if key.endswith(suffix):
                metric = canonicalize_metric(key[: -len(suffix)])
                directions[metric] = "higher_better" if suffix == "_min" else "lower_better"
                break
    return directions


def _compare_metrics(
    runs: list[ApproachRunSummary],
    directions: dict[str, str],
) -> tuple[list[MetricComparison], str | None, str]:
    """Rank comparable approaches per metric and pick an overall recommendation."""
    comparable = [r for r in runs if r.measured_metrics]
    comparisons: list[MetricComparison] = []
    wins: dict[str, int] = {}
    for metric, direction in sorted(directions.items()):
        values = {
            r.approach_id: r.measured_metrics[metric]
            for r in comparable
            if metric in r.measured_metrics
        }
        if len(values) < 2:
            continue
        if direction == "higher_better":
            best = max(values, key=values.get)
        else:
            best = min(values, key=values.get)
        wins[best] = wins.get(best, 0) + 1
        comparisons.append(
            MetricComparison(
                metric=metric, direction=direction, values=values, best_approach_id=best
            )
        )

    if not wins:
        return comparisons, None, "No shared, directional metric was measured by ≥2 approaches."

    top = max(wins.values())
    leaders = [aid for aid, n in wins.items() if n == top]
    if len(leaders) == 1:
        aid = leaders[0]
        return comparisons, aid, f"Approach {aid[:8]}… wins {top} of {len(comparisons)} metric(s)."

    # Tie on metric wins → prefer a leader whose own child validated.
    validated = {r.approach_id for r in comparable if r.decision == "validated"}
    tiebreak = [aid for aid in leaders if aid in validated]
    if len(tiebreak) == 1:
        aid = tiebreak[0]
        return comparisons, aid, f"Tie on metric wins; {aid[:8]}… broke it with a validated verdict."
    return comparisons, None, f"No clear winner: {len(leaders)} approaches tied on metric wins."


def run_comparison(
    db: Session,
    experiment_id: str,
    goal_id: str,
    *,
    timeout: float | None = None,
) -> ComparisonResult:
    governance_svc.assert_execution_boundary("run experiments")
    goal_svc.raise_if_restricted(db, goal_id)
    parent = experiment_svc.get(db, experiment_id)
    if parent.workspace_id != goal_id:
        raise HTTPException(
            status_code=404,
            detail=f"Experiment {experiment_id!r} not found in goal {goal_id!r}",
        )
    if parent.status != ExperimentStatusEnum.approved:
        raise HTTPException(
            status_code=409,
            detail=f"Experiment must be 'approved' to run, got {parent.status.value!r}",
        )
    if len(parent.approach_ids) < 2:
        raise HTTPException(
            status_code=422,
            detail="Not a comparison card (needs ≥2 approaches); use 'cs experiment run' single-method path.",
        )

    experiment_svc.supersede_comparison_children(db, parent)
    goal = goal_svc.get(db, goal_id)

    runs: list[ApproachRunSummary] = []
    for approach_id in parent.approach_ids:
        try:
            approach_resp = approach_svc.get(db, approach_id)
        except HTTPException as exc:
            runs.append(
                ApproachRunSummary(
                    approach_id=approach_id,
                    child_experiment_id="",
                    status="error",
                    error=str(exc.detail),
                )
            )
            continue

        child = experiment_svc.create_comparison_child(db, parent, approach_resp, goal)
        try:
            child_result = run_experiment(db, child.id, goal_id, timeout=timeout)
        except HTTPException as exc:
            runs.append(
                ApproachRunSummary(
                    approach_id=approach_id,
                    child_experiment_id=child.id,
                    method_family=approach_resp.method_family,
                    status="error",
                    error=str(exc.detail),
                )
            )
            continue
        child_card = experiment_svc.get(db, child.id)
        runs.append(
            ApproachRunSummary(
                approach_id=approach_id,
                child_experiment_id=child.id,
                method_family=approach_resp.method_family,
                status=child_card.status.value,
                decision=child_result.validation.decision.value,
                measured_metrics=child_result.measured_metrics,
            )
        )

    comparable = [r for r in runs if r.measured_metrics]
    if not comparable:
        errors = "; ".join(f"{r.approach_id[:8]}…: {r.error}" for r in runs if r.error)
        raise HTTPException(
            status_code=502,
            detail=(
                f"No approach produced measurable metrics; comparison left 'approved'. {errors}"
            ),
        )

    directions = _metric_directions(parent.validation.pass_conditions)
    comparisons, recommended, rationale = _compare_metrics(runs, directions)

    if len(comparable) == 1:
        recommended = None
        rationale = "Only one approach produced metrics; a head-to-head comparison needs ≥2."
        final_status = ExperimentStatusEnum.inconclusive
    else:
        final_status = ExperimentStatusEnum.completed

    experiment_svc.transition(db, experiment_id, ExperimentStatusEnum.running)
    experiment_svc.transition(db, experiment_id, final_status)

    _record_comparison(db, experiment_id, runs, comparisons, recommended, rationale)
    roadmap_svc.retire_for_experiment(db, experiment_id, goal_id)

    return ComparisonResult(
        experiment_id=experiment_id,
        goal_id=goal_id,
        approach_runs=runs,
        metric_comparisons=comparisons,
        recommended_approach_id=recommended,
        rationale=rationale,
        status=final_status.value,
    )


def _record_comparison(
    db: Session,
    experiment_id: str,
    runs: list[ApproachRunSummary],
    comparisons: list[MetricComparison],
    recommended: str | None,
    rationale: str,
) -> None:
    row = db.get(ExperimentCard, experiment_id)
    if row is None:
        return
    existing = json.loads(row.batch_expansion) if row.batch_expansion else {}
    existing["comparison"] = {
        "child_experiment_ids": {r.approach_id: r.child_experiment_id for r in runs},
        "per_approach": [r.model_dump() for r in runs],
        "metric_comparisons": [c.model_dump() for c in comparisons],
        "recommended_approach_id": recommended,
        "rationale": rationale,
    }
    row.batch_expansion = json.dumps(existing)
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
