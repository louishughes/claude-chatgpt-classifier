"""Topic and project masters in the readable layout (NOTE-010).

The DOC-004/005 masters list every record the same way: the assertion, then
a list of its status, its sources and its record and event IDs, then its
quotes in full. Everything is there, but a reader has to dig. This module
renders the *same document* (``build_document``) with the rules the chat
notes follow (``docs/plans/RICH_NOTES_GAP_ANALYSIS.md`` §7):

* a **summary** box first, in the engine's own words: how many items, from
  how many chats, and how many are current, replaced or in conflict;
* each item is **one line**: the claim in bold, what kind it is and who
  holds it, its status, and short citations;
* a citation is ``[c2·m12]``: message 12 of chat 2, where the chats are
  numbered once in the **Chats** section at the end. A master spans many
  chats, so the chat number keeps each link short;
* quotes sit in a **folded** evidence box under the item, at most two, each
  re-checked word for word first (RET-006);
* the DOC-004 rule still holds: an old choice is never shown without its
  label. A replaced item says what replaced it, in words, not by ID;
* hashes, record IDs and event IDs go to a JSON sidecar in ``.meta/``;
* the front matter is flat, so Dataview can filter on any property.

Nothing here calls a model. The older layout stays the default; this one is
chosen with ``ke docs topic|project --template v2``.

Talking points:
    - "A master note now opens with a two-line summary and one line per
      decision, instead of a wall of IDs."
    - "Old choices still carry their label: 'Replaced by …' in plain words."
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.documents.model import (
    DocItem,
    DocumentKind,
    KnowledgeDocument,
    build_document,
)
from knowledge_engine.documents.notes import resolve_topic, topic_path, topic_segments
from knowledge_engine.documents.render import (
    _IN_MODE,
    Mode,
    SourceLink,
    evidence_of,
    project_path,
    source_links,
    transcript_stem,
)
from knowledge_engine.documents.rich_note import MAX_QUOTES, _short
from knowledge_engine.domain.models import EvidenceRef
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.reconciliation.graph import edges
from knowledge_engine.reconciliation.timeline import timeline
from knowledge_engine.relationships.view import related_links
from knowledge_engine.rendering.markdown import (
    Block,
    BulletList,
    Callout,
    DocumentModel,
    Heading,
    Paragraph,
    PropertyValue,
    escape_text,
    render_note,
    safe_relative_path,
    write_note,
)
from knowledge_engine.rendering.transcript import StoredConversation, load_conversation
from knowledge_engine.retrieval.citations import Citation, quote, resolve
from knowledge_engine.taxonomy.registry import TaxonomySnapshot

MASTER_TEMPLATE_VERSION = "note-010-master-v2"
META_DIR = ".meta"
SHORT_CHARS = 80  # a replaced item names its replacement in this many characters

# Body budget for a master: room for the fixed parts, then a line and a
# folded box per item and a line per chat. A master grows with its subject,
# so unlike a chat note it has no fixed ceiling; this stops it padding.
MASTER_BASE = 4_000
MASTER_PER_RECORD = 1_200
MASTER_PER_CHAT = 400

_PROVENANCE = {
    "current": "From the chats: what holds now, worked out from when each message was sent",
    "conflicted": "From the chats: these disagree and nothing has settled them yet",
    "pending": "From the chats: waiting for a check before they count",
    "unknown": "From the chats: the message has no date, so its standing is unknown",
    "superseded": "From the chats: replaced later, shown so the history is clear",
    "proposals": "From the chats: suggested, and whether the user took them up",
    "other": "From the chats",
}
_PROPOSAL_WORDS = {"accepted": "taken up", "rejected": "turned down", "open": "open"}


def master_budget(records: int, chats: int) -> int:
    """The most characters a master's body should take for this many items and chats."""
    return MASTER_BASE + MASTER_PER_RECORD * records + MASTER_PER_CHAT * chats


@dataclass(frozen=True)
class ReadableMaster:
    """A rendered-ready master and its sidecar data."""

    model: DocumentModel
    meta: dict[str, object]


