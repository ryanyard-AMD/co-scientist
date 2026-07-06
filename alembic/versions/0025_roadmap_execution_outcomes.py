"""roadmap execution outcomes: outcome, provisional, evidence_adjusted_score

Revision ID: 0025
Revises: 0024
Create Date: 2026-07-06
"""

import sqlalchemy as sa
from alembic import op

revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "research_roadmap_items",
        sa.Column("execution_outcome", sa.String(24), nullable=True),
    )
    op.add_column(
        "research_roadmap_items",
        sa.Column("provisional", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "research_roadmap_items",
        sa.Column("evidence_adjusted_score", sa.Float, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("research_roadmap_items", "evidence_adjusted_score")
    op.drop_column("research_roadmap_items", "provisional")
    op.drop_column("research_roadmap_items", "execution_outcome")
