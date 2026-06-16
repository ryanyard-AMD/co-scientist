import json
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from coscientist.models.goal import ResearchGoal
from coscientist.schemas.goal import (
    DeviceConstraints,
    GoalCreate,
    GoalResponse,
    GoalStatusEnum,
    GoalUpdate,
    SuccessCriterion,
)

ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    GoalStatusEnum.draft:    {GoalStatusEnum.active, GoalStatusEnum.archived},
    GoalStatusEnum.active:   {GoalStatusEnum.archived},
    GoalStatusEnum.archived: set(),
}


def _to_response(goal: ResearchGoal) -> GoalResponse:
    criteria = [SuccessCriterion(**c) for c in json.loads(goal.success_criteria)]
    constraints = (
        DeviceConstraints(**json.loads(goal.device_constraints))
        if goal.device_constraints
        else None
    )
    return GoalResponse(
        id=goal.id,
        name=goal.name,
        description=goal.description,
        target_application=goal.target_application,
        success_criteria=criteria,
        device_constraints=constraints,
        status=GoalStatusEnum(goal.status),
        workspace_id=goal.workspace_id,
        created_at=goal.created_at,
        updated_at=goal.updated_at,
    )


def _get_or_404(db: Session, goal_id: str) -> ResearchGoal:
    goal = db.get(ResearchGoal, goal_id)
    if goal is None:
        raise HTTPException(status_code=404, detail=f"Goal {goal_id!r} not found")
    return goal


def create(db: Session, data: GoalCreate) -> GoalResponse:
    goal_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    goal = ResearchGoal(
        id=goal_id,
        name=data.name,
        description=data.description,
        target_application=data.target_application,
        success_criteria=json.dumps([c.model_dump() for c in data.success_criteria]),
        device_constraints=(
            data.device_constraints.model_dump_json() if data.device_constraints else None
        ),
        status=GoalStatusEnum.draft,
        workspace_id=goal_id,
        created_at=now,
        updated_at=now,
    )
    db.add(goal)
    db.commit()
    db.refresh(goal)
    return _to_response(goal)


def get(db: Session, goal_id: str) -> GoalResponse:
    return _to_response(_get_or_404(db, goal_id))


def list_goals(
    db: Session,
    status: GoalStatusEnum | None = None,
    skip: int = 0,
    limit: int = 20,
) -> tuple[list[GoalResponse], int]:
    q = select(ResearchGoal)
    if status is not None:
        q = q.where(ResearchGoal.status == status.value)

    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.scalars(q.offset(skip).limit(limit)).all()
    return [_to_response(r) for r in rows], total or 0


def update(db: Session, goal_id: str, data: GoalUpdate) -> GoalResponse:
    goal = _get_or_404(db, goal_id)
    if data.name is not None:
        goal.name = data.name
    if data.description is not None:
        goal.description = data.description
    if data.target_application is not None:
        goal.target_application = data.target_application
    if data.success_criteria is not None:
        goal.success_criteria = json.dumps([c.model_dump() for c in data.success_criteria])
    if data.device_constraints is not None:
        goal.device_constraints = data.device_constraints.model_dump_json()
    goal.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(goal)
    return _to_response(goal)


def transition(db: Session, goal_id: str, new_status: GoalStatusEnum) -> GoalResponse:
    goal = _get_or_404(db, goal_id)
    current = GoalStatusEnum(goal.status)
    if new_status not in ALLOWED_TRANSITIONS[current]:
        allowed = {s.value for s in ALLOWED_TRANSITIONS[current]}
        raise HTTPException(
            status_code=422,
            detail=(
                f"Cannot transition from {current.value!r} to {new_status.value!r}. "
                f"Allowed: {sorted(allowed) or 'none (terminal state)'}"
            ),
        )
    goal.status = new_status.value
    goal.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(goal)
    return _to_response(goal)


def delete(db: Session, goal_id: str) -> None:
    goal = _get_or_404(db, goal_id)
    if goal.status != GoalStatusEnum.draft.value:
        raise HTTPException(
            status_code=409,
            detail=f"Only draft goals can be deleted; goal is {goal.status!r}",
        )
    db.delete(goal)
    db.commit()
