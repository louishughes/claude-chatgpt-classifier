"""Add record equivalence proposals and their append-only reviews (REC-001).

Revision ID: 0022_record_equivalences
Revises: 0021_segment_overrides
Create Date: 2026-10-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from knowledge_engine.infrastructure.dialects import run_triggers
from knowledge_engine.reconciliation.equivalence import APPEND_ONLY_TRIGGERS

revision: str = "0022_record_equivalences"
down_revision: str | None = "0021_segment_overrides"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create record_equivalences and record_equivalence_reviews, with triggers."""
    op.create_table(
        "record_equivalences",
        sa.Column("pair_id", sa.String(length=40), nullable=False),
        sa.Column("record_a", sa.String(length=40), nullable=False),
        sa.Column("record_b", sa.String(length=40), nullable=False),
        sa.Column("basis", sa.String(length=10), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("differences_json", sa.Text(), nullable=False),
        sa.Column("detector", sa.String(length=40), nullable=False),
        sa.Column("state", sa.String(length=10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("basis IN ('exact','similar','near_miss')", name="basis_valid"),
        sa.CheckConstraint("record_a < record_b", name="pair_ordered"),
        sa.CheckConstraint("state IN ('proposed','confirmed','rejected')", name="state_valid"),
        sa.ForeignKeyConstraint(["record_a"], ["knowledge_records.record_id"]),
        sa.ForeignKeyConstraint(["record_b"], ["knowledge_records.record_id"]),
        sa.PrimaryKeyConstraint("pair_id"),
    )
    with op.batch_alter_table("record_equivalences", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_record_equivalences_record_a"), ["record_a"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_record_equivalences_record_b"), ["record_b"], unique=False
        )
    op.create_table(
        "record_equivalence_reviews",
        sa.Column("review_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("pair_id", sa.String(length=40), nullable=False),
        sa.Column("from_state", sa.String(length=10), nullable=False),
        sa.Column("to_state", sa.String(length=10), nullable=False),
        sa.Column("reviewer", sa.String(length=100), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["pair_id"], ["record_equivalences.pair_id"]),
        sa.PrimaryKeyConstraint("review_id"),
    )
    with op.batch_alter_table("record_equivalence_reviews", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_record_equivalence_reviews_pair_id"), ["pair_id"], unique=False
        )
    run_triggers(APPEND_ONLY_TRIGGERS)


def downgrade() -> None:
    """Drop both tables (the triggers go with the reviews table)."""
    with op.batch_alter_table("record_equivalence_reviews", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_record_equivalence_reviews_pair_id"))
    op.drop_table("record_equivalence_reviews")
    with op.batch_alter_table("record_equivalences", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_record_equivalences_record_b"))
        batch_op.drop_index(batch_op.f("ix_record_equivalences_record_a"))
    op.drop_table("record_equivalences")
