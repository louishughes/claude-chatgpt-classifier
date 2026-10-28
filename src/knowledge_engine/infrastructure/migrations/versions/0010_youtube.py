"""Add the YouTube video registry: youtube_videos and youtube_mentions (YTB-001).

Revision ID: 0010_youtube
Revises: 0009_links
Create Date: 2026-10-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "0010_youtube"
down_revision: str | None = "0009_links"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    """Create youtube_videos and youtube_mentions."""
    op.create_table(
        "youtube_videos",
        sa.Column("video_id", sa.String(length=11), nullable=False),
        sa.Column("transcript_status", sa.String(length=20), nullable=False),
        sa.Column("first_import_id", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "transcript_status IN ('not_requested','queued','succeeded','unavailable',"
            "'permission_required','rate_limited','failed')",
            name=op.f("ck_youtube_videos_transcript_status_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["first_import_id"],
            ["import_batches.import_id"],
            name=op.f("fk_youtube_videos_first_import_id_import_batches"),
        ),
        sa.PrimaryKeyConstraint("video_id", name=op.f("pk_youtube_videos")),
    )
    op.create_table(
        "youtube_mentions",
        sa.Column("mention_id", sa.String(length=40), nullable=False),
        sa.Column("video_id", sa.String(length=11), nullable=False),
        sa.Column("t_seconds", sa.Integer(), nullable=True),
        sa.Column("playlist_id", sa.String(length=64), nullable=True),
        sa.Column("channel_hint", sa.String(length=100), nullable=True),
        sa.ForeignKeyConstraint(
            ["mention_id"],
            ["link_occurrences.occurrence_id"],
            name=op.f("fk_youtube_mentions_mention_id_link_occurrences"),
        ),
        sa.ForeignKeyConstraint(
            ["video_id"],
            ["youtube_videos.video_id"],
            name=op.f("fk_youtube_mentions_video_id_youtube_videos"),
        ),
        sa.PrimaryKeyConstraint("mention_id", name=op.f("pk_youtube_mentions")),
    )
    with op.batch_alter_table("youtube_mentions", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_youtube_mentions_video_id"), ["video_id"], unique=False
        )


def downgrade() -> None:
    """Drop youtube_mentions, then youtube_videos."""
    op.drop_table("youtube_mentions")
    op.drop_table("youtube_videos")
