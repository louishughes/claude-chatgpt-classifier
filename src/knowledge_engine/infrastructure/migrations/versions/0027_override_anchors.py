"""Add append-only override anchors (IMP-006).

Revision ID: 0027_override_anchors
Revises: 0026_document_builds
Create Date: 2026-10-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from knowledge_engine.importer.corrections import APPEND_ONLY_TRIGGERS

revision: str = "0027_override_anchors"
down_revision: str | None = "0026_document_builds"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create override_anchors and its triggers."""
    op.create_table(
        "override_anchors",
        sa.Column("anchor_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("override_ref", sa.String(length=40), nullable=False),
        sa.Column("conversation_id", sa.String(length=40), nullable=False),
        sa.Column("node_key", sa.String(length=40), nullable=False),
        sa.Column("revision_id", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("anchor_id"),
    )
    with op.batch_alter_table("override_anchors", schema=None) as batch_op:
        for column in ("conversation_id", "node_key", "override_ref"):
            batch_op.create_index(
                batch_op.f(f"ix_override_anchors_{column}"), [column], unique=False
            )
    for statement in APPEND_ONLY_TRIGGERS:
        op.execute(statement)


def downgrade() -> None:
    """Drop override_anchors (its triggers go with it)."""
    with op.batch_alter_table("override_anchors", schema=None) as batch_op:
        for column in ("override_ref", "node_key", "conversation_id"):
            batch_op.drop_index(batch_op.f(f"ix_override_anchors_{column}"))
    op.drop_table("override_anchors")
