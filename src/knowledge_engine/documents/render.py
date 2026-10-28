"""Knowledge documents as Obsidian notes; the project master (DOC-004).

``knowledge_note`` turns a ``KnowledgeDocument`` (DOC-001) into a note model
for the DOC-002 renderer. Every item is written the same way:

* the record's assertion as its own paragraph, with a block anchor
  (``^krec-…``) so other notes and items can link to it. The assertion is
  imported text, so it is escaped;
* a list the engine writes itself: the **status label** ("Current",
  "Replaced by …", "In conflict with …", "Waiting for a check"...), the
  **sources** as links to the exact messages in the source transcripts
  (``[[note#^node-…]]``), and the record and event IDs behind it.

The rule that matters (DOC-004's acceptance): **an old choice is never
shown without its label.** Replaced decisions sit in their own "Replaced"
section, each saying which record replaced it and linking to it; disputes
show both sides, each labelled; nothing is merged into one line.

The **project master** is a project's document with three extra parts:

* ``mode``: ``current`` (what holds now, disputes and pending items),
  ``history`` (what was replaced, and the decision timeline), or ``all``;
* **Dependencies**: the typed connections between the project's records
  (REC-007 edges: creates, references, supersedes, conflicts...), each with
  its direction and origin;
* **Sources**: every chat the project's records come from, linked.

Talking points:
    - "Every line in a master note carries its status, so last year's
      decision can't pass for today's."
    - "Each item links to the exact message it came from, one click away."
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePosixPath

from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.documents.model import (
    DocItem,
    DocumentKind,
    KnowledgeDocument,
    build_document,
)
from knowledge_engine.domain.models import EvidenceRef
from knowledge_engine.extraction.records import KnowledgeRecord
from knowledge_engine.extraction.store import KnowledgeRecordRow
from knowledge_engine.importer.records import ConversationRow, MessageNodeRow, MessageRevisionRow
from knowledge_engine.reconciliation.graph import edges
from knowledge_engine.reconciliation.timeline import TimelineEntry, timeline
from knowledge_engine.relationships.view import RelatedLink, related_links
from knowledge_engine.rendering.markdown import (
    Block,
    BulletList,
    DocumentModel,
    Heading,
    Paragraph,
    PropertyValue,
    block_anchor,
    escape_text,
    render_note,
    safe_filename,
    safe_relative_path,
    write_note,
)
from knowledge_engine.rendering.transcript import message_anchor
from knowledge_engine.retrieval.citations import Citation, quote, resolve

RENDER_VERSION = "doc-004-v1"
PROJECTS_DIR = "Projects"


class Mode(StrEnum):
    """Which part of a project's story a master note tells."""

    CURRENT = "current"
    HISTORY = "history"
    ALL = "all"


_IN_MODE = {
    Mode.CURRENT: {"current", "conflicted", "pending", "unknown", "proposals", "other"},
    Mode.HISTORY: {"superseded", "proposals"},
    Mode.ALL: {"current", "conflicted", "pending", "unknown", "superseded", "proposals", "other"},
}


def record_anchor(record_id: str) -> str:
    """The block anchor of a record's paragraph (``krec_x`` -> ``krec-x``)."""
    return block_anchor(record_id.replace("_", "-", 1))


@dataclass(frozen=True)
class SourceLink:
    """Where a cited message lives in the vault."""

    conversation_id: str
    note: str  # the transcript note's file stem
    anchor: str  # the message's block anchor

    @property
    def wikilink(self) -> str:
        """``[[note#^anchor]]``."""
        return f"[[{self.note}#^{self.anchor}]]"


def transcript_stem(conversation_id: str, title: str | None) -> str:
    """The file stem BRW-001 gives a chat's transcript note."""
    suffix = conversation_id.replace("_", "-", 1)[:13]
    return safe_filename(title or "Untitled conversation", suffix).removesuffix(".md")


def source_links(session: Session, revision_ids: list[str]) -> dict[str, SourceLink]:
    """Revision ID -> a link to that message in its transcript note."""
    wanted = sorted(set(revision_ids))
    found: dict[str, SourceLink] = {}
    for start in range(0, len(wanted), 500):
        for revision, node_key, conversation, title in session.execute(
            select(
                MessageRevisionRow.revision_id,
                MessageNodeRow.node_key,
                ConversationRow.conversation_id,
                ConversationRow.title,
            )
            .join(MessageNodeRow, MessageNodeRow.node_key == MessageRevisionRow.node_key)
            .join(
                ConversationRow, ConversationRow.conversation_id == MessageNodeRow.conversation_id
            )
            .where(MessageRevisionRow.revision_id.in_(wanted[start : start + 500]))
        ):
            found[revision] = SourceLink(
                conversation, transcript_stem(conversation, title), message_anchor(node_key)
            )
    return found


