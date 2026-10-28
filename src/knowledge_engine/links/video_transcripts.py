"""Video transcripts: where getting each one stands, and the ones attached (YTB-002).

Two ways a video gets a transcript:

* **you supply it** (``attach_user_transcript``): a VTT, SRT or text file
  you have. It is read with the transcript adapter (ING-010), its bytes go
  into the archive, and it is stored as an immutable snapshot with its
  cues and a note of where it came from;
* **a provider fetches it** (``request_transcript``): only behind the
  ``transcript_fetch`` network switch, which is off by default. With the
  switch off, the provider is never called: the request is recorded as
  ``permission_required`` with the reason. With it on, a provider gets at
  most ``DEFAULT_MAX_ATTEMPTS`` tries for temporary problems (rate limits,
  timeouts); "unavailable" and "permission required" are final answers
  and are recorded, not retried.

Transcript text only ever comes from a file or a provider. Nothing here
writes, summarises or guesses words, and no provider is built in yet:
YTB-002 defines the contract; a real one needs an authorised source
(INT-002).

Talking points:
    - "With the network switch off, asking for a transcript can't reach the
      network: it records 'permission required' and stops."
    - "A transcript I attach keeps its file's fingerprint and where it came
      from, and it's never edited afterwards."
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, Session, mapped_column

from knowledge_engine.domain.enums import TranscriptStatus
from knowledge_engine.domain.ids import transcript_acquisition_id, transcript_snapshot_id
from knowledge_engine.importer.archive import BlobStore
from knowledge_engine.infrastructure.db import Base
from knowledge_engine.infrastructure.jobs import DEFAULT_MAX_ATTEMPTS
from knowledge_engine.ingestion.transcripts import (
    TranscriptDocument,
    TranscriptFormat,
    parse_transcript,
)
from knowledge_engine.links.youtube import YouTubeVideoRow
from knowledge_engine.settings import Capability, Settings

USER_SUPPLIED = "user_supplied"
POLICY_VERSION = "ytb-002-v1"
_STATUSES = ",".join(f"'{s.value}'" for s in TranscriptStatus)
# Answers that won't change by asking again: recorded, never retried.
_FINAL = {TranscriptStatus.UNAVAILABLE, TranscriptStatus.PERMISSION_REQUIRED}
_TEMPORARY = {TranscriptStatus.RATE_LIMITED, TranscriptStatus.FAILED}


def _utc_now() -> datetime:
    return datetime.now(UTC)


class TranscriptAcquisitionRow(Base):
    """The effort to get one video's transcript by one method."""

    __tablename__ = "transcript_acquisitions"
    __table_args__ = (
        UniqueConstraint("video_id", "method"),
        CheckConstraint(f"status IN ({_STATUSES})", name="status_valid"),
    )

    acquisition_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    video_id: Mapped[str] = mapped_column(ForeignKey("youtube_videos.video_id"), index=True)
    method: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(20))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    # A short code-like reason, e.g. "transcript_fetch switched off".
    last_error: Mapped[str | None] = mapped_column(String(200), default=None)
    policy_version: Mapped[str] = mapped_column(String(20), default=POLICY_VERSION)
    transcript_id: Mapped[str | None] = mapped_column(
        ForeignKey("transcript_snapshots.transcript_id"), default=None
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, onupdate=_utc_now
    )


class TranscriptSnapshotRow(Base):
    """One transcript file attached to one video. Never edited after it's stored."""

    __tablename__ = "transcript_snapshots"
    __table_args__ = (UniqueConstraint("video_id", "file_sha256"),)

    transcript_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    video_id: Mapped[str] = mapped_column(ForeignKey("youtube_videos.video_id"), index=True)
    # The file's bytes are in the archive under this fingerprint.
    file_sha256: Mapped[str] = mapped_column(String(64))
    format: Mapped[str] = mapped_column(String(10))
    language: Mapped[str | None] = mapped_column(String(35), default=None)
    # Where it came from: method, source URL, a note, when it was added.
    provenance_json: Mapped[str] = mapped_column(Text)
    parser_version: Mapped[str] = mapped_column(String(20))
    warnings_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


