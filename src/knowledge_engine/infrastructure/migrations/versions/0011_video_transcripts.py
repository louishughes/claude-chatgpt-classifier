"""Add video transcripts: acquisitions, snapshots and cues (YTB-002).

Revision ID: 0011_video_transcripts
Revises: 0010_youtube
Create Date: 2026-10-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0011_video_transcripts"
down_revision: str | None = "0010_youtube"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create transcript_snapshots, transcript_acquisitions and transcript_cues."""
    op.create_table(
        "transcript_snapshots",
        sa.Column("transcript_id", sa.String(length=40), nullable=False),
        sa.Column("video_id", sa.String(length=11), nullable=False),
        sa.Column("file_sha256", sa.String(length=64), nullable=False),
        sa.Column("format", sa.String(length=10), nullable=False),
        sa.Column("language", sa.String(length=35), nullable=True),
        sa.Column("provenance_json", sa.Text(), nullable=False),
        sa.Column("parser_version", sa.String(length=20), nullable=False),
        sa.Column("warnings_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["video_id"],
            ["youtube_videos.video_id"],
            name=op.f("fk_transcript_snapshots_video_id_youtube_videos"),
        ),
        sa.PrimaryKeyConstraint("transcript_id", name=op.f("pk_transcript_snapshots")),
        sa.UniqueConstraint(
            "video_id", "file_sha256", name=op.f("uq_transcript_snapshots_video_id_file_sha256")
        ),
    )
    with op.batch_alter_table("transcript_snapshots", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_transcript_snapshots_video_id"), ["video_id"], unique=False
        )

    op.create_table(
        "transcript_acquisitions",
        sa.Column("acquisition_id", sa.String(length=40), nullable=False),
        sa.Column("video_id", sa.String(length=11), nullable=False),
        sa.Column("method", sa.String(length=60), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.String(length=200), nullable=True),
        sa.Column("policy_version", sa.String(length=20), nullable=False),
        sa.Column("transcript_id", sa.String(length=40), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('not_requested','queued','succeeded','unavailable',"
            "'permission_required','rate_limited','failed')",
            name=op.f("ck_transcript_acquisitions_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["transcript_id"],
            ["transcript_snapshots.transcript_id"],
            name=op.f("fk_transcript_acquisitions_transcript_id_transcript_snapshots"),
        ),
        sa.ForeignKeyConstraint(
            ["video_id"],
            ["youtube_videos.video_id"],
            name=op.f("fk_transcript_acquisitions_video_id_youtube_videos"),
        ),
        sa.PrimaryKeyConstraint("acquisition_id", name=op.f("pk_transcript_acquisitions")),
        sa.UniqueConstraint(
            "video_id", "method", name=op.f("uq_transcript_acquisitions_video_id_method")
        ),
    )
    with op.batch_alter_table("transcript_acquisitions", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_transcript_acquisitions_video_id"), ["video_id"], unique=False
        )

    op.create_table(
        "transcript_cues",
        sa.Column("cue_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("transcript_id", sa.String(length=40), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("start_ms", sa.Integer(), nullable=True),
        sa.Column("end_ms", sa.Integer(), nullable=True),
        sa.Column("speaker", sa.String(length=200), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["transcript_id"],
            ["transcript_snapshots.transcript_id"],
            name=op.f("fk_transcript_cues_transcript_id_transcript_snapshots"),
        ),
        sa.PrimaryKeyConstraint("cue_id", name=op.f("pk_transcript_cues")),
        sa.UniqueConstraint(
            "transcript_id", "ordinal", name=op.f("uq_transcript_cues_transcript_id_ordinal")
        ),
    )
    with op.batch_alter_table("transcript_cues", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_transcript_cues_transcript_id"), ["transcript_id"], unique=False
        )


def downgrade() -> None:
    """Drop the transcript tables, children first."""
    op.drop_table("transcript_cues")
    op.drop_table("transcript_acquisitions")
    op.drop_table("transcript_snapshots")
