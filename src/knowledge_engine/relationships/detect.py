"""Deterministic detectors for links between conversations (REL-002).

Four detectors, each using only exact evidence:

* **shared node IDs** (native): two conversations contain a message with the
  same native node ID, as when ChatGPT copies messages into a new chat. The
  newer one is proposed as ``forked_from`` the older. Each chat gets **one
  parent**: the older chat it shares the most nodes with, the earliest on a
  tie. Two forks of the same chat both hold their parent's nodes, and a fork
  of a fork holds its grandparent's, but neither is the chat it came from
  (EVAL-012 caught the engine calling siblings and grandparents parents);
* **copied prefix** (structural): two conversations open with the same
  messages, word for word, in the same order (at least two, including a user
  message; OD-12). The newer one is proposed as ``forked_from`` the earlier
  conversation it shares the longest opening with (the earliest on a tie),
  unless shared node IDs already gave it a parent. A pasted setup prompt
  ("You are...") at the very start is skipped first (NOTE-009): many
  unrelated chats open with the same one;
* **ChatGPT URLs** (native): a message links to ``chatgpt.com/c/<id>`` and
  ``<id>`` is a conversation in the archive: ``references``. Share links
  (``/share/<id>``) use a different ID that the export doesn't map to a
  conversation, so they are only counted as unresolved;
* **verbatim quotes** (lexical): a user message contains a whole paragraph
  (100+ characters) that first appeared in an earlier, different
  conversation: ``quotes``. A paragraph found in more than five
  conversations is treated as boilerplate and ignored, and so is a pasted
  setup prompt ("You are...", NOTE-009), however few chats share it.

Everything is proposed as a ``candidate``. Similar wording, the same title
or the same topic is never evidence here: that is REL-003's job, and even
there similarity can't prove a fork (ADR-0005).

When two conversations have no usable create times, which came first is
unknown, so the link is proposed as ``related_to`` instead of guessing a
direction.

Talking points:
    - "Each detector looks for proof, not resemblance: the same IDs, the
      same opening messages, a link, or a pasted paragraph."
    - "If I can't tell which chat came first, I don't guess a direction."
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter, defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field
from itertools import combinations
from urllib.parse import urlsplit

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from knowledge_engine.extraction.preamble import looks_like_preamble
from knowledge_engine.graph.nodes import NodeFlag
from knowledge_engine.importer.records import ConversationRow, MessageNodeRow, MessageRevisionRow
from knowledge_engine.links.store import LinkOccurrenceRow, LinkTargetRow
from knowledge_engine.relationships.store import EvidenceClass, RelationKind, propose
from knowledge_engine.rendering.transcript import load_conversation

PREFIX_DETECTOR = "prefix-v1"
NATIVE_NODE_DETECTOR = "native-node-v1"
URL_DETECTOR = "chatgpt-url-v1"
QUOTE_DETECTOR = "quote-v1"

MIN_PREFIX = 2  # OD-12
MIN_QUOTE_CHARS = 100
MAX_QUOTE_SPREAD = 5  # more conversations than this: boilerplate

_CHATGPT_HOSTS = frozenset({"chatgpt.com", "www.chatgpt.com", "chat.openai.com"})
_CONVERSATION_PATH = re.compile(r"^(?:/g/[^/]+)?/c/([0-9A-Za-z-]{8,})/?$")
_SHARE_PATH = re.compile(r"^/share/[0-9A-Za-z-]{8,}/?$")
_SPACE = re.compile(r"\s+")
_SPOKEN = frozenset({"user", "assistant"})


@dataclass
class _Chat:
    conversation_id: str
    create_time: float | None
    # Text keys of the active path's spoken messages, in order.
    opening: list[tuple[str, str]] = field(default_factory=list)  # (role, key)
    opening_revisions: list[str] = field(default_factory=list)
    # Paragraph key -> (revision ID, role, message create time), first seen.
    paragraphs: dict[str, tuple[str, str, float | None]] = field(default_factory=dict)


def detect_relationships(
    session: Session, *, workspace_id: str, import_id: str | None
) -> Counter[str]:
    """Run every structural detector over the whole workspace.

    Safe to run any number of times: known relationships, whatever their
    review state, are never changed or proposed again.

    Args:
        session: A write session.
        workspace_id: Only conversations in this workspace are compared.
        import_id: The batch to credit new candidates to, if any.

    Returns:
        Counts: ``new_<detector kind>`` per new candidate, and
        ``unresolved_share_links``.
    """
    counts: Counter[str] = Counter()
    chats = {chat.conversation_id: chat for chat in _load(session, workspace_id)}
    forks: set[frozenset[str]] = set()

    native = list(_shared_nodes(session, workspace_id, chats))
    for older, newer, evidence in native:
        forks.add(frozenset((older, newer)))
        if _propose(
            session,
            chats,
            newer,
            older,
            RelationKind.FORKED_FROM,
            EvidenceClass.NATIVE,
            1.0,
            NATIVE_NODE_DETECTOR,
            evidence,
            import_id,
        ):
            counts["new_forked_from_native"] += 1

    # Shared node IDs are the stronger proof: a chat they gave a parent
    # doesn't get a second one from a copied opening.
    has_parent = {newer for _, newer, _ in native}
    for older, newer, shared in _copied_prefixes(list(chats.values())):
        if newer in has_parent or frozenset((older, newer)) in forks:
            continue
        forks.add(frozenset((older, newer)))
        evidence = {
            "shared_messages": shared,
            "revisions": {
                "from": chats[newer].opening_revisions[:shared],
                "to": chats[older].opening_revisions[:shared],
            },
        }
        confidence = min(0.9, 0.5 + 0.1 * shared)
        if _propose(
            session,
            chats,
            newer,
            older,
            RelationKind.FORKED_FROM,
            EvidenceClass.STRUCTURAL,
            confidence,
            PREFIX_DETECTOR,
            evidence,
            import_id,
        ):
            counts["new_forked_from_prefix"] += 1

    references, unresolved = _chatgpt_links(session, workspace_id)
    counts["unresolved_share_links"] += unresolved
    for source, target, occurrences in references:
        if source == target or source not in chats or target not in chats:
            continue
        added = propose(
            session,
            from_conversation_id=source,
            kind=RelationKind.REFERENCES,
            to_conversation_id=target,
            evidence_class=EvidenceClass.NATIVE,
            confidence=1.0,
            detector=URL_DETECTOR,
            evidence={"link_occurrences": occurrences},
            import_id=import_id,
        )
        counts["new_references"] += added

    for quoter, quoted, pieces in _quotes(list(chats.values())):
        if frozenset((quoter, quoted)) in forks:
            continue  # the shared text is the fork's copied opening
        added = propose(
            session,
            from_conversation_id=quoter,
            kind=RelationKind.QUOTES,
            to_conversation_id=quoted,
            evidence_class=EvidenceClass.LEXICAL,
            confidence=0.8,
            detector=QUOTE_DETECTOR,
            evidence={"paragraphs": len(pieces), "revisions": pieces},
            import_id=import_id,
        )
        counts["new_quotes"] += added
    return Counter({k: v for k, v in counts.items() if v})


def _propose(
    session: Session,
    chats: dict[str, _Chat],
    newer: str,
    older: str,
    kind: RelationKind,
    evidence_class: EvidenceClass,
    confidence: float,
    detector: str,
    evidence: dict[str, object],
    import_id: str | None,
) -> bool:
    # Without both create times there's no "older": record the link
    # without a direction claim.
    if _order(chats[newer], chats[older]) is None:
        kind = RelationKind.RELATED_TO
        evidence = {**evidence, "direction": "unknown"}
    return propose(
        session,
        from_conversation_id=newer,
        kind=kind,
        to_conversation_id=older,
        evidence_class=evidence_class,
        confidence=confidence,
        detector=detector,
        evidence=evidence,
        import_id=import_id,
    )


def _order(a: _Chat, b: _Chat) -> tuple[_Chat, _Chat] | None:
    """Return (older, newer), or None if their times don't say."""
    if a.create_time is None or b.create_time is None or a.create_time == b.create_time:
        return None
    return (a, b) if a.create_time < b.create_time else (b, a)


