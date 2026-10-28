"""Count provider failures apart from model errors (LEG-003).

Revision ID: 0020_provider_failures
Revises: 0019_knowledge_records
Create Date: 2026-10-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0020_provider_failures"
down_revision: str | None = "0019_knowledge_records"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Add transient_failures and last_transient to model_requests."""
    with op.batch_alter_table("model_requests", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("transient_failures", sa.Integer(), server_default="0", nullable=False)
        )
        batch_op.add_column(sa.Column("last_transient", sa.String(length=40), nullable=True))


def downgrade() -> None:
    """Drop the two columns."""
    with op.batch_alter_table("model_requests", schema=None) as batch_op:
        batch_op.drop_column("last_transient")
        batch_op.drop_column("transient_failures")
