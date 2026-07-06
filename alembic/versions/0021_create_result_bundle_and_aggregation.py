"""create result bundle references and validation aggregations

Revision ID: 0021
Revises: 0020
Create Date: 2026-07-06
"""

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "result_bundle_references",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("ingestion_key", sa.String(256), nullable=False, unique=True),
        sa.Column("result_bundle_id", sa.String(128), nullable=False),
        sa.Column("run_request_id", sa.String(128), nullable=False),
        sa.Column("run_id", sa.String(128), nullable=True),
        sa.Column("attempt_id", sa.String(128), nullable=True),
        sa.Column("experiment_id", sa.String(36), nullable=False),
        sa.Column("goal_id", sa.String(36), nullable=False),
        sa.Column("hypothesis_id", sa.String(36), nullable=True),
        sa.Column("approach_ids", sa.Text, nullable=False, server_default="[]"),
        sa.Column("execution_batch_id", sa.String(36), nullable=True),
        sa.Column("validation_status", sa.String(24), nullable=False, server_default="inconclusive"),
        sa.Column("metrics", sa.Text, nullable=False, server_default="{}"),
        sa.Column("artifacts", sa.Text, nullable=False, server_default="{}"),
        sa.Column("deviations", sa.Text, nullable=False, server_default="[]"),
        sa.Column("warnings", sa.Text, nullable=False, server_default="[]"),
        sa.Column("provenance", sa.Text, nullable=False, server_default="{}"),
        sa.Column("failure_type", sa.String(64), nullable=True),
        sa.Column("failure_summary", sa.Text, nullable=True),
        sa.Column("retryable", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("is_partial", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_result_bundle_references_experiment_id", "result_bundle_references", ["experiment_id"])
    op.create_index("ix_result_bundle_references_goal_id", "result_bundle_references", ["goal_id"])
    op.create_index("ix_result_bundle_references_run_request_id", "result_bundle_references", ["run_request_id"])
    op.create_index("ix_result_bundle_references_execution_batch_id", "result_bundle_references", ["execution_batch_id"])

    op.create_table(
        "validation_aggregations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("experiment_id", sa.String(36), nullable=False, unique=True),
        sa.Column("goal_id", sa.String(36), nullable=False),
        sa.Column("execution_batch_id", sa.String(36), nullable=True),
        sa.Column("aggregate_status", sa.String(16), nullable=False, server_default="inconclusive"),
        sa.Column("expected_run_count", sa.Integer, nullable=True),
        sa.Column("total_runs", sa.Integer, nullable=False, server_default="0"),
        sa.Column("passed_runs", sa.Integer, nullable=False, server_default="0"),
        sa.Column("failed_runs", sa.Integer, nullable=False, server_default="0"),
        sa.Column("blocked_runs", sa.Integer, nullable=False, server_default="0"),
        sa.Column("missing_runs", sa.Integer, nullable=False, server_default="0"),
        sa.Column("is_partial", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("metric_summaries", sa.Text, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_validation_aggregations_goal_id", "validation_aggregations", ["goal_id"])


def downgrade() -> None:
    op.drop_index("ix_validation_aggregations_goal_id", table_name="validation_aggregations")
    op.drop_table("validation_aggregations")
    op.drop_index("ix_result_bundle_references_execution_batch_id", table_name="result_bundle_references")
    op.drop_index("ix_result_bundle_references_run_request_id", table_name="result_bundle_references")
    op.drop_index("ix_result_bundle_references_goal_id", table_name="result_bundle_references")
    op.drop_index("ix_result_bundle_references_experiment_id", table_name="result_bundle_references")
    op.drop_table("result_bundle_references")
