"""CS-EXEC-007 run-request correlation + CS-VALIDATION-013 artifact manifest labels

Revision ID: 0026
Revises: 0025
Create Date: 2026-07-07
"""

import sqlalchemy as sa
from alembic import op

revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # CS-EXEC-007: direct Approach/Hypothesis correlation on RunRequest references.
    op.add_column(
        "run_request_references",
        sa.Column("hypothesis_id", sa.String(36), nullable=True),
    )
    op.add_column(
        "run_request_references",
        sa.Column("approach_ids", sa.Text, nullable=False, server_default="[]"),
    )
    # CS-VALIDATION-013: artifact manifest URI + permission-aware access labels.
    op.add_column(
        "result_bundle_references",
        sa.Column("manifest_uri", sa.String(512), nullable=True),
    )
    op.add_column(
        "result_bundle_references",
        sa.Column(
            "artifact_visibility",
            sa.String(24),
            nullable=False,
            server_default="internal",
        ),
    )
    op.add_column(
        "result_bundle_references",
        sa.Column("access_label", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("result_bundle_references", "access_label")
    op.drop_column("result_bundle_references", "artifact_visibility")
    op.drop_column("result_bundle_references", "manifest_uri")
    op.drop_column("run_request_references", "approach_ids")
    op.drop_column("run_request_references", "hypothesis_id")
