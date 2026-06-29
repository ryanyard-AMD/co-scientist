"""create approach_critiques

Revision ID: 0017
Revises: 0016
Create Date: 2026-06-29
"""

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "approach_critiques",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("approach_id", sa.String(36), nullable=False),
        sa.Column("critique_run_id", sa.String(36), nullable=False),
        sa.Column("verdict", sa.String(16), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("grounding_issues", sa.Text(), nullable=True),
        sa.Column("device_fit_issues", sa.Text(), nullable=True),
        sa.Column("maturity_issues", sa.Text(), nullable=True),
        sa.Column("strengths", sa.Text(), nullable=True),
        sa.Column("cited_evidence_ids", sa.Text(), nullable=False),
        sa.Column("recommended_status", sa.String(16), nullable=False),
        sa.Column("applied", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("model_used", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_critique_workspace_id", "approach_critiques", ["workspace_id"])
    op.create_index("ix_critique_approach_id", "approach_critiques", ["approach_id"])


def downgrade() -> None:
    op.drop_index("ix_critique_approach_id", table_name="approach_critiques")
    op.drop_index("ix_critique_workspace_id", table_name="approach_critiques")
    op.drop_table("approach_critiques")