def _older_newer(a: _Chat, b: _Chat) -> tuple[str, str]:
    # A stable pair order even when times are missing (ID order then).
    ordered = _order(a, b)
    if ordered is None:
        first, second = sorted((a, b), key=lambda chat: chat.conversation_id)
        return first.conversation_id, second.conversation_id
    return ordered[0].conversation_id, ordered[1].conversation_id


def _key(*parts: str) -> str:
    return hashlib.sha256("\x00".join(parts).encode("utf-8")).hexdigest()


def _normal(text: str) -> str:
    return _SPACE.sub(" ", text).strip()


def _load(session: Session, workspace_id: str) -> Iterator[_Chat]:
    ids = session.scalars(
        select(ConversationRow.conversation_id)
        .where(ConversationRow.workspace_id == workspace_id)
        .order_by(ConversationRow.conversation_id)
    ).all()
    for conversation_id in ids:
        stored = load_conversation(session, conversation_id)
        chat = _Chat(conversation_id, stored.create_time)
        for native_id in stored.graph.active_messages:
            node = stored.messages.get(native_id)
            if node is None or node.role not in _SPOKEN or NodeFlag.HIDDEN in node.flags:
                continue
            text = _normal(node.text)
            if not text:
                continue
            if not chat.opening and looks_like_preamble(node.role, node.text):
                continue  # chats that open with one pasted setup prompt are not copies
            chat.opening.append((node.role, _key(node.role, text)))
            chat.opening_revisions.append(stored.revisions[native_id])
        for native_id, node in stored.messages.items():
            revision = stored.revisions.get(native_id)
            if revision is None or node.role not in _SPOKEN:
                continue
            if looks_like_preamble(node.role, node.text):
                continue  # a pasted setup prompt is shared boilerplate, not a quote
            for paragraph in re.split(r"\n\s*\n", node.text):
                text = _normal(paragraph)
                if len(text) < MIN_QUOTE_CHARS:
                    continue
                key = _key(text)
                seen = chat.paragraphs.get(key)
                if seen is None or _earlier(node.create_time, seen[2]):
                    chat.paragraphs[key] = (revision, node.role, node.create_time)
        yield chat


