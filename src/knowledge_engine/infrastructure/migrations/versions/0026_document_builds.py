"""Add append-only document builds and their dependencies (DOC-001).

Revision ID: 0026_document_builds
Revises: 0025_decision_events
Create Date: 2026-10-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from knowledge_engine.documents.dependencies import APPEND_ONLY_TRIGGERS
from knowledge_engine.infrastructure.dialects import run_triggers

revision: str = "0026_document_builds"
down_revision: str | None = "0025_decision_events"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create document_builds, document_dependencies and their triggers."""
    op.create_table(
        "document_builds",
        sa.Column("build_id", sa.String(length=40), nullable=False),
        sa.Column("document_id", sa.String(length=40), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=12), nullable=False),
        sa.Column("subject_id", sa.String(length=200), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("builder_version", sa.String(length=40), nullable=False),
        sa.Column("record_count", sa.Integer(), nullable=False),
        sa.Column("built_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("kind IN ('conversation','project','topic')", name="kind_valid"),
        sa.PrimaryKeyConstraint("build_id"),
    )
    with op.batch_alter_table("document_builds", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_document_builds_document_id"), ["document_id"], unique=False
        )
    op.create_table(
        "document_dependencies",
        sa.Column("build_id", sa.String(length=40), nullable=False),
        sa.Column("dep_kind", sa.String(length=10), nullable=False),
        sa.Column("dep_id", sa.String(length=40), nullable=False),
        sa.CheckConstraint("dep_kind IN ('record','revision')", name="dep_kind_valid"),
        sa.ForeignKeyConstraint(["build_id"], ["document_builds.build_id"]),
        sa.PrimaryKeyConstraint("build_id", "dep_kind", "dep_id"),
    )
    with op.batch_alter_table("document_dependencies", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_document_dependencies_dep_id"), ["dep_id"], unique=False
        )
    run_triggers(APPEND_ONLY_TRIGGERS)


def downgrade() -> None:
    """Drop both tables (their triggers go with them)."""
    with op.batch_alter_table("document_dependencies", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_document_dependencies_dep_id"))
    op.drop_table("document_dependencies")
    with op.batch_alter_table("document_builds", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_document_builds_document_id"))
    op.drop_table("document_builds")
