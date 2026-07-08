"""Approach revision provenance (revised_from_id)

Revision ID: 0031
Revises: 0030
Create Date: 2026-07-08
"""

import sqlalchemy as sa
from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "approach_cards",
        sa.Column("revised_from_id", sa.String(length=36), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("approach_cards", "revised_from_id")
