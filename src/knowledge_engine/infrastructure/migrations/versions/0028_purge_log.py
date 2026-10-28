"""Add the purge audit log and tombstones (OPS-004).

Revision ID: 0028_purge_log
Revises: 0027_override_anchors
Create Date: 2026-10-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from knowledge_engine.infrastructure.dialects import run_triggers
from knowledge_engine.retention.tombstones import PURGE_LOG_TRIGGERS

revision: str = "0028_purge_log"
down_revision: str | None = "0027_override_anchors"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create purge_events (no deletes) and purge_tombstones."""
    op.create_table(
        "purge_events",
        sa.Column("purge_id", sa.String(length=40), nullable=False),
        sa.Column("actor", sa.String(length=80), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("plan_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("counts_json", sa.Text(), nullable=False),
        sa.Column("verification_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("purge_id"),
    )
    op.create_table(
        "purge_tombstones",
        sa.Column("tombstone_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("key_sha256", sa.String(length=64), nullable=False),
        sa.Column("purge_id", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("tombstone_id"),
        sa.UniqueConstraint("kind", "key_sha256", name="uq_purge_tombstone"),
    )
    with op.batch_alter_table("purge_tombstones", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_purge_tombstones_purge_id"), ["purge_id"], unique=False
        )
    run_triggers(PURGE_LOG_TRIGGERS)


def downgrade() -> None:
    """Drop both tables (the trigger goes with its table)."""
    with op.batch_alter_table("purge_tombstones", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_purge_tombstones_purge_id"))
    op.drop_table("purge_tombstones")
    op.drop_table("purge_events")
