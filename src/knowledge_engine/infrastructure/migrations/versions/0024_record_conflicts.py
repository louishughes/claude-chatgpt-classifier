"""Add record conflicts and their append-only reviews (REC-003).

Revision ID: 0024_record_conflicts
Revises: 0023_record_links
Create Date: 2026-10-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from knowledge_engine.reconciliation.conflicts import APPEND_ONLY_TRIGGERS

revision: str = "0024_record_conflicts"
down_revision: str | None = "0023_record_links"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create record_conflicts and record_conflict_reviews, with triggers."""
    op.create_table(
        "record_conflicts",
        sa.Column("conflict_id", sa.String(length=40), nullable=False),
        sa.Column("record_a", sa.String(length=40), nullable=False),
        sa.Column("record_b", sa.String(length=40), nullable=False),
        sa.Column("kinds_json", sa.Text(), nullable=False),
        sa.Column("scope_json", sa.Text(), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=False),
        sa.Column("detector", sa.String(length=40), nullable=False),
        sa.Column("state", sa.String(length=10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("record_a < record_b", name="pair_ordered"),
        sa.CheckConstraint("state IN ('unresolved','dismissed','resolved')", name="state_valid"),
        sa.ForeignKeyConstraint(["record_a"], ["knowledge_records.record_id"]),
        sa.ForeignKeyConstraint(["record_b"], ["knowledge_records.record_id"]),
        sa.PrimaryKeyConstraint("conflict_id"),
    )
    with op.batch_alter_table("record_conflicts", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_record_conflicts_record_a"), ["record_a"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_record_conflicts_record_b"), ["record_b"], unique=False
        )
    op.create_table(
        "record_conflict_reviews",
        sa.Column("review_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("conflict_id", sa.String(length=40), nullable=False),
        sa.Column("from_state", sa.String(length=10), nullable=False),
        sa.Column("to_state", sa.String(length=10), nullable=False),
        sa.Column("reviewer", sa.String(length=100), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["conflict_id"], ["record_conflicts.conflict_id"]),
        sa.PrimaryKeyConstraint("review_id"),
    )
    with op.batch_alter_table("record_conflict_reviews", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_record_conflict_reviews_conflict_id"), ["conflict_id"], unique=False
        )
    for statement in APPEND_ONLY_TRIGGERS:
        op.execute(statement)


def downgrade() -> None:
    """Drop both tables (the triggers go with the reviews table)."""
    with op.batch_alter_table("record_conflict_reviews", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_record_conflict_reviews_conflict_id"))
    op.drop_table("record_conflict_reviews")
    with op.batch_alter_table("record_conflicts", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_record_conflicts_record_b"))
        batch_op.drop_index(batch_op.f("ix_record_conflicts_record_a"))
    op.drop_table("record_conflicts")
