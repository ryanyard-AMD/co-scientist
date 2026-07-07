from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from coscientist.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class HandoffRequest(Base):
    """Co-scientist-side record of a handoff control action against the external
    Experimentation System: an initial submit that failed, a retry, or a
    cancellation / resubmission request.

    The co-scientist never controls execution — it records that a request was
    made and the status the Experimentation System reported. Actual execution
    control (starting, stopping, re-running) is owned by that system.
    """

    __tablename__ = "handoff_requests"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False)
    experiment_id: Mapped[str] = mapped_column(String(36), nullable=False)
    goal_id: Mapped[str] = mapped_column(String(36), nullable=False)
    # submit | retry | cancel | resubmit
    request_type: Mapped[str] = mapped_column(String(24), nullable=False)
    # failed | requested | acknowledged | rejected
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    approval_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    retryable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    run_request_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    execution_batch_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        Index("ix_handoff_requests_workspace_id", "workspace_id"),
        Index("ix_handoff_requests_experiment_id", "experiment_id"),
        Index("ix_handoff_requests_goal_id", "goal_id"),
    )
