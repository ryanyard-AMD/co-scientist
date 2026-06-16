from datetime import datetime, timezone

from sqlalchemy import Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from coscientist.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ApproachCard(Base):
    __tablename__ = "approach_cards"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    method_family: Mapped[str] = mapped_column(String(128), nullable=False)
    domain: Mapped[str] = mapped_column(String(128), nullable=False, default="personal_sound_zones")
    problem_fit: Mapped[str | None] = mapped_column(Text, nullable=True)
    mechanism_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    key_assumptions: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    reported_metrics: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    hardware_requirements: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    device_relevance: Mapped[str | None] = mapped_column(Text, nullable=True)
    risks_and_limitations: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    unresolved_questions: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    suggested_experiments: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    evidence_links: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="generated")
    maturity: Mapped[str] = mapped_column(String(32), nullable=False, default="theoretical")
    generation_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    merged_into_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(nullable=False, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        Index("ix_approach_cards_workspace_id", "workspace_id"),
        Index("ix_approach_cards_status", "status"),
        Index("ix_approach_cards_method_family", "method_family"),
        Index("ix_approach_cards_ws_method", "workspace_id", "method_family"),
    )
