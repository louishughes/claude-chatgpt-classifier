"""Add the model request ledger and validated model outputs (FND-007/FND-009).

Revision ID: 0014_model_ledger
Revises: 0013_conversation_relationships
Create Date: 2026-10-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0014_model_ledger"
down_revision: str | None = "0013_conversation_relationships"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create model_requests and model_outputs."""
    op.create_table(
        "model_requests",
        sa.Column("stage_key", sa.String(length=70), nullable=False),
        sa.Column("stage_id", sa.String(length=100), nullable=False),
        sa.Column("provider_id", sa.String(length=40), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("waiting_id", sa.String(length=70), nullable=False),
        sa.Column("batch_ids_json", sa.Text(), nullable=False),
        sa.Column("characters", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('pending','done','review_required')",
            name=op.f("ck_model_requests_state_valid"),
        ),
        sa.CheckConstraint("attempts IN (1, 2)", name=op.f("ck_model_requests_attempts_bounded")),
        sa.PrimaryKeyConstraint("stage_key", name=op.f("pk_model_requests")),
    )
    with op.batch_alter_table("model_requests", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_model_requests_stage_id"), ["stage_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_model_requests_state"), ["state"], unique=False)

    op.create_table(
        "model_outputs",
        sa.Column("stage_key", sa.String(length=70), nullable=False),
        sa.Column("stage_id", sa.String(length=100), nullable=False),
        sa.Column("prompt_version", sa.String(length=50), nullable=False),
        sa.Column("schema_version", sa.String(length=50), nullable=False),
        sa.Column("provider_id", sa.String(length=40), nullable=False),
        sa.Column("provider_version", sa.String(length=40), nullable=False),
        sa.Column("served_model", sa.String(length=100), nullable=True),
        sa.Column("session_ref", sa.String(length=200), nullable=True),
        sa.Column("output_json", sa.Text(), nullable=False),
        sa.Column("stored_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["stage_key"],
            ["model_requests.stage_key"],
            name=op.f("fk_model_outputs_stage_key_model_requests"),
        ),
        sa.PrimaryKeyConstraint("stage_key", name=op.f("pk_model_outputs")),
    )
    with op.batch_alter_table("model_outputs", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_model_outputs_stage_id"), ["stage_id"], unique=False)


def downgrade() -> None:
    """Drop both tables, outputs first."""
    with op.batch_alter_table("model_outputs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_model_outputs_stage_id"))
    op.drop_table("model_outputs")
    with op.batch_alter_table("model_requests", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_model_requests_state"))
        batch_op.drop_index(batch_op.f("ix_model_requests_stage_id"))
    op.drop_table("model_requests")
