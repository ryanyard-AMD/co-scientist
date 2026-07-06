from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, Index, Integer, String, Text
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
    # Architecture confidence, updated from downstream execution evidence
    # (CS-EPIC-DEVICE). Starts neutral; validated experiments raise it, failed
    # ones lower it.
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.5)

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


class DeviceEvidenceUpdate(Base):
    """Records a Device Concept confidence/risk change driven by downstream
    execution evidence (CS-EPIC-DEVICE). Idempotent on (source_key, device_id)
    so a replayed ResultBundle ingestion never double-records."""

    __tablename__ = "device_evidence_updates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_key: Mapped[str] = mapped_column(String(320), nullable=False)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False)
    device_id: Mapped[str] = mapped_column(String(36), nullable=False)

    validation_status: Mapped[str] = mapped_column(String(24), nullable=False, default="inconclusive")
    previous_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    new_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    confidence_delta: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)

    passed_experiments: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failed_experiments: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    inconclusive_experiments: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    supporting_result_bundle_refs: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    affected_approach_ids: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    score_deltas: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    added_risks: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=_utcnow)

    __table_args__ = (
        Index("ix_device_evidence_updates_device_id", "device_id"),
        Index("ix_device_evidence_updates_workspace_id", "workspace_id"),
    )
