import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from coscientist.models.feedback import Feedback
from coscientist.schemas.feedback import (
    FeedbackCreate,
    FeedbackListResponse,
    FeedbackResponse,
    FeedbackTargetEnum,
)
from coscientist.services import goal as goal_svc


def create(db: Session, goal_id: str, data: FeedbackCreate) -> FeedbackResponse:
    goal_svc.get(db, goal_id)
    row = Feedback(
        id=str(uuid.uuid4()),
        workspace_id=goal_id,
        target_type=data.target_type.value,
        target_id=data.target_id,
        is_positive=data.is_positive,
        comment=data.comment,
        reviewer_id=data.reviewer_id,
        created_at=datetime.now(timezone.utc),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return FeedbackResponse.model_validate(row)


def list_feedback(
    db: Session,
    goal_id: str,
    target_type: FeedbackTargetEnum | None = None,
    target_id: str | None = None,
) -> FeedbackListResponse:
    goal_svc.get(db, goal_id)
    stmt = (
        select(Feedback)
        .where(Feedback.workspace_id == goal_id)
        .order_by(Feedback.created_at.desc())
    )
    if target_type is not None:
        stmt = stmt.where(Feedback.target_type == target_type.value)
    if target_id is not None:
        stmt = stmt.where(Feedback.target_id == target_id)
    rows = list(db.scalars(stmt))
    return FeedbackListResponse(
        items=[FeedbackResponse.model_validate(r) for r in rows],
        total=len(rows),
    )


def satisfaction_counts(db: Session, goal_id: str) -> tuple[int, int]:
    """Return (positive, total) feedback counts for a goal's workspace."""
    rows = list(
        db.scalars(select(Feedback).where(Feedback.workspace_id == goal_id))
    )
    positive = sum(1 for r in rows if r.is_positive)
    return positive, len(rows)
