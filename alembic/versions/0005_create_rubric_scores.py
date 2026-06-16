"""create rubric_scores table

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-16
"""

from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "rubric_scores",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("approach_id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("dimension", sa.String(64), nullable=False),
        sa.Column("score", sa.Float, nullable=False),
        sa.Column("weight", sa.Float, nullable=False),
        sa.Column("weighted_score", sa.Float, nullable=False),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.Column("rationale", sa.Text, nullable=False),
        sa.Column("evidence_ids", sa.Text, nullable=False, server_default="[]"),
        sa.Column("low_confidence", sa.Boolean, nullable=False, server_default=sa.text("0")),
        sa.Column("scoring_run_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_rubric_scores_approach_id", "rubric_scores", ["approach_id"])
    op.create_index("ix_rubric_scores_workspace_id", "rubric_scores", ["workspace_id"])
    op.create_index("ix_rubric_scores_scoring_run_id", "rubric_scores", ["scoring_run_id"])
    op.create_unique_constraint("uq_approach_dimension", "rubric_scores", ["approach_id", "dimension"])


def downgrade() -> None:
    op.drop_constraint("uq_approach_dimension", "rubric_scores", type_="unique")
    op.drop_index("ix_rubric_scores_scoring_run_id", table_name="rubric_scores")
    op.drop_index("ix_rubric_scores_workspace_id", table_name="rubric_scores")
    op.drop_index("ix_rubric_scores_approach_id", table_name="rubric_scores")
    op.drop_table("rubric_scores")
