"""Add evidence to asset occurrences: why each pointer resolved as it did (slice M2).

Revision ID: 0008_occurrence_evidence
Revises: 0007_media
Create Date: 2026-10-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0008_occurrence_evidence"
down_revision: str | None = "0007_media"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Add asset_occurrences.evidence_json."""
    with op.batch_alter_table("asset_occurrences", schema=None) as batch_op:
        batch_op.add_column(sa.Column("evidence_json", sa.Text(), nullable=True))


def downgrade() -> None:
    """Drop asset_occurrences.evidence_json."""
    with op.batch_alter_table("asset_occurrences", schema=None) as batch_op:
        batch_op.drop_column("evidence_json")
