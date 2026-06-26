"""create agent_action_logs table

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-24
"""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "agent_action_logs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("service", sa.String(64), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("model_used", sa.String(64), nullable=False),
        sa.Column("prompt_tokens", sa.Integer, nullable=True),
        sa.Column("completion_tokens", sa.Integer, nullable=True),
        sa.Column("elapsed_ms", sa.Integer, nullable=True),
        sa.Column("response_summary", sa.Text, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agent_action_logs_workspace_id", "agent_action_logs", ["workspace_id"])
    op.create_index("ix_agent_action_logs_service", "agent_action_logs", ["service"])
    op.create_index("ix_agent_action_logs_created_at", "agent_action_logs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_agent_action_logs_created_at", table_name="agent_action_logs")
    op.drop_index("ix_agent_action_logs_service", table_name="agent_action_logs")
    op.drop_index("ix_agent_action_logs_workspace_id", table_name="agent_action_logs")
    op.drop_table("agent_action_logs")
