"""Add the append-only history of social account reviews (SOC-004).

Revision ID: 0034_account_reviews
Revises: 0033_candidate_decisions
Create Date: 2026-10-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from knowledge_engine.infrastructure.dialects import run_triggers
from knowledge_engine.links.social_store import APPEND_ONLY_TRIGGERS

revision: str = "0034_account_reviews"
down_revision: str | None = "0033_candidate_decisions"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create account_reviews and its append-only triggers."""
    op.create_table(
        "account_reviews",
        sa.Column("review_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("account_id", sa.String(length=40), nullable=False),
        sa.Column("mention_id", sa.String(length=40), nullable=True),
        sa.Column("action", sa.String(length=10), nullable=False),
        sa.Column("from_state", sa.String(length=12), nullable=False),
        sa.Column("to_state", sa.String(length=12), nullable=False),
        sa.Column("reviewer", sa.String(length=100), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "action IN ('confirm','reject','link')", name=op.f("ck_account_reviews_action_valid")
        ),
        sa.CheckConstraint(
            "action != 'link' OR mention_id IS NOT NULL",
            name=op.f("ck_account_reviews_link_has_mention"),
        ),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["social_accounts.account_id"],
            name=op.f("fk_account_reviews_account_id_social_accounts"),
        ),
        sa.ForeignKeyConstraint(
            ["mention_id"],
            ["account_mentions.mention_id"],
            name=op.f("fk_account_reviews_mention_id_account_mentions"),
        ),
        sa.PrimaryKeyConstraint("review_id", name=op.f("pk_account_reviews")),
    )
    with op.batch_alter_table("account_reviews", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_account_reviews_account_id"), ["account_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_account_reviews_mention_id"), ["mention_id"], unique=False
        )
    run_triggers(APPEND_ONLY_TRIGGERS)


def downgrade() -> None:
    """Drop account_reviews (its triggers go with it)."""
    with op.batch_alter_table("account_reviews", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_account_reviews_mention_id"))
        batch_op.drop_index(batch_op.f("ix_account_reviews_account_id"))
    op.drop_table("account_reviews")