def _earlier(a: float | None, b: float | None) -> bool:
    return a is not None and (b is None or a < b)


def _copied_prefixes(chats: list[_Chat]) -> Iterator[tuple[str, str, int]]:
    """Yield (older, newer, shared count) for each copied opening.

    Each conversation is linked once: to the conversation it shares the
    longest opening with (earliest on a tie), so a prompt reused across
    many chats doesn't produce every pair.
    """
    groups: dict[tuple[tuple[str, str], ...], list[_Chat]] = defaultdict(list)
    for chat in chats:
        head = tuple(chat.opening[:MIN_PREFIX])
        if len(head) == MIN_PREFIX and any(role == "user" for role, _ in head):
            groups[head].append(chat)
    for members in groups.values():
        if len(members) < 2:
            continue
        members.sort(key=_age)  # so a tie keeps the earliest (strict > below)
        for chat in members:
            best: tuple[int, str] | None = None
            for other in members:
                if other is chat:
                    continue
                ordered = _order(chat, other)
                if ordered is not None and ordered[1] is not chat:
                    continue  # only look back in time
                if ordered is None and other.conversation_id > chat.conversation_id:
                    continue  # unknown order: report each pair once
                shared = _common(chat.opening, other.opening)
                if best is None or shared > best[0]:
                    best = (shared, other.conversation_id)
            if best is not None and best[0] >= MIN_PREFIX:
                yield best[1], chat.conversation_id, best[0]


def _common(a: list[tuple[str, str]], b: list[tuple[str, str]]) -> int:
    count = 0
    for x, y in zip(a, b, strict=False):
        if x != y:
            break
        count += 1
    return count


