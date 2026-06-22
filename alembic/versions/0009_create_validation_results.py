"""create validation_results table

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-19
"""

from alembic import op
import sqlalchemy as sa

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "validation_results",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("experiment_id", sa.String(36), nullable=False),
        sa.Column("goal_id", sa.String(36), nullable=False),
        sa.Column("approach_id", sa.String(36), nullable=False),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("reasoning", sa.Text, nullable=False),
        sa.Column("criterion_results", sa.Text, nullable=False, server_default="[]"),
        sa.Column("refinement_suggestions", sa.Text, nullable=False, server_default="[]"),
        sa.Column("measured_metrics", sa.Text, nullable=False, server_default="{}"),
        sa.Column("artifact_paths", sa.Text, nullable=True),
        sa.Column("model_used", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_validation_results_experiment_id", "validation_results", ["experiment_id"])
    op.create_index("ix_validation_results_approach_id", "validation_results", ["approach_id"])
    op.create_index("ix_validation_results_goal_id", "validation_results", ["goal_id"])


def downgrade() -> None:
    op.drop_index("ix_validation_results_goal_id", table_name="validation_results")
    op.drop_index("ix_validation_results_approach_id", table_name="validation_results")
    op.drop_index("ix_validation_results_experiment_id", table_name="validation_results")
    op.drop_table("validation_results")
