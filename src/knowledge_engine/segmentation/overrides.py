"""Reviewer splits and merges of topic segments, kept forever (NRM-005).

The segmenter's boundaries are a proposal. A reviewer can correct them:

* **split** at a message: a new segment starts there;
* **merge** at a message: the segment that starts there joins the one
  before it;
* **clear** at a message: forget the earlier decision there.

Each decision is one row in ``segment_overrides``, an **append-only** log
(database triggers refuse UPDATE and DELETE). The latest decision at a
message wins; the earlier ones stay as history.

Why decisions are tied to *native message IDs*: those IDs come from the
export and stay the same in every later export of the chat. So when the
chat is imported again, or segments are recomputed, the same decisions
apply again: overrides survive a rerun. A decision whose message no longer
starts an exchange (the chat changed) is not dropped silently; it is
reported as **orphaned** and needs another look.

Splits only go where an exchange starts, the same rule the segmenter
follows, so a short "no" can never be cut off from what it rejects. No
message is ever lost: a split or merge only moves boundaries, and every
message still lands in exactly one segment.

Changing segments changes segment IDs. Old classifications and extraction
runs are never deleted; ``revalidation`` lists which ones belong to
segments that are no longer current, so they can be redone.

Talking points:
    - "A reviewer can split or merge segments; each decision is logged
      for good and re-applied every time the chat is processed."
    - "Decisions point at the export's own message IDs, so they survive a
      re-import, and one that no longer fits is flagged, not dropped."
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, DateTime, Integer, String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from knowledge_engine.classification.store import ClassificationRow
from knowledge_engine.extraction.runner import ExtractionRunRow
from knowledge_engine.infrastructure.db import Base
from knowledge_engine.rendering.transcript import StoredConversation
from knowledge_engine.segmentation.segmenter import (
    Segment,
    SegmenterSettings,
    exchange_starts,
    section_messages,
    segment_conversation,
)


class Action(StrEnum):
    """What a reviewer decided at one message."""

    SPLIT = "split"
    MERGE = "merge"
    CLEAR = "clear"


def _utc_now() -> datetime:
    return datetime.now(UTC)


class SegmentOverrideRow(Base):
    """One reviewer decision about a segment boundary. Append-only."""

    __tablename__ = "segment_overrides"
    __table_args__ = (CheckConstraint("action IN ('split','merge','clear')", name="action_valid"),)

    override_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(String(40), index=True)
    native_message_id: Mapped[str] = mapped_column(String(200))
    action: Mapped[str] = mapped_column(String(8))
    reviewer: Mapped[str] = mapped_column(String(100))
    note: Mapped[str | None] = mapped_column(Text, default=None)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


# Created by migration 0021. Kept here so tests that build the schema
# without Alembic can install the same guard.
APPEND_ONLY_TRIGGERS = (
    "CREATE TRIGGER IF NOT EXISTS segment_overrides_no_update "
    "BEFORE UPDATE ON segment_overrides "
    "BEGIN SELECT RAISE(ABORT, 'segment_overrides is append-only'); END",
    "CREATE TRIGGER IF NOT EXISTS segment_overrides_no_delete "
    "BEFORE DELETE ON segment_overrides "
    "BEGIN SELECT RAISE(ABORT, 'segment_overrides is append-only'); END",
)


class OverrideError(ValueError):
    """A decision that can't be recorded (no reviewer, not a boundary...)."""


def active_overrides(session: Session, conversation_id: str) -> dict[str, str]:
    """The decisions in force: native message ID -> ``split`` or ``merge``."""
    latest: dict[str, str] = {}
    for row in session.scalars(
        select(SegmentOverrideRow)
        .where(SegmentOverrideRow.conversation_id == conversation_id)
        .order_by(SegmentOverrideRow.override_id)
    ):
        latest[row.native_message_id] = row.action
    return {native: action for native, action in latest.items() if action != Action.CLEAR}


def load_segments(
    session: Session, conversation: StoredConversation, settings: SegmenterSettings | None = None
) -> list[Segment]:
    """The conversation's segments with every reviewer decision applied."""
    overrides = active_overrides(session, conversation.conversation_id)
    return segment_conversation(conversation, settings, overrides or None)


