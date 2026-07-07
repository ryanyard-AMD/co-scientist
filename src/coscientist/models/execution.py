from datetime import datetime, timezone

from sqlalchemy import DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from coscientist.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ExecutionBatchReference(Base):
    """Co-scientist-side reference to an ExecutionBatch owned by the
    Experimentation System. Tracks aggregate status across its RunRequests
    without owning execution."""

    __tablename__ = "execution_batch_references"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False)
    experiment_id: Mapped[str] = mapped_column(String(36), nullable=False)
    goal_id: Mapped[str] = mapped_column(String(36), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    submission_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="single_run")
    aggregate_status: Mapped[str] = mapped_column(String(32), nullable=False, default="submitted")
    approval_policy: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    submitter: Mapped[str | None] = mapped_column(String(128), nullable=True)
    control_plane_uri: Mapped[str | None] = mapped_column(String(256), nullable=True)

    total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    queued_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    running_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    completed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    canceled_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    blocked_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    timed_out_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        Index("ix_execution_batch_references_workspace_id", "workspace_id"),
        Index("ix_execution_batch_references_experiment_id", "experiment_id"),
        Index("ix_execution_batch_references_goal_id", "goal_id"),
        Index("ix_execution_batch_references_correlation_id", "correlation_id"),
    )


class RunRequestReference(Base):
    """Co-scientist-side reference to a single RunRequest owned by the
    Experimentation System."""

    __tablename__ = "run_request_references"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_request_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False)
    experiment_id: Mapped[str] = mapped_column(String(36), nullable=False)
    goal_id: Mapped[str] = mapped_column(String(36), nullable=False)
    execution_batch_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # CS-EXEC-007: direct correlation to the Approach/Hypothesis cards this run
    # tests, so events can be reconciled without traversing the Experiment card.
    hypothesis_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    approach_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="pending")
    control_plane_uri: Mapped[str | None] = mapped_column(String(256), nullable=True)
    parameters: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)
    latest_update_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        Index("ix_run_request_references_workspace_id", "workspace_id"),
        Index("ix_run_request_references_experiment_id", "experiment_id"),
        Index("ix_run_request_references_execution_batch_id", "execution_batch_id"),
        Index("ix_run_request_references_correlation_id", "correlation_id"),
    )


class RunAttemptReference(Base):
    """Co-scientist-side reference to a RunAttempt (a single execution attempt of
    a RunRequest) — surfaces retries/failures without owning runner internals."""

    __tablename__ = "run_attempt_references"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    attempt_id: Mapped[str] = mapped_column(String(128), nullable=False)
    run_request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    runner_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    failure_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        Index("ix_run_attempt_references_run_request_id", "run_request_id"),
        Index("ix_run_attempt_references_attempt_id", "attempt_id"),
    )
