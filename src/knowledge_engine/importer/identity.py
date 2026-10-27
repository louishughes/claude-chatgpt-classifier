"""Candidate matches: what the importer does when identity is unsafe (IMP-002).

Logical identity is native-ID-first (ADR-0003). Two situations make that
unsafe, and in both the importer records a **candidate match** for review
instead of guessing:

* ``id_collision``: one export holds two *different* conversations under the
  same native ID. The first is imported; the second is kept aside as a
  candidate. Merging them would silently mix two chats.
* ``missing_native_id``: a conversation has no native ID at all. Keying it
  by title or timestamp would be a guess, so it isn't imported; it becomes a
  candidate instead.

A candidate is never merged automatically. Its key is the incoming
conversation's content hash, so re-importing the same export finds the
candidate already recorded and adds nothing. Candidates hold hashes and
locators only, never message text or titles.

Talking points:
    - "When the export's own ID can't be trusted, the importer parks the
      chat as 'review required' instead of guessing which chat it is."
    - "Title, date and similar wording never decide identity: two chats
      called the same thing stay two chats."
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, Session, mapped_column

from knowledge_engine.domain.ids import sha256_hex
from knowledge_engine.graph.nodes import canonical_json
from knowledge_engine.infrastructure.db import Base


class CandidateReason(StrEnum):
    """Why a conversation needs a person to decide its identity."""

    ID_COLLISION = "id_collision"
    MISSING_NATIVE_ID = "missing_native_id"


def _utc_now() -> datetime:
    return datetime.now(UTC)


class IdentityCandidateRow(Base):
    """One conversation whose identity is ``review_required``."""

    __tablename__ = "identity_candidates"
    __table_args__ = (
        UniqueConstraint("workspace_id", "account_namespace", "reason", "conversation_hash"),
        CheckConstraint("reason IN ('id_collision','missing_native_id')", name="reason_valid"),
        CheckConstraint("status IN ('review_required','accepted','rejected')", name="status_valid"),
    )

    candidate_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.workspace_id"))
    account_namespace: Mapped[str] = mapped_column(String(63))
    reason: Mapped[str] = mapped_column(String(30))
    # The colliding native ID, or None when the conversation had none.
    native_conversation_id: Mapped[str | None] = mapped_column(String(200), default=None)
    # The logical conversation it collided with, if any. Never merged into.
    existing_conversation_id: Mapped[str | None] = mapped_column(
        ForeignKey("conversations.conversation_id"), default=None
    )
    # Hash of the whole incoming conversation object: the candidate's identity.
    conversation_hash: Mapped[str] = mapped_column(String(64))
    snapshot_id: Mapped[str] = mapped_column(ForeignKey("source_snapshots.snapshot_id"))
    source_index: Mapped[int | None] = mapped_column(Integer, default=None)
    status: Mapped[str] = mapped_column(String(20), default="review_required")
    first_import_id: Mapped[str] = mapped_column(ForeignKey("import_batches.import_id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


def conversation_hash(native: Mapping[str, Any]) -> str:
    """Return the exact-content hash of a whole native conversation.

    Args:
        native: The native conversation object.

    Returns:
        SHA-256 hex of its canonical JSON.
    """
    return sha256_hex(canonical_json(native).encode())


def record_candidate(
    session: Session,
    native: Mapping[str, Any],
    *,
    reason: CandidateReason,
    workspace_id: str,
    account_namespace: str,
    native_id: str | None,
    existing_conversation_id: str | None,
    snapshot_id: str,
    source_index: int | None,
    import_id: str,
) -> bool:
    """Record a review-required candidate, once.

    Args:
        session: The batch's write session.
        native: The incoming conversation (only its hash is stored).
        reason: Why identity is unsafe.
        workspace_id: Target workspace.
        account_namespace: The raw root's account label.
        native_id: The native ID, if the conversation has one.
        existing_conversation_id: The logical conversation it collided with.
        snapshot_id: Snapshot of the file it came from.
        source_index: Its position in that file.
        import_id: The running batch.

    Returns:
        True if this candidate is new; False if an earlier import recorded it.
    """
    digest = conversation_hash(native)
    key = sha256_hex(f"{workspace_id}:{account_namespace}:{reason.value}:{digest}".encode())
    if session.get(IdentityCandidateRow, key) is not None:
        return False
    session.add(
        IdentityCandidateRow(
            candidate_id=key,
            workspace_id=workspace_id,
            account_namespace=account_namespace,
            reason=reason.value,
            native_conversation_id=native_id,
            existing_conversation_id=existing_conversation_id,
            conversation_hash=digest,
            snapshot_id=snapshot_id,
            source_index=source_index,
            first_import_id=import_id,
        )
    )
    session.flush()
    return True
