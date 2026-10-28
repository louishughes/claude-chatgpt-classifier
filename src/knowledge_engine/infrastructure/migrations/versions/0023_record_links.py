"""Add typed links between knowledge records and their append-only reviews (REC-002).

Revision ID: 0023_record_links
Revises: 0022_record_equivalences
Create Date: 2026-10-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from knowledge_engine.reconciliation.relations import APPEND_ONLY_TRIGGERS

revision: str = "0023_record_links"
down_revision: str | None = "0022_record_equivalences"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create record_links and record_link_reviews, with triggers."""
    op.create_table(
        "record_links",
        sa.Column("link_id", sa.String(length=40), nullable=False),
        sa.Column("from_record", sa.String(length=40), nullable=False),
        sa.Column("predicate", sa.String(length=14), nullable=False),
        sa.Column("to_record", sa.String(length=40), nullable=False),
        sa.Column("detector", sa.String(length=40), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=False),
        sa.Column("state", sa.String(length=10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("from_record <> to_record", name="not_self"),
        sa.CheckConstraint(
            "predicate IN ('creates','references','elaborates','same_project')",
            name="predicate_valid",
        ),
        sa.CheckConstraint("state IN ('candidate','accepted','rejected')", name="state_valid"),
        sa.ForeignKeyConstraint(["from_record"], ["knowledge_records.record_id"]),
        sa.ForeignKeyConstraint(["to_record"], ["knowledge_records.record_id"]),
        sa.PrimaryKeyConstraint("link_id"),
    )
    with op.batch_alter_table("record_links", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_record_links_from_record"), ["from_record"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_record_links_to_record"), ["to_record"], unique=False)
    op.create_table(
        "record_link_reviews",
        sa.Column("review_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("link_id", sa.String(length=40), nullable=False),
        sa.Column("from_state", sa.String(length=10), nullable=False),
        sa.Column("to_state", sa.String(length=10), nullable=False),
        sa.Column("reviewer", sa.String(length=100), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["link_id"], ["record_links.link_id"]),
        sa.PrimaryKeyConstraint("review_id"),
    )
    with op.batch_alter_table("record_link_reviews", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_record_link_reviews_link_id"), ["link_id"], unique=False
        )
    for statement in APPEND_ONLY_TRIGGERS:
        op.execute(statement)


def downgrade() -> None:
    """Drop both tables (the triggers go with the reviews table)."""
    with op.batch_alter_table("record_link_reviews", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_record_link_reviews_link_id"))
    op.drop_table("record_link_reviews")
    with op.batch_alter_table("record_links", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_record_links_to_record"))
        batch_op.drop_index(batch_op.f("ix_record_links_from_record"))
    op.drop_table("record_links")
