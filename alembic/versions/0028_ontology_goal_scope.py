"""Goal-scoped ontology terms (workspace_id + composite unique)

Revision ID: 0028
Revises: 0027
Create Date: 2026-07-07
"""

import sqlalchemy as sa
from alembic import op

revision = "0028"
down_revision = "0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite cannot ALTER/DROP a named constraint in place; batch mode recreates
    # the table. Existing rows keep workspace_id = NULL (shared global seed).
    with op.batch_alter_table("ontology_terms", schema=None) as batch_op:
        batch_op.add_column(sa.Column("workspace_id", sa.String(36), nullable=True))
        batch_op.drop_constraint("uq_category_name", type_="unique")
        batch_op.create_unique_constraint(
            "uq_category_name_ws", ["category", "canonical_name", "workspace_id"]
        )
        batch_op.create_index(
            "ix_ontology_terms_workspace", ["workspace_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("ontology_terms", schema=None) as batch_op:
        batch_op.drop_index("ix_ontology_terms_workspace")
        batch_op.drop_constraint("uq_category_name_ws", type_="unique")
        batch_op.create_unique_constraint(
            "uq_category_name", ["category", "canonical_name"]
        )
        batch_op.drop_column("workspace_id")
