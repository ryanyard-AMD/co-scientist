from datetime import datetime, timezone

from sqlalchemy import Boolean, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from coscientist.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class HypothesisCard(Base):
    __tablename__ = "hypothesis_cards"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    hypothesis_type: Mapped[str] = mapped_column(String(32), nullable=False, default="conservative")
    approach_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    assumptions: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    expected_benefits: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    failure_modes: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    required_experiments: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    compatibility_notes: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    has_conflicts: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="generated")
    generation_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(nullable=False, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        Index("ix_hypothesis_cards_workspace_id", "workspace_id"),
        Index("ix_hypothesis_cards_status", "status"),
        Index("ix_hypothesis_cards_type", "hypothesis_type"),
        Index("ix_hypothesis_cards_generation_run_id", "generation_run_id"),
    )
