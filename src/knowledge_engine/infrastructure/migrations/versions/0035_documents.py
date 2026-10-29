"""Store imported Markdown and text notes: documents, revisions, blocks, links (ING-012).

Revision ID: 0035_documents
Revises: 0034_account_reviews
Create Date: 2026-10-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0035_documents"
down_revision: str | None = "0034_account_reviews"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create the four document tables."""
    op.create_table(
        "source_documents",
        sa.Column("document_id", sa.String(length=40), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("path_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("format", sa.String(length=10), nullable=False),
        sa.Column("current_revision_id", sa.String(length=40), nullable=False),
        sa.Column("first_import_id", sa.String(length=32), nullable=False),
        sa.Column("last_import_id", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["first_import_id"],
            ["import_batches.import_id"],
            name=op.f("fk_source_documents_first_import_id_import_batches"),
        ),
        sa.ForeignKeyConstraint(
            ["last_import_id"],
            ["import_batches.import_id"],
            name=op.f("fk_source_documents_last_import_id_import_batches"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.workspace_id"],
            name=op.f("fk_source_documents_workspace_id_workspaces"),
        ),
        sa.PrimaryKeyConstraint("document_id", name=op.f("pk_source_documents")),
        sa.UniqueConstraint(
            "workspace_id",
            "path_fingerprint",
            name=op.f("uq_source_documents_workspace_id_path_fingerprint"),
        ),
    )
    op.create_table(
        "document_revisions",
        sa.Column("revision_id", sa.String(length=40), nullable=False),
        sa.Column("document_id", sa.String(length=40), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("snapshot_id", sa.String(length=40), nullable=False),
        sa.Column("encoding", sa.String(length=20), nullable=True),
        sa.Column("parser", sa.String(length=30), nullable=False),
        sa.Column("warnings_json", sa.Text(), nullable=False),
        sa.Column("first_import_id", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["source_documents.document_id"],
            name=op.f("fk_document_revisions_document_id_source_documents"),
        ),
        sa.ForeignKeyConstraint(
            ["first_import_id"],
            ["import_batches.import_id"],
            name=op.f("fk_document_revisions_first_import_id_import_batches"),
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["source_snapshots.snapshot_id"],
            name=op.f("fk_document_revisions_snapshot_id_source_snapshots"),
        ),
        sa.PrimaryKeyConstraint("revision_id", name=op.f("pk_document_revisions")),
        sa.UniqueConstraint(
            "document_id", "sha256", name=op.f("uq_document_revisions_document_id_sha256")
        ),
    )
    with op.batch_alter_table("document_revisions", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_document_revisions_document_id"), ["document_id"], unique=False
        )
    op.create_table(
        "document_blocks",
        sa.Column("block_id", sa.String(length=40), nullable=False),
        sa.Column("revision_id", sa.String(length=40), nullable=False),
        sa.Column("block_index", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=12), nullable=False),
        sa.Column("start", sa.Integer(), nullable=False),
        sa.Column("end", sa.Integer(), nullable=False),
        sa.Column("line_start", sa.Integer(), nullable=True),
        sa.Column("line_end", sa.Integer(), nullable=True),
        sa.Column("locator", sa.String(length=40), nullable=False),
        sa.Column("heading_path_json", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["revision_id"],
            ["document_revisions.revision_id"],
            name=op.f("fk_document_blocks_revision_id_document_revisions"),
        ),
        sa.PrimaryKeyConstraint("block_id", name=op.f("pk_document_blocks")),
        sa.UniqueConstraint(
            "revision_id", "block_index", name=op.f("uq_document_blocks_revision_id_block_index")
        ),
    )
    with op.batch_alter_table("document_blocks", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_document_blocks_revision_id"), ["revision_id"], unique=False
        )
    op.create_table(
        "document_links",
        sa.Column("link_id", sa.String(length=40), nullable=False),
        sa.Column("revision_id", sa.String(length=40), nullable=False),
        sa.Column("block_id", sa.String(length=40), nullable=False),
        sa.Column("target_id", sa.String(length=40), nullable=False),
        sa.Column("start", sa.Integer(), nullable=False),
        sa.Column("end", sa.Integer(), nullable=False),
        sa.Column("original_text", sa.Text(), nullable=False),
        sa.Column("video_id", sa.String(length=11), nullable=True),
        sa.Column("t_seconds", sa.Integer(), nullable=True),
        sa.Column("first_import_id", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(
            ["block_id"],
            ["document_blocks.block_id"],
            name=op.f("fk_document_links_block_id_document_blocks"),
        ),
        sa.ForeignKeyConstraint(
            ["first_import_id"],
            ["import_batches.import_id"],
            name=op.f("fk_document_links_first_import_id_import_batches"),
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"],
            ["document_revisions.revision_id"],
            name=op.f("fk_document_links_revision_id_document_revisions"),
        ),
        sa.ForeignKeyConstraint(
            ["target_id"],
            ["link_targets.target_id"],
            name=op.f("fk_document_links_target_id_link_targets"),
        ),
        sa.ForeignKeyConstraint(
            ["video_id"],
            ["youtube_videos.video_id"],
            name=op.f("fk_document_links_video_id_youtube_videos"),
        ),
        sa.PrimaryKeyConstraint("link_id", name=op.f("pk_document_links")),
    )
    with op.batch_alter_table("document_links", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_document_links_revision_id"), ["revision_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_document_links_target_id"), ["target_id"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_document_links_video_id"), ["video_id"], unique=False)


def downgrade() -> None:
    """Drop the document tables, children first."""
    for table in ("document_links", "document_blocks", "document_revisions", "source_documents"):
        op.drop_table(table)
