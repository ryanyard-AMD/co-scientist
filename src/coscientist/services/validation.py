import json
import time
import uuid
from datetime import datetime, timezone

import anthropic
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from coscientist.config import settings
from coscientist.models.approach import ApproachCard
from coscientist.models.experiment import ExperimentCard
from coscientist.models.validation import ValidationResult
from coscientist.schemas.approach import ApproachMaturityEnum, ApproachStatusEnum
from coscientist.schemas.experiment import ExperimentStatusEnum, ExperimentTypeEnum
from coscientist.schemas.validation import (
    AgentValidationOutput,
    CriterionResult,
    ExperimentResultSubmission,
    ReproductionStatusEnum,
    ValidationDecisionEnum,
    ValidationResultListResponse,
    ValidationResultResponse,
)
from coscientist.services import goal as goal_svc
from coscientist.services import governance as governance_svc
from coscientist.services import roadmap as roadmap_svc

_VALIDATION_TOOL = {
    "name": "record_validation",
    "description": "Record the validation verdict for an experiment's measured results against its pass conditions.",
    "input_schema": {
        "type": "object",
        "properties": {
            "decision": {
                "type": "string",
                "enum": ["validated", "refuted"],
                "description": "validated = ALL criteria pass; refuted = ANY criterion fails.",
            },
            "confidence": {"type": "number", "description": "Confidence in the verdict, 0.0-1.0."},
            "reasoning": {"type": "string", "description": "Narrative explanation of the verdict."},
            "criterion_results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "measured": {"type": ["number", "null"]},
                        "target": {"type": "number"},
                        "operator": {"type": "string"},
                        "passed": {"type": "boolean"},
                        "unit": {"type": "string"},
                    },
                    "required": ["name", "target", "operator", "passed", "unit"],
                },
                "description": "One entry per pass condition evaluated against the measured results.",
            },
            "refinement_suggestions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Populate only when decision is 'refuted'.",
            },
        },
        "required": ["decision", "confidence", "reasoning", "criterion_results"],
    },
}

_MATURITY_ORDER = {
    ApproachMaturityEnum.theoretical.value: 0,
    ApproachMaturityEnum.simulated.value: 1,
    ApproachMaturityEnum.measured.value: 2,
    ApproachMaturityEnum.validated.value: 3,
}


def _to_response(result: ValidationResult) -> ValidationResultResponse:
    return ValidationResultResponse(
        id=result.id,
        experiment_id=result.experiment_id,
        goal_id=result.goal_id,
        approach_id=result.approach_id,
        decision=ValidationDecisionEnum(result.decision),
        reproduction_status=ReproductionStatusEnum(result.reproduction_status),
        confidence=result.confidence,
        reasoning=result.reasoning,
        criterion_results=[
            CriterionResult(**c) for c in json.loads(result.criterion_results)
        ] if result.criterion_results else [],
        refinement_suggestions=json.loads(result.refinement_suggestions) if result.refinement_suggestions else [],
        measured_metrics=json.loads(result.measured_metrics) if result.measured_metrics else {},
        artifact_paths=json.loads(result.artifact_paths) if result.artifact_paths else None,
        model_used=result.model_used,
        created_at=result.created_at,
    )


def _get_experiment_or_404(db: Session, experiment_id: str, goal_id: str) -> ExperimentCard:
    card = db.get(ExperimentCard, experiment_id)
    if card is None:
        raise HTTPException(status_code=404, detail=f"Experiment {experiment_id!r} not found")
    if card.workspace_id != goal_id:
        raise HTTPException(
            status_code=404,
            detail=f"Experiment {experiment_id!r} not found in goal {goal_id!r}",
        )
    return card


