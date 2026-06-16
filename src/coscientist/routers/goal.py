from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from coscientist.database import get_db
from coscientist.schemas.goal import (
    GoalCreate,
    GoalListResponse,
    GoalResponse,
    GoalStatusEnum,
    GoalStatusUpdate,
    GoalUpdate,
)
from coscientist.services import goal as svc

router = APIRouter(prefix="/goals", tags=["goals"])


@router.post("", response_model=GoalResponse, status_code=201)
def create_goal(body: GoalCreate, db: Session = Depends(get_db)):
    return svc.create(db, body)


@router.get("", response_model=GoalListResponse)
def list_goals(
    status: GoalStatusEnum | None = Query(default=None),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    items, total = svc.list_goals(db, status=status, skip=skip, limit=limit)
    return GoalListResponse(items=items, total=total)


@router.get("/{goal_id}", response_model=GoalResponse)
def get_goal(goal_id: str, db: Session = Depends(get_db)):
    return svc.get(db, goal_id)


@router.patch("/{goal_id}", response_model=GoalResponse)
def update_goal(goal_id: str, body: GoalUpdate, db: Session = Depends(get_db)):
    return svc.update(db, goal_id, body)


@router.post("/{goal_id}/transition", response_model=GoalResponse)
def transition_goal(goal_id: str, body: GoalStatusUpdate, db: Session = Depends(get_db)):
    return svc.transition(db, goal_id, body.status)


@router.delete("/{goal_id}", status_code=204)
def delete_goal(goal_id: str, db: Session = Depends(get_db)):
    svc.delete(db, goal_id)
    return Response(status_code=204)
