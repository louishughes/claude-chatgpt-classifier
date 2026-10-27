"""Add media: blobs, assets, occurrences and derived artefacts (slice M1).

Revision ID: 0007_media
Revises: 0006_identity_candidates
Create Date: 2026-10-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0007_media"
down_revision: str | None = "0006_identity_candidates"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create media_blobs, derived_media_artifacts, media_assets and asset_occurrences."""
    op.create_table(
        "media_blobs",
        sa.Column("blob_sha256", sa.String(length=64), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("storage_mode", sa.String(length=10), nullable=False),
        sa.Column("location", sa.Text(), nullable=True),
        sa.Column("media_type", sa.String(length=60), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("first_import_id", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "storage_mode IN ('copy','reference')", name=op.f("ck_media_blobs_storage_mode_valid")
        ),
        sa.ForeignKeyConstraint(
            ["first_import_id"],
            ["import_batches.import_id"],
            name=op.f("fk_media_blobs_first_import_id_import_batches"),
        ),
        sa.PrimaryKeyConstraint("blob_sha256", name=op.f("pk_media_blobs")),
    )
    op.create_table(
        "derived_media_artifacts",
        sa.Column("artifact_id", sa.String(length=64), nullable=False),
        sa.Column("blob_sha256", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("generator_version", sa.String(length=40), nullable=False),
        sa.Column("location", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "kind IN ('thumbnail','header_metadata')",
            name=op.f("ck_derived_media_artifacts_kind_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["blob_sha256"],
            ["media_blobs.blob_sha256"],
            name=op.f("fk_derived_media_artifacts_blob_sha256_media_blobs"),
        ),
        sa.PrimaryKeyConstraint("artifact_id", name=op.f("pk_derived_media_artifacts")),
        sa.UniqueConstraint(
            "blob_sha256",
            "kind",
            "generator_version",
            name=op.f("uq_derived_media_artifacts_blob_sha256_kind_generator_version"),
        ),
    )
    with op.batch_alter_table("derived_media_artifacts", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_derived_media_artifacts_blob_sha256"), ["blob_sha256"], unique=False
        )

    op.create_table(
        "media_assets",
        sa.Column("asset_id", sa.String(length=40), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("source_system", sa.String(length=20), nullable=False),
        sa.Column("native_file_id", sa.String(length=200), nullable=True),
        sa.Column("blob_sha256", sa.String(length=64), nullable=True),
        sa.Column("first_import_id", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(
            ["blob_sha256"],
            ["media_blobs.blob_sha256"],
            name=op.f("fk_media_assets_blob_sha256_media_blobs"),
        ),
        sa.ForeignKeyConstraint(
            ["first_import_id"],
            ["import_batches.import_id"],
            name=op.f("fk_media_assets_first_import_id_import_batches"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.workspace_id"],
            name=op.f("fk_media_assets_workspace_id_workspaces"),
        ),
        sa.PrimaryKeyConstraint("asset_id", name=op.f("pk_media_assets")),
        sa.UniqueConstraint(
            "workspace_id",
            "source_system",
            "native_file_id",
            name=op.f("uq_media_assets_workspace_id_source_system_native_file_id"),
        ),
    )
    op.create_table(
        "asset_occurrences",
        sa.Column("occurrence_id", sa.String(length=40), nullable=False),
        sa.Column("revision_id", sa.String(length=40), nullable=False),
        sa.Column("part_index", sa.Integer(), nullable=False),
        sa.Column("pointer", sa.Text(), nullable=False),
        sa.Column("content_type", sa.String(length=60), nullable=True),
        sa.Column("asset_id", sa.String(length=40), nullable=True),
        sa.Column("availability", sa.String(length=12), nullable=False),
        sa.Column("candidate_count", sa.Integer(), nullable=False),
        sa.Column("declared_size", sa.Integer(), nullable=True),
        sa.Column("declared_width", sa.Integer(), nullable=True),
        sa.Column("declared_height", sa.Integer(), nullable=True),
        sa.Column("first_import_id", sa.String(length=32), nullable=False),
        sa.Column("resolved_import_id", sa.String(length=32), nullable=False),
        sa.CheckConstraint(
            "availability IN ('available','missing','unresolved','ambiguous','unsupported')",
            name=op.f("ck_asset_occurrences_availability_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["media_assets.asset_id"],
            name=op.f("fk_asset_occurrences_asset_id_media_assets"),
        ),
        sa.ForeignKeyConstraint(
            ["first_import_id"],
            ["import_batches.import_id"],
            name=op.f("fk_asset_occurrences_first_import_id_import_batches"),
        ),
        sa.ForeignKeyConstraint(
            ["resolved_import_id"],
            ["import_batches.import_id"],
            name=op.f("fk_asset_occurrences_resolved_import_id_import_batches"),
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"],
            ["message_revisions.revision_id"],
            name=op.f("fk_asset_occurrences_revision_id_message_revisions"),
        ),
        sa.PrimaryKeyConstraint("occurrence_id", name=op.f("pk_asset_occurrences")),
        sa.UniqueConstraint(
            "revision_id",
            "part_index",
            "pointer",
            name=op.f("uq_asset_occurrences_revision_id_part_index_pointer"),
        ),
    )
    with op.batch_alter_table("asset_occurrences", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_asset_occurrences_asset_id"), ["asset_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_asset_occurrences_revision_id"), ["revision_id"], unique=False
        )


def downgrade() -> None:
    """Drop the media tables."""
    with op.batch_alter_table("asset_occurrences", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_asset_occurrences_revision_id"))
        batch_op.drop_index(batch_op.f("ix_asset_occurrences_asset_id"))
    op.drop_table("asset_occurrences")
    op.drop_table("media_assets")
    with op.batch_alter_table("derived_media_artifacts", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_derived_media_artifacts_blob_sha256"))
    op.drop_table("derived_media_artifacts")
    op.drop_table("media_blobs")
