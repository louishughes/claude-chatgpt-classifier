"""Human corrections survive re-imports (IMP-006).

A person's correction is tied to the exact words it was made on. Every
override kind is anchored to logical message IDs (``node_``) plus the
message revision (``rev_``) in force when the person decided:

* **segment overrides** (NRM-005) and **classification reviews** (CLS-004):
  anchored when they are recorded, in the append-only ``override_anchors``
  table (one row per message the decision covers);
* **record decisions** (EXT-007): already anchored, by the record's
  evidence revisions;
* **relationship reviews** (REL-002): already anchored, by the revision
  IDs in the relationship's evidence.

After a re-import, ``check_overrides`` compares each anchor with the
message's newest revision:

* every anchored message unchanged: ``kept``. The correction keeps
  applying, untouched;
* any anchored message revised: ``review_required``, listing each changed
  message with **both** revisions (the one decided on and the new one), so
  a reviewer can compare them. Nothing is undone automatically: the person
  decides again;
* nothing to compare against (a decision recorded before anchoring
  existed, or one whose evidence names no message): ``unanchored``.

A message missing from a new export is not a change (OPS rule: absence is
never deletion), so it counts as unchanged.

Talking points:
    - "Each correction remembers which version of the message it was made
      on, so after a re-import I can tell which still stand and which need
      another look."
    - "A changed message never silently keeps or loses a correction; it is
      flagged with both versions side by side."
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import DateTime, Integer, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from knowledge_engine.importer.records import MessageNodeRow, MessageRevisionRow
from knowledge_engine.infrastructure.db import Base


def _utc_now() -> datetime:
    return datetime.now(UTC)


class OverrideKind(StrEnum):
    """Which kind of human correction."""

    SEGMENT = "segment_override"
    CLASSIFICATION = "classification_review"
    RECORD = "record_decision"
    RELATIONSHIP = "relationship_review"


class OverrideState(StrEnum):
    """Where a correction stands after the latest import."""

    KEPT = "kept"
    REVIEW_REQUIRED = "review_required"
    UNANCHORED = "unanchored"


class OverrideAnchorRow(Base):
    """One message a correction was made on, at the revision it saw. Append-only."""

    __tablename__ = "override_anchors"

    anchor_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(24))
    # The correction's own ID (override_id, review_id...), as text.
    override_ref: Mapped[str] = mapped_column(String(40), index=True)
    conversation_id: Mapped[str] = mapped_column(String(40), index=True)
    node_key: Mapped[str] = mapped_column(String(40), index=True)
    revision_id: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


# Created by migration 0027. Kept here so tests that build the schema
# without Alembic can install the same guard.
APPEND_ONLY_TRIGGERS = tuple(
    f"CREATE TRIGGER IF NOT EXISTS override_anchors_no_{action} BEFORE {action.upper()} "
    "ON override_anchors BEGIN SELECT RAISE(ABORT, 'override_anchors is append-only'); END"
    for action in ("update", "delete")
)


def anchor(
    session: Session,
    kind: OverrideKind,
    override_ref: str,
    conversation_id: str,
    messages: Iterable[tuple[str, str]],
) -> None:
    """Record the (node_key, revision_id) pairs a correction was made on. Caller commits."""
    for node_key, revision_id in sorted(set(messages)):
        session.add(
            OverrideAnchorRow(
                kind=kind.value,
                override_ref=override_ref,
                conversation_id=conversation_id,
                node_key=node_key,
                revision_id=revision_id,
            )
        )
    session.flush()


@dataclass(frozen=True)
class Change:
    """One anchored message whose newest revision differs from the one decided on."""

    node_key: str
    decided_on: str
    now: str


@dataclass(frozen=True)
class OverrideCheck:
    """One correction's standing after the latest import.

    Attributes:
        kind: Which kind of correction.
        override_ref: Its ID (``override_id``, ``review_id``, ``krec_``, ``rel_``).
        state: Kept, review required, or unanchored.
        changes: For review required: each changed message, both revisions.
    """

    kind: OverrideKind
    override_ref: str
    state: OverrideState
    changes: tuple[Change, ...] = ()


def newest_revisions(session: Session, node_keys: Iterable[str]) -> dict[str, str]:
    """Node key -> its newest revision (later imports win, as in BRW-001)."""
    wanted = sorted(set(node_keys))
    newest: dict[str, str] = {}
    for start in range(0, len(wanted), 500):
        for node_key, revision_id in session.execute(
            select(MessageRevisionRow.node_key, MessageRevisionRow.revision_id)
            .where(MessageRevisionRow.node_key.in_(wanted[start : start + 500]))
            .order_by(MessageRevisionRow.created_at, MessageRevisionRow.revision_id)
        ):
            newest[node_key] = revision_id
    return newest


def _nodes_of(session: Session, revision_ids: Iterable[str]) -> dict[str, str]:
    """Revision ID -> its node key."""
    wanted = sorted(set(revision_ids))
    found: dict[str, str] = {}
    for start in range(0, len(wanted), 500):
        found |= dict(
            session.execute(
                select(MessageRevisionRow.revision_id, MessageRevisionRow.node_key).where(
                    MessageRevisionRow.revision_id.in_(wanted[start : start + 500])
                )
            )
            .tuples()
            .all()
        )
    return found


def _judge(
    kind: OverrideKind, ref: str, pairs: Sequence[tuple[str, str]], newest: dict[str, str]
) -> OverrideCheck:
    if not pairs:
        return OverrideCheck(kind, ref, OverrideState.UNANCHORED)
    changes = tuple(
        Change(node, rev, newest[node])
        for node, rev in sorted(set(pairs))
        if node in newest and newest[node] != rev
    )
    state = OverrideState.REVIEW_REQUIRED if changes else OverrideState.KEPT
    return OverrideCheck(kind, ref, state, changes)


def check_overrides(session: Session) -> list[OverrideCheck]:
    """Every human correction's standing against the newest revisions. Reads only."""
    from knowledge_engine.classification.store import ClassificationReviewRow
    from knowledge_engine.extraction.records import KnowledgeRecord
    from knowledge_engine.extraction.store import KnowledgeRecordRow
    from knowledge_engine.relationships.store import (
        ConversationRelationshipRow,
        RelationshipReviewRow,
    )
    from knowledge_engine.relationships.view import revision_ids_in
    from knowledge_engine.segmentation.overrides import SegmentOverrideRow

    pairs: dict[tuple[OverrideKind, str], list[tuple[str, str]]] = defaultdict(list)
    for row in session.scalars(select(OverrideAnchorRow)):
        pairs[(OverrideKind(row.kind), row.override_ref)].append((row.node_key, row.revision_id))
    # Corrections recorded before anchors existed still get a verdict: unanchored.
    for override_id in session.scalars(select(SegmentOverrideRow.override_id)):
        pairs.setdefault((OverrideKind.SEGMENT, str(override_id)), [])
    for review_id in session.scalars(select(ClassificationReviewRow.review_id)):
        pairs.setdefault((OverrideKind.CLASSIFICATION, str(review_id)), [])
    cited: dict[tuple[OverrideKind, str], list[str]] = {}
    for stored in session.scalars(select(KnowledgeRecordRow)):
        record = KnowledgeRecord.model_validate_json(stored.record_json)
        if record.reviewer:
            cited[(OverrideKind.RECORD, record.record_id)] = [
                e.revision_id for e in record.evidence
            ]
    reviewed = set(session.scalars(select(RelationshipReviewRow.relationship_id)))
    for rel in session.scalars(select(ConversationRelationshipRow)):
        if rel.relationship_id in reviewed:
            evidence = json.loads(rel.evidence_json or "{}")
            cited[(OverrideKind.RELATIONSHIP, rel.relationship_id)] = revision_ids_in(evidence)
    node_of = _nodes_of(session, [r for revs in cited.values() for r in revs])
    for key, revisions in cited.items():
        pairs[key] = [(node_of[r], r) for r in revisions if r in node_of]
    newest = newest_revisions(session, [n for p in pairs.values() for n, _ in p])
    return [_judge(kind, ref, pairs[(kind, ref)], newest) for kind, ref in sorted(pairs)]


