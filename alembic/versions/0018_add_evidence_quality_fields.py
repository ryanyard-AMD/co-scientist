"""add evidence quality fields

Revision ID: 0018
Revises: 0017
Create Date: 2026-06-29
"""

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "evidence_records",
        sa.Column("is_substantive", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "evidence_records",
        sa.Column("record_kind", sa.String(16), nullable=False, server_default="chunk"),
    )


def downgrade() -> None:
    op.drop_column("evidence_records", "record_kind")
    op.drop_column("evidence_records", "is_substantive")
