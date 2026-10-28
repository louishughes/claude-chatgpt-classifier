"""Record review decisions on taxonomy proposals (TAX-004).

Revision ID: 0016_taxonomy_review
Revises: 0015_taxonomy
Create Date: 2026-10-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0016_taxonomy_review"
down_revision: str | None = "0015_taxonomy"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Add the decision note and the ID an approved ``add`` created."""
    with op.batch_alter_table("taxonomy_proposals", schema=None) as batch_op:
        batch_op.add_column(sa.Column("decision_note", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("result_id", sa.String(length=40), nullable=True))


def downgrade() -> None:
    """Drop the two columns."""
    with op.batch_alter_table("taxonomy_proposals", schema=None) as batch_op:
        batch_op.drop_column("result_id")
        batch_op.drop_column("decision_note")
