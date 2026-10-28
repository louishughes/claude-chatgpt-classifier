"""Add conversation relationships and their append-only review history (REL-002).

Revision ID: 0013_conversation_relationships
Revises: 0012_social_accounts
Create Date: 2026-10-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from knowledge_engine.infrastructure.dialects import run_triggers
from knowledge_engine.relationships.store import APPEND_ONLY_TRIGGERS

revision: str = "0013_conversation_relationships"
down_revision: str | None = "0012_social_accounts"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create conversation_relationships and relationship_reviews, with triggers."""
    op.create_table(
        "conversation_relationships",
        sa.Column("relationship_id", sa.String(length=40), nullable=False),
        sa.Column("from_conversation_id", sa.String(length=40), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("to_conversation_id", sa.String(length=40), nullable=False),
        sa.Column("evidence_class", sa.String(length=12), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("review_state", sa.String(length=12), nullable=False),
        sa.Column("detector", sa.String(length=40), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=False),
        sa.Column("first_import_id", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "evidence_class IN ('native','structural','lexical','semantic','human')",
            name=op.f("ck_conversation_relationships_evidence_valid"),
        ),
        sa.CheckConstraint(
            "kind IN ('continues','forked_from','quotes','references','related_to','same_project')",
            name=op.f("ck_conversation_relationships_kind_valid"),
        ),
        sa.CheckConstraint(
            "review_state IN ('candidate','accepted','rejected','superseded')",
            name=op.f("ck_conversation_relationships_review_state_valid"),
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name=op.f("ck_conversation_relationships_confidence_range"),
        ),
        sa.CheckConstraint(
            "from_conversation_id != to_conversation_id",
            name=op.f("ck_conversation_relationships_not_self"),
        ),
        sa.ForeignKeyConstraint(
            ["first_import_id"],
            ["import_batches.import_id"],
            name=op.f("fk_conversation_relationships_first_import_id_import_batches"),
        ),
        sa.ForeignKeyConstraint(
            ["from_conversation_id"],
            ["conversations.conversation_id"],
            name=op.f("fk_conversation_relationships_from_conversation_id_conversations"),
        ),
        sa.ForeignKeyConstraint(
            ["to_conversation_id"],
            ["conversations.conversation_id"],
            name=op.f("fk_conversation_relationships_to_conversation_id_conversations"),
        ),
        sa.PrimaryKeyConstraint("relationship_id", name=op.f("pk_conversation_relationships")),
        sa.UniqueConstraint(
            "from_conversation_id",
            "kind",
            "to_conversation_id",
            "detector",
            name=op.f(
                "uq_conversation_relationships_from_conversation_id_kind_to_conversation_id_detector"
            ),
        ),
    )
    with op.batch_alter_table("conversation_relationships", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_conversation_relationships_from_conversation_id"),
            ["from_conversation_id"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_conversation_relationships_to_conversation_id"),
            ["to_conversation_id"],
            unique=False,
        )

    op.create_table(
        "relationship_reviews",
        sa.Column("review_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("relationship_id", sa.String(length=40), nullable=False),
        sa.Column("action", sa.String(length=12), nullable=False),
        sa.Column("from_state", sa.String(length=12), nullable=False),
        sa.Column("to_state", sa.String(length=12), nullable=False),
        sa.Column("reviewer", sa.String(length=100), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "action IN ('accept','reject','supersede')",
            name=op.f("ck_relationship_reviews_action_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["relationship_id"],
            ["conversation_relationships.relationship_id"],
            name=op.f("fk_relationship_reviews_relationship_id_conversation_relationships"),
        ),
        sa.PrimaryKeyConstraint("review_id", name=op.f("pk_relationship_reviews")),
    )
    with op.batch_alter_table("relationship_reviews", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_relationship_reviews_relationship_id"), ["relationship_id"], unique=False
        )
    run_triggers(APPEND_ONLY_TRIGGERS)


def downgrade() -> None:
    """Drop both tables (the triggers go with relationship_reviews)."""
    with op.batch_alter_table("relationship_reviews", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_relationship_reviews_relationship_id"))
    op.drop_table("relationship_reviews")
    with op.batch_alter_table("conversation_relationships", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_conversation_relationships_to_conversation_id"))
        batch_op.drop_index(batch_op.f("ix_conversation_relationships_from_conversation_id"))
    op.drop_table("conversation_relationships")
