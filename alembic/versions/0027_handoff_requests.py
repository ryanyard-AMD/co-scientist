"""CS-APPROVAL-010/011 handoff control: failed handoffs, retries, cancel/resubmit

Revision ID: 0027
Revises: 0026
Create Date: 2026-07-07
"""

import sqlalchemy as sa
from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "handoff_requests",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("experiment_id", sa.String(36), nullable=False),
        sa.Column("goal_id", sa.String(36), nullable=False),
        sa.Column("request_type", sa.String(24), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("payload_summary", sa.Text, nullable=True),
        sa.Column("approval_id", sa.String(36), nullable=True),
        sa.Column("retryable", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("run_request_ids", sa.Text, nullable=False, server_default="[]"),
        sa.Column("execution_batch_id", sa.String(36), nullable=True),
        sa.Column("correlation_id", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_handoff_requests_workspace_id", "handoff_requests", ["workspace_id"])
    op.create_index("ix_handoff_requests_experiment_id", "handoff_requests", ["experiment_id"])
    op.create_index("ix_handoff_requests_goal_id", "handoff_requests", ["goal_id"])


def downgrade() -> None:
    op.drop_index("ix_handoff_requests_goal_id", table_name="handoff_requests")
    op.drop_index("ix_handoff_requests_experiment_id", table_name="handoff_requests")
    op.drop_index("ix_handoff_requests_workspace_id", table_name="handoff_requests")
    op.drop_table("handoff_requests")
