"""create approval_decisions table

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-18
"""

from alembic import op
import sqlalchemy as sa

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "approval_decisions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("experiment_id", sa.String(36), nullable=False),
        sa.Column("goal_id", sa.String(36), nullable=False),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("reviewer_id", sa.String(256), nullable=True),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("resource_flags", sa.Text, nullable=False, server_default="[]"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_approval_decisions_experiment_id", "approval_decisions", ["experiment_id"])
    op.create_index("ix_approval_decisions_goal_id", "approval_decisions", ["goal_id"])
    op.create_index(
        "ix_approval_decisions_experiment_created",
        "approval_decisions",
        ["experiment_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_approval_decisions_experiment_created", table_name="approval_decisions")
    op.drop_index("ix_approval_decisions_goal_id", table_name="approval_decisions")
    op.drop_index("ix_approval_decisions_experiment_id", table_name="approval_decisions")
    op.drop_table("approval_decisions")
