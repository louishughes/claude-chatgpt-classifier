"""Conversation knowledge notes (DOC-003) and topic master notes (DOC-005).

A **conversation note** is the "what this chat gave me" page that sits
next to the chat's source transcript (BRW-001). It shows, in this order:

* **Summary**: counts the engine can stand behind (messages, branches,
  images, links, records). No model writes it, so it can't invent anything;
* **Classification**: each segment's labels in force (a reviewer's choice
  wins over the machine's), with where it starts in the transcript;
* **Knowledge**: the chat's DOC-001 document, every item labelled with its
  status and followed by its evidence quotes, each naming who said it and
  re-checked word for word against the stored message;
* **Branches**: each alternate (edited or regenerated) branch, linked to
  where it leaves the active path. They are listed, never merged;
* **Images**: an embed for each image the export holds, a visible marker
  (with the reason) for each one it doesn't;
* **Links**, **Videos** and **Accounts**: every URL, YouTube mention and
  social account mention, with who wrote it and a link to the message;
* **Related conversations**: links to and from other chats, with kind,
  direction, how they are known and their review state. Rejected links
  are left out.

A **topic master** gathers one canonical topic from every source: the
records tagged with that term (as a DOC-001 topic document) and the
segments labelled with it. The topic can be named by its ID, label or an
alias; a name that fits several terms is refused, never guessed. Only
material tagged or labelled with that exact term is shown, so a chat that
merely mentions the word doesn't leak in.

Talking points:
    - "Each chat gets a knowledge page beside its transcript: what was
      decided, who said it, exact quotes, branches, images and links."
    - "A topic page pulls one subject together from every chat, by the
      topic's ID, never by a loose keyword match."
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.classification.store import FieldLabels, effective_labels
from knowledge_engine.documents.model import DocumentKind, build_document
from knowledge_engine.documents.render import (
    Mode,
    SourceLink,
    knowledge_note,
    relationship_lines,
    source_links,
    transcript_stem,
)
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.links.social_store import AccountMentionRow
from knowledge_engine.links.store import LinkOccurrenceRow
from knowledge_engine.links.youtube import YouTubeMentionRow, YouTubeVideoRow
from knowledge_engine.relationships.view import related_links
from knowledge_engine.rendering.markdown import (
    Block,
    BulletList,
    DocumentModel,
    Heading,
    Paragraph,
    PropertyValue,
    escape_text,
    render_note,
    safe_filename,
    safe_relative_path,
    write_note,
)
from knowledge_engine.rendering.media import (
    MediaRef,
    blob_sources,
    export_attachments,
    media_block,
)
from knowledge_engine.rendering.transcript import (
    StoredConversation,
    load_conversation,
    message_anchor,
    transcript_sections,
)
from knowledge_engine.segmentation.overrides import load_segments
from knowledge_engine.segmentation.segmenter import Segment
from knowledge_engine.taxonomy.aliases import AliasResolver, MatchStatus
from knowledge_engine.taxonomy.registry import TaxonomySnapshot, UnknownTermError

NOTES_VERSION = "doc-003-v1"
TOPIC_VERSION = "doc-005-v1"
KNOWLEDGE_DIR = "Knowledge"
TOPICS_DIR = "Topics"


def _anchor_link(chat: StoredConversation, native_id: str) -> str:
    """``[[transcript#^node-…]]`` for one message of this chat."""
    stem = transcript_stem(chat.conversation_id, chat.title)
    return f"[[{stem}#^{message_anchor(chat.node_keys[native_id])}]]"


def _revision_links(chat: StoredConversation) -> dict[str, str]:
    """Revision ID -> link to its message, for this chat's newest revisions."""
    return {rev: _anchor_link(chat, native) for native, rev in chat.revisions.items()}


def _label_text(snapshot: TaxonomySnapshot, target: str) -> str:
    """``Label (`term_x`)``; IDs the snapshot doesn't approve are shown bare."""
    try:
        return f"{escape_text(snapshot.term(target).label)} (`{target}`)"
    except UnknownTermError:
        names = {p.project_id: p.name for p in snapshot.projects}
        if target in names:
            return f"{escape_text(names[target])} (`{target}`)"
        return f"`{target}` (not in {snapshot.version})"


def _field_line(snapshot: TaxonomySnapshot, labels: FieldLabels) -> str:
    chosen = [labels.primary] if labels.primary else []
    shown = [_label_text(snapshot, t) for t in [*chosen, *labels.secondary]]
    return f"{labels.field}: {', '.join(shown)} ({labels.source})"


def _classification(
    session: Session,
    chat: StoredConversation,
    segments: Sequence[Segment],
    snapshot: TaxonomySnapshot | None,
) -> list[Block]:
    if snapshot is None:
        return [Paragraph("No taxonomy version was given, so labels aren't shown.", True)]
    blocks: list[Block] = []
    for number, segment in enumerate(segments, 1):
        labels = effective_labels(session, segment.segment_id, snapshot)
        lines = [_field_line(snapshot, f) for f in labels.values() if f.source != "none"]
        where = _anchor_link(chat, segment.messages[0])
        blocks.append(Paragraph(f"Segment {number} (`{segment.segment_id}`), from {where}", True))
        blocks.append(BulletList(tuple(lines or ["not classified yet"]), trusted=True))
    return blocks


def _branches(chat: StoredConversation) -> list[str]:
    lines = []
    for section in transcript_sections(chat):
        if section.kind == "active" or not section.messages:
            continue
        first = _anchor_link(chat, section.messages[0])
        if section.kind == "outside":
            lines.append(f"{len(section.messages)} message(s) outside the tree, from {first}")
        elif section.parent is None:
            lines.append(f"Detached ({section.branch_kind or 'other'}), from {first}")
        else:
            after = _anchor_link(chat, section.parent)
            lines.append(
                f"{section.branch_kind or 'other'}: {len(section.messages)} message(s) "
                f"from {first}, branching off after {after}"
            )
    return lines


def _images(chat: StoredConversation) -> tuple[list[Block], list[MediaRef]]:
    blocks: list[Block] = []
    refs: list[MediaRef] = []
    links = _revision_links(chat)
    for revision in sorted(chat.media, key=lambda r: links.get(r, r)):
        for ref in chat.media[revision]:
            refs.append(ref)
            blocks += [Paragraph(f"In {links.get(revision, '`' + revision + '`')}:", True)]
            blocks.append(media_block(ref))
    return blocks, refs


def _links(session: Session, chat: StoredConversation) -> tuple[list[str], list[str], list[str]]:
    where = _revision_links(chat)
    urls, videos, accounts = [], [], []
    rows = session.execute(
        select(LinkOccurrenceRow, YouTubeMentionRow, YouTubeVideoRow)
        .outerjoin(
            YouTubeMentionRow, YouTubeMentionRow.mention_id == LinkOccurrenceRow.occurrence_id
        )
        .outerjoin(YouTubeVideoRow, YouTubeVideoRow.video_id == YouTubeMentionRow.video_id)
        .where(LinkOccurrenceRow.conversation_id == chat.conversation_id)
        .order_by(LinkOccurrenceRow.revision_id, LinkOccurrenceRow.start)
    ).all()
    for occurrence, mention, video in rows:
        at = where.get(occurrence.revision_id, f"`{occurrence.revision_id}`")
        by = occurrence.actor or "unknown"
        # URLs are imported text: shown in code spans, so nothing in them is acted on.
        urls.append(f"`{_code(occurrence.original_text)}` (by {by}, in {at})")
        if mention is not None:
            extra = f", at {mention.t_seconds}s" if mention.t_seconds is not None else ""
            status = video.transcript_status if video is not None else "unknown"
            videos.append(
                f"YouTube `{mention.video_id}`{extra} (by {by}, in {at}; transcript: {status})"
            )
    for row in session.scalars(
        select(AccountMentionRow)
        .where(AccountMentionRow.conversation_id == chat.conversation_id)
        .order_by(AccountMentionRow.revision_id, AccountMentionRow.start)
    ):
        at = where.get(row.revision_id, f"`{row.revision_id}`")
        account = f"`{row.account_id}`" if row.account_id else "no account linked"
        accounts.append(
            f"{row.platform or 'unknown platform'} `{_code(row.raw_text)}`: {row.resolution}, "
            f"{account} (by {row.actor or 'unknown'}, in {at})"
        )
    return urls, videos, accounts


def _code(text: str) -> str:
    """Make imported text safe inside a one-line code span."""
    return " ".join(text.replace("`", "'").split())


@dataclass(frozen=True)
class Related:
    """One relationship as a chat's note shows it (rejected ones are never built)."""

    relationship_id: str
    kind: str
    direction: str  # "to" (this chat -> other) or "from" (other -> this chat)
    other: str
    evidence_class: str
    confidence: float
    review_state: str
    because: tuple[str, ...] = ()
    revisions: tuple[str, ...] = ()


def related_conversations(session: Session, conversation_id: str) -> list[Related]:
    """Links to and from a chat, in either direction, except rejected ones."""
    return [
        Related(
            link.relationship_id,
            link.kind,
            "to" if link.from_conversation_id == conversation_id else "from",
            link.other(conversation_id),
            link.evidence_class,
            link.confidence,
            link.review_state,
            link.because,
            link.revisions,
        )
        for link in related_links(session, [conversation_id])
    ]


def _related_lines(session: Session, conversation_id: str) -> list[str]:
    return relationship_lines(
        session, related_links(session, [conversation_id]), here=conversation_id
    )


def _section(title: str, lines: list[str], empty: str) -> list[Block]:
    return [Heading(title, 2), BulletList(tuple(lines or [empty]), trusted=True)]


@dataclass(frozen=True)
class ConversationNote:
    """A conversation note and the media it embeds (to copy into the vault)."""

    model: DocumentModel
    media: tuple[MediaRef, ...]


def conversation_note(
    session: Session, conversation_id: str, *, taxonomy: TaxonomySnapshot | None = None
) -> ConversationNote:
    """Build one chat's knowledge note. Reads only.

    Args:
        session: A read session.
        conversation_id: The ``conv_`` ID.
        taxonomy: The published version to show labels under, or None.
    """
    chat = load_conversation(session, conversation_id)
    segments = load_segments(session, chat)
    document = build_document(session, DocumentKind.CONVERSATION, conversation_id)
    knowledge = knowledge_note(session, document, quotes=True)
    branches = _branches(chat)
    image_blocks, refs = _images(chat)
    urls, videos, accounts = _links(session, chat)
    related = _related_lines(session, conversation_id)
    missing = sum(1 for r in refs if r.blob_sha256 is None)
    transcript = transcript_stem(conversation_id, chat.title)
    summary = (
        f"{len(chat.graph.active_messages)} message(s) on the active path, "
        f"{len(branches)} other branch(es), {len(segments)} segment(s), "
        f"{len(document.record_ids)} knowledge record(s), "
        f"{len(refs)} image(s) ({missing} not available), {len(urls)} link(s), "
        f"{len(related)} related chat(s). Full text: [[{transcript}]]."
    )
    blocks: list[Block] = [Heading("Summary", 2), Paragraph(summary, True)]
    blocks += [Heading("Classification", 2), *_classification(session, chat, segments, taxonomy)]
    blocks.append(Heading("Knowledge", 2))
    if knowledge.blocks:
        # Its sections become level 3 under "Knowledge".
        blocks += [Heading(b.text, 3) if isinstance(b, Heading) else b for b in knowledge.blocks]
    else:
        blocks.append(Paragraph("No knowledge records from this chat yet.", True))
    blocks += _section("Branches", branches, "no other branches")
    blocks += [Heading("Images", 2), *(image_blocks or [Paragraph("no images", True)])]
    blocks += _section("Links", urls, "no links")
    blocks += _section("Videos", videos, "no videos")
    blocks += _section("Accounts", accounts, "no account mentions")
    blocks += _section("Related conversations", related, "none found")
    properties: dict[str, PropertyValue] = {
        "ke_type": "conversation_knowledge",
        "conversation_id": conversation_id,
        "document_id": document.document_id,
        "transcript": f"[[{transcript}]]",
        "records": len(document.record_ids),
        "taxonomy_version": taxonomy.version if taxonomy else "none",
        "generator": f"{document.builder_version}+{NOTES_VERSION}",
    }
    title = f"Knowledge: {chat.title or 'Untitled conversation'}"
    return ConversationNote(DocumentModel(title, properties, tuple(blocks)), tuple(refs))


def knowledge_path(conversation_id: str, title: str | None) -> PurePosixPath:
    """Where a chat's knowledge note lives (``Knowledge/…``).

    Same title and ID part as the transcript, so the two notes sort side by side.
    """
    suffix = conversation_id.replace("_", "-", 1)[:13]
    name = safe_filename(f"{title or 'Untitled conversation'} knowledge", suffix)
    return safe_relative_path(KNOWLEDGE_DIR, name)


def write_conversation_note(
    session: Session,
    conversation_id: str,
    vault_root: Path,
    store_root: Path,
    *,
    taxonomy: TaxonomySnapshot | None = None,
) -> PurePosixPath:
    """Write a chat's knowledge note into ``vault_root/Knowledge``, with its images."""
    note = conversation_note(session, conversation_id, taxonomy=taxonomy)
    export_attachments(note.media, vault_root, blob_sources(session, store_root))
    relative = knowledge_path(
        conversation_id, session.get_one(ConversationRow, conversation_id).title
    )
    write_note(vault_root, relative, render_note(note.model))
    return relative


class TopicNotFound(ValueError):
    """A topic name that names no approved term, or several."""


def resolve_topic(snapshot: TaxonomySnapshot, name: str) -> str:
    """The one approved term a name stands for: an ID, a label or an alias.

    Raises:
        TopicNotFound: Nothing matches, or several terms do (never guessed).
    """
    try:
        return snapshot.term(name).term_id
    except UnknownTermError:
        pass
    found = AliasResolver(snapshot).resolve(name)
    terms = tuple(c for c in found.candidates if c.target_id.startswith("term_"))
    if found.status is MatchStatus.UNMATCHED or not terms:
        raise TopicNotFound(f"no approved term in {snapshot.version} is called that")
    if len({c.target_id for c in terms}) > 1:
        options = ", ".join(sorted({c.target_id for c in terms}))
        raise TopicNotFound(f"that name fits several terms: {options}")
    return terms[0].target_id


@dataclass(frozen=True)
class TopicSegment:
    """A segment labelled with the topic, and where it is."""

    conversation_id: str
    segment_id: str
    first_message: SourceLink
    fields: tuple[str, ...]  # the fields that carry the term


def topic_segments(
    session: Session, term_id: str, snapshot: TaxonomySnapshot
) -> list[TopicSegment]:
    """Every segment whose labels in force include the term, in any field.

    Labels come from ``effective_labels`` (a review beats the machine), so a
    reviewer removing the label removes the segment from the topic.
    """
    found = []
    for (conversation_id,) in session.execute(
        select(ConversationRow.conversation_id).order_by(ConversationRow.conversation_id)
    ):
        chat = load_conversation(session, conversation_id)
        stem = transcript_stem(conversation_id, chat.title)
        for segment in load_segments(session, chat):
            labels = effective_labels(session, segment.segment_id, snapshot)
            fields = tuple(
                f.field for f in labels.values() if term_id == f.primary or term_id in f.secondary
            )
            if fields:
                first = segment.messages[0]
                found.append(
                    TopicSegment(
                        conversation_id,
                        segment.segment_id,
                        SourceLink(conversation_id, stem, message_anchor(chat.node_keys[first])),
                        fields,
                    )
                )
    return found


def topic_master(
    session: Session, name: str, snapshot: TaxonomySnapshot, *, mode: Mode = Mode.ALL
) -> DocumentModel:
    """The topic master note: tagged knowledge plus labelled segments, with sources.

    Raises:
        TopicNotFound: See ``resolve_topic``.
    """
    term_id = resolve_topic(snapshot, name)
    term = snapshot.term(term_id)
    document = build_document(session, DocumentKind.TOPIC, term_id)
    knowledge = knowledge_note(session, document, mode=mode, quotes=True)
    segments = topic_segments(session, term_id, snapshot)
    blocks: list[Block] = []
    if term.definition:
        blocks.append(Paragraph(term.definition))
    blocks += list(knowledge.blocks) or [Paragraph("No knowledge records carry this topic.", True)]
    blocks += _section(
        "Conversations on this topic",
        [
            f"{s.first_message.wikilink} (`{s.segment_id}`, labelled in {', '.join(s.fields)})"
            for s in segments
        ],
        "no segment is labelled with this topic",
    )
    chats = {
        link.conversation_id: link.note
        for link in source_links(session, list(document.revision_ids)).values()
    }
    chats |= {s.conversation_id: s.first_message.note for s in segments}
    blocks += _section(
        "Sources", [f"[[{note}]] (`{conv}`)" for conv, note in sorted(chats.items())], "none"
    )
    related = relationship_lines(session, related_links(session, chats))
    if related:
        blocks += _section("Related conversations", related, "")
    properties: dict[str, PropertyValue] = {
        "ke_type": "topic_master",
        "term_id": term_id,
        "dimension": term.dimension,
        "document_id": document.document_id,
        "taxonomy_version": snapshot.version,
        "mode": mode.value,
        "records": len(document.record_ids),
        "segments": len(segments),
        "generator": f"{document.builder_version}+{TOPIC_VERSION}",
    }
    return DocumentModel(f"Topic {term.label}", properties, tuple(blocks))


def topic_path(snapshot: TaxonomySnapshot, term_id: str, mode: Mode = Mode.ALL) -> PurePosixPath:
    """Where a topic master lives (``Topics/…``), named by label and term ID."""
    suffix = term_id.replace("_", "-")[:13]
    name = safe_filename(f"{snapshot.term(term_id).label} {mode.value}", suffix)
    return safe_relative_path(TOPICS_DIR, name)


def write_topic_master(
    session: Session,
    name: str,
    snapshot: TaxonomySnapshot,
    vault_root: Path,
    *,
    mode: Mode = Mode.ALL,
) -> PurePosixPath:
    """Write a topic master into ``vault_root/Topics`` (named by the term ID)."""
    note = topic_master(session, name, snapshot, mode=mode)
    relative = topic_path(snapshot, str(note.properties["term_id"]), mode)
    write_note(vault_root, relative, render_note(note))
    return relative
