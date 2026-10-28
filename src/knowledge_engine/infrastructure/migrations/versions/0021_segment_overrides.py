"""Add reviewer segment splits and merges, append-only (NRM-005).

Revision ID: 0021_segment_overrides
Revises: 0020_provider_failures
Create Date: 2026-10-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from knowledge_engine.segmentation.overrides import APPEND_ONLY_TRIGGERS

revision: str = "0021_segment_overrides"
down_revision: str | None = "0020_provider_failures"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create segment_overrides and its append-only triggers."""
    op.create_table(
        "segment_overrides",
        sa.Column("override_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("conversation_id", sa.String(length=40), nullable=False),
        sa.Column("native_message_id", sa.String(length=200), nullable=False),
        sa.Column("action", sa.String(length=8), nullable=False),
        sa.Column("reviewer", sa.String(length=100), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("action IN ('split','merge','clear')", name="action_valid"),
        sa.PrimaryKeyConstraint("override_id"),
    )
    with op.batch_alter_table("segment_overrides", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_segment_overrides_conversation_id"), ["conversation_id"], unique=False
        )
    for statement in APPEND_ONLY_TRIGGERS:
        op.execute(statement)


def downgrade() -> None:
    """Drop segment_overrides (its triggers go with it)."""
    with op.batch_alter_table("segment_overrides", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_segment_overrides_conversation_id"))
    op.drop_table("segment_overrides")
