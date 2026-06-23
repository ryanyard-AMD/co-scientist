from datetime import datetime, timezone

from sqlalchemy import DateTime, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from coscientist.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class DeviceConceptCard(Base):
    __tablename__ = "device_concept_cards"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="generated")
    maturity: Mapped[str] = mapped_column(String(32), nullable=False, default="theoretical")

    # JSON dict fields
    form_factor: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    use_case: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    acoustic_architecture: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    hardware: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    expected_performance: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    # JSON list fields
    approach_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    experiment_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    validation_result_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    unresolved_risks: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    next_steps: Mapped[str] = mapped_column(Text, nullable=False, default="[]")

    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_used: Mapped[str | None] = mapped_column(String(64), nullable=True)
    generation_run_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        nullable=False, default=_utcnow, onupdate=_utcnow
    )

    __table_args__ = (
        Index("ix_device_concept_cards_workspace_id", "workspace_id"),
        Index("ix_device_concept_cards_status", "status"),
    )
