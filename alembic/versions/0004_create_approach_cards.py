"""create approach_cards table

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-16
"""

from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "approach_cards",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("method_family", sa.String(128), nullable=False),
        sa.Column("domain", sa.String(128), nullable=False, server_default="personal_sound_zones"),
        sa.Column("problem_fit", sa.Text, nullable=True),
        sa.Column("mechanism_summary", sa.Text, nullable=True),
        sa.Column("key_assumptions", sa.Text, nullable=False, server_default="[]"),
        sa.Column("reported_metrics", sa.Text, nullable=False, server_default="[]"),
        sa.Column("hardware_requirements", sa.Text, nullable=False, server_default="[]"),
        sa.Column("device_relevance", sa.Text, nullable=True),
        sa.Column("risks_and_limitations", sa.Text, nullable=False, server_default="[]"),
        sa.Column("unresolved_questions", sa.Text, nullable=False, server_default="[]"),
        sa.Column("suggested_experiments", sa.Text, nullable=False, server_default="[]"),
        sa.Column("evidence_links", sa.Text, nullable=False, server_default="[]"),
        sa.Column("status", sa.String(32), nullable=False, server_default="generated"),
        sa.Column("maturity", sa.String(32), nullable=False, server_default="theoretical"),
        sa.Column("generation_run_id", sa.String(36), nullable=True),
        sa.Column("merged_into_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_approach_cards_workspace_id", "approach_cards", ["workspace_id"])
    op.create_index("ix_approach_cards_status", "approach_cards", ["status"])
    op.create_index("ix_approach_cards_method_family", "approach_cards", ["method_family"])
    op.create_index("ix_approach_cards_ws_method", "approach_cards", ["workspace_id", "method_family"])


def downgrade() -> None:
    op.drop_index("ix_approach_cards_ws_method", table_name="approach_cards")
    op.drop_index("ix_approach_cards_method_family", table_name="approach_cards")
    op.drop_index("ix_approach_cards_status", table_name="approach_cards")
    op.drop_index("ix_approach_cards_workspace_id", table_name="approach_cards")
    op.drop_table("approach_cards")
