"""create device_concept_cards table

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-22
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "device_concept_cards",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="generated"),
        sa.Column("maturity", sa.String(32), nullable=False, server_default="theoretical"),
        sa.Column("form_factor", sa.Text, nullable=False, server_default="{}"),
        sa.Column("use_case", sa.Text, nullable=False, server_default="{}"),
        sa.Column("acoustic_architecture", sa.Text, nullable=False, server_default="{}"),
        sa.Column("hardware", sa.Text, nullable=False, server_default="{}"),
        sa.Column("expected_performance", sa.Text, nullable=False, server_default="{}"),
        sa.Column("approach_ids", sa.Text, nullable=False, server_default="[]"),
        sa.Column("experiment_ids", sa.Text, nullable=False, server_default="[]"),
        sa.Column("validation_result_ids", sa.Text, nullable=False, server_default="[]"),
        sa.Column("unresolved_risks", sa.Text, nullable=False, server_default="[]"),
        sa.Column("next_steps", sa.Text, nullable=False, server_default="[]"),
        sa.Column("rationale", sa.Text, nullable=True),
        sa.Column("model_used", sa.String(64), nullable=True),
        sa.Column("generation_run_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_index(
        "ix_device_concept_cards_workspace_id", "device_concept_cards", ["workspace_id"]
    )
    op.create_index(
        "ix_device_concept_cards_status", "device_concept_cards", ["status"]
    )


def downgrade() -> None:
    op.drop_index("ix_device_concept_cards_status", table_name="device_concept_cards")
    op.drop_index("ix_device_concept_cards_workspace_id", table_name="device_concept_cards")
    op.drop_table("device_concept_cards")
