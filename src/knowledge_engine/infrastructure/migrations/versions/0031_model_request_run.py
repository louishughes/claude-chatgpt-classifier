"""Remember which run a waiting model request was written to (LEG-007).

Revision ID: 0031_model_request_run
Revises: 0030_taxonomy_refresh_packs
Create Date: 2026-10-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0031_model_request_run"
down_revision: str | None = "0030_taxonomy_refresh_packs"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Add run_id to model_requests (empty on older rows)."""
    with op.batch_alter_table("model_requests", schema=None) as batch_op:
        batch_op.add_column(sa.Column("run_id", sa.String(length=64), nullable=True))


def downgrade() -> None:
    """Drop the column."""
    with op.batch_alter_table("model_requests", schema=None) as batch_op:
        batch_op.drop_column("run_id")
