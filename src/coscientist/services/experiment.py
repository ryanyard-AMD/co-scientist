import json
import pprint
import uuid
from datetime import datetime, timezone
from functools import reduce
from itertools import combinations
from operator import mul
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from coscientist.config import settings
from coscientist.domain import METRIC_NAMES, RELATED_METHODS
from coscientist.models.approach import ApproachCard
from coscientist.models.experiment import ExperimentCard
from coscientist.models.hypothesis import HypothesisCard
from coscientist.schemas.experiment import (
    CostEstimateEnum,
    ExperimentCardCreate,
    ExperimentCardResponse,
    ExperimentCardUpdate,
    ExperimentDimensionScoreResponse,
    ExperimentExportResponse,
    ExperimentGenerateRequest,
    ExperimentGenerateResponse,
    ExperimentRubricDimensionEnum,
    ExperimentScoreResponse,
    ExperimentStatusEnum,
    ExperimentTypeEnum,
    RuntimeSpec,
    ValidationCriteria,
)
from coscientist.schemas.goal import GoalResponse
from coscientist.services import approach as approach_svc
from coscientist.services import goal as goal_svc

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    ExperimentStatusEnum.generated:  {ExperimentStatusEnum.reviewed, ExperimentStatusEnum.superseded},
    ExperimentStatusEnum.reviewed:   {ExperimentStatusEnum.approved, ExperimentStatusEnum.superseded},
    ExperimentStatusEnum.approved:   {ExperimentStatusEnum.running, ExperimentStatusEnum.superseded},
    ExperimentStatusEnum.running:    {ExperimentStatusEnum.completed, ExperimentStatusEnum.failed, ExperimentStatusEnum.superseded},
    ExperimentStatusEnum.completed:  {ExperimentStatusEnum.superseded},
    ExperimentStatusEnum.failed:     {ExperimentStatusEnum.superseded},
    ExperimentStatusEnum.superseded: set(),
}

EXPERIMENT_WEIGHTS: dict[str, float] = {
    "hypothesis_clarity":      0.12,
    "device_relevance":        0.15,
    "baseline_quality":        0.10,
    "metric_quality":          0.12,
    "reproducibility":         0.12,
    "information_gain":        0.15,
    "cost_time":               0.08,
    "failure_informativeness": 0.06,
    "robustness_coverage":     0.07,
    "artifact_quality":        0.03,
}

_STANDARD_ARTIFACTS = [
    "transfer_functions",
    "impulse_responses",
    "metrics_json",
    "plots",
    "validation_report",
    "reproduction_manifest",
]

_ROBUSTNESS_VARS = {"listener_shift_cm", "reverberation_condition", "calibration_error"}

_UNIVERSAL_BASELINE = "delay_and_sum_beamforming"


def _to_response(card: ExperimentCard) -> ExperimentCardResponse:
    return ExperimentCardResponse(
        id=card.id,
        workspace_id=card.workspace_id,
        name=card.name,
        objective=card.objective,
        hypothesis_text=card.hypothesis_text,
        approach_ids=json.loads(card.approach_ids) if card.approach_ids else [],
        hypothesis_id=card.hypothesis_id,
        baseline_methods=json.loads(card.baseline_methods) if card.baseline_methods else [],
        independent_variables=json.loads(card.independent_variables) if card.independent_variables else {},
        fixed_assumptions=json.loads(card.fixed_assumptions) if card.fixed_assumptions else {},
        metrics=json.loads(card.metrics) if card.metrics else [],
        validation=ValidationCriteria(**json.loads(card.validation)) if card.validation else ValidationCriteria(),
        runtime=RuntimeSpec(**json.loads(card.runtime)) if card.runtime else RuntimeSpec(),
        artifacts=json.loads(card.artifacts) if card.artifacts else [],
        estimated_cost=card.estimated_cost,
        estimated_runtime=card.estimated_runtime,
        estimated_compute=card.estimated_compute,
        requires_human_approval=card.requires_human_approval,
        experiment_type=ExperimentTypeEnum(card.experiment_type),
        parameter_sweep_count=card.parameter_sweep_count,
        status=ExperimentStatusEnum(card.status),
        generation_run_id=card.generation_run_id,
        created_at=card.created_at,
        updated_at=card.updated_at,
    )


