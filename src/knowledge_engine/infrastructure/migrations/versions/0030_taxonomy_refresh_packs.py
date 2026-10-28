"""Remember each taxonomy refresh pack (NOTE-014).

Revision ID: 0030_taxonomy_refresh_packs
Revises: 0029_accounts
Create Date: 2026-10-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0030_taxonomy_refresh_packs"
down_revision: str | None = "0029_accounts"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create taxonomy_refresh_packs (no chat text: a fingerprint, counts and import IDs)."""
    op.create_table(
        "taxonomy_refresh_packs",
        sa.Column("pack_sha256", sa.String(length=64), nullable=False),
        sa.Column("from_version", sa.String(length=40), nullable=False),
        sa.Column("queued", sa.Integer(), nullable=False),
        sa.Column("sampled", sa.Integer(), nullable=False),
        sa.Column("imports_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("pack_sha256", name=op.f("pk_taxonomy_refresh_packs")),
    )


def downgrade() -> None:
    """Drop the table."""
    op.drop_table("taxonomy_refresh_packs")