def _shared_nodes(
    session: Session, workspace_id: str, chats: dict[str, _Chat]
) -> Iterator[tuple[str, str, dict[str, object]]]:
    """Yield (older, newer, evidence) for conversations sharing native node IDs."""
    shared = (
        select(MessageNodeRow.native_node_id)
        .join(ConversationRow, ConversationRow.conversation_id == MessageNodeRow.conversation_id)
        .join(MessageRevisionRow, MessageRevisionRow.node_key == MessageNodeRow.node_key)
        .where(ConversationRow.workspace_id == workspace_id)
        .where(MessageRevisionRow.role.in_(_SPOKEN))
        .group_by(MessageNodeRow.native_node_id)
        .having(func.count(func.distinct(MessageNodeRow.conversation_id)) > 1)
    )
    rows = session.execute(
        select(MessageNodeRow.native_node_id, MessageNodeRow.conversation_id)
        .where(MessageNodeRow.native_node_id.in_(shared))
        .order_by(MessageNodeRow.native_node_id, MessageNodeRow.conversation_id)
    ).all()
    by_node: dict[str, list[str]] = defaultdict(list)
    for native_id, conversation_id in rows:
        if conversation_id in chats:
            by_node[native_id].append(conversation_id)
    pairs: Counter[tuple[str, str]] = Counter()
    for members in by_node.values():
        for a, b in combinations(sorted(set(members)), 2):
            pairs[_older_newer(chats[a], chats[b])] += 1
    # One parent per chat: the older chat sharing the most nodes with it,
    # the earliest on a tie. A sibling holds only the parent's nodes (a tie,
    # which the parent wins by being older); a grandparent holds fewer of
    # them than the parent does.
    parent: dict[str, tuple[str, int]] = {}
    for (older, newer), count in sorted(pairs.items(), key=lambda item: _age(chats[item[0][0]])):
        if newer not in parent or count > parent[newer][1]:
            parent[newer] = (older, count)
    for newer, (older, count) in sorted(parent.items()):
        yield older, newer, {"shared_native_nodes": count}


def _age(chat: _Chat) -> tuple[bool, float, str]:
    """Sort key, oldest first; chats without a create time last, by ID."""
    return (chat.create_time is None, chat.create_time or 0.0, chat.conversation_id)


def _chatgpt_links(
    session: Session, workspace_id: str
) -> tuple[list[tuple[str, str, list[str]]], int]:
    """Return (source, target, occurrence IDs) per resolved link, and unresolved count."""
    rows = session.execute(
        select(
            LinkOccurrenceRow.conversation_id,
            LinkOccurrenceRow.occurrence_id,
            LinkTargetRow.canonical_url,
            ConversationRow.account_namespace,
        )
        .join(LinkTargetRow, LinkTargetRow.target_id == LinkOccurrenceRow.target_id)
        .join(ConversationRow, ConversationRow.conversation_id == LinkOccurrenceRow.conversation_id)
        .where(LinkTargetRow.host.in_(_CHATGPT_HOSTS))
        .where(ConversationRow.workspace_id == workspace_id)
        .order_by(LinkOccurrenceRow.occurrence_id)
    ).all()
    found: dict[tuple[str, str], list[str]] = defaultdict(list)
    unresolved = 0
    for source, occurrence, url, namespace in rows:
        path = urlsplit(url).path
        match = _CONVERSATION_PATH.match(path)
        if match is None:
            unresolved += bool(_SHARE_PATH.match(path))
            continue
        targets = session.execute(
            select(ConversationRow.conversation_id, ConversationRow.account_namespace).where(
                ConversationRow.workspace_id == workspace_id,
                ConversationRow.native_conversation_id == match.group(1),
            )
        ).all()
        # Same account first; another account's chat only if it's the only one.
        same = [t for t, ns in targets if ns == namespace]
        chosen = same or ([targets[0][0]] if len(targets) == 1 else [])
        if not chosen:
            unresolved += 1
            continue
        found[(source, chosen[0])].append(occurrence)
    return [(s, t, occ) for (s, t), occ in sorted(found.items())], unresolved


def _quotes(chats: list[_Chat]) -> Iterator[tuple[str, str, list[str]]]:
    """Yield (quoting conversation, quoted conversation, quoting revision IDs)."""
    where: dict[str, list[tuple[_Chat, tuple[str, str, float | None]]]] = defaultdict(list)
    for chat in chats:
        for key, seen in chat.paragraphs.items():
            where[key].append((chat, seen))
    pairs: dict[tuple[str, str], list[str]] = defaultdict(list)
    for places in where.values():
        if not 2 <= len(places) <= MAX_QUOTE_SPREAD:
            continue
        timed = [p for p in places if p[1][2] is not None]
        if len(timed) < 2:
            continue  # without times, who quoted whom is unknown
        source, (_, _, first_time) = min(timed, key=lambda p: (p[1][2], p[0].conversation_id))
        for chat, (revision, role, at) in timed:
            if chat is source or role != "user" or at is None or first_time is None:
                continue
            if at > first_time:
                pairs[(chat.conversation_id, source.conversation_id)].append(revision)
    for (quoter, quoted), revisions in sorted(pairs.items()):
        yield quoter, quoted, sorted(set(revisions))