class _Cites:
    """Numbers the chats a master cites and writes ``[c2·m12]`` links."""

    def __init__(self, session: Session, revision_ids: Sequence[str]) -> None:
        self.links: dict[str, SourceLink] = source_links(session, list(revision_ids))
        ids = sorted({link.conversation_id for link in self.links.values()})
        rows = (
            session.execute(
                select(ConversationRow.conversation_id, ConversationRow.create_time).where(
                    ConversationRow.conversation_id.in_(ids)
                )
            )
            .tuples()
            .all()
        )
        started = dict(rows)
        # Oldest chat first, so c1 is where the subject started.
        self.order = sorted(ids, key=lambda c: (started.get(c) or 0.0, c))
        self.number = {c: n for n, c in enumerate(self.order, 1)}
        self.chats: dict[str, StoredConversation] = {}
        self.session = session

    def add(self, conversation_id: str) -> None:
        """Give a chat a number even if no item cites it (a topic's labelled chat)."""
        if conversation_id not in self.number:
            self.order.append(conversation_id)
            self.number[conversation_id] = len(self.order)

    def chat(self, conversation_id: str) -> StoredConversation:
        if conversation_id not in self.chats:
            self.chats[conversation_id] = load_conversation(self.session, conversation_id)
        return self.chats[conversation_id]

    def label(self, revision_id: str) -> str | None:
        """``c2·m12``; ``c2·alt`` off the active path; ``c2`` for an older revision."""
        link = self.links.get(revision_id)
        if link is None:
            return None
        chat = self.chat(link.conversation_id)
        prefix = f"c{self.number[link.conversation_id]}"
        native = {rev: n for n, rev in chat.revisions.items()}.get(revision_id)
        if native is None:
            return prefix
        number = chat.graph.message_number(native)
        return f"{prefix}·m{number}" if number is not None else f"{prefix}·alt"

    def cite(self, revision_id: str) -> str | None:
        """The citation link for one message revision, or None if it isn't stored."""
        label = self.label(revision_id)
        if label is None:
            return None
        link = self.links[revision_id]
        return f"[[{link.note}#^{link.anchor}|{label}]]"

    def cites(self, revisions: Sequence[str]) -> str:
        found = [c for r in dict.fromkeys(revisions) if (c := self.cite(r))]
        return " ".join(found)


def _evidence(session: Session, refs: Sequence[EvidenceRef], cites: _Cites) -> Callout | None:
    """The folded evidence box for one item (re-checked quotes), or None."""
    if not refs:
        return None
    lines = []
    for ref in refs[:MAX_QUOTES]:
        where = cites.label(ref.revision_id) or "elsewhere"
        found = resolve(
            session, ref.revision_id, ref.start, ref.end, ref.quote_sha256, actor=ref.actor
        )
        if not isinstance(found, Citation):
            lines.append(f"{where}: quote not shown ({found.problem.value})")
            continue
        lines.append(f'{where} ({found.actor}): "{escape_text(_short(quote(session, found)))}"')
    if len(refs) > MAX_QUOTES:
        lines.append(f"and {len(refs) - MAX_QUOTES} more")
    return Callout("quote", "Evidence", tuple(lines), trusted=True)


def _brief(text: str) -> str:
    """A claim cut short to name it in another line (escaped: it is chat text)."""
    line = " ".join(text.split())
    if len(line) > SHORT_CHARS:
        line = (line[:SHORT_CHARS].rsplit(" ", 1)[0] or line[:SHORT_CHARS]) + " …"
    return f'"{escape_text(line)}"'


def _names(document: KnowledgeDocument, cites: _Cites) -> dict[str, str]:
    """Record ID -> how other lines name it: its claim, short, and where it was said.

    Two records can say the same words in different chats, so the place
    (``c1·m2``) keeps them apart without showing a record ID.
    """
    names = {}
    for section in document.sections:
        for item in section.items:
            where = next((w for r in item.revisions if (w := cites.label(r))), None)
            names[item.record_id] = _brief(item.assertion) + (f" ({where})" if where else "")
    return names


def _item_line(item: DocItem, key: str, names: dict[str, str], cites: _Cites) -> str:
    """One item as one line: bold claim, kind and holder, status, citations."""
    line = (
        f"**{escape_text(' '.join(item.assertion.split()))}** {item.record_type}, by {item.actor}"
    )
    if key == "proposals":
        line += f", {_PROPOSAL_WORDS.get(item.status, item.status)}"
    if item.superseded_by:
        line += ". Replaced by " + "; ".join(
            names.get(r, "a later item") for r in item.superseded_by
        )
    if item.conflicts_with:
        line += ". Disagrees with " + "; ".join(
            names.get(r, "another item") for r in item.conflicts_with
        )
    line += "."
    cited = cites.cites(item.revisions)
    return f"{line} {cited}" if cited else line