class TranscriptCueRow(Base):
    """One timed (or untimed) piece of a stored transcript."""

    __tablename__ = "transcript_cues"
    __table_args__ = (UniqueConstraint("transcript_id", "ordinal"),)

    cue_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    transcript_id: Mapped[str] = mapped_column(
        ForeignKey("transcript_snapshots.transcript_id"), index=True
    )
    ordinal: Mapped[int] = mapped_column(Integer)
    # None when the file gives no time: never filled in.
    start_ms: Mapped[int | None] = mapped_column(Integer, default=None)
    end_ms: Mapped[int | None] = mapped_column(Integer, default=None)
    speaker: Mapped[str | None] = mapped_column(String(200), default=None)
    text: Mapped[str] = mapped_column(Text)


@dataclass(frozen=True)
class ProviderAnswer:
    """What a transcript provider said.

    Attributes:
        status: ``succeeded`` (with ``data``), ``unavailable``,
            ``permission_required``, ``rate_limited`` or ``failed``.
        data: The transcript file's bytes, when succeeded.
        format: The file's format, if the provider knows it.
        language: Its language tag, if known.
        source_url: Where it was fetched from.
        reason: A short reason for anything but success.
    """

    status: TranscriptStatus
    data: bytes | None = None
    format: TranscriptFormat | None = None
    language: str | None = None
    source_url: str | None = None
    reason: str | None = None


class TranscriptProvider(Protocol):
    """A source of transcripts that needs the network (none built in yet)."""

    name: str

    def fetch(self, video_id: str) -> ProviderAnswer:
        """Try to get one video's transcript."""
        ...


class UnknownVideoError(KeyError):
    """The video isn't in the registry (it was never linked in a chat)."""


def attach_user_transcript(
    session: Session,
    settings: Settings,
    video_id: str,
    data: bytes,
    *,
    format: TranscriptFormat | None = None,  # noqa: A002 - mirrors the CLI flag
    language: str | None = None,
    source_url: str | None = None,
    note: str | None = None,
) -> TranscriptSnapshotRow:
    """Attach a transcript file you supplied to a video.

    Attaching the same file to the same video again changes nothing and
    returns the stored snapshot.

    Args:
        session: A write session.
        settings: For the archive and size limits.
        video_id: The video, which must already be in the registry.
        data: The file's bytes.
        format: Force a format; None detects it.
        language: Its language tag, if you know it.
        source_url: Where you got it, if you want that recorded.
        note: A short note on where it came from (e.g. "my own captions").

    Returns:
        The stored snapshot.

    Raises:
        UnknownVideoError: If the video isn't in the registry.
        TranscriptTooLargeError: If the file is over the size limit.
    """
    document = parse_transcript(
        data,
        format=format,
        source_url=source_url,
        language=language,
        max_bytes=settings.limits.max_source_file_bytes,
    )
    provenance = {"method": USER_SUPPLIED, "source_url": source_url, "note": note}
    snapshot = _store(session, settings, video_id, data, document, provenance)
    _settle(session, video_id, USER_SUPPLIED, TranscriptStatus.SUCCEEDED, snapshot=snapshot)
    return snapshot


def request_transcript(
    session: Session,
    settings: Settings,
    video_id: str,
    provider: TranscriptProvider,
    *,
    max_attempts: int = DEFAULT_MAX_ATTEMPTS,
) -> TranscriptAcquisitionRow:
    """Ask a provider for a video's transcript, if the network switch allows it.

    Args:
        session: A write session.
        settings: Its ``egress.transcript_fetch`` switch decides.
        video_id: The video, which must already be in the registry.
        provider: Where to ask.
        max_attempts: Tries in total for temporary problems.

    Returns:
        The acquisition record, with its final status and reason.

    Raises:
        UnknownVideoError: If the video isn't in the registry.
    """
    _video(session, video_id)
    method = f"provider:{provider.name}"
    if not settings.egress.allows(Capability.TRANSCRIPT_FETCH):
        # The provider is never called: this is the policy gate.
        return _settle(
            session,
            video_id,
            method,
            TranscriptStatus.PERMISSION_REQUIRED,
            reason="transcript_fetch switched off",
        )
    row = _settle(session, video_id, method, TranscriptStatus.QUEUED)
    if row.status == TranscriptStatus.SUCCEEDED.value:
        return row  # already have it; never fetched twice
    row.attempts = 0  # each request gets its own bounded number of tries
    while row.attempts < max_attempts:
        row.attempts += 1
        answer = provider.fetch(video_id)
        if answer.status == TranscriptStatus.SUCCEEDED and answer.data is not None:
            document = parse_transcript(
                answer.data,
                format=answer.format,
                source_url=answer.source_url,
                language=answer.language,
                max_bytes=settings.limits.max_source_file_bytes,
            )
            provenance = {
                "method": method,
                "source_url": answer.source_url,
                "retrieved_at": _utc_now().isoformat(),
            }
            snapshot = _store(session, settings, video_id, answer.data, document, provenance)
            return _settle(session, video_id, method, TranscriptStatus.SUCCEEDED, snapshot=snapshot)
        if answer.status in _FINAL:
            return _settle(session, video_id, method, answer.status, reason=answer.reason)
        status = answer.status if answer.status in _TEMPORARY else TranscriptStatus.FAILED
        _settle(session, video_id, method, status, reason=answer.reason or "no transcript")
    return _settle(
        session,
        video_id,
        method,
        TranscriptStatus.FAILED,
        reason=f"gave up after {row.attempts} attempts: {row.last_error or 'no reason'}",
    )


