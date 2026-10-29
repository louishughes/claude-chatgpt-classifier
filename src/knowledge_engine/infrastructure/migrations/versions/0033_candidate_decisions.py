"""Record who accepted or rejected an identity candidate, and when (IMP-009).

Revision ID: 0033_candidate_decisions
Revises: 0032_record_link_depends_on
Create Date: 2026-10-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0033_candidate_decisions"
down_revision: str | None = "0032_record_link_depends_on"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Add the decision columns to identity_candidates."""
    with op.batch_alter_table("identity_candidates", schema=None) as batch_op:
        batch_op.add_column(sa.Column("decided_by", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(
            sa.Column("assigned_conversation_id", sa.String(length=40), nullable=True)
        )


def downgrade() -> None:
    """Drop the decision columns."""
    with op.batch_alter_table("identity_candidates", schema=None) as batch_op:
        batch_op.drop_column("assigned_conversation_id")
        batch_op.drop_column("decided_at")
        batch_op.drop_column("decided_by")
