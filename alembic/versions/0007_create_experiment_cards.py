"""create experiment_cards table

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-18
"""

from alembic import op
import sqlalchemy as sa

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "experiment_cards",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("objective", sa.Text, nullable=False),
        sa.Column("hypothesis_text", sa.Text, nullable=False),
        sa.Column("approach_ids", sa.Text, nullable=False, server_default="[]"),
        sa.Column("hypothesis_id", sa.String(36), nullable=True),
        sa.Column("baseline_methods", sa.Text, nullable=False, server_default="[]"),
        sa.Column("independent_variables", sa.Text, nullable=False, server_default="{}"),
        sa.Column("fixed_assumptions", sa.Text, nullable=False, server_default="{}"),
        sa.Column("metrics", sa.Text, nullable=False, server_default="[]"),
        sa.Column("validation", sa.Text, nullable=False, server_default="{}"),
        sa.Column("runtime", sa.Text, nullable=False, server_default="{}"),
        sa.Column("artifacts", sa.Text, nullable=False, server_default="[]"),
        sa.Column("estimated_cost", sa.String(32), nullable=False, server_default="low"),
        sa.Column("estimated_runtime", sa.String(32), nullable=False, server_default="medium"),
        sa.Column("estimated_compute", sa.Text, nullable=True),
        sa.Column("requires_human_approval", sa.Boolean, nullable=False, server_default=sa.text("1")),
        sa.Column("experiment_type", sa.String(32), nullable=False, server_default="simulation"),
        sa.Column("parameter_sweep_count", sa.Integer, nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="generated"),
        sa.Column("generation_run_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_experiment_cards_workspace_id", "experiment_cards", ["workspace_id"])
    op.create_index("ix_experiment_cards_status", "experiment_cards", ["status"])
    op.create_index("ix_experiment_cards_experiment_type", "experiment_cards", ["experiment_type"])
    op.create_index("ix_experiment_cards_generation_run_id", "experiment_cards", ["generation_run_id"])


def downgrade() -> None:
    op.drop_index("ix_experiment_cards_generation_run_id", table_name="experiment_cards")
    op.drop_index("ix_experiment_cards_experiment_type", table_name="experiment_cards")
    op.drop_index("ix_experiment_cards_status", table_name="experiment_cards")
    op.drop_index("ix_experiment_cards_workspace_id", table_name="experiment_cards")
    op.drop_table("experiment_cards")
