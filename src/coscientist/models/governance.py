from datetime import datetime, timezone

from sqlalchemy import DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from coscientist.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AgentActionLog(Base):
    __tablename__ = "agent_action_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False)
    service: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    model_used: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    elapsed_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        Index("ix_agent_action_logs_workspace_id", "workspace_id"),
        Index("ix_agent_action_logs_service", "service"),
        Index("ix_agent_action_logs_created_at", "created_at"),
    )


class ExecutionAuditLog(Base):
    """Accountability trail for every execution-related action (CS-GOV-009).

    The co-scientist never executes; it hands off RunRequests and ingests
    ResultBundles. Each such action — handoff submission, run status update,
    and result ingestion — is recorded here with its submitter, approval ID,
    Experiment Card ID, RunRequest IDs, governing policy, and a payload
    checksum so the action is reproducible and accountable.
    """

    __tablename__ = "execution_audit_logs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    actor: Mapped[str | None] = mapped_column(String(128), nullable=True)
    experiment_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    execution_batch_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    approval_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    run_request_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    policy: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        Index("ix_execution_audit_logs_workspace_id", "workspace_id"),
        Index("ix_execution_audit_logs_experiment_id", "experiment_id"),
        Index("ix_execution_audit_logs_execution_batch_id", "execution_batch_id"),
        Index("ix_execution_audit_logs_created_at", "created_at"),
    )
