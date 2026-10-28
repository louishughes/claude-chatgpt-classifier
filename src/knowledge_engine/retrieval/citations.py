"""Turn search hits into citable evidence with its surrounding messages (RET-006).

A search hit is a pointer. Before anything is shown as evidence, or handed
to an answer writer (RET-007), it goes through this module:

1. **Resolve.** Every citation is checked against the stored, immutable
   message text: the revision must exist, the range must fit inside the
   text, and the quote's fingerprint must match the text at that range
   (and, when known, the speaker must match). A hit whose citation fails
   is **rejected** with a problem code, never returned. That is how stale
   references are caught: an index row pointing at a revision that has
   since been purged, or a record whose quote no longer matches.
2. **Hydrate.** A passing hit gets its **source window**: up to ``window``
   messages before it (its ancestors) and after it (following the chat's
   selected branch where it can), so a reader sees what the quote answered
   and what came next. Context is shown, but never cited.

A **citation** is ``(revision, start, end, quote fingerprint)`` with a
stable ID, ``kcit_`` + a hash of those four, so the same evidence always
has the same ID and an ID can be audited later (``audit``). It also says
whether the cited revision is still the message's newest version; an
older version is still valid evidence (snapshots are immutable), and the
flag lets a reader see that the message was later edited.

For a message hit, the citation covers the whole message. For a record
hit, each of the record's evidence references is a citation; if any of
them fails, the record is rejected.

Talking points:
    - "Nothing is cited unless the exact quote is still there at the exact
      place, checked by fingerprint."
    - "You get a couple of messages either side for context, but only the
      matched message is ever cited."
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.domain.enums import Role
from knowledge_engine.extraction.evidence import revision_text
from knowledge_engine.extraction.records import KnowledgeRecord
from knowledge_engine.extraction.store import KnowledgeRecordRow
from knowledge_engine.graph.offsets import Span, quote_hash, verify
from knowledge_engine.importer.records import MessageNodeRow, MessageRevisionRow
from knowledge_engine.rendering.transcript import StoredConversation, load_conversation
from knowledge_engine.retrieval.hybrid import HybridHit

CITATION_VERSION = "ret-006-v1"


class Problem(StrEnum):
    """Why a citation was rejected."""

    REVISION_MISSING = "revision_missing"
    SPAN_OUT_OF_RANGE = "span_out_of_range"
    QUOTE_MISMATCH = "quote_mismatch"
    ACTOR_MISMATCH = "actor_mismatch"
    NO_TEXT = "no_text"
    RECORD_MISSING = "record_missing"
    ID_MISMATCH = "id_mismatch"


@dataclass(frozen=True)
class Citation:
    """A checked pointer to exact, stored text.

    Attributes:
        citation_id: ``kcit_`` + hash of revision, start, end and fingerprint.
        revision_id: The exact message version.
        start: First character (inclusive), in code points.
        end: Last character (exclusive).
        quote_sha256: The quote's fingerprint (``graph.offsets.quote_hash``).
        actor: Who wrote the message.
        conversation_id: Its chat.
        node_key: Its logical message.
        native_node_id: The export's node ID.
        create_time: When it was written, as exported.
        newest_version: False if the message was edited in a later export.
    """

    citation_id: str
    revision_id: str
    start: int
    end: int
    quote_sha256: str
    actor: str
    conversation_id: str
    node_key: str
    native_node_id: str
    create_time: float | None
    newest_version: bool


@dataclass(frozen=True)
class Rejected:
    """A citation (or hit) that failed, and why."""

    key: str
    problem: Problem


def citation_id(revision_id: str, start: int, end: int, quote_sha256: str) -> str:
    """The stable ID of one piece of evidence."""
    digest = hashlib.sha256(f"{revision_id}|{start}|{end}|{quote_sha256}".encode())
    return "kcit_" + digest.hexdigest()[:32]


def resolve(
    session: Session,
    revision_id: str,
    start: int,
    end: int,
    quote_sha256: str,
    *,
    actor: Role | None = None,
) -> Citation | Rejected:
    """Check one reference against the stored text; a Citation only if it holds."""
    found = revision_text(session, revision_id)
    if found is None:
        return Rejected(revision_id, Problem.REVISION_MISSING)
    text, speaker = found
    if start < 0 or end > len(text) or end <= start:
        return Rejected(revision_id, Problem.SPAN_OUT_OF_RANGE)
    if not verify(text, Span(start, end), quote_sha256):
        return Rejected(revision_id, Problem.QUOTE_MISMATCH)
    if actor is not None and actor is not speaker:
        return Rejected(revision_id, Problem.ACTOR_MISMATCH)
    node_key, native, conversation, created, newest = _place(session, revision_id)
    return Citation(
        citation_id(revision_id, start, end, quote_sha256),
        revision_id,
        start,
        end,
        quote_sha256,
        speaker.value,
        conversation,
        node_key,
        native,
        created,
        newest,
    )


def cite_message(session: Session, revision_id: str) -> Citation | Rejected:
    """A citation of a whole message (rejected if it is missing or has no text)."""
    found = revision_text(session, revision_id)
    if found is None:
        return Rejected(revision_id, Problem.REVISION_MISSING)
    text = found[0]
    if not text.strip():
        return Rejected(revision_id, Problem.NO_TEXT)
    return resolve(session, revision_id, 0, len(text), quote_hash(text))


def quote(session: Session, citation: Citation) -> str:
    """The cited text itself (call only with a resolved citation)."""
    found = revision_text(session, citation.revision_id)
    assert found is not None, "a resolved citation's revision is immutable"
    return found[0][citation.start : citation.end]


def audit(session: Session, citations: Iterable[Citation]) -> list[Rejected]:
    """Re-check citations, e.g. ones an answer claims to rest on; empty if all hold.

    Each must still resolve, and its ID must be the one its contents give,
    so an invented or altered ID is caught.
    """
    problems = []
    for cited in citations:
        if cited.citation_id != citation_id(
            cited.revision_id, cited.start, cited.end, cited.quote_sha256
        ):
            problems.append(Rejected(cited.citation_id, Problem.ID_MISMATCH))
            continue
        again = resolve(session, cited.revision_id, cited.start, cited.end, cited.quote_sha256)
        if isinstance(again, Rejected):
            problems.append(Rejected(cited.citation_id, again.problem))
    return problems


def _place(session: Session, revision_id: str) -> tuple[str, str, str, float | None, bool]:
    node_key, native, conversation, created = session.execute(
        select(
            MessageNodeRow.node_key,
            MessageNodeRow.native_node_id,
            MessageNodeRow.conversation_id,
            MessageRevisionRow.create_time,
        )
        .join(MessageRevisionRow, MessageRevisionRow.node_key == MessageNodeRow.node_key)
        .where(MessageRevisionRow.revision_id == revision_id)
    ).one()
    # The same rule the transcript uses: the latest stored revision is the newest version.
    newest = session.scalars(
        select(MessageRevisionRow.revision_id)
        .where(MessageRevisionRow.node_key == node_key)
        .order_by(MessageRevisionRow.created_at.desc(), MessageRevisionRow.revision_id.desc())
    ).first()
    return node_key, native, conversation, created, newest == revision_id


@dataclass(frozen=True)
class ContextMessage:
    """A neighbouring message shown for context (never cited).

    Attributes:
        offset: Messages before (negative) or after (positive) the cited one.
        native_node_id: The export's node ID.
        node_key: Its logical message.
        revision_id: Its newest version.
        role: Who wrote it.
        text: Its text.
    """

    offset: int
    native_node_id: str
    node_key: str
    revision_id: str
    role: str | None
    text: str


@dataclass(frozen=True)
class EvidenceBundle:
    """A hit that passed, with its citations, quoted passages and context.

    Attributes:
        hit: The search hit.
        citations: Its checked citations.
        passages: The cited text, one per citation.
        context: Neighbouring messages around the first citation, in order.
    """

    hit: HybridHit
    citations: tuple[Citation, ...]
    passages: tuple[str, ...]
    context: tuple[ContextMessage, ...]


@dataclass(frozen=True)
class Hydrated:
    """What ``hydrate`` kept and what it rejected (in the hits' order)."""

    bundles: tuple[EvidenceBundle, ...]
    rejected: tuple[Rejected, ...]


def hydrate(session: Session, hits: Sequence[HybridHit], *, window: int = 2) -> Hydrated:
    """Check each hit's citations and add its source window. Reads only.

    Args:
        session: A read session on the archive.
        hits: From the hybrid search or a route (RET-004/005).
        window: Messages of context before and after (0 for none).

    Returns:
        Bundles for the hits whose citations all hold; the rest, rejected.
    """
    bundles, rejected = [], []
    chats: dict[str, StoredConversation] = {}
    for hit in hits:
        cited = _cite(session, hit)
        if isinstance(cited, Rejected):
            rejected.append(cited)
            continue
        first = cited[0]
        if first.conversation_id not in chats:
            chats[first.conversation_id] = load_conversation(session, first.conversation_id)
        bundles.append(
            EvidenceBundle(
                hit,
                tuple(cited),
                tuple(quote(session, c) for c in cited),
                _window(chats[first.conversation_id], first.native_node_id, window),
            )
        )
    return Hydrated(tuple(bundles), tuple(rejected))


def _cite(session: Session, hit: HybridHit) -> list[Citation] | Rejected:
    if hit.kind == "message":
        if hit.revision_id is None:
            return Rejected(hit.key, Problem.REVISION_MISSING)
        cited = cite_message(session, hit.revision_id)
        return [cited] if isinstance(cited, Citation) else Rejected(hit.key, cited.problem)
    row = session.get(KnowledgeRecordRow, hit.key)
    if row is None:
        return Rejected(hit.key, Problem.RECORD_MISSING)
    record = KnowledgeRecord.model_validate_json(row.record_json)
    found = []
    for ref in record.evidence:
        one = resolve(
            session, ref.revision_id, ref.start, ref.end, ref.quote_sha256, actor=ref.actor
        )
        if isinstance(one, Rejected):
            return Rejected(hit.key, one.problem)  # one bad quote rejects the record
        found.append(one)
    return found or Rejected(hit.key, Problem.NO_TEXT)


def _window(chat: StoredConversation, native: str, window: int) -> tuple[ContextMessage, ...]:
    if window <= 0:
        return ()
    nodes = chat.graph.nodes
    selected = set(chat.graph.active_path)

    def message(node: str, offset: int) -> ContextMessage | None:
        if node not in chat.messages or node not in chat.revisions:
            return None
        return ContextMessage(
            offset,
            node,
            chat.node_keys[node],
            chat.revisions[node],
            nodes[node].role,
            chat.messages[node].text,
        )

    before: list[ContextMessage] = []
    node = nodes[native].parent_id if native in nodes else None
    while node is not None and len(before) < window:
        found = message(node, -(len(before) + 1))
        if found is not None and found.text.strip():
            before.append(found)
        node = nodes[node].parent_id
    after: list[ContextMessage] = []
    node = native
    while len(after) < window:
        children = nodes[node].children if node in nodes else ()
        if not children:
            break
        on_path = [c for c in children if c in selected]
        node = on_path[0] if on_path else sorted(children)[0]
        found = message(node, len(after) + 1)
        if found is not None and found.text.strip():
            after.append(found)
    return (*reversed(before), *after)
