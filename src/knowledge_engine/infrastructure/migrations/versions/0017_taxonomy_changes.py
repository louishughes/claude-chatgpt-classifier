"""Record taxonomy version diffs and stale stage outputs (TAX-007).

Revision ID: 0017_taxonomy_changes
Revises: 0016_taxonomy_review
Create Date: 2026-10-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0017_taxonomy_changes"
down_revision: str | None = "0016_taxonomy_review"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create taxonomy_changes and stage_invalidations."""
    op.create_table(
        "stage_invalidations",
        sa.Column("invalidation_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("stage_key", sa.String(length=70), nullable=False),
        sa.Column("from_version", sa.String(length=40), nullable=False),
        sa.Column("to_version", sa.String(length=40), nullable=False),
        sa.Column("cited_ids_json", sa.Text(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("invalidation_id", name=op.f("pk_stage_invalidations")),
        sa.UniqueConstraint(
            "stage_key", "to_version", name=op.f("uq_stage_invalidations_stage_key_to_version")
        ),
    )
    with op.batch_alter_table("stage_invalidations", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_stage_invalidations_stage_key"), ["stage_key"], unique=False
        )

    op.create_table(
        "taxonomy_changes",
        sa.Column("from_version", sa.String(length=40), nullable=False),
        sa.Column("to_version", sa.String(length=40), nullable=False),
        sa.Column("added_json", sa.Text(), nullable=False),
        sa.Column("removed_json", sa.Text(), nullable=False),
        sa.Column("changed_json", sa.Text(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("from_version", "to_version", name=op.f("pk_taxonomy_changes")),
    )


def downgrade() -> None:
    """Drop both tables."""
    op.drop_table("taxonomy_changes")
    with op.batch_alter_table("stage_invalidations", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_stage_invalidations_stage_key"))
    op.drop_table("stage_invalidations")
