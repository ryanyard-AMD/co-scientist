from datetime import datetime, timezone

from sqlalchemy import Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from coscientist.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class OntologyTerm(Base):
    __tablename__ = "ontology_terms"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    canonical_name: Mapped[str] = mapped_column(String(128), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    keywords: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(nullable=False, default=_utcnow, onupdate=_utcnow)

    __table_args__ = (
        UniqueConstraint("category", "canonical_name", name="uq_category_name"),
        Index("ix_ontology_terms_category", "category"),
        Index("ix_ontology_terms_status", "status"),
    )


class OntologyRelationship(Base):
    __tablename__ = "ontology_relationships"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_term_id: Mapped[str] = mapped_column(String(36), nullable=False)
    target_term_id: Mapped[str] = mapped_column(String(36), nullable=False)
    relationship_type: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=_utcnow)

    __table_args__ = (
        Index("ix_ontology_rel_source", "source_term_id"),
        Index("ix_ontology_rel_target", "target_term_id"),
    )
