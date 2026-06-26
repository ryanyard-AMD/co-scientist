"""add is_restricted to research_goals

Revision ID: 0013
Revises: 0012
Create Date: 2026-06-24
"""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "research_goals",
        sa.Column("is_restricted", sa.Boolean, nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("research_goals", "is_restricted")
