from datetime import datetime, timezone

from sqlalchemy import Boolean, Float, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from coscientist.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ApproachCritique(Base):
    """Claude-generated adversarial review of one approach card.

    Grounding invariant: every id in cited_evidence_ids is a real EvidenceRecord.id
    that was linked to the critiqued card and supplied to the critic agent — ids the
    model invents are dropped before persistence, so grounding audits stay valid.
    """

    __tablename__ = "approach_critiques"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(36), nullable=False)
    approach_id: Mapped[str] = mapped_column(String(36), nullable=False)
    critique_run_id: Mapped[str] = mapped_column(String(36), nullable=False)

    verdict: Mapped[str] = mapped_column(String(16), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    grounding_issues: Mapped[str | None] = mapped_column(Text, nullable=True)
    device_fit_issues: Mapped[str | None] = mapped_column(Text, nullable=True)
    maturity_issues: Mapped[str | None] = mapped_column(Text, nullable=True)
    strengths: Mapped[str | None] = mapped_column(Text, nullable=True)

    cited_evidence_ids: Mapped[str] = mapped_column(Text, nullable=False)
    recommended_status: Mapped[str] = mapped_column(String(16), nullable=False)
    applied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)

    model_used: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=_utcnow)

    __table_args__ = (
        Index("ix_critique_workspace_id", "workspace_id"),
        Index("ix_critique_approach_id", "approach_id"),
    )
