from datetime import datetime, timezone

from sqlalchemy import Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from coscientist.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EvidenceRecord(Base):
    __tablename__ = "evidence_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False)
    scout_run_id: Mapped[str] = mapped_column(String(36), nullable=False)

    query_text: Mapped[str] = mapped_column(Text, nullable=False)

    paper_id: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    year: Mapped[int | None] = mapped_column(nullable=True)

    section_title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    page_number: Mapped[int | None] = mapped_column(nullable=True)
    chunk_id: Mapped[str] = mapped_column(String(64), nullable=False)
    chunk_index: Mapped[int] = mapped_column(nullable=False)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)

    score: Mapped[float] = mapped_column(nullable=False)
    vector_score: Mapped[float | None] = mapped_column(nullable=True)
    fulltext_score: Mapped[float | None] = mapped_column(nullable=True)

    method_families: Mapped[str | None] = mapped_column(Text, nullable=True)
    metric_names: Mapped[str | None] = mapped_column(Text, nullable=True)
    hardware_assumptions: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_modes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_primary_method: Mapped[bool] = mapped_column(nullable=False, default=False)

    claim_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    confidence: Mapped[float | None] = mapped_column(nullable=True)
    source_claim_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    claim_relationships: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list of edges
    evidence_strength: Mapped[str] = mapped_column(String(16), nullable=False, default="none")

    is_substantive: Mapped[bool] = mapped_column(nullable=False, default=True)
    record_kind: Mapped[str] = mapped_column(String(16), nullable=False, default="chunk")

    source_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_type: Mapped[str | None] = mapped_column(String(32), nullable=True)

    created_at: Mapped[datetime] = mapped_column(nullable=False, default=_utcnow)

    __table_args__ = (
        Index("ix_evidence_workspace_id", "workspace_id"),
        Index("ix_evidence_scout_run_id", "scout_run_id"),
        Index("ix_evidence_paper_id", "paper_id"),
    )