MAX_CITED = 4  # evidence links per relationship line; the rest are counted


def relationship_lines(
    session: Session, links: Sequence[RelatedLink], *, here: str | None = None
) -> list[str]:
    """One bullet per link: both chats, kind, state, reasons and cited messages.

    Read in the stored direction: "[[B]] **continues** [[A]]". Seen from
    ``here`` (a chat's own note), that chat is called "this chat".
    """
    ends = {c for link in links for c in (link.from_conversation_id, link.to_conversation_id)}
    titles = {
        c: t
        for c, t in session.execute(
            select(ConversationRow.conversation_id, ConversationRow.title).where(
                ConversationRow.conversation_id.in_(sorted(ends))
            )
        )
    }
    cited = source_links(session, [r for link in links for r in link.revisions])

    def name(conversation_id: str) -> str:
        if conversation_id == here:
            return "this chat"
        return f"[[{transcript_stem(conversation_id, titles.get(conversation_id))}]]"

    lines = []
    for link in links:
        line = (
            f"{name(link.from_conversation_id)} **{link.kind}** "
            f"{name(link.to_conversation_id)} ({link.evidence_class}, confidence "
            f"{link.confidence:.2f}, {link.review_state}, `{link.relationship_id}`)"
        )
        if link.because:
            line += " because " + "; ".join(escape_text(b) for b in link.because)
        sources = [cited[r].wikilink for r in link.revisions if r in cited]
        if sources:
            more = len(sources) - MAX_CITED
            line += ". Evidence: " + ", ".join(sources[:MAX_CITED])
            line += f" and {more} more" if more > 0 else ""
        lines.append(line)
    return lines


_STATUS_WORDS = {
    "current": "Current",
    "conflicted": "In conflict",
    "pending": "Waiting for a check",
    "unknown": "Date unknown",
    "superseded": "Replaced",
    "accepted": "Accepted suggestion",
    "rejected": "Rejected suggestion",
    "open": "Open suggestion",
}


def _label(item: DocItem) -> str:
    word = _STATUS_WORDS.get(item.status, f"Trust: {item.status}")
    label = f"**{word}** {item.record_type} (by {item.actor})"
    if item.superseded_by:
        label += " · replaced by " + ", ".join(
            f"[[#^{record_anchor(r)}]]" for r in item.superseded_by
        )
    if item.conflicts_with:
        label += " · in conflict with " + ", ".join(
            f"[[#^{record_anchor(r)}]]" for r in item.conflicts_with
        )
    return label


def evidence_of(session: Session, record_ids: list[str]) -> dict[str, tuple[EvidenceRef, ...]]:
    """Record ID -> the evidence spans it was extracted with."""
    found: dict[str, tuple[EvidenceRef, ...]] = {}
    wanted = sorted(set(record_ids))
    for start in range(0, len(wanted), 500):
        for row in session.scalars(
            select(KnowledgeRecordRow).where(
                KnowledgeRecordRow.record_id.in_(wanted[start : start + 500])
            )
        ):
            found[row.record_id] = KnowledgeRecord.model_validate_json(row.record_json).evidence
    return found


def evidence_blocks(
    session: Session, refs: tuple[EvidenceRef, ...], links: dict[str, SourceLink]
) -> list[Block]:
    """Each evidence span as a quote with its speaker and a link to the message.

    The span is re-checked against the stored text first (RET-006): a quote
    is shown only if it still matches, word for word, and the speaker is
    the one the record names. Otherwise a marker says why it isn't shown.
    """
    blocks: list[Block] = []
    for ref in refs:
        found = resolve(
            session, ref.revision_id, ref.start, ref.end, ref.quote_sha256, actor=ref.actor
        )
        where = links[ref.revision_id].wikilink if ref.revision_id in links else "source not found"
        if not isinstance(found, Citation):
            blocks.append(Paragraph(f"> Evidence not shown: {found.problem.value} ({where})", True))
            continue
        said = " ".join(quote(session, found).split())  # one line, so the quote stays a quote
        blocks.append(
            Paragraph(f"> {escape_text(said)} (said by **{found.actor}**, {where})", True)
        )
    return blocks


def _item_blocks(
    item: DocItem,
    links: dict[str, SourceLink],
    quotes: list[Block] | None = None,
) -> list[Block]:
    sources = [links[r].wikilink for r in item.revisions if r in links]
    facts = [
        _label(item),
        "Sources: " + (", ".join(sources) if sources else "none found"),
        f"Record: `{item.record_id}`",
    ]
    if item.because:
        facts.append("Because: " + ", ".join(f"`{e}`" for e in item.because))
    return [
        Paragraph(item.assertion, anchor=record_anchor(item.record_id)),
        BulletList(tuple(facts), trusted=True),
        *(quotes or []),
    ]


