"""Device concept simulation (predicted performance from geometry sim)

Revision ID: 0032
Revises: 0031
Create Date: 2026-07-25
"""

import sqlalchemy as sa
from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "device_concept_cards",
        sa.Column("simulation", sa.Text(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("device_concept_cards", "simulation")