def _item_sections(
    session: Session, document: KnowledgeDocument, mode: Mode, cites: _Cites
) -> tuple[list[Block], dict[str, int]]:
    """The item sections this mode shows, and how many items each status has."""
    names = _names(document, cites)
    spans = evidence_of(session, list(document.record_ids))
    blocks: list[Block] = []
    counts: dict[str, int] = {}
    for section in document.sections:
        counts[section.key] = len(section.items)
        if section.key not in _IN_MODE[mode]:
            continue
        blocks += [Heading(section.title, 2), Paragraph(f"*{_PROVENANCE[section.key]}*", True)]
        for item in section.items:
            line = _item_line(item, section.key, names, cites)
            blocks.append(BulletList((line,), trusted=True))
            box = _evidence(session, spans.get(item.record_id, ()), cites)
            if box is not None:
                blocks.append(box)
    return blocks, counts


def _summary(noun: str, document: KnowledgeDocument, counts: dict[str, int], chats: int) -> str:
    parts = [
        f"{counts.get(k, 0)} {w}"
        for k, w in (
            ("current", "current"),
            ("conflicted", "in conflict"),
            ("superseded", "replaced"),
            ("proposals", "suggestion(s)"),
        )
        if counts.get(k)
    ]
    total = len(document.record_ids)
    line = f"{total} item(s) about this {noun} from {chats} chat(s)"
    return line + (": " + ", ".join(parts) + "." if parts else ".")


def _chat_lines(session: Session, cites: _Cites) -> list[str]:
    titles = dict(
        session.execute(
            select(ConversationRow.conversation_id, ConversationRow.title).where(
                ConversationRow.conversation_id.in_(cites.order)
            )
        )
        .tuples()
        .all()
    )
    return [f"c{n}: [[{transcript_stem(c, titles.get(c))}]]" for n, c in enumerate(cites.order, 1)]


def _related_lines(session: Session, cites: _Cites) -> tuple[list[str], list[str]]:
    """Links between the master's chats, by chat number; and their IDs for the sidecar."""
    links = related_links(session, cites.order)
    lines = []
    for link in links:
        ends = [link.from_conversation_id, link.to_conversation_id]
        if not all(c in cites.number for c in ends):
            continue  # a link out of this subject's chats: that chat's own note shows it
        a, b = (f"c{cites.number[c]}" for c in ends)
        line = f"{a} {link.kind.replace('_', ' ')} {b} ({link.evidence_class}, {link.review_state})"
        if link.because:
            line += ". Why: " + "; ".join(escape_text(x) for x in link.because)
        lines.append(line)
    return lines, [link.relationship_id for link in links]


def _assemble(
    session: Session,
    document: KnowledgeDocument,
    *,
    noun: str,
    title: str,
    mode: Mode,
    intro: Sequence[str],
    cites: _Cites,
    extra: Sequence[Block],
    properties: dict[str, PropertyValue],
) -> ReadableMaster:
    """The parts every master shares, around the subject's own sections."""
    items, counts = _item_sections(session, document, mode, cites)
    summary = [*intro, _summary(noun, document, counts, len(cites.order))]
    blocks: list[Block] = [
        Callout("summary", "Summary", tuple(summary), trusted=True, collapsed=False)
    ]
    blocks += items or [Paragraph(f"Nothing about this {noun} is recorded yet.", True)]
    blocks += list(extra)
    related, relationship_ids = _related_lines(session, cites)
    if related:
        blocks += [
            Heading("Related chats", 2),
            Paragraph("*Links between these chats; rejected ones are left out*", True),
            BulletList(tuple(related), trusted=True),
        ]
    chats = _chat_lines(session, cites)
    blocks += [
        Heading("Chats", 2),
        Paragraph("*Each [c2·m12] above is message 12 of chat 2*", True),
        BulletList(tuple(chats), trusted=True)
        if chats
        else Paragraph("No chat is linked yet.", True),
    ]
    properties = {
        **properties,
        "mode": mode.value,
        "records": len(document.record_ids),
        "chats": len(cites.order),
        "current": counts.get("current", 0),
        "replaced": counts.get("superseded", 0),
        "conflicted": counts.get("conflicted", 0),
        "generator": MASTER_TEMPLATE_VERSION,
    }
    meta: dict[str, object] = {
        "generator": MASTER_TEMPLATE_VERSION,
        "document_id": document.document_id,
        "subject_id": document.subject_id,
        "content_hash": document.content_hash,
        "record_ids": list(document.record_ids),
        "conversation_ids": list(cites.order),
        "relationship_ids": relationship_ids,
    }
    return ReadableMaster(DocumentModel(title, properties, tuple(blocks)), meta)


