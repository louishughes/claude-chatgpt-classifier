"""Add the import ledger: batches, source snapshots and batch files (IMP-001).

Revision ID: 0003_import_ledger
Revises: 0002_jobs
Create Date: 2026-10-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0003_import_ledger"
down_revision: str | None = "0002_jobs"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create import_batches, source_snapshots and import_batch_files."""
    op.create_table(
        "import_batches",
        sa.Column("import_id", sa.String(length=32), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("account_namespace", sa.String(length=63), nullable=False),
        sa.Column("root_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("format_id", sa.String(length=40), nullable=False),
        sa.Column("versions_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tree_hash_before", sa.String(length=64), nullable=False),
        sa.Column("tree_hash_after", sa.String(length=64), nullable=True),
        sa.Column("counts_json", sa.Text(), nullable=True),
        sa.Column("warnings_json", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('running','succeeded','partial','failed','abandoned')",
            name=op.f("ck_import_batches_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["workspaces.workspace_id"],
            name=op.f("fk_import_batches_workspace_id_workspaces"),
        ),
        sa.PrimaryKeyConstraint("import_id", name=op.f("pk_import_batches")),
    )
    op.create_index(op.f("ix_import_batches_status"), "import_batches", ["status"], unique=False)
    op.create_table(
        "source_snapshots",
        sa.Column("snapshot_id", sa.String(length=40), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("storage_mode", sa.String(length=10), nullable=False),
        sa.Column("storage_ref", sa.Text(), nullable=False),
        sa.Column("first_import_id", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "storage_mode IN ('copy','reference')",
            name=op.f("ck_source_snapshots_storage_mode_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["first_import_id"],
            ["import_batches.import_id"],
            name=op.f("fk_source_snapshots_first_import_id_import_batches"),
        ),
        sa.PrimaryKeyConstraint("snapshot_id", name=op.f("pk_source_snapshots")),
        sa.UniqueConstraint("sha256", name=op.f("uq_source_snapshots_sha256")),
    )
    op.create_table(
        "import_batch_files",
        sa.Column("import_id", sa.String(length=32), nullable=False),
        sa.Column("relative_path", sa.Text(), nullable=False),
        sa.Column("snapshot_id", sa.String(length=40), nullable=False),
        sa.ForeignKeyConstraint(
            ["import_id"],
            ["import_batches.import_id"],
            name=op.f("fk_import_batch_files_import_id_import_batches"),
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["source_snapshots.snapshot_id"],
            name=op.f("fk_import_batch_files_snapshot_id_source_snapshots"),
        ),
        sa.PrimaryKeyConstraint("import_id", "relative_path", name=op.f("pk_import_batch_files")),
    )


def downgrade() -> None:
    """Drop the import ledger tables."""
    op.drop_table("import_batch_files")
    op.drop_table("source_snapshots")
    op.drop_index(op.f("ix_import_batches_status"), table_name="import_batches")
    op.drop_table("import_batches")
