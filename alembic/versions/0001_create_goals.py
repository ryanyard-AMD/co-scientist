"""create research_goals table

Revision ID: 0001
Revises:
Create Date: 2026-06-15
"""

from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "research_goals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("target_application", sa.String(256), nullable=False),
        sa.Column("success_criteria", sa.Text, nullable=False),
        sa.Column("device_constraints", sa.Text, nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_research_goals_status", "research_goals", ["status"])
    op.create_index("ix_research_goals_name", "research_goals", ["name"])


def downgrade() -> None:
    op.drop_index("ix_research_goals_name", table_name="research_goals")
    op.drop_index("ix_research_goals_status", table_name="research_goals")
    op.drop_table("research_goals")
