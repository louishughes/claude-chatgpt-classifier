"""Add accounts, tokens, workspace membership and the authorisation log (PROD-002).

Revision ID: 0029_accounts
Revises: 0028_purge_log
Create Date: 2026-10-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from knowledge_engine.access.accounts import AUTHZ_LOG_TRIGGERS
from knowledge_engine.infrastructure.dialects import run_triggers

revision: str = "0029_accounts"
down_revision: str | None = "0028_purge_log"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create the four tables; authz_events refuses edits and deletes."""
    op.create_table(
        "accounts",
        sa.Column("account_id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("account_id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "account_tokens",
        sa.Column("token_id", sa.String(length=32), nullable=False),
        sa.Column("account_id", sa.String(length=32), nullable=False),
        sa.Column("token_sha256", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("token_id"),
        sa.UniqueConstraint("token_sha256"),
    )
    with op.batch_alter_table("account_tokens", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_account_tokens_account_id"), ["account_id"], unique=False
        )
    op.create_table(
        "workspace_members",
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("account_id", sa.String(length=32), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("granted_by", sa.String(length=64), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("workspace_id", "account_id"),
    )
    op.create_table(
        "authz_events",
        sa.Column("event_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("account", sa.String(length=64), nullable=False),
        sa.Column("workspace_id", sa.String(length=32), nullable=True),
        sa.Column("permission", sa.String(length=16), nullable=False),
        sa.Column("resource", sa.String(length=200), nullable=False),
        sa.Column("allowed", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=False),
        sa.PrimaryKeyConstraint("event_id"),
    )
    run_triggers(AUTHZ_LOG_TRIGGERS)


def downgrade() -> None:
    """Drop the four tables (the triggers go with their table)."""
    op.drop_table("authz_events")
    op.drop_table("workspace_members")
    with op.batch_alter_table("account_tokens", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_account_tokens_account_id"))
    op.drop_table("account_tokens")
    op.drop_table("accounts")
