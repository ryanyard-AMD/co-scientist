"""device execution evidence: confidence + evidence updates

Revision ID: 0024
Revises: 0023
Create Date: 2026-07-06
"""

import sqlalchemy as sa
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "device_concept_cards",
        sa.Column("confidence", sa.Float, nullable=False, server_default="0.5"),
    )

    op.create_table(
        "device_evidence_updates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source_key", sa.String(320), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("device_id", sa.String(36), nullable=False),
        sa.Column("validation_status", sa.String(24), nullable=False, server_default="inconclusive"),
        sa.Column("previous_confidence", sa.Float, nullable=False, server_default="0"),
        sa.Column("new_confidence", sa.Float, nullable=False, server_default="0"),
        sa.Column("confidence_delta", sa.Float, nullable=False, server_default="0"),
        sa.Column("passed_experiments", sa.Integer, nullable=False, server_default="0"),
        sa.Column("failed_experiments", sa.Integer, nullable=False, server_default="0"),
        sa.Column("inconclusive_experiments", sa.Integer, nullable=False, server_default="0"),
        sa.Column("supporting_result_bundle_refs", sa.Text, nullable=False, server_default="[]"),
        sa.Column("affected_approach_ids", sa.Text, nullable=False, server_default="[]"),
        sa.Column("score_deltas", sa.Text, nullable=False, server_default="{}"),
        sa.Column("added_risks", sa.Text, nullable=False, server_default="[]"),
        sa.Column("rationale", sa.Text, nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_key", "device_id", name="uq_device_evidence_source"),
    )
    op.create_index("ix_device_evidence_updates_device_id", "device_evidence_updates", ["device_id"])
    op.create_index("ix_device_evidence_updates_workspace_id", "device_evidence_updates", ["workspace_id"])


def downgrade() -> None:
    op.drop_index("ix_device_evidence_updates_workspace_id", table_name="device_evidence_updates")
    op.drop_index("ix_device_evidence_updates_device_id", table_name="device_evidence_updates")
    op.drop_table("device_evidence_updates")
    op.drop_column("device_concept_cards", "confidence")
