"""Add the jobs table (FND-006).

Revision ID: 0002_jobs
Revises: 0001_baseline
Create Date: 2026-10-27
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0002_jobs"
down_revision: str | None = "0001_baseline"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create the jobs table with its state and attempt constraints."""
    op.create_table(
        "jobs",
        sa.Column("job_id", sa.String(length=32), nullable=False),
        sa.Column("stage_id", sa.String(length=100), nullable=False),
        sa.Column("stage_key", sa.String(length=68), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("versions_json", sa.Text(), nullable=False),
        sa.Column("state", sa.String(length=20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("checkpoint_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state IN ('pending','running','succeeded','failed','review_required','skipped')",
            name=op.f("ck_jobs_state_valid"),
        ),
        sa.CheckConstraint(
            "attempts >= 0 AND attempts <= max_attempts", name=op.f("ck_jobs_attempts_bounded")
        ),
        sa.PrimaryKeyConstraint("job_id", name=op.f("pk_jobs")),
        sa.UniqueConstraint("stage_key", name=op.f("uq_jobs_stage_key")),
    )
    op.create_index(op.f("ix_jobs_stage_id"), "jobs", ["stage_id"], unique=False)


def downgrade() -> None:
    """Drop the jobs table."""
    op.drop_index(op.f("ix_jobs_stage_id"), table_name="jobs")
    op.drop_table("jobs")