def _get_or_404(db: Session, experiment_id: str) -> ExperimentCard:
    card = db.get(ExperimentCard, experiment_id)
    if card is None:
        raise HTTPException(status_code=404, detail=f"Experiment {experiment_id!r} not found")
    return card


def create(db: Session, goal_id: str, data: ExperimentCardCreate) -> ExperimentCardResponse:
    goal = goal_svc.get(db, goal_id)
    for aid in data.approach_ids:
        ac = db.get(ApproachCard, aid)
        if ac is None:
            raise HTTPException(status_code=404, detail=f"Approach {aid!r} not found")
        if ac.workspace_id != goal.workspace_id:
            raise HTTPException(status_code=422, detail=f"Approach {aid!r} belongs to a different workspace")
    if data.hypothesis_id:
        hc = db.get(HypothesisCard, data.hypothesis_id)
        if hc is None:
            raise HTTPException(status_code=404, detail=f"Hypothesis {data.hypothesis_id!r} not found")

    now = datetime.now(timezone.utc)
    card = ExperimentCard(
        id=str(uuid.uuid4()),
        workspace_id=goal.workspace_id,
        name=data.name,
        objective=data.objective,
        hypothesis_text=data.hypothesis_text,
        approach_ids=json.dumps(data.approach_ids),
        hypothesis_id=data.hypothesis_id,
        baseline_methods=json.dumps(data.baseline_methods),
        independent_variables=json.dumps(data.independent_variables),
        fixed_assumptions=json.dumps(data.fixed_assumptions),
        metrics=json.dumps(data.metrics),
        validation=json.dumps(data.validation.model_dump()),
        runtime=json.dumps(data.runtime.model_dump()),
        artifacts=json.dumps(data.artifacts),
        estimated_cost=data.estimated_cost.value,
        estimated_runtime=data.estimated_runtime.value,
        requires_human_approval=data.requires_human_approval,
        experiment_type=data.experiment_type.value,
        parameter_sweep_count=_compute_sweep_cardinality(data.independent_variables),
        status=ExperimentStatusEnum.generated.value,
        created_at=now,
        updated_at=now,
    )
    db.add(card)
    db.commit()
    db.refresh(card)
    return _to_response(card)


def get(db: Session, experiment_id: str) -> ExperimentCardResponse:
    return _to_response(_get_or_404(db, experiment_id))


def list_experiments(
    db: Session,
    goal_id: str,
    *,
    status: ExperimentStatusEnum | None = None,
    experiment_type: ExperimentTypeEnum | None = None,
    skip: int = 0,
    limit: int = 20,
) -> tuple[list[ExperimentCardResponse], int]:
    goal_svc.get(db, goal_id)
    q = select(ExperimentCard).where(ExperimentCard.workspace_id == goal_id)
    if status is not None:
        q = q.where(ExperimentCard.status == status.value)
    if experiment_type is not None:
        q = q.where(ExperimentCard.experiment_type == experiment_type.value)

    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.scalars(q.order_by(ExperimentCard.name).offset(skip).limit(limit)).all()
    return [_to_response(r) for r in rows], total or 0


