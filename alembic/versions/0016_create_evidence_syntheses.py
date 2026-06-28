"""create evidence_syntheses

Revision ID: 0016
Revises: 0015
Create Date: 2026-06-28
"""

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "evidence_syntheses",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("scout_run_id", sa.String(36), nullable=False),
        sa.Column("method_family", sa.String(128), nullable=False),
        sa.Column("synthesis_text", sa.Text(), nullable=False),
        sa.Column("key_findings", sa.Text(), nullable=True),
        sa.Column("reported_metrics", sa.Text(), nullable=True),
        sa.Column("hardware_requirements", sa.Text(), nullable=True),
        sa.Column("failure_modes", sa.Text(), nullable=True),
        sa.Column("open_questions", sa.Text(), nullable=True),
        sa.Column("cited_evidence_ids", sa.Text(), nullable=False),
        sa.Column("evidence_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("paper_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("model_used", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_synthesis_workspace_id", "evidence_syntheses", ["workspace_id"])
    op.create_index("ix_synthesis_scout_run_id", "evidence_syntheses", ["scout_run_id"])


def downgrade() -> None:
    op.drop_index("ix_synthesis_scout_run_id", table_name="evidence_syntheses")
    op.drop_index("ix_synthesis_workspace_id", table_name="evidence_syntheses")
    op.drop_table("evidence_syntheses")
