"""Baseline schema: the workspaces table.

Revision ID: 0001_baseline
Revises:
Create Date: 2026-10-27

The first migration. Later tickets add their tables in new numbered files;
this one is never edited once released, because databases on disk already
record that it ran.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0001_baseline"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create the workspaces table."""
    op.create_table(
        "workspaces",
        sa.Column("workspace_id", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("workspace_id", name=op.f("pk_workspaces")),
        sa.UniqueConstraint("name", name=op.f("uq_workspaces_name")),
    )


def downgrade() -> None:
    """Drop the workspaces table."""
    op.drop_table("workspaces")
