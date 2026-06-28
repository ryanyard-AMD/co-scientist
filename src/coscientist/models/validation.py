from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from coscientist.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ValidationResult(Base):
    __tablename__ = "validation_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    experiment_id: Mapped[str] = mapped_column(String(36), nullable=False)
    goal_id: Mapped[str] = mapped_column(String(36), nullable=False)
    approach_id: Mapped[str] = mapped_column(String(36), nullable=False)
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    reproduction_status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="failed"
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    criterion_results: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    refinement_suggestions: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    measured_metrics: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    artifact_paths: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_used: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        Index("ix_validation_results_experiment_id", "experiment_id"),
        Index("ix_validation_results_approach_id", "approach_id"),
        Index("ix_validation_results_goal_id", "goal_id"),
    )
