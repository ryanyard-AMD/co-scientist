from datetime import datetime, timezone

from sqlalchemy import Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from coscientist.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EvidenceSynthesis(Base):
    """Claude-generated synthesis of one method family's evidence for a scout run.

    Grounding invariant: every id in cited_evidence_ids is a real EvidenceRecord.id
    that was supplied to the synthesis agent — ids the model invents are dropped
    before persistence, so downstream grounding audits stay valid.
    """

    __tablename__ = "evidence_syntheses"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False)
    scout_run_id: Mapped[str] = mapped_column(String(36), nullable=False)

    method_family: Mapped[str] = mapped_column(String(128), nullable=False)

    synthesis_text: Mapped[str] = mapped_column(Text, nullable=False)
    key_findings: Mapped[str | None] = mapped_column(Text, nullable=True)
    reported_metrics: Mapped[str | None] = mapped_column(Text, nullable=True)
    hardware_requirements: Mapped[str | None] = mapped_column(Text, nullable=True)
    failure_modes: Mapped[str | None] = mapped_column(Text, nullable=True)
    open_questions: Mapped[str | None] = mapped_column(Text, nullable=True)

    cited_evidence_ids: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_count: Mapped[int] = mapped_column(nullable=False, default=0)
    paper_count: Mapped[int] = mapped_column(nullable=False, default=0)

    model_used: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=_utcnow)

    __table_args__ = (
        Index("ix_synthesis_workspace_id", "workspace_id"),
        Index("ix_synthesis_scout_run_id", "scout_run_id"),
    )