def _derive_reproduction_status(
    criterion_results: list[CriterionResult],
) -> ReproductionStatusEnum:
    """Map evaluated criteria to a reproduction outcome (CS-VALIDATION-005).

    blocked  = nothing measurable could be evaluated
    reproduced = every criterion passed
    failed   = no criterion passed
    partially_reproduced = some but not all passed
    """
    measurable = [c for c in criterion_results if c.measured is not None]
    if not measurable:
        return ReproductionStatusEnum.blocked
    passed = sum(1 for c in measurable if c.passed)
    if passed == len(measurable):
        return ReproductionStatusEnum.reproduced
    if passed == 0:
        return ReproductionStatusEnum.failed
    return ReproductionStatusEnum.partially_reproduced


def _advance_maturity(approach_card: ApproachCard, experiment_type: str) -> str:
    current = approach_card.maturity or ApproachMaturityEnum.theoretical.value
    if experiment_type == ExperimentTypeEnum.measurement.value:
        target = ApproachMaturityEnum.measured.value
    else:
        target = ApproachMaturityEnum.simulated.value
    if _MATURITY_ORDER.get(target, 0) > _MATURITY_ORDER.get(current, 0):
        return target
    return current


def _run_validation_agent(
    db: Session,
    goal_id: str,
    experiment: ExperimentCard,
    goal,
    primary_approach: ApproachCard | None,
    submission: ExperimentResultSubmission,
) -> AgentValidationOutput:
    validation_spec = json.loads(experiment.validation) if experiment.validation else {}
    pass_conditions = validation_spec.get("pass_conditions", {})

    system_prompt = (
        "You are a scientific validation agent. Evaluate whether an experiment's measured "
        "results satisfy its validation criteria. For each pass condition, determine whether "
        "the measured value satisfies the operator and target. Record your verdict by calling "
        "the record_validation tool. Set decision to 'validated' if ALL criteria pass, "
        "'refuted' if ANY fail. Populate refinement_suggestions only when decision is 'refuted'."
    )

    success_criteria_text = json.dumps(
        [sc.model_dump() for sc in goal.success_criteria], indent=2
    )
    approach_info = ""
    if primary_approach is not None:
        approach_info = (
            f"## Approach\n"
            f"Name: {primary_approach.name}\n"
            f"Method family: {primary_approach.method_family}\n"
        )

    user_message = (
        f"## Experiment\n"
        f"Name: {experiment.name}\n"
        f"Objective: {experiment.objective}\n"
        f"Type: {experiment.experiment_type}\n\n"
        f"## Pass Conditions\n{json.dumps(pass_conditions, indent=2)}\n\n"
        f"## Measured Results\n{json.dumps(submission.measured_metrics, indent=2)}\n\n"
        f"{approach_info}\n"
        f"## Goal Success Criteria\n{success_criteria_text}\n\n"
        "Evaluate each pass condition against the measured results. "
        "For each criterion determine whether the measured value satisfies the operator and target. "
        "Use the goal success_criteria for units where available; use an empty string if unknown."
    )
    if submission.notes:
        user_message += f"\n\n## Experimenter Notes\n{submission.notes}"

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    start = time.monotonic()
    message = client.messages.create(
        model=settings.validation_model,
        max_tokens=1024,
        system=system_prompt,
        tools=[_VALIDATION_TOOL],
        tool_choice={"type": "tool", "name": "record_validation"},
        messages=[{"role": "user", "content": user_message}],
    )
    elapsed_ms = int((time.monotonic() - start) * 1000)

    tool_use = next((b for b in message.content if b.type == "tool_use"), None)
    governance_svc.log_agent_call(
        db=db,
        workspace_id=goal_id,
        service="validation",
        action="validate_experiment",
        model_used=settings.validation_model,
        prompt_tokens=message.usage.input_tokens,
        completion_tokens=message.usage.output_tokens,
        elapsed_ms=elapsed_ms,
        response_summary=(json.dumps(tool_use.input)[:512] if tool_use else "no tool_use block"),
    )
    if tool_use is None:
        raise HTTPException(
            status_code=502,
            detail="Validation agent did not return a record_validation tool call",
        )
    try:
        return AgentValidationOutput(**tool_use.input)
    except ValueError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Validation agent returned invalid output: {exc}",
        )


