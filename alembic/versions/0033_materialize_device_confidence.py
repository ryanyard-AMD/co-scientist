"""materialize device confidence defaults

Revision ID: 0033
Revises: 0032
Create Date: 2026-08-13
"""

from alembic import op

revision = "0033"
down_revision = "0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite reads server-default values for rows that predate an added column,
    # but PRAGMA integrity_check still reports a NOT NULL violation until the
    # value is physically written into each record. Rewriting the column
    # materializes the neutral confidence default for historical device cards.
    op.execute(
        "UPDATE device_concept_cards "
        "SET confidence = COALESCE(confidence, 0.5)"
    )


def downgrade() -> None:
    # Data repair only; do not reintroduce invalid NULL confidence values.
    pass
