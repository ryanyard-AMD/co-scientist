"""create execution reference tables

Revision ID: 0020
Revises: 0019
Create Date: 2026-07-06
"""

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "execution_batch_references",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("experiment_id", sa.String(36), nullable=False),
        sa.Column("goal_id", sa.String(36), nullable=False),
        sa.Column("correlation_id", sa.String(64), nullable=False),
        sa.Column("submission_mode", sa.String(32), nullable=False, server_default="single_run"),
        sa.Column("aggregate_status", sa.String(32), nullable=False, server_default="submitted"),
        sa.Column("approval_policy", sa.Text, nullable=False, server_default="{}"),
        sa.Column("submitter", sa.String(128), nullable=True),
        sa.Column("control_plane_uri", sa.String(256), nullable=True),
        sa.Column("total_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("queued_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("running_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("completed_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("canceled_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("blocked_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("timed_out_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_execution_batch_references_workspace_id", "execution_batch_references", ["workspace_id"])
    op.create_index("ix_execution_batch_references_experiment_id", "execution_batch_references", ["experiment_id"])
    op.create_index("ix_execution_batch_references_goal_id", "execution_batch_references", ["goal_id"])
    op.create_index("ix_execution_batch_references_correlation_id", "execution_batch_references", ["correlation_id"])

    op.create_table(
        "run_request_references",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("run_request_id", sa.String(128), nullable=False, unique=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("experiment_id", sa.String(36), nullable=False),
        sa.Column("goal_id", sa.String(36), nullable=False),
        sa.Column("execution_batch_id", sa.String(36), nullable=True),
        sa.Column("correlation_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("control_plane_uri", sa.String(256), nullable=True),
        sa.Column("parameters", sa.Text, nullable=False, server_default="{}"),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("latest_update_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_run_request_references_workspace_id", "run_request_references", ["workspace_id"])
    op.create_index("ix_run_request_references_experiment_id", "run_request_references", ["experiment_id"])
    op.create_index("ix_run_request_references_execution_batch_id", "run_request_references", ["execution_batch_id"])
    op.create_index("ix_run_request_references_correlation_id", "run_request_references", ["correlation_id"])

    op.create_table(
        "run_attempt_references",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("attempt_id", sa.String(128), nullable=False),
        sa.Column("run_request_id", sa.String(128), nullable=False),
        sa.Column("runner_id", sa.String(128), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="running"),
        sa.Column("failure_summary", sa.Text, nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_run_attempt_references_run_request_id", "run_attempt_references", ["run_request_id"])
    op.create_index("ix_run_attempt_references_attempt_id", "run_attempt_references", ["attempt_id"])


def downgrade() -> None:
    op.drop_index("ix_run_attempt_references_attempt_id", table_name="run_attempt_references")
    op.drop_index("ix_run_attempt_references_run_request_id", table_name="run_attempt_references")
    op.drop_table("run_attempt_references")
    op.drop_index("ix_run_request_references_correlation_id", table_name="run_request_references")
    op.drop_index("ix_run_request_references_execution_batch_id", table_name="run_request_references")
    op.drop_index("ix_run_request_references_experiment_id", table_name="run_request_references")
    op.drop_index("ix_run_request_references_workspace_id", table_name="run_request_references")
    op.drop_table("run_request_references")
    op.drop_index("ix_execution_batch_references_correlation_id", table_name="execution_batch_references")
    op.drop_index("ix_execution_batch_references_goal_id", table_name="execution_batch_references")
    op.drop_index("ix_execution_batch_references_experiment_id", table_name="execution_batch_references")
    op.drop_index("ix_execution_batch_references_workspace_id", table_name="execution_batch_references")
    op.drop_table("execution_batch_references")
