"""The purge audit log and the tombstones that stop deleted chats coming back (OPS-004).

Two small tables:

* ``purge_events``: one row per purge: when, who, why, how many rows of
  each kind went, and what the check afterwards found. Counts and
  fingerprints only, never the deleted words. Rows can't be deleted.
* ``purge_tombstones``: one fingerprint per purged conversation and per
  purged export file. The importer looks here first, so re-importing the
  same export (which still holds the chat) skips it instead of quietly
  bringing it back.

A tombstone is a SHA-256 of an ID, not the ID: it can answer "was this
chat purged?" but can't be read back into anything.

Talking points:
    - "Deleting a chat leaves a fingerprint behind, so the next import of
      my full history doesn't resurrect it."
    - "The audit log says what was deleted by count and fingerprint; it
      never keeps the words it was asked to forget."
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from knowledge_engine.infrastructure.db import Base


def _utc_now() -> datetime:
    return datetime.now(UTC)


class TombstoneKind(StrEnum):
    """What a tombstone stands for."""

    CONVERSATION = "conversation"  # key: fingerprint of the conversation ID
    SNAPSHOT = "snapshot"  # key: the export file's own SHA-256


class PurgeEventRow(Base):
    """One purge, as the audit log keeps it. Never deleted."""

    __tablename__ = "purge_events"

    purge_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    actor: Mapped[str] = mapped_column(String(80))
    reason: Mapped[str] = mapped_column(Text)
    # The fingerprint of the plan the person confirmed.
    plan_sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))  # "purged", then "verified" or "residual"
    counts_json: Mapped[str] = mapped_column(Text)
    verification_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


class PurgeTombstoneRow(Base):
    """A fingerprint of something purged, so an import won't bring it back."""

    __tablename__ = "purge_tombstones"
    __table_args__ = (UniqueConstraint("kind", "key_sha256", name="uq_purge_tombstone"),)

    tombstone_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(16))
    key_sha256: Mapped[str] = mapped_column(String(64))
    purge_id: Mapped[str] = mapped_column(String(40), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


# Created by migration 0028: the audit log outlives what it describes.
PURGE_LOG_TRIGGERS = (
    "CREATE TRIGGER IF NOT EXISTS purge_events_no_delete BEFORE DELETE ON purge_events "
    "BEGIN SELECT RAISE(ABORT, 'purge_events is an audit log'); END",
)


def conversation_key(conversation_id: str) -> str:
    """The tombstone fingerprint of a conversation ID."""
    return hashlib.sha256(f"conversation|{conversation_id}".encode()).hexdigest()


def is_purged(session: Session, kind: TombstoneKind, key_sha256: str) -> bool:
    """Whether a purge left a tombstone with this fingerprint."""
    found = session.scalar(
        select(PurgeTombstoneRow.tombstone_id).where(
            PurgeTombstoneRow.kind == kind.value, PurgeTombstoneRow.key_sha256 == key_sha256
        )
    )
    return found is not None