def update(db: Session, experiment_id: str, data: ExperimentCardUpdate) -> ExperimentCardResponse:
    card = _get_or_404(db, experiment_id)
    if data.name is not None:
        card.name = data.name
    if data.objective is not None:
        card.objective = data.objective
    if data.hypothesis_text is not None:
        card.hypothesis_text = data.hypothesis_text
    if data.baseline_methods is not None:
        card.baseline_methods = json.dumps(data.baseline_methods)
    if data.independent_variables is not None:
        card.independent_variables = json.dumps(data.independent_variables)
        card.parameter_sweep_count = _compute_sweep_cardinality(data.independent_variables)
    if data.fixed_assumptions is not None:
        card.fixed_assumptions = json.dumps(data.fixed_assumptions)
    if data.metrics is not None:
        card.metrics = json.dumps(data.metrics)
    if data.validation is not None:
        card.validation = json.dumps(data.validation.model_dump())
    if data.runtime is not None:
        card.runtime = json.dumps(data.runtime.model_dump())
    if data.artifacts is not None:
        card.artifacts = json.dumps(data.artifacts)
    if data.estimated_cost is not None:
        card.estimated_cost = data.estimated_cost.value
    if data.estimated_runtime is not None:
        card.estimated_runtime = data.estimated_runtime.value
    if data.experiment_type is not None:
        card.experiment_type = data.experiment_type.value
    if data.requires_human_approval is not None:
        card.requires_human_approval = data.requires_human_approval
    card.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(card)
    return _to_response(card)


def transition(db: Session, experiment_id: str, new_status: ExperimentStatusEnum) -> ExperimentCardResponse:
    card = _get_or_404(db, experiment_id)
    current = ExperimentStatusEnum(card.status)
    if new_status not in ALLOWED_TRANSITIONS[current]:
        allowed = {s.value for s in ALLOWED_TRANSITIONS[current]}
        raise HTTPException(
            status_code=422,
            detail=(
                f"Cannot transition from {current.value!r} to {new_status.value!r}. "
                f"Allowed: {sorted(allowed) or 'none (terminal state)'}"
            ),
        )
    card.status = new_status.value
    card.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(card)
    return _to_response(card)


def delete(db: Session, experiment_id: str) -> None:
    card = _get_or_404(db, experiment_id)
    if card.status != ExperimentStatusEnum.generated.value:
        raise HTTPException(
            status_code=409,
            detail=f"Only generated experiments can be deleted; experiment is {card.status!r}",
        )
    db.delete(card)
    db.commit()


# ---------------------------------------------------------------------------
# Generation helpers
# ---------------------------------------------------------------------------

def _select_baselines(method_family: str) -> list[str]:
    related = RELATED_METHODS.get(method_family, [])
    baselines = list(dict.fromkeys(related))
    if _UNIVERSAL_BASELINE not in baselines:
        baselines.append(_UNIVERSAL_BASELINE)
    return baselines


