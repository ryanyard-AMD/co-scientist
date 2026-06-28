"""add reproduction_status to validation_results

Revision ID: 0015
Revises: 0014
Create Date: 2026-06-28
"""

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "validation_results",
        sa.Column(
            "reproduction_status",
            sa.String(24),
            nullable=False,
            server_default="failed",
        ),
    )


def downgrade() -> None:
    op.drop_column("validation_results", "reproduction_status")
