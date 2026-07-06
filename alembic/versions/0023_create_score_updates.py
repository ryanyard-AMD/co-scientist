"""create score updates

Revision ID: 0023
Revises: 0022
Create Date: 2026-07-06
"""

import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "score_updates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_key", sa.String(320), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("approach_id", sa.String(36), nullable=False),
        sa.Column("experiment_id", sa.String(36), nullable=False),
        sa.Column("execution_batch_id", sa.String(36), nullable=True),
        sa.Column("dimension", sa.String(64), nullable=False),
        sa.Column("validation_status", sa.String(24), nullable=False),
        sa.Column("evidence_type", sa.String(32), nullable=False),
        sa.Column("previous_score", sa.Float, nullable=False),
        sa.Column("new_score", sa.Float, nullable=False),
        sa.Column("score_delta", sa.Float, nullable=False),
        sa.Column("previous_confidence", sa.Float, nullable=True),
        sa.Column("new_confidence", sa.Float, nullable=True),
        sa.Column("confidence_delta", sa.Float, nullable=False, server_default="0"),
        sa.Column("run_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("passed_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("missing_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("result_bundle_refs", sa.Text, nullable=False, server_default="[]"),
        sa.Column("aggregate_metrics", sa.Text, nullable=False, server_default="{}"),
        sa.Column("rationale", sa.Text, nullable=False),
        sa.Column("reviewer_notes", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_key", "approach_id", "dimension", name="uq_score_update_source"),
    )
    op.create_index("ix_score_updates_approach_id", "score_updates", ["approach_id"])
    op.create_index("ix_score_updates_workspace_id", "score_updates", ["workspace_id"])
    op.create_index("ix_score_updates_experiment_id", "score_updates", ["experiment_id"])


def downgrade() -> None:
    op.drop_index("ix_score_updates_experiment_id", table_name="score_updates")
    op.drop_index("ix_score_updates_workspace_id", table_name="score_updates")
    op.drop_index("ix_score_updates_approach_id", table_name="score_updates")
    op.drop_table("score_updates")