def submit_results(
    db: Session,
    experiment_id: str,
    goal_id: str,
    submission: ExperimentResultSubmission,
) -> ValidationResultResponse:
    goal_svc.raise_if_restricted(db, goal_id)
    card = _get_experiment_or_404(db, experiment_id, goal_id)

    if card.status != ExperimentStatusEnum.running.value:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Experiment must be in 'running' status to submit results, "
                f"got {card.status!r}"
            ),
        )

    goal = goal_svc.get(db, goal_id)
    approach_ids: list[str] = json.loads(card.approach_ids) if card.approach_ids else []
    primary_approach_id = approach_ids[0] if approach_ids else None
    primary_approach = db.get(ApproachCard, primary_approach_id) if primary_approach_id else None

    agent_output = _run_validation_agent(db, goal_id, card, goal, primary_approach, submission)

    now = datetime.now(timezone.utc)

    # A re-run supersedes any prior result for the same experiment.
    prior_results = list(
        db.scalars(
            select(ValidationResult).where(ValidationResult.experiment_id == experiment_id)
        )
    )
    for prior in prior_results:
        prior.reproduction_status = ReproductionStatusEnum.superseded.value

    reproduction_status = _derive_reproduction_status(agent_output.criterion_results)
    result = ValidationResult(
        id=str(uuid.uuid4()),
        experiment_id=experiment_id,
        goal_id=goal_id,
        approach_id=primary_approach_id or "",
        decision=agent_output.decision.value,
        reproduction_status=reproduction_status.value,
        confidence=agent_output.confidence,
        reasoning=agent_output.reasoning,
        criterion_results=json.dumps([cr.model_dump() for cr in agent_output.criterion_results]),
        refinement_suggestions=json.dumps(agent_output.refinement_suggestions),
        measured_metrics=json.dumps(submission.measured_metrics),
        artifact_paths=json.dumps(submission.artifact_paths) if submission.artifact_paths else None,
        model_used=settings.validation_model,
        created_at=now,
    )
    db.add(result)
    db.flush()

    if agent_output.decision == ValidationDecisionEnum.validated:
        card.status = ExperimentStatusEnum.completed.value
    else:
        card.status = ExperimentStatusEnum.failed.value
    card.updated_at = now
    db.flush()

    for aid in approach_ids:
        approach_card = db.get(ApproachCard, aid)
        if approach_card is None:
            continue

        if approach_card.status == ApproachStatusEnum.experiment_proposed.value:
            approach_card.status = ApproachStatusEnum.tested.value
            approach_card.updated_at = now
            db.flush()

        if approach_card.status == ApproachStatusEnum.tested.value:
            if agent_output.decision == ValidationDecisionEnum.validated:
                approach_card.status = ApproachStatusEnum.validated.value
            else:
                approach_card.status = ApproachStatusEnum.refuted.value
            approach_card.updated_at = now

        approach_card.maturity = _advance_maturity(approach_card, card.experiment_type)
        db.flush()

    # Ingesting a result advances the roadmap: open items tied to this
    # experiment are retired so next-best recommendations reflect what was learned.
    roadmap_svc.retire_for_experiment(db, experiment_id, goal_id)

    db.commit()
    db.refresh(result)
    return _to_response(result)


def get_result(
    db: Session,
    experiment_id: str,
    goal_id: str,
) -> ValidationResultResponse | None:
    _get_experiment_or_404(db, experiment_id, goal_id)
    stmt = (
        select(ValidationResult)
        .where(ValidationResult.experiment_id == experiment_id)
        .order_by(ValidationResult.created_at.desc())
    )
    record = db.scalars(stmt).first()
    if record is None:
        return None
    return _to_response(record)


def list_results(
    db: Session,
    goal_id: str,
) -> ValidationResultListResponse:
    goal_svc.get(db, goal_id)
    stmt = (
        select(ValidationResult)
        .where(ValidationResult.goal_id == goal_id)
        .order_by(ValidationResult.created_at.desc())
    )
    records = db.scalars(stmt).all()
    return ValidationResultListResponse(
        items=[_to_response(r) for r in records],
        total=len(records),
    )
