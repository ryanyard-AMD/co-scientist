from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from coscientist.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ResearchRoadmapItem(Base):
    __tablename__ = "research_roadmap_items"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    lane: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    priority_score: Mapped[float] = mapped_column(Float, nullable=False)
    priority_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    estimated_cost: Mapped[str] = mapped_column(String(32), nullable=False, default="medium")
    estimated_information_gain: Mapped[str] = mapped_column(String(32), nullable=False, default="medium")
    source_approach_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    source_experiment_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_device_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    generation_run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    model_used: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Execution linkage (CS-EPIC-ROADMAP). Populated when a linked experiment's
    # ResultBundles aggregate: passed/failed/inconclusive/partial. `provisional`
    # marks updates driven by a still-incomplete (partial) batch, to be confirmed
    # or replaced once the batch finishes. `evidence_adjusted_score` is the
    # validation-aware ranking score that supersedes priority_score for ordering.
    execution_outcome: Mapped[str | None] = mapped_column(String(24), nullable=True)
    provisional: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    evidence_adjusted_score: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        nullable=False, default=_utcnow, onupdate=_utcnow
    )

    __table_args__ = (
        Index("ix_roadmap_items_workspace_id", "workspace_id"),
        Index("ix_roadmap_items_status", "status"),
        Index("ix_roadmap_items_lane", "lane"),
        Index("ix_roadmap_items_generation_run_id", "generation_run_id"),
    )
