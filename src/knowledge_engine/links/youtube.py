"""YouTube videos: one record per video, linked to every mention (YTB-001).

A video can be linked in many ways: ``youtube.com/watch?v=ID``,
``youtu.be/ID``, ``/shorts/ID``, ``/live/ID``, ``/embed/ID`` and the mobile
and music sites. They all mean the same video, so they share one record
keyed by the 11-character video ID. Each mention keeps what was special
about that link: a start time (``t=1m30s``), a playlist (``list=``) and a
channel hint (``ab_channel=``).

Only real YouTube hosts count. ``youtube.com.example.net`` or
``notyoutube.com`` are lookalikes and are left as ordinary web links.
Channel and playlist pages aren't videos and are left alone too.

Every video starts with transcript status ``not_requested``. Nothing is
fetched here (YTB-002 handles transcripts, behind the network switch).

Talking points:
    - "A video linked 12 different ways is one video with 12 mentions, each
      remembering its own timestamp or playlist."
    - "Lookalike domains don't count: the host must really be YouTube."
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, Session, mapped_column

from knowledge_engine.domain.enums import TranscriptStatus
from knowledge_engine.infrastructure.db import Base

_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
_PLAYLIST_RE = re.compile(r"^[A-Za-z0-9_-]{2,64}$")
_DURATION_RE = re.compile(r"^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s?)?$")
_VIDEO_HOSTS = {"youtube.com", "m.youtube.com", "music.youtube.com", "youtube-nocookie.com"}
_PATH_FORMS = ("shorts", "live", "embed", "v", "e")
_STATUSES = ",".join(f"'{s.value}'" for s in TranscriptStatus)


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class YouTubeRef:
    """What one YouTube link says.

    Attributes:
        video_id: The 11-character video ID.
        t_seconds: The start time in the link, if any and readable.
        playlist_id: The ``list=`` playlist, if any.
        channel_hint: The ``ab_channel=`` name, if any (a hint, not an identity).
    """

    video_id: str
    t_seconds: int | None = None
    playlist_id: str | None = None
    channel_hint: str | None = None


def parse_youtube(url: str) -> YouTubeRef | None:
    """Return the video a URL links to, or None if it isn't a YouTube video link.

    Args:
        url: A URL as written (http or https).

    Returns:
        The video and the link's context, or None.
    """
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    if parts.scheme.lower() not in {"http", "https"}:
        return None
    host = (parts.hostname or "").rstrip(".").lower().removeprefix("www.")
    query = parse_qs(parts.query)
    segments = [s for s in parts.path.split("/") if s]
    video: str | None = None
    if host == "youtu.be":
        video = segments[0] if segments else None
    elif host in _VIDEO_HOSTS:
        if segments == ["watch"]:
            video = _first(query, "v")
        elif len(segments) >= 2 and segments[0] in _PATH_FORMS:
            video = segments[1]
    if video is None or not _ID_RE.fullmatch(video):
        return None
    fragment = parse_qs(parts.fragment)
    raw_time = _first(query, "t") or _first(query, "start") or _first(fragment, "t")
    playlist = _first(query, "list")
    channel = _first(query, "ab_channel")
    return YouTubeRef(
        video_id=video,
        t_seconds=_seconds(raw_time),
        playlist_id=playlist if playlist and _PLAYLIST_RE.fullmatch(playlist) else None,
        channel_hint=channel[:100] if channel else None,
    )


class YouTubeVideoRow(Base):
    """One YouTube video, however many times and ways it was linked."""

    __tablename__ = "youtube_videos"
    __table_args__ = (
        CheckConstraint(f"transcript_status IN ({_STATUSES})", name="transcript_status_valid"),
    )

    video_id: Mapped[str] = mapped_column(String(11), primary_key=True)
    transcript_status: Mapped[str] = mapped_column(
        String(20), default=TranscriptStatus.NOT_REQUESTED.value
    )
    first_import_id: Mapped[str] = mapped_column(ForeignKey("import_batches.import_id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


class YouTubeMentionRow(Base):
    """One link to a video: a link occurrence plus what the link said."""

    __tablename__ = "youtube_mentions"

    # The same ID as the link occurrence it extends (one mention per link).
    mention_id: Mapped[str] = mapped_column(
        ForeignKey("link_occurrences.occurrence_id"), primary_key=True
    )
    video_id: Mapped[str] = mapped_column(ForeignKey("youtube_videos.video_id"), index=True)
    t_seconds: Mapped[int | None] = mapped_column(Integer, default=None)
    playlist_id: Mapped[str | None] = mapped_column(String(64), default=None)
    channel_hint: Mapped[str | None] = mapped_column(String(100), default=None)


def record_mention(
    session: Session, occurrence_id: str, ref: YouTubeRef, *, import_id: str
) -> bool:
    """Store a video mention (and the video, first time). Returns True if new.

    Args:
        session: The batch's write session.
        occurrence_id: The link occurrence this mention extends.
        ref: From ``parse_youtube``.
        import_id: The running batch.
    """
    if session.get(YouTubeVideoRow, ref.video_id) is None:
        session.add(YouTubeVideoRow(video_id=ref.video_id, first_import_id=import_id))
        session.flush()
    if session.get(YouTubeMentionRow, occurrence_id) is not None:
        return False
    session.add(
        YouTubeMentionRow(
            mention_id=occurrence_id,
            video_id=ref.video_id,
            t_seconds=ref.t_seconds,
            playlist_id=ref.playlist_id,
            channel_hint=ref.channel_hint,
        )
    )
    return True


def _first(query: dict[str, list[str]], key: str) -> str | None:
    values = query.get(key)
    return values[0] if values else None


def _seconds(raw: str | None) -> int | None:
    # "90", "90s", "1m30s", "1h2m3s". Anything else: no time (never guessed).
    if not raw:
        return None
    match = _DURATION_RE.fullmatch(raw.strip().lower())
    if not match or not any(match.groups()):
        return None
    hours, minutes, seconds = (int(g or 0) for g in match.groups())
    return hours * 3600 + minutes * 60 + seconds
