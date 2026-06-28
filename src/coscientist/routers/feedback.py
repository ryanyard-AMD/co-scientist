from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from coscientist.database import get_db
from coscientist.schemas.feedback import (
    FeedbackCreate,
    FeedbackListResponse,
    FeedbackResponse,
    FeedbackTargetEnum,
)
from coscientist.services import feedback as svc

router = APIRouter(prefix="/goals/{goal_id}/feedback", tags=["feedback"])


@router.post("", response_model=FeedbackResponse, status_code=201)
def create_feedback(goal_id: str, body: FeedbackCreate, db: Session = Depends(get_db)):
    return svc.create(db, goal_id, body)


@router.get("", response_model=FeedbackListResponse)
def list_feedback(
    goal_id: str,
    target_type: FeedbackTargetEnum | None = Query(default=None),
    target_id: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    return svc.list_feedback(db, goal_id, target_type=target_type, target_id=target_id)
