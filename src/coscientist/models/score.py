from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, Text, UniqueConstraint
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


class ScoreUpdate(Base):
    """Execution-evidence score update (CS-EPIC-SCORE).

    Records how a completed / failed / partial / mixed validation outcome moved
    an Approach Card's rubric dimension score and confidence. Idempotent on
    ``source_key`` (the triggering ResultBundle ingestion key) so a replayed
    ingestion never applies a second delta (CS-SCORE-010). Each row is a full,
    explainable audit of the change (CS-SCORE-009 / CS-SCORE-012).
    """

    __tablename__ = "score_updates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_key: Mapped[str] = mapped_column(String(320), nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False)
    approach_id: Mapped[str] = mapped_column(String(36), nullable=False)
    experiment_id: Mapped[str] = mapped_column(String(36), nullable=False)
    execution_batch_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    dimension: Mapped[str] = mapped_column(String(64), nullable=False)
    validation_status: Mapped[str] = mapped_column(String(24), nullable=False)
    evidence_type: Mapped[str] = mapped_column(String(32), nullable=False)

    previous_score: Mapped[float] = mapped_column(Float, nullable=False)
    new_score: Mapped[float] = mapped_column(Float, nullable=False)
    score_delta: Mapped[float] = mapped_column(Float, nullable=False)
    previous_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    new_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    confidence_delta: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    run_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    passed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    missing_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    result_bundle_refs: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    aggregate_metrics: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    reviewer_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    __table_args__ = (
        UniqueConstraint("source_key", "approach_id", "dimension", name="uq_score_update_source"),
        Index("ix_score_updates_approach_id", "approach_id"),
        Index("ix_score_updates_workspace_id", "workspace_id"),
        Index("ix_score_updates_experiment_id", "experiment_id"),
    )