def segment_messages(
    session: Session, segment_id: str, conversation_id: str | None = None
) -> tuple[str, list[tuple[str, str]]] | None:
    """(conversation, [(node_key, revision)]) of a current segment, if one has that ID.

    Without ``conversation_id``, the chat is found through the segment's
    stored classifications; a segment never classified can't be found then.
    """
    from knowledge_engine.classification.store import ClassificationRow
    from knowledge_engine.rendering.transcript import load_conversation
    from knowledge_engine.segmentation.overrides import load_segments

    conversation_id = conversation_id or session.scalar(
        select(ClassificationRow.conversation_id).where(ClassificationRow.segment_id == segment_id)
    )
    if conversation_id is None:
        return None
    chat = load_conversation(session, conversation_id)
    for segment in load_segments(session, chat):
        if segment.segment_id == segment_id:
            return conversation_id, [
                (chat.node_keys[native], chat.revisions[native])
                for native in segment.messages
                if native in chat.revisions
            ]
    return None


def node_revision(session: Session, conversation_id: str, native_id: str) -> tuple[str, str] | None:
    """(node_key, newest revision) of one message, by its native ID."""
    node_key = session.scalar(
        select(MessageNodeRow.node_key).where(
            MessageNodeRow.conversation_id == conversation_id,
            MessageNodeRow.native_node_id == native_id,
        )
    )
    if node_key is None:
        return None
    revision = newest_revisions(session, [node_key]).get(node_key)
    return (node_key, revision) if revision else None
