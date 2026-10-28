"""Store knowledge records, their trust events and extraction runs (EXT-007, EXT-008).

Revision ID: 0019_knowledge_records
Revises: 0018_classifications
Create Date: 2026-10-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0019_knowledge_records"
down_revision: str | None = "0018_classifications"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create extraction_runs, knowledge_records and knowledge_record_events."""
    op.create_table(
        "extraction_runs",
        sa.Column("stage_key", sa.String(length=70), nullable=False),
        sa.Column("extractor", sa.String(length=40), nullable=False),
        sa.Column("segment_id", sa.String(length=40), nullable=False),
        sa.Column("state", sa.String(length=10), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error", sa.String(length=100), nullable=True),
        sa.Column("record_ids_json", sa.Text(), nullable=False),
        sa.Column("versions_json", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("stage_key", name=op.f("pk_extraction_runs")),
    )
    with op.batch_alter_table("extraction_runs", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_extraction_runs_segment_id"), ["segment_id"], unique=False
        )

    op.create_table(
        "knowledge_records",
        sa.Column("record_id", sa.String(length=40), nullable=False),
        sa.Column("stage_key", sa.String(length=70), nullable=False),
        sa.Column("record_type", sa.String(length=20), nullable=False),
        sa.Column("scope_id", sa.String(length=60), nullable=True),
        sa.Column("trust", sa.String(length=20), nullable=False),
        sa.Column("record_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("record_id", name=op.f("pk_knowledge_records")),
    )
    with op.batch_alter_table("knowledge_records", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_knowledge_records_record_type"), ["record_type"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_knowledge_records_scope_id"), ["scope_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_knowledge_records_stage_key"), ["stage_key"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_knowledge_records_trust"), ["trust"], unique=False)

    op.create_table(
        "knowledge_record_events",
        sa.Column("event_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("record_id", sa.String(length=40), nullable=False),
        sa.Column("from_trust", sa.String(length=20), nullable=True),
        sa.Column("to_trust", sa.String(length=20), nullable=False),
        sa.Column("actor", sa.String(length=100), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("problems_json", sa.Text(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["record_id"],
            ["knowledge_records.record_id"],
            name=op.f("fk_knowledge_record_events_record_id_knowledge_records"),
        ),
        sa.PrimaryKeyConstraint("event_id", name=op.f("pk_knowledge_record_events")),
    )
    with op.batch_alter_table("knowledge_record_events", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_knowledge_record_events_record_id"), ["record_id"], unique=False
        )


def downgrade() -> None:
    """Drop the three tables."""
    with op.batch_alter_table("knowledge_record_events", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_knowledge_record_events_record_id"))
    op.drop_table("knowledge_record_events")
    with op.batch_alter_table("knowledge_records", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_knowledge_records_trust"))
        batch_op.drop_index(batch_op.f("ix_knowledge_records_stage_key"))
        batch_op.drop_index(batch_op.f("ix_knowledge_records_scope_id"))
        batch_op.drop_index(batch_op.f("ix_knowledge_records_record_type"))
    op.drop_table("knowledge_records")
    with op.batch_alter_table("extraction_runs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_extraction_runs_segment_id"))
    op.drop_table("extraction_runs")
