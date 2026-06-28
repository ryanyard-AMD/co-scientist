"""create feedback table

Revision ID: 0014
Revises: 0013
Create Date: 2026-06-28
"""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "feedback",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("target_type", sa.String(32), nullable=False),
        sa.Column("target_id", sa.String(36), nullable=False),
        sa.Column("is_positive", sa.Boolean, nullable=False),
        sa.Column("comment", sa.Text, nullable=True),
        sa.Column("reviewer_id", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_feedback_workspace_id", "feedback", ["workspace_id"])
    op.create_index("ix_feedback_target", "feedback", ["target_type", "target_id"])


def downgrade() -> None:
    op.drop_index("ix_feedback_target", table_name="feedback")
    op.drop_index("ix_feedback_workspace_id", table_name="feedback")
    op.drop_table("feedback")