def readable_topic_master(
    session: Session, name: str, snapshot: TaxonomySnapshot, *, mode: Mode = Mode.ALL
) -> ReadableMaster:
    """A topic master in the readable layout.

    Raises:
        TopicNotFound: See ``resolve_topic``.
    """
    term_id = resolve_topic(snapshot, name)
    term = snapshot.term(term_id)
    document = build_document(session, DocumentKind.TOPIC, term_id)
    segments = topic_segments(session, term_id, snapshot)
    cites = _Cites(session, list(document.revision_ids))
    by_chat: dict[str, list[str]] = {}
    for segment in segments:
        cites.add(segment.conversation_id)
        by_chat.setdefault(segment.conversation_id, []).extend(segment.fields)
    first = {s.conversation_id: s.first_message for s in reversed(segments)}
    labelled = [
        f"c{cites.number[c]}: {sum(1 for s in segments if s.conversation_id == c)} segment(s), "
        f"labelled in {', '.join(sorted(set(fields)))}, from "
        f"[[{first[c].note}#^{first[c].anchor}|start]]"
        for c, fields in sorted(by_chat.items(), key=lambda kv: cites.number[kv[0]])
    ]
    extra: list[Block] = [
        Heading("Where this topic comes up", 2),
        Paragraph(f"*Classification under {snapshot.version}*", True),
        BulletList(tuple(labelled), trusted=True)
        if labelled
        else Paragraph("No segment is labelled with this topic yet.", True),
    ]
    intro = [escape_text(" ".join(term.definition.split()))] if term.definition else []
    return _assemble(
        session,
        document,
        noun="topic",
        title=f"Topic {term.label}",
        mode=mode,
        intro=intro,
        cites=cites,
        extra=extra,
        properties={
            "ke_type": "topic_master",
            "term_id": term_id,
            "label": term.label,
            "dimension": term.dimension,
            "taxonomy_version": snapshot.version,
            "segments": len(segments),
        },
    )


def readable_project_master(
    session: Session, project_id: str, *, mode: Mode = Mode.ALL
) -> ReadableMaster:
    """A project master in the readable layout: items, how they connect, and when."""
    document = build_document(session, DocumentKind.PROJECT, project_id)
    cites = _Cites(session, list(document.revision_ids))
    names = _names(document, cites)
    # Only records this mode shows, so no line names an item the note leaves out.
    shown = {
        item.record_id
        for section in document.sections
        if section.key in _IN_MODE[mode]
        for item in section.items
    }
    extra: list[Block] = []
    if mode is not Mode.HISTORY:
        between = [e for e in edges(session) if e.source in shown and e.target in shown]
        if between:
            extra += [
                Heading("How these connect", 2),
                Paragraph("*From the reconciliation step: links between the items above*", True),
                BulletList(
                    tuple(
                        f"{names[e.source]} **{e.kind.replace('_', ' ')}** {names[e.target]} "
                        f"({e.state})"
                        for e in between
                    ),
                    trusted=True,
                ),
            ]
    if mode is not Mode.CURRENT:
        steps = [s for s in timeline(session, sorted(shown)) if s.revokes_event is None]
        lines = []
        for step in steps:
            line = names.get(step.from_record or "", "an item")
            line += f" **{step.predicate.replace('_', ' ')}**"
            if step.to_record:
                line += f" {names.get(step.to_record, 'an item')}"
            lines.append(line + (" (withdrawn later)" if step.revoked else ""))
        if lines:
            extra += [
                Heading("Decision timeline", 2),
                Paragraph("*From the chats, oldest first*", True),
                BulletList(tuple(lines), trusted=True),
            ]
    return _assemble(
        session,
        document,
        noun="project",
        title=f"Project {project_id}",
        mode=mode,
        intro=[],
        cites=cites,
        extra=extra,
        properties={"ke_type": "project_master", "project_id": project_id},
    )


def _write(vault_root: Path, relative: PurePosixPath, note: ReadableMaster) -> PurePosixPath:
    write_note(vault_root, relative, render_note(note.model))
    sidecar = safe_relative_path(relative.parts[0], META_DIR, f"{relative.stem}.json")
    write_note(vault_root, sidecar, json.dumps(note.meta, indent=2, sort_keys=True) + "\n")
    return relative


def write_readable_topic_master(
    session: Session,
    name: str,
    snapshot: TaxonomySnapshot,
    vault_root: Path,
    *,
    mode: Mode = Mode.ALL,
) -> PurePosixPath:
    """Write the readable topic master where the older one goes, plus its sidecar."""
    note = readable_topic_master(session, name, snapshot, mode=mode)
    relative = topic_path(snapshot, str(note.model.properties["term_id"]), mode)
    return _write(vault_root, relative, note)


def write_readable_project_master(
    session: Session, project_id: str, vault_root: Path, *, mode: Mode = Mode.ALL
) -> PurePosixPath:
    """Write the readable project master where the older one goes, plus its sidecar."""
    return _write(
        vault_root,
        project_path(project_id, mode),
        readable_project_master(session, project_id, mode=mode),
    )
