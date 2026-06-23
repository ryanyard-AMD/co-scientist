"""create research_roadmap_items table

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-23
"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "research_roadmap_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("lane", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="open"),
        sa.Column("priority_score", sa.Float, nullable=False),
        sa.Column("priority_rank", sa.Integer, nullable=False),
        sa.Column("rationale", sa.Text, nullable=False),
        sa.Column("estimated_cost", sa.String(32), nullable=False, server_default="medium"),
        sa.Column("estimated_information_gain", sa.String(32), nullable=False, server_default="medium"),
        sa.Column("source_approach_ids", sa.Text, nullable=False, server_default="[]"),
        sa.Column("source_experiment_id", sa.String(36), nullable=True),
        sa.Column("source_device_id", sa.String(36), nullable=True),
        sa.Column("generation_run_id", sa.String(36), nullable=False),
        sa.Column("model_used", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
    )
    op.create_index("ix_roadmap_items_workspace_id", "research_roadmap_items", ["workspace_id"])
    op.create_index("ix_roadmap_items_status", "research_roadmap_items", ["status"])
    op.create_index("ix_roadmap_items_lane", "research_roadmap_items", ["lane"])
    op.create_index("ix_roadmap_items_generation_run_id", "research_roadmap_items", ["generation_run_id"])


def downgrade() -> None:
    op.drop_index("ix_roadmap_items_generation_run_id", table_name="research_roadmap_items")
    op.drop_index("ix_roadmap_items_lane", table_name="research_roadmap_items")
    op.drop_index("ix_roadmap_items_status", table_name="research_roadmap_items")
    op.drop_index("ix_roadmap_items_workspace_id", table_name="research_roadmap_items")
    op.drop_table("research_roadmap_items")