def knowledge_note(
    session: Session,
    document: KnowledgeDocument,
    *,
    mode: Mode = Mode.ALL,
    title: str | None = None,
    quotes: bool = False,
) -> DocumentModel:
    """A note model for any knowledge document: labelled, linked items by section.

    With ``quotes``, each item is followed by its checked evidence quotes,
    each naming who said it (DOC-003).
    """
    links = source_links(session, list(document.revision_ids))
    spans = evidence_of(session, list(document.record_ids)) if quotes else {}
    if quotes:  # evidence can cite messages the item's own revisions don't list
        extra = [r.revision_id for refs in spans.values() for r in refs]
        links |= source_links(session, extra)
    blocks: list[Block] = []
    for section in document.sections:
        if section.key not in _IN_MODE[mode]:
            continue
        blocks.append(Heading(section.title, 2))
        for item in section.items:
            said = evidence_blocks(session, spans.get(item.record_id, ()), links) if quotes else []
            blocks += _item_blocks(item, links, said)
    properties: dict[str, PropertyValue] = {
        "ke_type": f"{document.kind.value}_knowledge",
        "document_id": document.document_id,
        "subject_id": document.subject_id,
        "mode": mode.value,
        "records": len(document.record_ids),
        "content_hash": document.content_hash,
        "generator": f"{document.builder_version}+{RENDER_VERSION}",
    }
    return DocumentModel(
        title=title or f"{document.kind.value.title()} {document.subject_id}",
        properties=properties,
        blocks=tuple(blocks),
    )


def _step(step: TimelineEntry) -> str:
    line = f"`{step.event_id}` "
    if step.from_record:
        line += f"[[#^{record_anchor(step.from_record)}]] "
    line += f"**{step.predicate}**"
    if step.to_record:
        line += f" [[#^{record_anchor(step.to_record)}]]"
    return line + (" (revoked)" if step.revoked else "")


def project_master(session: Session, project_id: str, *, mode: Mode = Mode.ALL) -> DocumentModel:
    """The project master note: labelled knowledge, dependencies, history and sources."""
    document = build_document(session, DocumentKind.PROJECT, project_id)
    note = knowledge_note(session, document, mode=mode, title=f"Project {project_id}")
    blocks = list(note.blocks)
    # Only records this mode shows, so no link points at a record the note leaves out.
    shown = {
        item.record_id
        for section in document.sections
        if section.key in _IN_MODE[mode]
        for item in section.items
    }
    if mode is not Mode.HISTORY:
        between = [e for e in edges(session) if e.source in shown and e.target in shown]
        if between:
            blocks.append(Heading("Dependencies", 2))
            blocks.append(
                BulletList(
                    tuple(
                        f"[[#^{record_anchor(e.source)}]] **{e.kind}** "
                        f"[[#^{record_anchor(e.target)}]] ({e.state}, by `{e.origin}`)"
                        for e in between
                    ),
                    trusted=True,
                )
            )
    if mode is not Mode.CURRENT:
        steps = [s for s in timeline(session, sorted(shown)) if s.revokes_event is None]
        if steps:
            blocks.append(Heading("Decision timeline", 2))
            blocks.append(BulletList(tuple(_step(s) for s in steps), trusted=True))
    links = source_links(session, list(document.revision_ids))
    chats = sorted({(link.conversation_id, link.note) for link in links.values()})
    if chats:
        blocks.append(Heading("Sources", 2))
        blocks.append(
            BulletList(tuple(f"[[{note}]] (`{conv}`)" for conv, note in chats), trusted=True)
        )
        related = relationship_lines(session, related_links(session, [c for c, _ in chats]))
        if related:
            blocks.append(Heading("Related conversations", 2))
            blocks.append(BulletList(tuple(related), trusted=True))
    return DocumentModel(note.title, note.properties, tuple(blocks))


def project_path(project_id: str, mode: Mode = Mode.ALL) -> PurePosixPath:
    """Where a project master lives in the vault (``Projects/…``)."""
    return safe_relative_path(PROJECTS_DIR, safe_filename(f"{project_id} {mode.value}", "master"))


def write_project_master(
    session: Session, project_id: str, vault_root: Path, *, mode: Mode = Mode.ALL
) -> PurePosixPath:
    """Write the project master into ``vault_root/Projects`` (unchanged notes aren't rewritten)."""
    note = project_master(session, project_id, mode=mode)
    relative = project_path(project_id, mode)
    write_note(vault_root, relative, render_note(note))
    return relative
