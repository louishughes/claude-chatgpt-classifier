"""Rich conversation notes, template v2: the readable parts first (NOTE-001).

The DOC-003 note (``notes.py``) lists everything a chat holds, but a reader
learns little from it: it opens with counts and shows every record in the
same shape. This module renders the *same stored facts* in the layout
agreed in ``docs/plans/RICH_NOTES_GAP_ANALYSIS.md`` §7:

* **Summary** and a **knowledge card** at the top, so the first screen says
  what the chat was about and where it sits in the taxonomy;
* records sorted into the sections a person thinks in: **decisions**
  (what the user settled or ruled out), **suggestions not taken up**,
  **action items**, **open questions**, **requirements and preferences**;
* the generated sections (**insights**, **tensions**, **next steps**) as
  placeholders until the digest step (NOTE-003) fills them;
* **category and subcategory**, **related chats** (linked to the other
  chat's *knowledge note*, so the vault becomes a web of notes), and the
  existing links, images and branches sections.

How evidence is shown, and why (the old v2 notes drowned in it):

* a citation is ``[m12]``: a link to message 12 of the transcript note,
  numbered exactly as the transcript numbers it. A message on another
  branch has no number and is cited as ``[alt]``;
* the quotes sit in a folded callout under the item, at most two per item,
  each re-checked word for word against the stored message first (RET-006)
  and cut at a word boundary;
* an empty section is one plain sentence, never an evidence block;
* hashes, record IDs and stage keys go to a JSON sidecar in
  ``Knowledge/.meta/`` instead of the reader's way.

Each action item says where it stands: open, reported done or dropped,
from the user's own later words, citing the message that decided it
(EXT-009), and what it waits for when a dependency link stands (EXT-010).

Where a model extraction (NOTE-005) has finished for a segment, the older
rule-extractor records of that segment are left out of the note (NOTE-022):
they repeat what the model found and pick up pasted instructions and drafted
text as if the user had said them. They stay stored, and the Source section
says how many were held back.

Only stored facts are used: nothing here calls a model, and a section with
nothing behind it says so instead of guessing. DOC-003 stays the default
note; this one is chosen with ``ke docs chat --template v2``.

Talking points:
    - "The note answers 'what happened in this chat?' on the first screen,
      and every claim is one click from the exact message."
    - "Evidence is folded away, not deleted: open the box and the quote is
      there, re-checked against the archive."
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.classification.store import effective_labels
from knowledge_engine.digest.contract import ConversationDigest, DigestItem
from knowledge_engine.digest.stage import chat_messages, has_quotable_text
from knowledge_engine.documents.categories import (
    Suggestion,
    category_shares,
    suggested_category,
    waiting_candidates,
)
from knowledge_engine.documents.keywords import ChatKeywords, Tier
from knowledge_engine.documents.model import DocItem, DocumentKind, build_document
from knowledge_engine.documents.notes import _branches, _images, _links, knowledge_path
from knowledge_engine.documents.render import transcript_stem
from knowledge_engine.domain.models import EvidenceRef
from knowledge_engine.extraction.action_status import ActionStatus, action_status
from knowledge_engine.extraction.records import Acceptance, KnowledgeRecord
from knowledge_engine.extraction.runner import DONE as RUN_DONE
from knowledge_engine.extraction.runner import ExtractionRunRow
from knowledge_engine.extraction.store import KnowledgeRecordRow
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.reconciliation.equivalence import Basis, find_candidates
from knowledge_engine.reconciliation.relations import LinkState, Predicate, links_of
from knowledge_engine.relationships.view import RelatedLink, related_links
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
from knowledge_engine.rendering.media import MediaRef, blob_sources, export_attachments
from knowledge_engine.rendering.transcript import (
    StoredConversation,
    load_conversation,
    message_anchor,
)
from knowledge_engine.retrieval.citations import Citation, quote, resolve
from knowledge_engine.segmentation.overrides import load_segments
from knowledge_engine.taxonomy.aliases import MatchStatus
from knowledge_engine.taxonomy.registry import (
    Dimension,
    TaxonomySnapshot,
    UnknownTermError,
    normalise_alias,
)

TEMPLATE_VERSION = "note-001-v2"
META_DIR = ".meta"
MAX_QUOTES = 2  # quotes shown per item; the rest are counted
QUOTE_CHARS = 240  # a quote longer than this is cut at a word boundary

# Body size the note should stay under: room for the fixed sections plus a
# little per message, and a hard ceiling. The v2 attempt wrote 44 KB for a
# 3-message chat; this keeps a short chat to a screen or two.
BUDGET_BASE = 6_000
BUDGET_PER_MESSAGE = 250
BUDGET_MAX = 40_000

# The should-tier keywords shown in a note (all must-tier ones are shown):
# enough to say what the chat is about without crowding the page.
SHOWN_SHOULD = 8
WAITING = "Not written yet: the digest step hasn't run for this chat."
# NOTE-031: a chat with no user or assistant text is never sent for a digest.
NO_CONTENT = "Nothing to summarise: the chat has no user or assistant text on its selected path."


def body_budget(messages: int) -> int:
    """The most characters a note body should take for a chat this long."""
    return min(BUDGET_MAX, BUDGET_BASE + BUDGET_PER_MESSAGE * messages)


def body_of(text: str) -> str:
    """A rendered note without its front matter."""
    if text.startswith("---\n"):
        return text.split("\n---\n", 1)[1]
    return text


# ---------------------------------------------------------------- citations


@dataclass(frozen=True)
class Citer:
    """Turns message references into ``[m12]`` links to the transcript."""

    chat: StoredConversation
    stem: str  # the transcript note's file stem

    def native(self, native_id: str) -> str:
        """``[[transcript#^node-…|m12]]`` (``alt`` off the active path)."""
        number = self.chat.graph.message_number(native_id)
        label = f"m{number}" if number is not None else "alt"
        anchor = message_anchor(self.chat.node_keys[native_id])
        return f"[[{self.stem}#^{anchor}|{label}]]"

    def revision(self, revision_id: str) -> str | None:
        """The citation for a message revision of this chat, or None."""
        native = self._natives().get(revision_id)
        return self.native(native) if native is not None else None

    def label(self, revision_id: str) -> str:
        """``m12``, ``alt``, or ``elsewhere`` (a revision from another chat)."""
        native = self._natives().get(revision_id)
        if native is None:
            return "elsewhere"
        number = self.chat.graph.message_number(native)
        return f"m{number}" if number is not None else "alt"

    def _natives(self) -> dict[str, str]:
        return {rev: native for native, rev in self.chat.revisions.items()}


def _short(text: str) -> str:
    """One line, cut at a word boundary to ``QUOTE_CHARS`` with an ellipsis."""
    line = " ".join(text.split())
    if len(line) <= QUOTE_CHARS:
        return line
    cut = line[:QUOTE_CHARS].rsplit(" ", 1)[0] or line[:QUOTE_CHARS]
    return cut.rstrip(" ,.;:") + " …"


def _evidence_callout(
    session: Session, refs: Sequence[EvidenceRef], citer: Citer
) -> Callout | None:
    """The folded evidence box for one item, or None when it has no evidence.

    Each span is re-checked against the stored text; one that no longer
    matches is named with its problem instead of being shown.
    """
    if not refs:
        return None
    lines = []
    for ref in refs[:MAX_QUOTES]:
        where = citer.label(ref.revision_id)
        found = resolve(
            session, ref.revision_id, ref.start, ref.end, ref.quote_sha256, actor=ref.actor
        )
        if not isinstance(found, Citation):
            lines.append(f"{where}: quote not shown ({found.problem.value})")
            continue
        said = escape_text(_short(quote(session, found)))
        lines.append(f'{where} ({found.actor}): "{said}"')
    if len(refs) > MAX_QUOTES:
        lines.append(f"and {len(refs) - MAX_QUOTES} more")
    # The quotes were escaped above; the rest is the engine's own words.
    return Callout("quote", "Evidence", tuple(lines), trusted=True)


# ---------------------------------------------------------------- records


@dataclass(frozen=True)
class _Item:
    """One record, ready to place: what it says, its status and its proof."""

    item: DocItem
    record: KnowledgeRecord
    stated: int = 1  # how many records this line stands for (NOTE-027)


_PROPOSAL_STATUS = {
    "accepted": "accepted later",
    "rejected": "turned down",
    "open": "open",
}


def _cites(item: _Item, citer: Citer) -> str:
    """The item's citations, each message once, in transcript order."""
    natives = {rev: native for native, rev in citer.chat.revisions.items()}
    order = {native: i for i, native in enumerate(citer.chat.graph.active_messages)}
    revisions = sorted(
        {r for r in item.item.revisions if r in natives},
        key=lambda r: (order.get(natives[r], len(order)), r),
    )
    return " ".join(citer.native(natives[r]) for r in revisions)


def _item_blocks(session: Session, item: _Item, citer: Citer, note: str = "") -> list[Block]:
    """A one-line bullet (bold claim, status, citations) and its folded evidence."""
    line = f"**{escape_text(' '.join(item.item.assertion.split()))}**"
    if note:
        line += f" {note}."
    if item.stated > 1:
        line += f" Stated {item.stated} times."
    cites = _cites(item, citer)
    if cites:
        line += f" {cites}"
    blocks: list[Block] = [BulletList((line,), trusted=True)]
    box = _evidence_callout(session, item.record.evidence, citer)
    if box is not None:
        blocks.append(box)
    return blocks


def _load_items(session: Session, items: Sequence[DocItem]) -> list[_Item]:
    wanted = {i.record_id: i for i in items}
    rows = session.scalars(
        select(KnowledgeRecordRow).where(KnowledgeRecordRow.record_id.in_(sorted(wanted)))
    )
    loaded = {r.record_id: KnowledgeRecord.model_validate_json(r.record_json) for r in rows}
    return [_Item(wanted[k], loaded[k]) for k in sorted(wanted) if k in loaded]


@dataclass(frozen=True)
class _Sorted:
    """A chat's records, sorted into the note's sections."""

    decisions: list[_Item]
    ruled_out: list[_Item]
    suggestions: list[_Item]
    actions: list[_Item]
    questions: list[_Item]
    stated: list[_Item]  # requirements, preferences and facts
    artefacts: list[_Item]
    references: list[_Item]


def _prefer_model(session: Session, items: Sequence[_Item]) -> tuple[list[_Item], int]:
    """Leave out rule records of segments a model extraction covers (NOTE-022).

    A run is a model run when its versions name a prompt. Records with no
    extraction run behind them (a person's, say) are always kept.

    Returns:
        The records to show, and how many were left out.
    """
    keys = {i.record.provenance.stage_key for i in items if i.record.provenance}
    runs = {
        r.stage_key: r
        for r in session.scalars(
            select(ExtractionRunRow).where(ExtractionRunRow.stage_key.in_(sorted(keys)))
        )
    }
    segments = sorted({r.segment_id for r in runs.values()})
    covered = {
        r.segment_id
        for r in session.scalars(
            select(ExtractionRunRow).where(
                ExtractionRunRow.segment_id.in_(segments), ExtractionRunRow.state == RUN_DONE
            )
        )
        if "prompt" in json.loads(r.versions_json)
    }
    kept = []
    for it in items:
        provenance = it.record.provenance
        run = runs.get(provenance.stage_key) if provenance else None
        if (
            run is not None
            and provenance is not None
            and provenance.prompt_version is None
            and run.segment_id in covered
        ):
            continue
        kept.append(it)
    return kept, len(items) - len(kept)


def _collapse(items: Sequence[_Item], citer: Citer) -> tuple[list[_Item], int]:
    """One line per claim stated more than once in this chat (NOTE-027).

    Overlapping segments and a user repeating an ask give the same record
    several times. Records REC-001 rates ``exact`` or ``similar`` (same type,
    actor, polarity and projects), with the same status, share one line that
    keeps every citation and quote. A ``near_miss`` ("port 8080" against
    "port 8081") never shares a line, not even through a third record.

    Only the note's display changes: the records and REC-001's review state
    stay as they are, and nothing is joined outside this one chat.

    Returns:
        The lines to show, in the first record's place, and how many
        records were folded into another line.
    """
    by_id = {it.record.record_id: it for it in items}
    candidates = find_candidates([it.record for it in items])
    apart = {frozenset((c.record_a, c.record_b)) for c in candidates if c.basis is Basis.NEAR_MISS}
    groups: dict[str, set[str]] = {r: {r} for r in by_id}
    home = {r: r for r in by_id}
    for c in candidates:
        a, b = home[c.record_a], home[c.record_b]
        if c.basis is Basis.NEAR_MISS or a == b:
            continue
        if by_id[c.record_a].item.status != by_id[c.record_b].item.status:
            continue
        if any(frozenset((x, y)) in apart for x in groups[a] for y in groups[b]):
            continue
        groups[a] |= groups.pop(b)
        for member in groups[a]:
            home[member] = a
    position = {
        rev: i
        for i, n in enumerate(citer.chat.graph.active_messages)
        if (rev := citer.chat.revisions.get(n))
    }

    def first_cited(it: _Item) -> tuple[int, str]:
        cited = [position[r] for r in it.item.revisions if r in position]
        return (min(cited) if cited else len(position), it.record.record_id)

    kept: list[_Item] = []
    shown: set[str] = set()
    for it in items:
        group = home[it.record.record_id]
        if group in shown:
            continue  # folded into the line already placed
        shown.add(group)
        members = sorted((by_id[m] for m in groups[group]), key=first_cited)
        lead = members[0]
        if len(members) == 1:
            kept.append(lead)
            continue
        revisions = tuple(dict.fromkeys(r for m in members for r in m.item.revisions))
        evidence = tuple(
            {
                (e.revision_id, e.start, e.end): e for m in members for e in m.record.evidence
            }.values()
        )
        kept.append(
            _Item(
                replace(lead.item, revisions=revisions),
                lead.record.model_copy(update={"evidence": evidence}),
                stated=len(members),
            )
        )
    return kept, len(items) - len(kept)


# A user's own requirement or preference that picks one option or commits to
# a course reads as a decision (NOTE-035): "I'll go with the oak", "let's use
# Postgres", "we're doing the coast road".
_CHOICE = re.compile(
    r"\b(?:i'?ll go with|i'?m going with|i'?ll (?:use|take|stick with|pick)"
    r"|let'?s (?:go with|use|do|stick with|pick)|we'?re (?:going with|doing|using)"
    r"|i(?:'ve)? (?:chose|chosen|picked|decided)|i choose|decided (?:to|on)"
    r"|settled on|going with)\b",
    re.IGNORECASE,
)


def _user_choice(it: _Item) -> bool:
    """A requirement or preference the user explicitly holds that states a choice.

    Only the user's own explicitly accepted words count: an assistant's
    suggestion never becomes a decision here, however it is worded.
    """
    record = it.record
    return (
        it.item.record_type in ("requirement", "preference")
        and it.item.actor == "user"
        and record.acceptance is Acceptance.EXPLICIT
        and _CHOICE.search(record.assertion) is not None
    )


def _sort(items: Sequence[_Item]) -> _Sorted:
    """Place each record in exactly one section.

    Who holds it matters as much as its type: an assistant's task is a
    *suggestion*, not the user's action item (EXT-005), so it goes with the
    suggestions. A user's requirement or preference that states a choice
    (``_user_choice``) is shown once, under Decisions, not under
    Requirements as well.
    """
    out = _Sorted([], [], [], [], [], [], [], [])
    for it in items:
        kind, actor = it.item.record_type, it.item.actor
        if kind == "decision" or _user_choice(it):
            out.decisions.append(it)
        elif kind == "rejection":
            out.ruled_out.append(it)
        elif kind in ("proposal", "recommendation", "idea"):
            out.suggestions.append(it)
        elif kind == "action":
            (out.actions if actor == "user" else out.suggestions).append(it)
        elif kind == "question":
            out.questions.append(it)
        elif kind == "artefact":
            out.artefacts.append(it)
        elif kind == "reference":
            out.references.append(it)
        else:  # requirement, preference, fact
            out.stated.append(it)
    return out


_ACTION_STATUS = {
    ActionStatus.OPEN: "Open",
    ActionStatus.REPORTED_DONE: "Reported done",
    ActionStatus.DROPPED: "Dropped",
}


def _action_note(session: Session, it: _Item, citer: Citer, actions: Sequence[_Item] = ()) -> str:
    """The action's status, citing the message that decided it, and what it waits for."""
    messages = chat_messages(citer.chat)
    cited = {e.revision_id for e in it.record.evidence}
    positions = [n for n, m in enumerate(messages) if m.revision_id in cited]
    later = messages[max(positions) + 1 :] if positions else []
    found = action_status(it.record, later, others=[a.record for a in actions])
    note = _ACTION_STATUS[found.status]
    if found.evidence is not None:
        where = citer.revision(found.evidence.revision_id)
        if where:
            note += f" {where}"
    waits = []
    for link in links_of(session, it.record.record_id, (LinkState.CANDIDATE, LinkState.ACCEPTED)):
        if link.predicate != Predicate.DEPENDS_ON.value or link.from_record != it.record.record_id:
            continue
        row = session.get(KnowledgeRecordRow, link.to_record)
        if row is not None:
            target = KnowledgeRecord.model_validate_json(row.record_json)
            waits.append(f"“{escape_text(' '.join(target.assertion.split()))}”")
    if waits:
        note += ". Waits for " + ", ".join(waits)
    return note


def _section(title: str, provenance: str, blocks: list[Block], empty: str) -> list[Block]:
    """A section: heading, a small provenance line, then items or one sentence."""
    head: list[Block] = [Heading(title, 2), Paragraph(f"*{provenance}*", True)]
    return head + (blocks or [Paragraph(empty, True)])


# ---------------------------------------------------------------- digest


def _digest_line(item: DigestItem, citer: Citer) -> str:
    """One digest item as a line: the model's words (escaped) and its citations."""
    cites = " ".join(citer.native(m) for m in item.message_ids if m in citer.chat.node_keys)
    text = escape_text(" ".join(item.text.split()))
    return f"{text} {cites}".rstrip()


def _topics_line(topics: Sequence[DigestItem], citer: Citer) -> str:
    """Topics on one line, grouped by the messages they cite (NOTE-026).

    Several topics often come from the same message; citing it after each
    one repeated the same link on one line. Topics that cite the same
    messages share one citation ("raised beds, cedar [m5]"), in the order
    the topics were given.
    """
    groups: dict[tuple[str, ...], list[str]] = {}
    for item in topics:
        cited = tuple(dict.fromkeys(m for m in item.message_ids if m in citer.chat.node_keys))
        groups.setdefault(cited, []).append(escape_text(" ".join(item.text.split())))
    parts = []
    for cited, names in groups.items():
        cites = " ".join(citer.native(m) for m in cited)
        parts.append(f"{', '.join(names)} {cites}".rstrip())
    return "; ".join(parts)


def _digest_blocks(session: Session, items: Sequence[DigestItem], citer: Citer) -> list[Block]:
    """Digest items as bullets, each with its folded, re-checked evidence."""
    blocks: list[Block] = []
    for item in items:
        blocks.append(BulletList((_digest_line(item, citer),), trusted=True))
        box = _evidence_callout(session, item.evidence, citer)
        if box is not None:
            blocks.append(box)
    return blocks


# ---------------------------------------------------------------- labels


@dataclass(frozen=True)
class ChatLabels:
    """A chat's labels, rolled up from its segments.

    The classifier labels segments (a chat can cover several subjects). A
    chat-level label is the one that covers the most messages: each
    segment's primary counts once per message it holds. Ties go to the
    lower ID, so the result never depends on the order rows come back.

    Attributes:
        category: The domain term's parent label (or the term's own label
            when it has no parent), or None when nothing is labelled.
        subcategory: The domain term's label when it has a parent.
        facets: Purpose and output labels, by facet name.
        tags: Topic labels, most-covering first.
        project: The leading project's name, or None.
        segments: How many segments were labelled at all.
    """

    category: str | None = None
    subcategory: str | None = None
    facets: dict[str, list[str]] | None = None
    tags: tuple[str, ...] = ()
    project: str | None = None
    segments: int = 0


def _ranked(weights: dict[str, float]) -> list[str]:
    return [term for term, _ in sorted(weights.items(), key=lambda kv: (-kv[1], kv[0]))]


def chat_labels(
    session: Session, chat: StoredConversation, snapshot: TaxonomySnapshot | None
) -> ChatLabels:
    """Roll segment labels up to the chat (see ``ChatLabels``)."""
    if snapshot is None:
        return ChatLabels()
    weights: dict[str, dict[str, float]] = {}
    labelled = 0
    for segment in load_segments(session, chat):
        found = False
        for name, labels in effective_labels(session, segment.segment_id, snapshot).items():
            if labels.source == "none":
                continue
            found = True
            ids = [labels.primary] if labels.primary else []
            for term in ids + list(labels.secondary):
                # Primary labels carry the segment's full weight, secondaries a third,
                # so a side subject never outranks the main one of the same segment.
                size = len(segment.messages)
                share = size if term == labels.primary else size / 3
                field = weights.setdefault(name, {})
                field[term] = field.get(term, 0.0) + share
        labelled += found

    def label(term_id: str) -> str:
        try:
            return snapshot.term(term_id).label
        except UnknownTermError:
            names = {p.project_id: p.name for p in snapshot.projects}
            return names.get(term_id, term_id)

    category = subcategory = None
    domain = _ranked(weights.get(Dimension.DOMAIN.value, {}))
    if domain:
        lead = snapshot.term(domain[0])
        if lead.parent_id is not None:
            category, subcategory = snapshot.term(lead.parent_id).label, lead.label
        else:
            category = lead.label
    facets = {
        facet: [label(t) for t in _ranked(weights.get(dim.value, {}))]
        for facet, dim in (("activity", Dimension.PURPOSE), ("output", Dimension.OUTPUT))
    }
    projects = _ranked(weights.get("projects", {}))
    return ChatLabels(
        category=category,
        subcategory=subcategory,
        facets={k: v for k, v in facets.items() if v},
        tags=tuple(label(t) for t in _ranked(weights.get(Dimension.TOPIC.value, {}))),
        project=label(projects[0]) if projects else None,
        segments=labelled,
    )


def _category_lines(
    session: Session,
    chat: StoredConversation,
    taxonomy: TaxonomySnapshot,
    citer: Citer,
    suggestion: Suggestion | None,
) -> list[str]:
    """One line per domain term (NOTE-008), then the candidates waiting for review."""
    lines = []
    if suggestion is not None:
        segments = ", ".join(str(n) for n in suggestion.segments)
        lines.append(
            f"Suggested, waiting for review (not a label): **{escape_text(suggestion.label)}**, "
            f"the classifier's best candidate from segment(s) {segments}."
        )
    for share in category_shares(session, chat, taxonomy):
        segments = ", ".join(str(n) for n in share.segments)
        cites = " ".join(citer.native(n) for n in share.evidence if n in chat.node_keys)
        amount = f", {round(100 * share.share)}% of labelled messages" if share.share else ""
        line = f"**{escape_text(share.label)}**, {share.rank}{amount}, from segment(s) {segments}."
        if cites:
            line += f" Classifier cited {cites}."
        if share.verdicts:
            line += " " + "; ".join(share.verdicts).capitalize() + "."
        lines.append(line)
    waiting = waiting_candidates(session, chat)
    if waiting:
        names = ", ".join(f'"{escape_text(w)}"' for w in waiting)
        lines.append(f"Candidates waiting for review (not labels): {names}.")
    return lines


# ---------------------------------------------------------------- related chats


def _related_lines(
    session: Session, links: Sequence[RelatedLink], here: str
) -> tuple[list[str], list[str]]:
    """One plain line per link, naming the other chat's knowledge note.

    Returns the lines and the wikilinks (for the ``related`` property).
    """
    others = sorted({link.other(here) for link in links})
    titles = dict(
        session.execute(
            select(ConversationRow.conversation_id, ConversationRow.title).where(
                ConversationRow.conversation_id.in_(others)
            )
        )
        .tuples()
        .all()
    )
    lines, wikilinks = [], []
    for link in links:
        other = link.other(here)
        note = f"[[{knowledge_path(other, titles.get(other)).stem}]]"
        direction = "this chat" if link.from_conversation_id == here else "that chat"
        line = (
            f"{note}: {link.kind.replace('_', ' ')} (stored as {direction} -> the other; "
            f"{link.evidence_class}, {link.review_state})"
        )
        if link.because:
            line += ". Why: " + "; ".join(escape_text(b) for b in link.because)
        lines.append(line)
        wikilinks.append(note)
    return lines, list(dict.fromkeys(wikilinks))


# ---------------------------------------------------------------- the note


@dataclass(frozen=True)
class RichNote:
    """A rendered-ready rich note, the images it embeds and its sidecar data."""

    model: DocumentModel
    media: tuple[MediaRef, ...]
    meta: dict[str, object]


def _keyword_lines(
    digest: ConversationDigest | None, keywords: ChatKeywords | None, citer: Citer
) -> list[str]:
    """The "Keywords and topics" lines: keyword candidates, then the digest's topics.

    A keyword cites the first message it appears in (a title word cites
    none); keywords from the same message share one citation, as topics do
    (NOTE-026). With keywords, topics are split by whether they name an
    approved term: the others are only candidates, so a reader never
    mistakes one for a tag.
    """
    lines = []
    if keywords is not None:
        shown = [k for k in keywords.keywords if k.tier is Tier.MUST]
        shown += keywords.tier(Tier.SHOULD)[:SHOWN_SHOULD]
        groups: dict[tuple[str, ...], list[str]] = {}
        for k in shown:
            first = next((m for m in k.message_ids if m in citer.chat.node_keys), None)
            groups.setdefault((first,) if first else (), []).append(escape_text(k.term))
        if groups:
            parts = [
                f"{', '.join(names)} {' '.join(citer.native(m) for m in cited)}".rstrip()
                for cited, names in groups.items()
            ]
            lines.append("Keywords: " + "; ".join(parts))
    if digest and digest.topics:
        if keywords is None:
            # Without keywords the line is the topics alone, as before NOTE-021.
            lines.append(_topics_line(digest.topics, citer))
        else:
            matched = {
                normalise_alias(t.text) for t in keywords.topics if t.status is MatchStatus.MATCHED
            }
            approved = [t for t in digest.topics if normalise_alias(t.text) in matched]
            others = [t for t in digest.topics if normalise_alias(t.text) not in matched]
            if approved:
                lines.append("Topics (approved terms): " + _topics_line(approved, citer))
            if others:
                lines.append("Topic candidates (not tags): " + _topics_line(others, citer))
    return lines


def _artefact_names(session: Session, items: Sequence[_Item]) -> list[str]:
    """What the chat made, by name: "2 image(s) or file(s)", "code block (python)".

    A code block's language is read from its fence's first line, through the
    same checked quote the evidence uses; a block without one is just "code block".
    """
    images = sum(len(i.record.asset_occurrences) for i in items)
    names = [f"{images} image(s) or file(s)"] if images else []
    blocks: Counter[str] = Counter()
    for it in items:
        if it.record.asset_occurrences or not it.record.evidence:
            continue
        ref = it.record.evidence[0]
        found = resolve(session, ref.revision_id, ref.start, ref.end, ref.quote_sha256)
        text = quote(session, found) if isinstance(found, Citation) else ""
        words = text.lstrip("`~ ").split("\n", 1)[0].split()
        language = words[0][:20] if words else ""
        named = language.isascii() and language.isalnum()
        blocks[f"code block ({language})" if named else "code block"] += 1
    names += [f"{n} x{c}" if c > 1 else n for n, c in sorted(blocks.items())]
    return names


def _cell(text: str) -> str:
    """Text safe inside a Markdown table cell (a pipe would split the cell)."""
    return text.replace("|", "\\|")


def rich_conversation_note(
    session: Session,
    conversation_id: str,
    *,
    taxonomy: TaxonomySnapshot | None = None,
    digest: ConversationDigest | None = None,
    keywords: ChatKeywords | None = None,
) -> RichNote:
    """Build one chat's rich note (template v2) from stored facts. Reads only.

    Args:
        session: A read session.
        conversation_id: The ``conv_`` ID.
        taxonomy: The published version to show labels under, or None.
        digest: The chat's checked digest (NOTE-003), or None: its sections
            then say the digest hasn't run.
        keywords: The chat's keyword candidates (NOTE-007, from
            ``workspace_keywords``), or None to list only the digest's topics.
    """
    chat = load_conversation(session, conversation_id)
    stem = transcript_stem(conversation_id, chat.title)
    citer = Citer(chat, stem)
    document = build_document(session, DocumentKind.CONVERSATION, conversation_id)
    items, hidden = _prefer_model(
        session, _load_items(session, [i for s in document.sections for i in s.items])
    )
    items, folded = _collapse(items, citer)
    sorted_ = _sort(items)
    labels = chat_labels(session, chat, taxonomy)
    links = related_links(session, [conversation_id])
    related, related_notes = _related_lines(session, links, conversation_id)
    branches = _branches(chat)
    image_blocks, refs = _images(chat)
    urls, videos, accounts = _links(session, chat)
    messages = len(chat.graph.active_messages)
    empty = digest is None and not has_quotable_text(chat)
    waiting = NO_CONTENT if empty else WAITING

    category = labels.category or "unclassified"
    where = category if labels.subcategory is None else f"{category} › {labels.subcategory}"
    # Shown beside "unclassified", never in its place: the front-matter
    # category stays unset until a reviewer settles it (NOTE-018).
    suggestion = (
        suggested_category(session, chat, taxonomy)
        if taxonomy is not None and labels.category is None
        else None
    )
    shown = (
        where
        if suggestion is None
        else (f"{where}; suggested: {suggestion.label} (waiting for review)")
    )
    # A "name" made only of digits and punctuation ("48" from "playing 48
    # levels") is a number the entity cue caught, not a tool or a title.
    spelled = {
        " ".join(i.record.entity.name.split()) for i in sorted_.references if i.record.entity
    }
    names = sorted(n for n in spelled if any(ch.isalpha() for ch in n))
    made = _artefact_names(session, sorted_.artefacts)

    def card_cell(item: DigestItem | None, missing: str) -> str:
        return _cell(_digest_line(item, citer)) if item else missing

    card = ["| | |", "|---|---|"]
    if digest is None:
        missing = "nothing to summarise" if empty else "not written yet"
        card += [f"| **Purpose** | {missing} |", f"| **Outcome** | {missing} |"]
    else:
        # A digest that found no purpose or outcome leaves the row out: an
        # empty "not stated" row reads as a claim about the chat (NOTE-024).
        for title, item in (("Purpose", digest.purpose), ("Outcome", digest.outcome)):
            if item is not None:
                card.append(f"| **{title}** | {card_cell(item, '')} |")
    if digest is not None:
        status = digest.status.value if digest.status else "unknown"
        intent = digest.intent.value if digest.intent else "unknown"
        card.append(f"| **Status** | {status} |")
        card.append(f"| **Intent** | {intent}: {card_cell(digest.intent_item, 'unknown')} |")
    card += [
        f"| **Category** | {_cell(escape_text(shown))} |",
        f"| **Project** | {_cell(escape_text(labels.project or 'none matched'))} |",
        "| **Tools and names** | "
        + (_cell(", ".join(escape_text(n) for n in names)) or "none recorded")
        + " |",
        f"| **Made in this chat** | {', '.join(made) or 'nothing recorded'} |",
        f"| **Length** | {messages} message(s) on the active path, {len(branches)} other "
        f"branch(es), {len(refs)} image(s), {len(urls)} link(s) |",
    ]

    summary = tuple(_digest_line(item, citer) for item in digest.summary) if digest else (waiting,)
    blocks: list[Block] = [
        Callout(
            "summary",
            "Summary · generated, every sentence cited" if digest else "Summary",
            summary,
            trusted=True,
            collapsed=False,
        ),
        Heading("Knowledge card", 2),
        Paragraph("\n".join(card), True),
    ]

    decided: list[Block] = []
    for it in sorted_.decisions:
        decided += _item_blocks(session, it, citer, "Decided")
    for it in sorted_.ruled_out:
        decided += _item_blocks(session, it, citer, "Ruled out")
    blocks += _section(
        "Decisions",
        "From the chat: the user's own words only",
        decided,
        "Nothing was decided in this chat.",
    )
    # A suggestion the user answered is shown with that answer. The decision
    # extractor cites the proposal it answers (its antecedent), so a shared
    # evidence span is the link; the stored proposal status may lag behind it.
    answered = {
        (ref.revision_id, ref.start, ref.end): verdict
        for verdict, group in (("taken up", sorted_.decisions), ("turned down", sorted_.ruled_out))
        for it in group
        for ref in it.record.evidence
    }
    suggested: list[Block] = []
    for it in sorted_.suggestions:
        # A suggestion's standing is whether the user took it up, never its
        # extraction trust: "supported" only meant the quote checked out (NOTE-016).
        status = _PROPOSAL_STATUS.get(it.item.status, "not taken up")
        spans = {(r.revision_id, r.start, r.end) for r in it.record.evidence}
        verdicts = {answered[s] for s in spans if s in answered}
        if len(verdicts) == 1:
            status = f"{verdicts.pop()} (see Decisions)"
        suggested += _item_blocks(session, it, citer, f"Suggested by the {it.item.actor}, {status}")
    blocks += _section(
        "Suggestions",
        "From the chat: proposed, and whether the user took them up",
        suggested,
        "No suggestions recorded.",
    )
    blocks += _section(
        "Action items",
        "From the chat: things the user said they would do",
        [
            b
            for it in sorted_.actions
            for b in _item_blocks(
                session, it, citer, _action_note(session, it, citer, sorted_.actions)
            )
        ],
        "None in this chat.",
    )
    blocks += _section(
        "Open questions",
        "From the chat: asked and not answered",
        [b for it in sorted_.questions for b in _item_blocks(session, it, citer)]
        + (_digest_blocks(session, digest.open_questions, citer) if digest else []),
        "None recorded.",
    )
    blocks += _section(
        "Requirements and preferences",
        "From the chat",
        [
            b
            for it in sorted_.stated
            for b in _item_blocks(session, it, citer, it.item.record_type.capitalize())
        ],
        "None recorded.",
    )
    provenance = "Generated (check before relying on it)"
    generated = (
        ("Insights", "insights"),
        ("Tensions and trade-offs", "tensions"),
        ("Next steps", "next_steps"),
    )
    for title, name in generated:
        if digest is None:
            blocks += _section(title, provenance, [], waiting)
        else:
            items_ = getattr(digest, name)
            blocks += _section(
                title, provenance, _digest_blocks(session, items_, citer), "None in this chat."
            )

    if taxonomy is None:
        classified = "No taxonomy version was given, so labels aren't shown."
    elif labels.segments == 0:
        classified = f"No segment is labelled under {taxonomy.version} yet."
    else:
        classified = (
            f"**{escape_text(where)}** under {taxonomy.version}, "
            f"from {labels.segments} labelled segment(s)."
        )
    tag_lines = [classified]
    if taxonomy is not None:
        tag_lines += _category_lines(session, chat, taxonomy, citer, suggestion)
    if labels.tags:
        tag_lines.append("Topics: " + ", ".join(escape_text(t) for t in labels.tags))
    for facet, values in (labels.facets or {}).items():
        tag_lines.append(f"{facet.capitalize()}: " + ", ".join(escape_text(v) for v in values))
    blocks += [
        Heading("Category and subcategory", 2),
        Paragraph(
            f"*Classification under {taxonomy.version}*" if taxonomy else "*Classification*", True
        ),
        BulletList(tuple(tag_lines), trusted=True),
    ]
    topics = _keyword_lines(digest, keywords, citer)
    blocks += _section(
        "Keywords and topics",
        "Candidates; only approved terms become tags",
        [BulletList(tuple(topics), trusted=True)] if topics else [],
        waiting if digest is None and keywords is None else "None suggested.",
    )
    blocks += _section(
        "Related chats",
        "Links between chats; rejected ones are left out",
        [BulletList(tuple(related), trusted=True)] if related else [],
        "None found yet.",
    )
    if urls or videos or accounts:
        blocks.append(Heading("Links, videos and accounts", 2))
        blocks.append(BulletList(tuple(urls + videos + accounts), trusted=True))
    if image_blocks:
        blocks += [Heading("Images", 2), *image_blocks]
    if branches:
        blocks += [Heading("Branches", 2), BulletList(tuple(branches), trusted=True)]
    blocks += [
        Heading("Source", 2),
        Paragraph(
            f"Full transcript: [[{stem}]]. Built from stored records by {TEMPLATE_VERSION}; "
            + (
                "the selected path has no user or assistant text, so no summary was asked for."
                if empty
                else "no summary has been written or scored yet."
                if digest is None
                else f"summary and generated sections from a {digest.schema_version} digest, "
                "not yet scored."
            )
            + (
                f" {hidden} rule-based record(s) left out: a model extraction covers "
                "their segments."
                if hidden
                else ""
            )
            + (
                f" {folded} repeated record(s) shown on the line of the claim they repeat."
                if folded
                else ""
            ),
            True,
        ),
    ]

    created = datetime.fromtimestamp(chat.create_time, UTC).date() if chat.create_time else None
    properties: dict[str, PropertyValue] = {
        "ke_type": "conversation_knowledge",
        "conversation_id": conversation_id,
        "date": created,
        "messages": messages,
        "category": category,
        "subcategory": labels.subcategory,
        "activity": list((labels.facets or {}).get("activity", [])),
        "output": list((labels.facets or {}).get("output", [])),
        "tags": list(labels.tags),
        "project": labels.project,
        "related": related_notes,
        "transcript": f"[[{stem}]]",
        "taxonomy_version": taxonomy.version if taxonomy else "none",
        "digest": "no_content"
        if empty
        else "not written"
        if digest is None
        else "generated, not scored",
        "status": digest.status.value if digest and digest.status else None,
        "generator": TEMPLATE_VERSION,
    }
    meta: dict[str, object] = {
        "conversation_id": conversation_id,
        "generator": TEMPLATE_VERSION,
        "document_id": document.document_id,
        "content_hash": document.content_hash,
        "record_ids": list(document.record_ids),
        "revision_ids": list(document.revision_ids),
        "relationship_ids": [link.relationship_id for link in links],
        "taxonomy_version": taxonomy.version if taxonomy else None,
        "digest_flags": len(digest.flags) if digest else None,
    }
    title = chat.title or "Untitled conversation"
    return RichNote(DocumentModel(title, properties, tuple(blocks)), tuple(refs), meta)


def meta_path(conversation_id: str, title: str | None) -> PurePosixPath:
    """Where a rich note's sidecar lives (``Knowledge/.meta/<note stem>.json``)."""
    note = knowledge_path(conversation_id, title)
    return safe_relative_path(note.parts[0], META_DIR, f"{note.stem}.json")


def write_rich_note(
    session: Session,
    conversation_id: str,
    vault_root: Path,
    store_root: Path,
    *,
    taxonomy: TaxonomySnapshot | None = None,
    digest: ConversationDigest | None = None,
    keywords: ChatKeywords | None = None,
) -> PurePosixPath:
    """Write a chat's rich note into ``vault_root/Knowledge``, its images and sidecar.

    It goes where the DOC-003 note would, so a vault holds one knowledge
    note per chat whichever template wrote it.
    """
    note = rich_conversation_note(
        session, conversation_id, taxonomy=taxonomy, digest=digest, keywords=keywords
    )
    export_attachments(note.media, vault_root, blob_sources(session, store_root))
    title = session.get_one(ConversationRow, conversation_id).title
    relative = knowledge_path(conversation_id, title)
    write_note(vault_root, relative, render_note(note.model))
    sidecar = json.dumps(note.meta, indent=2, sort_keys=True) + "\n"
    write_note(vault_root, meta_path(conversation_id, title), sidecar)
    return relative
