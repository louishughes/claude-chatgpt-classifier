"""Add identity candidates: conversations whose identity needs review (slice I4).

Revision ID: 0006_identity_candidates
Revises: 0005_revision_observations
Create Date: 2026-10-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0006_identity_candidates"
down_revision: str | None = "0005_revision_observations"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create identity_candidates."""
    op.create_table(
        "identity_candidates",
        sa.Column("candidate_id", sa.String(length=64), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("account_namespace", sa.String(length=63), nullable=False),
        sa.Column("reason", sa.String(length=30), nullable=False),
        sa.Column("native_conversation_id", sa.String(length=200), nullable=True),
        sa.Column("existing_conversation_id", sa.String(length=40), nullable=True),
        sa.Column("conversation_hash", sa.String(length=64), nullable=False),
        sa.Column("snapshot_id", sa.String(length=40), nullable=False),
        sa.Column("source_index", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("first_import_id", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "reason IN ('id_collision','missing_native_id')",
            name=op.f("ck_identity_candidates_reason_valid"),
        ),
        sa.CheckConstraint(
            "status IN ('review_required','accepted','rejected')",
            name=op.f("ck_identity_candidates_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["existing_conversation_id"],
            ["conversations.conversation_id"],
            name=op.f("fk_identity_candidates_existing_conversation_id_conversations"),
        ),
        sa.ForeignKeyConstraint(
            ["first_import_id"],
            ["import_batches.import_id"],
            name=op.f("fk_identity_candidates_first_import_id_import_batches"),
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["source_snapshots.snapshot_id"],
            name=op.f("fk_identity_candidates_snapshot_id_source_snapshots"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.workspace_id"],
            name=op.f("fk_identity_candidates_workspace_id_workspaces"),
        ),
        sa.PrimaryKeyConstraint("candidate_id", name=op.f("pk_identity_candidates")),
        sa.UniqueConstraint(
            "workspace_id",
            "account_namespace",
            "reason",
            "conversation_hash",
            name=op.f(
                "uq_identity_candidates_workspace_id_account_namespace_reason_conversation_hash"
            ),
        ),
    )


def downgrade() -> None:
    """Drop identity_candidates."""
    op.drop_table("identity_candidates")
