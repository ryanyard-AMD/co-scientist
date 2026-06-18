from datetime import datetime, timezone

from sqlalchemy import Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from coscientist.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ApprovalDecision(Base):
    __tablename__ = "approval_decisions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    experiment_id: Mapped[str] = mapped_column(String(36), nullable=False)
    goal_id: Mapped[str] = mapped_column(String(36), nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    reviewer_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    resource_flags: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=_utcnow)

    __table_args__ = (
        Index("ix_approval_decisions_experiment_id", "experiment_id"),
        Index("ix_approval_decisions_goal_id", "goal_id"),
        Index("ix_approval_decisions_experiment_created", "experiment_id", "created_at"),
    )
