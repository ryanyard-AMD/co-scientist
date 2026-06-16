"""create evidence_records table

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-16
"""

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "evidence_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("scout_run_id", sa.String(36), nullable=False),
        sa.Column("query_text", sa.Text, nullable=False),
        sa.Column("paper_id", sa.String(64), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("year", sa.Integer, nullable=True),
        sa.Column("section_title", sa.String(512), nullable=True),
        sa.Column("page_number", sa.Integer, nullable=True),
        sa.Column("chunk_id", sa.String(64), nullable=False),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("chunk_text", sa.Text, nullable=False),
        sa.Column("score", sa.Float, nullable=False),
        sa.Column("vector_score", sa.Float, nullable=True),
        sa.Column("fulltext_score", sa.Float, nullable=True),
        sa.Column("method_families", sa.Text, nullable=True),
        sa.Column("metric_names", sa.Text, nullable=True),
        sa.Column("hardware_assumptions", sa.Text, nullable=True),
        sa.Column("failure_modes", sa.Text, nullable=True),
        sa.Column("is_primary_method", sa.Boolean, nullable=False, server_default="0"),
        sa.Column("claim_type", sa.String(64), nullable=True),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.Column("evidence_strength", sa.String(16), nullable=False, server_default="none"),
        sa.Column("source_id", sa.String(64), nullable=True),
        sa.Column("source_type", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_evidence_workspace_id", "evidence_records", ["workspace_id"])
    op.create_index("ix_evidence_scout_run_id", "evidence_records", ["scout_run_id"])
    op.create_index("ix_evidence_paper_id", "evidence_records", ["paper_id"])


def downgrade() -> None:
    op.drop_index("ix_evidence_paper_id", table_name="evidence_records")
    op.drop_index("ix_evidence_scout_run_id", table_name="evidence_records")
    op.drop_index("ix_evidence_workspace_id", table_name="evidence_records")
    op.drop_table("evidence_records")
