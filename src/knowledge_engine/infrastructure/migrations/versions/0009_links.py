"""Add the link registry: link_targets and link_occurrences (LNK-001).

Revision ID: 0009_links
Revises: 0008_occurrence_evidence
Create Date: 2026-10-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0009_links"
down_revision: str | None = "0008_occurrence_evidence"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create link_targets and link_occurrences."""
    op.create_table(
        "link_targets",
        sa.Column("target_id", sa.String(length=40), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("host", sa.String(length=255), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("first_import_id", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["first_import_id"],
            ["import_batches.import_id"],
            name=op.f("fk_link_targets_first_import_id_import_batches"),
        ),
        sa.PrimaryKeyConstraint("target_id", name=op.f("pk_link_targets")),
        sa.UniqueConstraint("canonical_url", name=op.f("uq_link_targets_canonical_url")),
    )
    with op.batch_alter_table("link_targets", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_link_targets_host"), ["host"], unique=False)

    op.create_table(
        "link_occurrences",
        sa.Column("occurrence_id", sa.String(length=40), nullable=False),
        sa.Column("revision_id", sa.String(length=40), nullable=False),
        sa.Column("conversation_id", sa.String(length=40), nullable=False),
        sa.Column("target_id", sa.String(length=40), nullable=False),
        sa.Column("origin", sa.String(length=20), nullable=False),
        sa.Column("start", sa.Integer(), nullable=False),
        sa.Column("end", sa.Integer(), nullable=False),
        sa.Column("original_text", sa.Text(), nullable=False),
        sa.Column("actor", sa.String(length=20), nullable=True),
        sa.Column("first_import_id", sa.String(length=32), nullable=False),
        sa.CheckConstraint(
            "origin IN ('message_text','citation_metadata')",
            name=op.f("ck_link_occurrences_origin_valid"),
        ),
        sa.CheckConstraint(
            'start >= 0 AND "end" > start', name=op.f("ck_link_occurrences_span_valid")
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversations.conversation_id"],
            name=op.f("fk_link_occurrences_conversation_id_conversations"),
        ),
        sa.ForeignKeyConstraint(
            ["first_import_id"],
            ["import_batches.import_id"],
            name=op.f("fk_link_occurrences_first_import_id_import_batches"),
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"],
            ["message_revisions.revision_id"],
            name=op.f("fk_link_occurrences_revision_id_message_revisions"),
        ),
        sa.ForeignKeyConstraint(
            ["target_id"],
            ["link_targets.target_id"],
            name=op.f("fk_link_occurrences_target_id_link_targets"),
        ),
        sa.PrimaryKeyConstraint("occurrence_id", name=op.f("pk_link_occurrences")),
        sa.UniqueConstraint(
            "revision_id",
            "start",
            "end",
            "origin",
            name=op.f("uq_link_occurrences_revision_id_start_end_origin"),
        ),
    )
    with op.batch_alter_table("link_occurrences", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_link_occurrences_conversation_id"), ["conversation_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_link_occurrences_revision_id"), ["revision_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_link_occurrences_target_id"), ["target_id"], unique=False
        )


def downgrade() -> None:
    """Drop link_occurrences, then link_targets."""
    op.drop_table("link_occurrences")
    op.drop_table("link_targets")
