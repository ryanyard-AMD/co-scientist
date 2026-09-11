"""Device concept sim-ready geometry block

Revision ID: 0034
Revises: 0033
Create Date: 2026-09-11
"""

import sqlalchemy as sa
from alembic import op

revision = "0034"
down_revision = "0033"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "device_concept_cards",
        sa.Column("geometry", sa.Text(), nullable=False, server_default="{}"),
    )
    # SQLite serves the server default on read but leaves pre-existing rows
    # physically NULL, which 0033 had to repair after the fact for `confidence`.
    op.execute("UPDATE device_concept_cards SET geometry = '{}' WHERE geometry IS NULL")


def downgrade() -> None:
    op.drop_column("device_concept_cards", "geometry")