def video_status(session: Session, video_id: str) -> TranscriptStatus:
    """Return a video's overall transcript status."""
    return TranscriptStatus(_video(session, video_id).transcript_status)


def _store(
    session: Session,
    settings: Settings,
    video_id: str,
    data: bytes,
    document: TranscriptDocument,
    provenance: dict[str, str | None],
) -> TranscriptSnapshotRow:
    _video(session, video_id)
    key = transcript_snapshot_id(video_id, document.sha256)
    existing = session.get(TranscriptSnapshotRow, key)
    if existing is not None:
        return existing
    BlobStore(
        settings.workspace_root / "archive", max_bytes=settings.limits.max_source_file_bytes
    ).put_bytes(data)
    provenance = {**provenance, "added_at": _utc_now().isoformat()}
    snapshot = TranscriptSnapshotRow(
        transcript_id=key,
        video_id=video_id,
        file_sha256=document.sha256,
        format=document.format.value,
        language=document.language,
        provenance_json=json.dumps(provenance, sort_keys=True),
        parser_version=document.parser_version,
        warnings_json=json.dumps(document.warnings, sort_keys=True),
    )
    session.add(snapshot)
    session.flush()
    for cue in document.cues:
        session.add(
            TranscriptCueRow(
                transcript_id=key,
                ordinal=cue.index,
                start_ms=cue.start_ms,
                end_ms=cue.end_ms,
                speaker=cue.speaker,
                text=cue.text,
            )
        )
    session.flush()
    return snapshot


def _settle(
    session: Session,
    video_id: str,
    method: str,
    status: TranscriptStatus,
    *,
    reason: str | None = None,
    snapshot: TranscriptSnapshotRow | None = None,
) -> TranscriptAcquisitionRow:
    # Record the latest status of one method and roll it up onto the video.
    video = _video(session, video_id)
    key = transcript_acquisition_id(video_id, method)
    row = session.get(TranscriptAcquisitionRow, key)
    if row is None:
        row = TranscriptAcquisitionRow(
            acquisition_id=key, video_id=video_id, method=method, status=status.value, attempts=0
        )
        session.add(row)
    if row.status == TranscriptStatus.SUCCEEDED.value and status != TranscriptStatus.SUCCEEDED:
        return row  # a transcript we already have is never "un-got"
    row.status = status.value
    row.last_error = reason[:200] if reason else None
    if snapshot is not None:
        row.transcript_id = snapshot.transcript_id
    if video.transcript_status != TranscriptStatus.SUCCEEDED.value:
        video.transcript_status = status.value
    session.flush()
    return row


def _video(session: Session, video_id: str) -> YouTubeVideoRow:
    video = session.get(YouTubeVideoRow, video_id)
    if video is None:
        raise UnknownVideoError(video_id)
    return video


def read_file(path: Path, settings: Settings) -> bytes:
    """Read a transcript file you supplied, within the size limit."""
    from knowledge_engine.ingestion.transcripts import TranscriptTooLargeError

    if path.stat().st_size > settings.limits.max_source_file_bytes:
        raise TranscriptTooLargeError("transcript is over the size limit")
    return path.read_bytes()
