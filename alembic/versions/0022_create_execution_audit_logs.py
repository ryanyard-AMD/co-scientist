"""create execution audit logs

Revision ID: 0022
Revises: 0021
Create Date: 2026-07-06
"""

import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "execution_audit_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("actor", sa.String(128), nullable=True),
        sa.Column("experiment_id", sa.String(36), nullable=True),
        sa.Column("execution_batch_id", sa.String(36), nullable=True),
        sa.Column("approval_id", sa.String(36), nullable=True),
        sa.Column("run_request_ids", sa.Text, nullable=False, server_default="[]"),
        sa.Column("policy", sa.Text, nullable=True),
        sa.Column("payload_checksum", sa.String(64), nullable=True),
        sa.Column("detail", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_execution_audit_logs_workspace_id", "execution_audit_logs", ["workspace_id"])
    op.create_index("ix_execution_audit_logs_experiment_id", "execution_audit_logs", ["experiment_id"])
    op.create_index("ix_execution_audit_logs_execution_batch_id", "execution_audit_logs", ["execution_batch_id"])
    op.create_index("ix_execution_audit_logs_created_at", "execution_audit_logs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_execution_audit_logs_created_at", table_name="execution_audit_logs")
    op.drop_index("ix_execution_audit_logs_execution_batch_id", table_name="execution_audit_logs")
    op.drop_index("ix_execution_audit_logs_experiment_id", table_name="execution_audit_logs")
    op.drop_index("ix_execution_audit_logs_workspace_id", table_name="execution_audit_logs")
    op.drop_table("execution_audit_logs")
