"""What the pages show, read from the workspace database (UI-001).

Everything here only reads. The plain-words summary turns a stored import
report into sentences a non-programmer can act on.

Talking points:
    - "The report page doesn't recompute anything: it reads the receipt the
      import saved and explains it in plain English."
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from knowledge_engine.importer.ledger import ImportBatchRow
from knowledge_engine.importer.records import ConversationRow


@dataclass(frozen=True)
class ImportRow:
    """One past import, as the home page lists it."""

    import_id: str
    status: str
    started_at: datetime
    format_id: str
    conversations: dict[str, int]


def workspace_status(session: Session) -> dict[str, int]:
    """Return headline counts: conversations stored, present, not seen, imports."""
    present = session.scalar(
        select(func.count())
        .select_from(ConversationRow)
        .where(ConversationRow.presence == "present")
    )
    total = session.scalar(select(func.count()).select_from(ConversationRow))
    imports = session.scalar(select(func.count()).select_from(ImportBatchRow))
    return {
        "conversations": int(total or 0),
        "present": int(present or 0),
        "not_seen": int((total or 0) - (present or 0)),
        "imports": int(imports or 0),
    }


def list_imports(session: Session, limit: int = 50) -> list[ImportRow]:
    """Return the most recent imports, newest first."""
    rows = session.scalars(
        select(ImportBatchRow).order_by(ImportBatchRow.started_at.desc()).limit(limit)
    ).all()
    return [
        ImportRow(
            import_id=row.import_id,
            status=row.status,
            started_at=row.started_at,
            format_id=row.format_id,
            conversations=dict(_counts(row).get("conversations", {})),
        )
        for row in rows
    ]


def load_report(session: Session, import_id: str) -> dict[str, Any] | None:
    """Return one stored import report (counts, warnings, status), or None."""
    row = session.get(ImportBatchRow, import_id)
    if row is None:
        return None
    # The ledger's own columns win over the stored copy in the counts.
    return {
        **_counts(row),
        "import_id": row.import_id,
        "status": row.status,
        "started_at": row.started_at,
        "finished_at": row.finished_at,
        "format_id": row.format_id,
        "warnings": json.loads(row.warnings_json or "{}"),
    }


def plain_words(report: dict[str, Any]) -> list[tuple[str, str]]:
    """Explain a stored report as short sentences, each with a tone.

    Args:
        report: From ``load_report``.

    Returns:
        ``(tone, sentence)`` pairs; tone is ``good``, ``info`` or ``look``
        (something a person may want to check).
    """
    lines: list[tuple[str, str]] = []
    status = report.get("status")
    if status == "running":
        return [("info", "This import is still running, or it stopped before finishing.")]
    if status == "abandoned":
        return [("look", "This import stopped part-way. Running it again finishes the job.")]
    conversations: dict[str, int] = report.get("conversations", {})
    new, revised = conversations.get("new", 0), conversations.get("revised", 0)
    unchanged = conversations.get("unchanged", 0)
    lines.append(
        ("info", f"{_n(new, 'new chat')}, {_n(revised, 'changed chat')}, {unchanged} unchanged.")
    )
    if not new and not revised:
        lines.append(("good", "Nothing new: this export was already in the archive."))
    if branches := report.get("new_branches", 0):
        lines.append(
            (
                "info",
                f"{_n(branches, 'new branch', 'new branches')} (edited or regenerated messages).",
            )
        )
    if not_seen := conversations.get("not_seen", 0):
        lines.append(
            (
                "info",
                f"{_n(not_seen, 'chat')} weren't in this export. They are kept, marked "
                "'not seen', never deleted.",
            )
        )
    summary: dict[str, Any] = report.get("summary", {})
    if new_media := summary.get("new_media", 0):
        lines.append(("info", f"{_n(new_media, 'new image or file', 'new images or files')}."))
    occurrences: dict[str, int] = report.get("asset_occurrences", {})
    problems = {state: n for state, n in occurrences.items() if state != "available" and n}
    if problems:
        detail = ", ".join(f"{n} {state}" for state, n in sorted(problems.items()))
        lines.append(("look", f"Some images couldn't be found or matched: {detail}."))
    if candidates := summary.get("candidate_duplicates", 0):
        lines.append(
            ("look", f"{_n(candidates, 'chat')} set aside because its ID was missing or clashed.")
        )
    if failed := summary.get("failed", 0):
        lines.append(("look", f"{_n(failed, 'chat')} couldn't be imported."))
    integrity: dict[str, Any] = report.get("integrity", {})
    if integrity and not integrity.get("reconciled", True):
        mismatches = ", ".join(integrity.get("mismatches", []))
        lines.append(("look", f"The source and the archive disagree on: {mismatches}."))
    elif integrity:
        lines.append(("good", "Every message and image reference in the source is accounted for."))
    if report.get("raw_tree_unchanged") is True:
        lines.append(("good", "Your original files were not changed."))
    elif report.get("raw_tree_unchanged") is False:
        lines.append(("look", "The source folder changed while it was being read. Run it again."))
    rebuild = summary.get("rebuild", {})
    if rebuild.get("conversations"):
        lines.append(
            ("info", f"{_n(rebuild['conversations'], 'chat')} will be (re)analysed by later steps.")
        )
    return lines


def _counts(row: ImportBatchRow) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(row.counts_json or "{}")
    return data


def _n(count: int, singular: str, plural: str | None = None) -> str:
    return f"{count} {singular if count == 1 else (plural or singular + 's')}"


# ---------------------------------------------------------------- UI-003

_IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}


@dataclass(frozen=True)
class ChatRow:
    """One conversation in the chat list."""

    conversation_id: str
    title: str
    created: datetime | None
    presence: str
    messages: int


def _vocabulary_names(snapshot: Any) -> dict[str, tuple[str, str]]:
    names = {t.term_id: (t.dimension, t.label) for t in snapshot.terms}
    names |= {p.project_id: ("project", p.name) for p in snapshot.projects}
    return names


def vocabulary_choices(session: Session) -> list[dict[str, Any]]:
    """Every approved term and project in the newest published vocabulary (UI-009).

    For the search page's Category list. It reads only the published
    snapshot, never the chats, so showing the form stays cheap on a big
    archive. Sorted by dimension then label. Nothing published: empty.
    """
    from knowledge_engine.retrieval.filters import newest_snapshot

    snapshot = newest_snapshot(session)
    if snapshot is None:
        return []
    names = _vocabulary_names(snapshot)
    return [
        {"dimension": names[i][0], "id": i, "label": names[i][1]}
        for i in sorted(names, key=lambda i: (names[i][0], names[i][1].casefold(), i))
    ]


def chat_categories(
    session: Session,
) -> tuple[list[dict[str, Any]], dict[str, frozenset[str]], frozenset[str]]:
    """Approved terms and projects that label at least one chat, with counts (UI-009).

    Uses the newest published vocabulary and labels in force, like search's
    ``--term``. This reads every segment's labels once, so only the chats
    page (which shows counts) calls it.

    Returns:
        The choices for the page (dimension, ID, label, chats) sorted by
        dimension then label; ID -> the chats it labels; and every approved
        ID, so an approved term on no chat yet is "0 chats", not "unknown".
        Nothing published yet: all empty.
    """
    from knowledge_engine.retrieval.filters import chats_by_label, newest_snapshot

    snapshot = newest_snapshot(session)
    if snapshot is None:
        return [], {}, frozenset()
    labelled = chats_by_label(session, snapshot)
    names = _vocabulary_names(snapshot)
    # A label no longer approved in this version isn't offered.
    offered = sorted(
        (i for i in labelled if i in names),
        key=lambda i: (names[i][0], names[i][1].casefold(), i),
    )
    choices: list[dict[str, Any]] = [
        {"dimension": names[i][0], "id": i, "label": names[i][1], "chats": len(labelled[i])}
        for i in offered
    ]
    return choices, {i: labelled[i] for i in offered}, frozenset(names)


def list_conversations(
    session: Session,
    query: str = "",
    offset: int = 0,
    limit: int = 100,
    *,
    since: float | None = None,
    until: float | None = None,
    only: frozenset[str] | None = None,
) -> tuple[list[ChatRow], int]:
    """Return one page of conversations, newest first, optionally filtered.

    Args:
        session: A read session.
        query: Words to look for in titles (case-insensitive); empty for all.
        offset: How many to skip.
        limit: Page size.
        since: Only chats started at or after this time (epoch seconds).
        until: Only chats started before this time (epoch seconds).
        only: Only these ``conv_`` IDs (a category filter), if given.

    Returns:
        The page and the total number of matches.
    """
    from knowledge_engine.importer.records import MessageNodeRow, MessageRevisionRow

    where = []
    # A chat with no start time can't be placed in a date range (UI-009).
    if since is not None:
        where.append(ConversationRow.create_time >= since)
    if until is not None:
        where.append(ConversationRow.create_time < until)
    if only is not None:
        where.append(ConversationRow.conversation_id.in_(sorted(only)))
    if query.strip():
        # Escape LIKE's wildcards so a search for "100%" means the text "100%".
        pattern = query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        where.append(ConversationRow.title.ilike(f"%{pattern}%", escape="\\"))
    total = session.scalar(select(func.count()).select_from(ConversationRow).where(*where))
    # Messages = nodes that carry a message (the tree's empty root doesn't).
    nodes = (
        select(
            MessageNodeRow.conversation_id,
            func.count(func.distinct(MessageRevisionRow.node_key)).label("n"),
        )
        .join(MessageRevisionRow, MessageRevisionRow.node_key == MessageNodeRow.node_key)
        .group_by(MessageNodeRow.conversation_id)
        .subquery()
    )
    rows = session.execute(
        select(ConversationRow, nodes.c.n)
        .outerjoin(nodes, nodes.c.conversation_id == ConversationRow.conversation_id)
        .where(*where)
        .order_by(ConversationRow.create_time.desc().nulls_last(), ConversationRow.conversation_id)
        .offset(offset)
        .limit(limit)
    ).all()
    page = [
        ChatRow(
            conversation_id=row.conversation_id,
            title=row.title or "Untitled conversation",
            created=datetime.fromtimestamp(row.create_time, UTC) if row.create_time else None,
            presence=row.presence,
            messages=int(n or 0),
        )
        for row, n in rows
    ]
    return page, int(total or 0)


def conversation_page(session: Session, conversation_id: str) -> dict[str, Any] | None:
    """Return everything the chat page shows, or None if there's no such chat.

    The page follows the transcript note exactly (BRW-001): the active path,
    then each alternate branch labelled with where it leaves, then anything
    outside the tree. Every message appears once.

    Args:
        session: A read session.
        conversation_id: The ``conv_`` ID.

    Returns:
        Title, facts and sections, ready for the template.
    """
    from knowledge_engine.rendering.media import REASONS
    from knowledge_engine.rendering.transcript import (
        load_conversation,
        message_anchor,
        transcript_sections,
    )

    try:
        conversation = load_conversation(session, conversation_id)
    except KeyError:
        return None
    graph = conversation.graph

    def message(native_id: str, numbered: bool) -> dict[str, Any]:
        node = conversation.messages[native_id]
        revision = conversation.revisions.get(native_id, "")
        media = []
        for ref in conversation.media.get(revision, []):
            available = ref.availability == "available" and ref.blob_sha256
            media.append(
                {
                    "state": ref.availability,
                    "pointer": ref.pointer,
                    "reason": REASONS.get(ref.rule or "", "no reason recorded"),
                    "url": f"/media/{ref.blob_sha256}" if available else None,
                    "inline": bool(available) and ref.media_type in _IMAGE_TYPES,
                    # Every message using the same file is listed on this page.
                    "asset": f"/assets/{ref.asset_id}" if ref.asset_id else None,
                }
            )
        return {
            "anchor": message_anchor(conversation.node_keys[native_id]),
            "number": graph.message_number(native_id) if numbered else None,
            "role": node.role or "unknown",
            "text": node.text or "",
            "media": media,
        }

    sections = []
    for section in transcript_sections(conversation):
        where: dict[str, Any] = {}
        if section.kind == "alternate":
            parent = section.parent
            if section.detached or parent is None:
                where = {"text": "Their parent message is missing from the export."}
            elif (number := graph.message_number(parent)) is not None:
                where = {
                    "text": f"Branches off after message {number} of the active path.",
                    "anchor": message_anchor(conversation.node_keys[parent]),
                }
            elif parent in conversation.messages:
                where = {
                    "text": "Branches off after another branch's message.",
                    "anchor": message_anchor(conversation.node_keys[parent]),
                }
            else:
                where = {"text": "Branches off at the start of the conversation."}
        sections.append(
            {
                "kind": section.kind,
                "branch_kind": section.branch_kind,
                "detached": section.detached,
                "where": where,
                "messages": [message(n, section.kind == "active") for n in section.messages],
            }
        )
    return {
        "conversation_id": conversation.conversation_id,
        "title": conversation.title or "Untitled conversation",
        "created": (
            datetime.fromtimestamp(conversation.create_time, UTC)
            if conversation.create_time
            else None
        ),
        "presence": conversation.presence,
        "messages": len(conversation.messages),
        "branch_points": len(graph.branch_points),
        "images": sum(len(uses) for uses in conversation.media.values()),
        "sections": sections,
        "related": related_view(session, [conversation.conversation_id]).get(
            conversation.conversation_id, []
        ),
    }


_KIND_WORDS = {
    "continues": "continues",
    "forked_from": "was forked from",
    "quotes": "quotes",
    "references": "links to",
    "related_to": "is related to",
    "same_project": "is in the same project as",
}


def related_view(session: Session, conversation_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    """Chat -> its visible links, phrased for a page (rejected links are left out).

    Each entry reads in the link's stored direction: "This chat continues X"
    or "X continues this chat".
    """
    from knowledge_engine.relationships.view import related_by_conversation

    grouped = related_by_conversation(session, conversation_ids)
    others = {link.other(c) for c, links in grouped.items() for link in links}
    titles = dict(
        session.execute(
            select(ConversationRow.conversation_id, ConversationRow.title).where(
                ConversationRow.conversation_id.in_(sorted(others))
            )
        )
        .tuples()
        .all()
    )
    view: dict[str, list[dict[str, Any]]] = {}
    for conversation_id, links in grouped.items():
        view[conversation_id] = [
            {
                "relationship_id": link.relationship_id,
                "other": link.other(conversation_id),
                "other_title": titles.get(link.other(conversation_id)) or "Untitled conversation",
                "outgoing": link.from_conversation_id == conversation_id,
                "words": _KIND_WORDS.get(link.kind, link.kind),
                "state": link.review_state,
                "because": list(link.because),
            }
            for link in links
        ]
    return view


def media_file(session: Session, store_root: Path, blob_sha256: str) -> tuple[bytes, str] | None:
    """Return a stored image's bytes and media type, after checking its fingerprint.

    Args:
        session: A read session.
        store_root: The workspace's content-addressed store.
        blob_sha256: The fingerprint from the page's link.

    Returns:
        ``(bytes, media_type)``, or None if unknown, gone or changed. Only
        known image types get their real type; anything else is sent as a
        download so a browser never runs it.
    """
    from knowledge_engine.importer.media import MediaBlobRow
    from knowledge_engine.rendering.media import blob_sources

    row = session.get(MediaBlobRow, blob_sha256)
    if row is None:
        return None
    try:
        content = blob_sources(session, store_root)(blob_sha256).read_bytes()
    except OSError:
        return None
    # Reference-mode files live outside the workspace and could have been
    # edited since import: serve them only if they are still the same bytes.
    if hashlib.sha256(content).hexdigest() != blob_sha256:
        return None
    media_type = row.media_type if row.media_type in _IMAGE_TYPES else "application/octet-stream"
    return content, media_type