def record_override(
    session: Session,
    conversation: StoredConversation,
    native_message_id: str,
    action: Action,
    *,
    reviewer: str,
    note: str | None = None,
    settings: SegmenterSettings | None = None,
) -> SegmentOverrideRow:
    """Record one reviewer decision after checking it makes sense now.

    Args:
        session: The caller commits.
        conversation: From ``load_conversation``.
        native_message_id: The message the decision is about.
        action: Split, merge or clear.
        reviewer: Who decided (required).
        note: Why.
        settings: The segmenter settings in use.

    Raises:
        OverrideError: No reviewer; a split where no exchange starts, at a
            section's first exchange or where a segment already starts; a
            merge where no segment starts; a clear with nothing to clear.
    """
    if not reviewer.strip():
        raise OverrideError("a decision needs a named reviewer")
    current = load_segments(session, conversation, settings)
    starts = {s.messages[0] for s in current}
    first = {s.messages[0] for s in current if s.sequence == 0}
    if action is Action.SPLIT:
        openers = {
            native
            for _, messages in section_messages(conversation)
            for native in exchange_starts(messages, settings)
        }
        if native_message_id not in openers:
            raise OverrideError("a split must be where an exchange starts")
        if native_message_id in starts:
            raise OverrideError("a segment already starts there")
    elif action is Action.MERGE:
        if native_message_id not in starts or native_message_id in first:
            raise OverrideError("a merge must be where a later segment starts")
    elif native_message_id not in active_overrides(session, conversation.conversation_id):
        raise OverrideError("no decision to clear there")
    row = SegmentOverrideRow(
        conversation_id=conversation.conversation_id,
        native_message_id=native_message_id,
        action=action.value,
        reviewer=reviewer,
        note=note,
    )
    session.add(row)
    session.flush()
    # IMP-006: remember which version of the message this decision was made on.
    from knowledge_engine.importer.corrections import OverrideKind, anchor, node_revision

    found = node_revision(session, conversation.conversation_id, native_message_id)
    if found is not None:
        anchor(
            session,
            OverrideKind.SEGMENT,
            str(row.override_id),
            conversation.conversation_id,
            [found],
        )
    return row


def orphaned(
    session: Session, conversation: StoredConversation, settings: SegmenterSettings | None = None
) -> list[str]:
    """Native IDs of decisions in force that no longer fit the chat.

    A split must still be at an exchange start. A merge is fine wherever it
    is (removing a boundary that is not there changes nothing), unless its
    message has vanished from the chat altogether.
    """
    openers = {
        native
        for _, messages in section_messages(conversation)
        for native in exchange_starts(messages, settings)
    }
    lost = []
    for native, action in sorted(active_overrides(session, conversation.conversation_id).items()):
        if native not in conversation.messages or (
            action == Action.SPLIT and native not in openers
        ):
            lost.append(native)
    return lost


@dataclass(frozen=True)
class Revalidation:
    """What a change of segments means for results already stored.

    Attributes:
        retired: Segment IDs no longer current (their results stay, unused).
        added: New segment IDs that need classifying and extracting.
        classifications: Stored classification IDs on retired segments.
        extraction_runs: Stored extraction stage keys on retired segments.
    """

    retired: tuple[str, ...]
    added: tuple[str, ...]
    classifications: tuple[str, ...]
    extraction_runs: tuple[str, ...]


def revalidation(
    session: Session, before: Iterable[Segment], after: Iterable[Segment]
) -> Revalidation:
    """Compare two segmentations of a chat and list the work to redo. Changes nothing."""
    old = {s.segment_id for s in before}
    new = {s.segment_id for s in after}
    retired = sorted(old - new)
    classifications = session.scalars(
        select(ClassificationRow.classification_id)
        .where(ClassificationRow.segment_id.in_(retired))
        .order_by(ClassificationRow.classification_id)
    ).all()
    runs = session.scalars(
        select(ExtractionRunRow.stage_key)
        .where(ExtractionRunRow.segment_id.in_(retired))
        .order_by(ExtractionRunRow.stage_key)
    ).all()
    return Revalidation(
        tuple(retired), tuple(sorted(new - old)), tuple(classifications), tuple(runs)
    )
