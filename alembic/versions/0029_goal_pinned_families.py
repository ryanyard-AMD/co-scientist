"""Goal pinned_method_families (must-have taxonomy families)

Revision ID: 0029
Revises: 0028
Create Date: 2026-07-08
"""

import sqlalchemy as sa
from alembic import op

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "research_goals",
        sa.Column("pinned_method_families", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("research_goals", "pinned_method_families")
