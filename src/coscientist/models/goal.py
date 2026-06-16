from datetime import datetime, timezone

from sqlalchemy import Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from coscientist.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ResearchGoal(Base):
    __tablename__ = "research_goals"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_application: Mapped[str] = mapped_column(String(256), nullable=False)
    success_criteria: Mapped[str] = mapped_column(Text, nullable=False)  # JSON list
    device_constraints: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON obj
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(nullable=False, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        Index("ix_research_goals_status", "status"),
        Index("ix_research_goals_name", "name"),
    )
