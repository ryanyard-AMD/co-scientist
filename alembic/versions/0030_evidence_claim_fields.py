"""Evidence claim fields (source_claim_id, claim_relationships)

Revision ID: 0030
Revises: 0029
Create Date: 2026-07-08
"""

import sqlalchemy as sa
from alembic import op

revision = "0030"
down_revision = "0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "evidence_records",
        sa.Column("source_claim_id", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "evidence_records",
        sa.Column("claim_relationships", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("evidence_records", "claim_relationships")
    op.drop_column("evidence_records", "source_claim_id")