def _build_parameter_sweep(goal: GoalResponse) -> dict[str, list]:
    speaker_count = [4, 8, 12]
    if goal.device_constraints and goal.device_constraints.speaker_count:
        sc = goal.device_constraints.speaker_count
        speaker_count = sorted({max(2, sc // 2), sc, sc * 2})

    return {
        "speaker_count": speaker_count,
        "listener_shift_cm": [0, 5, 10, 20],
        "reverberation_condition": ["anechoic", "low", "medium"],
        "frequency_band_hz": [[300, 1000], [1000, 4000], [4000, 8000]],
        "calibration_error": [0.0, 0.01, 0.05],
    }


def _build_fixed_assumptions(goal: GoalResponse) -> dict[str, str]:
    assumptions: dict[str, str] = {
        "room_geometry": "desktop_small_room",
        "bright_zone_position": "listener_head_center",
        "dark_zone_position": "adjacent_listener",
        "source_signal": "speech_and_music_test_set",
    }
    if goal.device_constraints:
        if goal.device_constraints.form_factor:
            assumptions["form_factor"] = goal.device_constraints.form_factor
        if goal.device_constraints.compute_budget:
            assumptions["compute_budget"] = goal.device_constraints.compute_budget
    return assumptions


def _derive_metrics(approach_resp, goal: GoalResponse) -> list[str]:
    metric_set: set[str] = set()
    if hasattr(approach_resp, "reported_metrics"):
        for m in approach_resp.reported_metrics:
            metric_set.add(m.metric_name)
    for sc in goal.success_criteria:
        metric_set.add(sc.name)
    for canonical in METRIC_NAMES:
        metric_set.add(canonical)
    return sorted(metric_set)


def _derive_validation(goal: GoalResponse) -> dict[str, Any]:
    pass_conditions: dict[str, float] = {}
    for sc in goal.success_criteria:
        if sc.operator in (">=", ">"):
            pass_conditions[f"{sc.name}_min"] = sc.target
        elif sc.operator in ("<=", "<"):
            pass_conditions[f"{sc.name}_max"] = sc.target
        elif sc.operator == "==":
            pass_conditions[f"{sc.name}_target"] = sc.target
    return {
        "pass_conditions": pass_conditions,
        "comparison": {"baseline_improvement_required": True},
    }


def _compute_sweep_cardinality(independent_variables: dict[str, list]) -> int:
    lengths = [len(v) for v in independent_variables.values() if isinstance(v, list) and len(v) > 0]
    if not lengths:
        return 0
    return reduce(mul, lengths, 1)


def _estimate_cost_runtime(sweep_count: int) -> tuple[str, str]:
    low_threshold = settings.experiment_sweep_cost_low
    medium_threshold = settings.experiment_sweep_cost_medium
    high_threshold = settings.experiment_sweep_cost_high
    if sweep_count <= low_threshold:
        return "low", "low"
    elif sweep_count <= medium_threshold:
        return "low", "medium"
    elif sweep_count <= high_threshold:
        return "medium", "medium"
    else:
        return "high", "high"


def _get_existing_approach_sets(db: Session, workspace_id: str) -> set[frozenset[str]]:
    rows = db.scalars(
        select(ExperimentCard.approach_ids).where(
            ExperimentCard.workspace_id == workspace_id,
            ExperimentCard.status != ExperimentStatusEnum.superseded.value,
        )
    ).all()
    result: set[frozenset[str]] = set()
    for raw in rows:
        aids = json.loads(raw) if raw else []
        result.add(frozenset(aids))
    return result


def _synthesize_experiment(
    approach_resp,
    goal: GoalResponse,
    generation_run_id: str,
    now: datetime,
) -> ExperimentCard:
    name = f"Validate {approach_resp.method_family}"
    objective = (
        f"Evaluate {approach_resp.method_family} for {goal.target_application} "
        f"under simulated conditions"
    )
    hypothesis_text = (
        f"{approach_resp.name} will achieve target performance criteria for "
        f"{goal.target_application}"
    )
    if approach_resp.mechanism_summary:
        hypothesis_text += f" via {approach_resp.mechanism_summary[:200]}"

    baselines = _select_baselines(approach_resp.method_family)
    sweep = _build_parameter_sweep(goal)
    fixed = _build_fixed_assumptions(goal)
    metrics = _derive_metrics(approach_resp, goal)
    validation = _derive_validation(goal)
    runtime = {"preferred": "python_numerics_or_treble", "alternatives": ["dolfinx", "elmer", "octave"]}
    sweep_count = _compute_sweep_cardinality(sweep)
    cost, runtime_est = _estimate_cost_runtime(sweep_count)

    return ExperimentCard(
        id=str(uuid.uuid4()),
        workspace_id=goal.workspace_id,
        name=name,
        objective=objective,
        hypothesis_text=hypothesis_text,
        approach_ids=json.dumps([approach_resp.id]),
        hypothesis_id=None,
        baseline_methods=json.dumps(baselines),
        independent_variables=json.dumps(sweep),
        fixed_assumptions=json.dumps(fixed),
        metrics=json.dumps(metrics),
        validation=json.dumps(validation),
        runtime=json.dumps(runtime),
        artifacts=json.dumps(list(_STANDARD_ARTIFACTS)),
        estimated_cost=cost,
        estimated_runtime=runtime_est,
        estimated_compute=f"{sweep_count} parameter combinations",
        requires_human_approval=True,
        experiment_type="simulation",
        parameter_sweep_count=sweep_count,
        status=ExperimentStatusEnum.generated.value,
        generation_run_id=generation_run_id,
        created_at=now,
        updated_at=now,
    )


def _synthesize_comparative_experiment(
    approach_a,
    approach_b,
    goal: GoalResponse,
    generation_run_id: str,
    now: datetime,
) -> ExperimentCard:
    name = f"{approach_a.method_family} vs {approach_b.method_family}"
    objective = (
        f"Compare {approach_a.method_family} against {approach_b.method_family} "
        f"for {goal.target_application}"
    )
    hypothesis_text = (
        f"{approach_a.method_family} will outperform {approach_b.method_family} on "
        f"acoustic contrast under fixed listener geometry, but {approach_b.method_family} "
        f"may be more robust under listener displacement"
    )

    baselines_a = set(_select_baselines(approach_a.method_family))
    baselines_b = set(_select_baselines(approach_b.method_family))
    baselines = sorted(baselines_a | baselines_b | {approach_a.method_family, approach_b.method_family})

    sweep = _build_parameter_sweep(goal)
    fixed = _build_fixed_assumptions(goal)
    metrics_a = set(_derive_metrics(approach_a, goal))
    metrics_b = set(_derive_metrics(approach_b, goal))
    metrics = sorted(metrics_a | metrics_b)
    validation = _derive_validation(goal)
    runtime = {"preferred": "python_numerics_or_treble", "alternatives": ["dolfinx", "elmer", "octave"]}
    sweep_count = _compute_sweep_cardinality(sweep)
    cost, runtime_est = _estimate_cost_runtime(sweep_count)

    return ExperimentCard(
        id=str(uuid.uuid4()),
        workspace_id=goal.workspace_id,
        name=name,
        objective=objective,
        hypothesis_text=hypothesis_text,
        approach_ids=json.dumps(sorted([approach_a.id, approach_b.id])),
        hypothesis_id=None,
        baseline_methods=json.dumps(baselines),
        independent_variables=json.dumps(sweep),
        fixed_assumptions=json.dumps(fixed),
        metrics=json.dumps(metrics),
        validation=json.dumps(validation),
        runtime=json.dumps(runtime),
        artifacts=json.dumps(list(_STANDARD_ARTIFACTS)),
        estimated_cost=cost,
        estimated_runtime=runtime_est,
        estimated_compute=f"{sweep_count} parameter combinations",
        requires_human_approval=True,
        experiment_type="simulation",
        parameter_sweep_count=sweep_count,
        status=ExperimentStatusEnum.generated.value,
        generation_run_id=generation_run_id,
        created_at=now,
        updated_at=now,
    )


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

def generate_experiments(
    db: Session,
    goal_id: str,
    request: ExperimentGenerateRequest,
) -> ExperimentGenerateResponse:
    goal = goal_svc.get(db, goal_id)
    now = datetime.now(timezone.utc)
    generation_run_id = str(uuid.uuid4())

    if request.approach_ids:
        approaches = [approach_svc.get(db, aid) for aid in request.approach_ids]
    elif request.hypothesis_id:
        hc = db.get(HypothesisCard, request.hypothesis_id)
        if hc is None:
            raise HTTPException(status_code=404, detail=f"Hypothesis {request.hypothesis_id!r} not found")
        h_approach_ids = json.loads(hc.approach_ids) if hc.approach_ids else []
        approaches = [approach_svc.get(db, aid) for aid in h_approach_ids]
    else:
        from coscientist.schemas.approach import ApproachStatusEnum
        rows = db.scalars(
            select(ApproachCard).where(
                ApproachCard.workspace_id == goal.workspace_id,
                ApproachCard.status.in_([
                    ApproachStatusEnum.scored.value,
                    ApproachStatusEnum.experiment_proposed.value,
                ]),
            )
        ).all()
        approaches = [approach_svc._to_response(r) for r in rows]

    if not approaches:
        return ExperimentGenerateResponse(
            generation_run_id=generation_run_id,
            goal_id=goal_id,
            experiments_created=0,
            experiments_skipped_duplicate=0,
            simulation_count=0,
            measurement_count=0,
            experiments=[],
        )

    existing_sets = _get_existing_approach_sets(db, goal.workspace_id)
    created: list[ExperimentCard] = []
    skipped = 0

    for approach in approaches:
        if len(created) >= request.max_experiments:
            break
        key = frozenset([approach.id])
        if key in existing_sets:
            skipped += 1
            continue
        card = _synthesize_experiment(approach, goal, generation_run_id, now)
        db.add(card)
        created.append(card)

    for a, b in combinations(approaches, 2):
        if len(created) >= request.max_experiments:
            break
        pair_key = frozenset([a.id, b.id])
        if pair_key in existing_sets:
            skipped += 1
            continue
        card = _synthesize_comparative_experiment(a, b, goal, generation_run_id, now)
        db.add(card)
        created.append(card)

    db.commit()
    for c in created:
        db.refresh(c)

    responses = [_to_response(c) for c in created]
    sim_count = sum(1 for r in responses if r.experiment_type == ExperimentTypeEnum.simulation)
    meas_count = sum(1 for r in responses if r.experiment_type == ExperimentTypeEnum.measurement)

    return ExperimentGenerateResponse(
        generation_run_id=generation_run_id,
        goal_id=goal_id,
        experiments_created=len(created),
        experiments_skipped_duplicate=skipped,
        simulation_count=sim_count,
        measurement_count=meas_count,
        experiments=responses,
    )


# ---------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------

def _to_yaml_value(value: Any, indent: int = 0) -> str:
    prefix = "  " * indent
    if isinstance(value, dict):
        if not value:
            return "{}"
        lines = []
        for k, v in value.items():
            rendered = _to_yaml_value(v, indent + 1)
            if isinstance(v, (dict, list)) and v:
                lines.append(f"{prefix}{k}:")
                lines.append(rendered)
            else:
                lines.append(f"{prefix}{k}: {rendered}")
        return "\n".join(lines)
    elif isinstance(value, list):
        if not value:
            return "[]"
        lines = []
        for item in value:
            if isinstance(item, (dict, list)) and item:
                rendered = _to_yaml_value(item, indent + 1)
                lines.append(f"{prefix}- ")
                lines.append(rendered)
            else:
                lines.append(f"{prefix}- {item}")
        return "\n".join(lines)
    elif isinstance(value, bool):
        return "true" if value else "false"
    elif isinstance(value, str):
        if "\n" in value or len(value) > 80:
            return f">\n{prefix}  {value}"
        return value
    elif value is None:
        return "null"
    else:
        return str(value)


def export_experiment(db: Session, experiment_id: str, fmt: str = "yaml") -> ExperimentExportResponse:
    card = _get_or_404(db, experiment_id)
    response = _to_response(card)

    data = {
        "experiment_card": {
            "id": response.id,
            "name": response.name,
            "objective": response.objective,
            "hypothesis": response.hypothesis_text,
            "approach_ids": response.approach_ids,
            "baseline_methods": response.baseline_methods,
            "independent_variables": response.independent_variables,
            "fixed_assumptions": response.fixed_assumptions,
            "metrics": response.metrics,
            "validation": response.validation.model_dump(),
            "runtime": response.runtime.model_dump(),
            "artifacts": response.artifacts,
            "approval": {
                "requires_human_approval": response.requires_human_approval,
                "estimated_cost": response.estimated_cost,
                "estimated_runtime": response.estimated_runtime,
            },
        }
    }

    if fmt == "yaml":
        content = _to_yaml_value(data)
    elif fmt == "python":
        content = pprint.pformat(data, width=100, sort_dicts=False)
    else:
        raise HTTPException(status_code=422, detail=f"Unsupported export format {fmt!r}. Use 'yaml' or 'python'.")

    return ExperimentExportResponse(
        experiment_id=experiment_id,
        format=fmt,
        content=content,
    )


# ---------------------------------------------------------------------------
# Experiment scoring
# ---------------------------------------------------------------------------

def _clamp(v: float) -> float:
    return max(0.0, min(1.0, v))


def _score_hypothesis_clarity(experiment: ExperimentCardResponse, goal: GoalResponse) -> tuple[float, str]:
    score = 0.0
    reasons = []
    text = experiment.hypothesis_text.lower()
    if experiment.hypothesis_text and len(experiment.hypothesis_text) > 10:
        score += 0.3
        reasons.append("hypothesis text present")
    if any(kw in text for kw in ("will", "should", "expected to", "outperform")):
        score += 0.3
        reasons.append("contains testable claim")
    if any(m in text for m in experiment.metrics):
        score += 0.2
        reasons.append("references specific metric")
    if len(experiment.approach_ids) >= 1:
        score += 0.2
        reasons.append("linked to approach(es)")
    return _clamp(score), "; ".join(reasons) or "no hypothesis provided"


def _score_device_relevance(experiment: ExperimentCardResponse, goal: GoalResponse) -> tuple[float, str]:
    score = 0.0
    reasons = []
    if goal.device_constraints:
        if goal.device_constraints.form_factor and goal.device_constraints.form_factor in json.dumps(experiment.fixed_assumptions):
            score += 0.3
            reasons.append("form factor reflected")
        if goal.device_constraints.speaker_count and "speaker_count" in experiment.independent_variables:
            score += 0.3
            reasons.append("speaker count in sweep")
        if goal.device_constraints.compute_budget and "compute_budget" in json.dumps(experiment.fixed_assumptions):
            score += 0.2
            reasons.append("compute budget reflected")
    goal_metrics = {sc.name for sc in goal.success_criteria}
    overlap = goal_metrics & set(experiment.metrics)
    if overlap:
        score += min(0.2, len(overlap) * 0.1)
        reasons.append(f"{len(overlap)} goal metrics covered")
    return _clamp(score), "; ".join(reasons) or "limited device relevance"


def _score_baseline_quality(experiment: ExperimentCardResponse, goal: GoalResponse) -> tuple[float, str]:
    n = len(experiment.baseline_methods)
    if n == 0:
        return 0.0, "no baselines defined"
    standard = {"pressure_matching", "delay_and_sum_beamforming", "acoustic_contrast_control"}
    has_standard = bool(set(experiment.baseline_methods) & standard)
    score = min(0.6, n * 0.3)
    if has_standard:
        score += 0.4
    return _clamp(score), f"{n} baselines, {'includes' if has_standard else 'missing'} standard methods"


def _score_metric_quality(experiment: ExperimentCardResponse, goal: GoalResponse) -> tuple[float, str]:
    n = len(experiment.metrics)
    goal_metrics = {sc.name for sc in goal.success_criteria}
    overlap = goal_metrics & set(experiment.metrics)
    score = min(0.4, n * 0.1)
    score += min(0.3, len(overlap) * 0.15)
    if experiment.validation.pass_conditions:
        score += 0.3
    return _clamp(score), f"{n} metrics, {len(overlap)} from goal criteria, {'has' if experiment.validation.pass_conditions else 'no'} pass conditions"


def _score_reproducibility(experiment: ExperimentCardResponse, goal: GoalResponse) -> tuple[float, str]:
    score = 0.0
    reasons = []
    if experiment.runtime.preferred:
        score += 0.3
        reasons.append("runtime specified")
    if experiment.fixed_assumptions:
        score += 0.3
        reasons.append(f"{len(experiment.fixed_assumptions)} fixed assumptions")
    if "reproduction_manifest" in experiment.artifacts:
        score += 0.2
        reasons.append("reproduction manifest included")
    if experiment.independent_variables:
        score += 0.2
        reasons.append("variables documented")
    return _clamp(score), "; ".join(reasons) or "no reproducibility info"


def _score_information_gain(experiment: ExperimentCardResponse, goal: GoalResponse) -> tuple[float, str]:
    score = 0.0
    reasons = []
    if len(experiment.approach_ids) >= 2:
        score += 0.4
        reasons.append("comparative experiment")
    n_vars = len(experiment.independent_variables)
    score += min(0.3, n_vars * 0.1)
    reasons.append(f"{n_vars} independent variables")
    sweep = experiment.parameter_sweep_count or 0
    if sweep > 50:
        score += 0.3
        reasons.append(f"broad sweep ({sweep} combos)")
    elif sweep > 10:
        score += 0.2
        reasons.append(f"moderate sweep ({sweep} combos)")
    return _clamp(score), "; ".join(reasons)


def _score_cost_time(experiment: ExperimentCardResponse, goal: GoalResponse) -> tuple[float, str]:
    sweep = experiment.parameter_sweep_count or 0
    if sweep <= 50:
        return 1.0, f"minimal sweep ({sweep} combos)"
    elif sweep <= 200:
        return 0.7, f"moderate sweep ({sweep} combos)"
    elif sweep <= 1000:
        return 0.4, f"large sweep ({sweep} combos)"
    else:
        return 0.2, f"very large sweep ({sweep} combos)"


def _score_failure_informativeness(experiment: ExperimentCardResponse, goal: GoalResponse) -> tuple[float, str]:
    score = 0.0
    reasons = []
    robustness_vars = _ROBUSTNESS_VARS & set(experiment.independent_variables.keys())
    score += min(0.6, len(robustness_vars) * 0.2)
    if robustness_vars:
        reasons.append(f"robustness variables: {', '.join(sorted(robustness_vars))}")
    text = experiment.hypothesis_text.lower()
    if any(kw in text for kw in ("fail", "robust", "degrad", "limit", "break")):
        score += 0.4
        reasons.append("hypothesis mentions failure conditions")
    return _clamp(score), "; ".join(reasons) or "no failure coverage"


def _score_robustness_coverage(experiment: ExperimentCardResponse, goal: GoalResponse) -> tuple[float, str]:
    robustness_vars = _ROBUSTNESS_VARS & set(experiment.independent_variables.keys())
    n = len(robustness_vars)
    total = len(_ROBUSTNESS_VARS)
    score = n / total if total else 0.0
    return _clamp(score), f"{n}/{total} robustness variables covered"


def _score_artifact_quality(experiment: ExperimentCardResponse, goal: GoalResponse) -> tuple[float, str]:
    standard = set(_STANDARD_ARTIFACTS)
    present = set(experiment.artifacts) & standard
    n = len(present)
    total = len(standard)
    score = n / total if total else 0.0
    return _clamp(score), f"{n}/{total} standard artifacts included"


_EXPERIMENT_SCORERS = {
    "hypothesis_clarity":      _score_hypothesis_clarity,
    "device_relevance":        _score_device_relevance,
    "baseline_quality":        _score_baseline_quality,
    "metric_quality":          _score_metric_quality,
    "reproducibility":         _score_reproducibility,
    "information_gain":        _score_information_gain,
    "cost_time":               _score_cost_time,
    "failure_informativeness": _score_failure_informativeness,
    "robustness_coverage":     _score_robustness_coverage,
    "artifact_quality":        _score_artifact_quality,
}


def score_experiment(db: Session, experiment_id: str, goal_id: str) -> ExperimentScoreResponse:
    experiment = get(db, experiment_id)
    goal = goal_svc.get(db, goal_id)
    dimensions = []
    total = 0.0
    for dim in ExperimentRubricDimensionEnum:
        scorer = _EXPERIMENT_SCORERS[dim.value]
        score, rationale = scorer(experiment, goal)
        weight = EXPERIMENT_WEIGHTS[dim.value]
        weighted = round(score * weight, 4)
        total += weighted
        dimensions.append(ExperimentDimensionScoreResponse(
            dimension=dim,
            score=round(score, 4),
            weight=weight,
            weighted_score=weighted,
            rationale=rationale,
        ))
    return ExperimentScoreResponse(
        experiment_id=experiment_id,
        dimensions=dimensions,
        total_score=round(total, 4),
    )
