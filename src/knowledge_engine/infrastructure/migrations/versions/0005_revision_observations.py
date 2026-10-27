"""Add revision observations: each raw form a message was exported in (slice I3).

Revision ID: 0005_revision_observations
Revises: 0004_conversations
Create Date: 2026-10-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0005_revision_observations"
down_revision: str | None = "0004_conversations"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create revision_observations."""
    op.create_table(
        "revision_observations",
        sa.Column("observation_id", sa.String(length=64), nullable=False),
        sa.Column("revision_id", sa.String(length=40), nullable=False),
        sa.Column("raw_payload_hash", sa.String(length=64), nullable=False),
        sa.Column("first_snapshot_id", sa.String(length=40), nullable=False),
        sa.Column("first_import_id", sa.String(length=32), nullable=False),
        sa.ForeignKeyConstraint(
            ["first_import_id"],
            ["import_batches.import_id"],
            name=op.f("fk_revision_observations_first_import_id_import_batches"),
        ),
        sa.ForeignKeyConstraint(
            ["first_snapshot_id"],
            ["source_snapshots.snapshot_id"],
            name=op.f("fk_revision_observations_first_snapshot_id_source_snapshots"),
        ),
        sa.ForeignKeyConstraint(
            ["revision_id"],
            ["message_revisions.revision_id"],
            name=op.f("fk_revision_observations_revision_id_message_revisions"),
        ),
        sa.PrimaryKeyConstraint("observation_id", name=op.f("pk_revision_observations")),
        sa.UniqueConstraint(
            "revision_id",
            "raw_payload_hash",
            name=op.f("uq_revision_observations_revision_id_raw_payload_hash"),
        ),
    )
    with op.batch_alter_table("revision_observations", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_revision_observations_revision_id"), ["revision_id"], unique=False
        )


def downgrade() -> None:
    """Drop revision_observations."""
    with op.batch_alter_table("revision_observations", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_revision_observations_revision_id"))

    op.drop_table("revision_observations")
