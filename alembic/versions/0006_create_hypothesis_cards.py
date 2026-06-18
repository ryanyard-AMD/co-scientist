"""create hypothesis_cards table

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-17
"""

from alembic import op
import sqlalchemy as sa

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "hypothesis_cards",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("rationale", sa.Text, nullable=False),
        sa.Column("hypothesis_type", sa.String(32), nullable=False, server_default="conservative"),
        sa.Column("approach_ids", sa.Text, nullable=False, server_default="[]"),
        sa.Column("assumptions", sa.Text, nullable=False, server_default="[]"),
        sa.Column("expected_benefits", sa.Text, nullable=False, server_default="[]"),
        sa.Column("failure_modes", sa.Text, nullable=False, server_default="[]"),
        sa.Column("required_experiments", sa.Text, nullable=False, server_default="[]"),
        sa.Column("compatibility_notes", sa.Text, nullable=False, server_default="[]"),
        sa.Column("has_conflicts", sa.Boolean, nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.String(32), nullable=False, server_default="generated"),
        sa.Column("generation_run_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_hypothesis_cards_workspace_id", "hypothesis_cards", ["workspace_id"])
    op.create_index("ix_hypothesis_cards_status", "hypothesis_cards", ["status"])
    op.create_index("ix_hypothesis_cards_type", "hypothesis_cards", ["hypothesis_type"])
    op.create_index("ix_hypothesis_cards_generation_run_id", "hypothesis_cards", ["generation_run_id"])


def downgrade() -> None:
    op.drop_index("ix_hypothesis_cards_generation_run_id", table_name="hypothesis_cards")
    op.drop_index("ix_hypothesis_cards_type", table_name="hypothesis_cards")
    op.drop_index("ix_hypothesis_cards_status", table_name="hypothesis_cards")
    op.drop_index("ix_hypothesis_cards_workspace_id", table_name="hypothesis_cards")
    op.drop_table("hypothesis_cards")
