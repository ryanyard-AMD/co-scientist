import json
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from coscientist.models.approval import ApprovalDecision
from coscientist.models.experiment import ExperimentCard
from coscientist.schemas.approval import (
    ApprovalDecisionCreate,
    ApprovalDecisionEnum,
    ApprovalDecisionListResponse,
    ApprovalDecisionResponse,
    ExperimentDuplicateResponse,
)
from coscientist.schemas.experiment import ExperimentCardResponse, ExperimentStatusEnum
from coscientist.services import experiment as experiment_svc


def _to_response(d: ApprovalDecision) -> ApprovalDecisionResponse:
    return ApprovalDecisionResponse(
        id=d.id,
        experiment_id=d.experiment_id,
        goal_id=d.goal_id,
        decision=ApprovalDecisionEnum(d.decision),
        reviewer_id=d.reviewer_id,
        reason=d.reason,
        resource_flags=json.loads(d.resource_flags) if d.resource_flags else [],
        created_at=d.created_at,
    )


def _classify_resource_flags(card: ExperimentCard) -> list[str]:
    flags: list[str] = []
    if card.estimated_cost == "high":
        flags.append("high_cost")
    compute = (card.estimated_compute or "").lower()
    if "gpu" in compute or "cuda" in compute:
        flags.append("gpu")
    if "treble" in compute:
        flags.append("treble")
    return flags


def _get_experiment_or_404(db: Session, experiment_id: str, goal_id: str) -> ExperimentCard:
    card = db.get(ExperimentCard, experiment_id)
    if card is None:
        raise HTTPException(status_code=404, detail=f"Experiment {experiment_id!r} not found")
    if card.workspace_id != goal_id:
        raise HTTPException(status_code=404, detail=f"Experiment {experiment_id!r} not found in goal {goal_id!r}")
    return card


def record_decision(
    db: Session,
    experiment_id: str,
    goal_id: str,
    body: ApprovalDecisionCreate,
) -> ApprovalDecisionResponse:
    card = _get_experiment_or_404(db, experiment_id, goal_id)

    if card.status != ExperimentStatusEnum.reviewed.value:
        raise HTTPException(
            status_code=409,
            detail=f"Experiment must be in 'reviewed' status to record an approval decision, got {card.status!r}",
        )

    resource_flags = [f.value for f in body.resource_flags] if body.resource_flags else _classify_resource_flags(card)

    reason = body.reason
    if body.decision == ApprovalDecisionEnum.approve and not reason:
        try:
            export = experiment_svc.export_experiment(db, experiment_id, "yaml")
            reason = export.content
        except Exception:
            reason = None

    decision = ApprovalDecision(
        id=str(uuid.uuid4()),
        experiment_id=experiment_id,
        goal_id=goal_id,
        decision=body.decision.value,
        reviewer_id=body.reviewer_id,
        reason=reason,
        resource_flags=json.dumps(resource_flags),
        created_at=datetime.now(timezone.utc),
    )
    db.add(decision)
    db.flush()

    if body.decision == ApprovalDecisionEnum.approve:
        experiment_svc.transition(db, experiment_id, ExperimentStatusEnum.approved)
    elif body.decision == ApprovalDecisionEnum.reject:
        experiment_svc.transition(db, experiment_id, ExperimentStatusEnum.superseded)
    elif body.decision == ApprovalDecisionEnum.request_edit:
        card.status = ExperimentStatusEnum.generated.value
        card.updated_at = datetime.now(timezone.utc)
        db.flush()

    db.commit()
    db.refresh(decision)
    return _to_response(decision)


def list_decisions(db: Session, experiment_id: str, goal_id: str) -> ApprovalDecisionListResponse:
    _get_experiment_or_404(db, experiment_id, goal_id)
    stmt = (
        select(ApprovalDecision)
        .where(ApprovalDecision.experiment_id == experiment_id)
        .order_by(ApprovalDecision.created_at)
    )
    decisions = db.execute(stmt).scalars().all()
    return ApprovalDecisionListResponse(
        items=[_to_response(d) for d in decisions],
        total=len(decisions),
    )


def list_pending(db: Session, goal_id: str | None = None) -> list[ExperimentCardResponse]:
    stmt = select(ExperimentCard).where(ExperimentCard.status == ExperimentStatusEnum.reviewed.value)
    if goal_id:
        stmt = stmt.where(ExperimentCard.workspace_id == goal_id)
    cards = db.execute(stmt).scalars().all()
    return [experiment_svc._to_response(c) for c in cards]


def duplicate_experiment(
    db: Session,
    experiment_id: str,
    goal_id: str,
) -> ExperimentDuplicateResponse:
    card = _get_experiment_or_404(db, experiment_id, goal_id)

    now = datetime.now(timezone.utc)
    new_card = ExperimentCard(
        id=str(uuid.uuid4()),
        workspace_id=card.workspace_id,
        name=card.name + " (copy)",
        objective=card.objective,
        hypothesis_text=card.hypothesis_text,
        approach_ids=card.approach_ids,
        hypothesis_id=card.hypothesis_id,
        baseline_methods=card.baseline_methods,
        independent_variables=card.independent_variables,
        fixed_assumptions=card.fixed_assumptions,
        metrics=card.metrics,
        validation=card.validation,
        runtime=card.runtime,
        artifacts=card.artifacts,
        estimated_cost=card.estimated_cost,
        estimated_runtime=card.estimated_runtime,
        estimated_compute=card.estimated_compute,
        requires_human_approval=card.requires_human_approval,
        experiment_type=card.experiment_type,
        parameter_sweep_count=card.parameter_sweep_count,
        status=ExperimentStatusEnum.generated.value,
        generation_run_id=card.generation_run_id,
        created_at=now,
        updated_at=now,
    )
    db.add(new_card)
    db.commit()
    db.refresh(new_card)

    return ExperimentDuplicateResponse(
        original_id=experiment_id,
        new_id=new_card.id,
        new_experiment=experiment_svc._to_response(new_card),
    )
