"""add experiment execution handoff fields

Revision ID: 0019
Revises: 0018
Create Date: 2026-07-06
"""

import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "experiment_cards",
        sa.Column("execution_status", sa.String(32), nullable=False, server_default="not_submitted"),
    )
    op.add_column(
        "experiment_cards",
        sa.Column("handoff_status", sa.String(32), nullable=False, server_default="not_submitted"),
    )
    op.add_column(
        "experiment_cards",
        sa.Column("submission_mode", sa.String(32), nullable=False, server_default="single_run"),
    )
    op.add_column(
        "experiment_cards",
        sa.Column("experiment_control_plane", sa.String(256), nullable=True),
    )
    op.add_column(
        "experiment_cards",
        sa.Column("required_capabilities", sa.Text, nullable=False, server_default="[]"),
    )
    op.add_column(
        "experiment_cards",
        sa.Column("runner_pool_preference", sa.String(64), nullable=True),
    )
    op.add_column(
        "experiment_cards",
        sa.Column("run_request_ids", sa.Text, nullable=False, server_default="[]"),
    )
    op.add_column(
        "experiment_cards",
        sa.Column("execution_batch_id", sa.String(36), nullable=True),
    )
    op.add_column(
        "experiment_cards",
        sa.Column("result_bundle_ids", sa.Text, nullable=False, server_default="[]"),
    )
    op.add_column(
        "experiment_cards",
        sa.Column("batch_expansion", sa.Text, nullable=False, server_default="{}"),
    )
    op.add_column(
        "experiment_cards",
        sa.Column("expected_run_count", sa.Integer, nullable=True),
    )
    op.create_index("ix_experiment_cards_execution_status", "experiment_cards", ["execution_status"])
    op.create_index("ix_experiment_cards_execution_batch_id", "experiment_cards", ["execution_batch_id"])


def downgrade() -> None:
    op.drop_index("ix_experiment_cards_execution_batch_id", table_name="experiment_cards")
    op.drop_index("ix_experiment_cards_execution_status", table_name="experiment_cards")
    op.drop_column("experiment_cards", "expected_run_count")
    op.drop_column("experiment_cards", "batch_expansion")
    op.drop_column("experiment_cards", "result_bundle_ids")
    op.drop_column("experiment_cards", "execution_batch_id")
    op.drop_column("experiment_cards", "run_request_ids")
    op.drop_column("experiment_cards", "runner_pool_preference")
    op.drop_column("experiment_cards", "required_capabilities")
    op.drop_column("experiment_cards", "experiment_control_plane")
    op.drop_column("experiment_cards", "submission_mode")
    op.drop_column("experiment_cards", "handoff_status")
    op.drop_column("experiment_cards", "execution_status")
