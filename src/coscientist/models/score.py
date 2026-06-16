from datetime import datetime, timezone

from sqlalchemy import Boolean, Float, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from coscientist.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RubricScore(Base):
    __tablename__ = "rubric_scores"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    approach_id: Mapped[str] = mapped_column(String(36), nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False)
    dimension: Mapped[str] = mapped_column(String(64), nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False)
    weighted_score: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    low_confidence: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    scoring_run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=_utcnow)

    __table_args__ = (
        UniqueConstraint("approach_id", "dimension", name="uq_approach_dimension"),
        Index("ix_rubric_scores_approach_id", "approach_id"),
        Index("ix_rubric_scores_workspace_id", "workspace_id"),
        Index("ix_rubric_scores_scoring_run_id", "scoring_run_id"),
    )
