"""Add the append-only decision event timeline (REC-004).

Revision ID: 0025_decision_events
Revises: 0024_record_conflicts
Create Date: 2026-10-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from knowledge_engine.infrastructure.dialects import run_triggers
from knowledge_engine.reconciliation.timeline import APPEND_ONLY_TRIGGERS

revision: str = "0025_decision_events"
down_revision: str | None = "0024_record_conflicts"
branch_labels: str | None = None
depends_on: str | None = None

PREDICATES = (
    "'proposes','accepts','rejects','clarifies','revises','supersedes','contradicts',"
    "'related_to','revokes'"
)


def upgrade() -> None:
    """Create decision_events and its triggers."""
    op.create_table(
        "decision_events",
        sa.Column("event_id", sa.String(length=40), nullable=False),
        sa.Column("predicate", sa.String(length=12), nullable=False),
        sa.Column("from_record", sa.String(length=40), nullable=True),
        sa.Column("to_record", sa.String(length=40), nullable=True),
        sa.Column("revokes_event", sa.String(length=40), nullable=True),
        sa.Column("happened_at", sa.Float(), nullable=True),
        sa.Column("actor", sa.String(length=100), nullable=False),
        sa.Column("evidence_json", sa.Text(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(f"predicate IN ({PREDICATES})", name="predicate_valid"),
        sa.ForeignKeyConstraint(["from_record"], ["knowledge_records.record_id"]),
        sa.ForeignKeyConstraint(["revokes_event"], ["decision_events.event_id"]),
        sa.ForeignKeyConstraint(["to_record"], ["knowledge_records.record_id"]),
        sa.PrimaryKeyConstraint("event_id"),
    )
    with op.batch_alter_table("decision_events", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_decision_events_from_record"), ["from_record"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_decision_events_to_record"), ["to_record"], unique=False
        )
    run_triggers(APPEND_ONLY_TRIGGERS)


def downgrade() -> None:
    """Drop decision_events (its triggers go with it)."""
    with op.batch_alter_table("decision_events", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_decision_events_to_record"))
        batch_op.drop_index(batch_op.f("ix_decision_events_from_record"))
    op.drop_table("decision_events")
