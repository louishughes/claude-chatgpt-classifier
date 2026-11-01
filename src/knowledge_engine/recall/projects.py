"""One project on one screen: ``recall projects show NAME`` (RCL-003).

This module adds no new knowledge. It reads what the engine already
decided about a project and lays it out for a person or an agent:

* **what holds now**: decisions, requirements, preferences and rejections
  whose REC-006 status is ``current``;
* **in conflict**, **waiting for a check**, **date unknown** and
  **replaced**: the other REC-006 statuses, each in its own section, so a
  replaced decision is never read as the current one;
* **suggestions**: only *counted* (accepted, rejected, never answered).
  An assistant suggestion is not your decision, so none is listed among
  the decisions, however often it was made;
* **open questions**: question records filed under the project;
* **chats** and **related chats**: where the project was talked about, and
  the links (REL-*) between those chats and others.

The sections come straight from ``documents.model.build_document``, the
same builder the project's vault master uses (DOC-001), so ``recall`` and
the vault can't disagree about a record's standing.

**Every line carries its evidence.** Each item's quotes are re-checked
against the stored message text (``retrieval.citations.resolve``) before
they are shown; a quote that no longer matches is reported as "not shown"
with the reason, never printed from memory.

**Finding the project from a name.** A name is matched against approved
projects' IDs, names and aliases, compared in their normalised form
("Unreal-Engine 5" = "unreal engine 5"). A project merged into another
leads to the one it was merged into. A name that matches only a proposal
waiting for review is "not yet a project", and a name that matches two
projects lists both and stops rather than guess.

Talking points:
    - "recall shows a project using the same builder as its vault page, so
      the two always agree on what's current, replaced or in conflict."
    - "Suggestions are counted, never listed as decisions: the assistant
      saying something isn't me deciding it."
    - "Every quote is re-checked against the stored message before it's
      printed, so a summary can't drift from what was actually said."
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.documents.model import DocItem, DocumentKind, build_document, chats_of
from knowledge_engine.domain.models import EvidenceRef
from knowledge_engine.extraction.records import KnowledgeRecord, RecordType
from knowledge_engine.extraction.store import KnowledgeRecordRow
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.relationships.view import RelatedLink, related_links
from knowledge_engine.retrieval.citations import Citation, quote, resolve
from knowledge_engine.taxonomy.registry import (
    ProjectAliasRow,
    ProjectRow,
    TaxonomyProposalRow,
    TermStatus,
    normalise_alias,
)

# Written into every result, so a later change to the layout is visible.
PROJECTS_VERSION = "rcl-003-v1"
# Quotes shown per item; the rest are counted. Three is enough to see
# where something was said without the screen turning into a transcript.
MAX_QUOTES = 3
# The REC-006 sections recall shows as lists, in reading order. The
# builder's "proposals" and "other" sections are handled separately.
LISTED = ("current", "conflicted", "pending", "unknown", "superseded")


class ProjectLookupError(LookupError):
    """A name that doesn't lead to exactly one approved project.

    Attributes:
        code: ``no_project``, ``not_yet_a_project`` or ``ambiguous``.
        matches: For ``ambiguous``, the (project ID, name) pairs it matched.
    """

    def __init__(self, code: str, message: str, matches: tuple[tuple[str, str], ...] = ()):
        """Keep the error code and any matches next to the message."""
        super().__init__(message)
        self.code = code
        self.matches = matches


@dataclass(frozen=True)
class Quote:
    """One re-checked piece of evidence for an item.

    Attributes:
        conversation_id: The chat it is in.
        native_node_id: The message's ID in the export.
        created: When the message was written, epoch seconds, if known.
        actor: Who wrote it (user or assistant).
        text: The quoted words, or None if the quote didn't check out.
        problem: Why it isn't shown (a ``citations.Problem`` value), if so.
    """

    conversation_id: str | None
    native_node_id: str | None
    created: float | None
    actor: str
    text: str | None
    problem: str | None = None


@dataclass(frozen=True)
class ProjectItem:
    """One record in the project, with its standing and its evidence.

    Attributes:
        record_id: The knowledge record (``krec_``).
        record_type: decision, requirement, preference, rejection, question...
        status: Its REC-006 status (or, for a question, its trust).
        assertion: What it says.
        quotes: Up to ``MAX_QUOTES`` re-checked quotes.
        more_quotes: How many further quotes exist.
        superseded_by: Records that replaced it.
        conflicts_with: Records it conflicts with.
    """

    record_id: str
    record_type: str
    status: str
    assertion: str
    quotes: tuple[Quote, ...]
    more_quotes: int = 0
    superseded_by: tuple[str, ...] = ()
    conflicts_with: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProjectChat:
    """A chat where the project comes up."""

    conversation_id: str
    title: str | None
    created: float | None


@dataclass(frozen=True)
class ProjectView:
    """Everything ``recall projects show`` prints for one project.

    Attributes:
        project_id: The project (``proj_``).
        name: Its name.
        aliases: Its other names.
        sections: Section key (see ``LISTED``) -> its items; empty ones omitted.
        suggestions: Assistant suggestions by outcome: accepted, rejected, open.
        questions: Open question records.
        chats: Chats its records cite, oldest first.
        related: Links between those chats and others (not rejected ones).
    """

    project_id: str
    name: str
    aliases: tuple[str, ...]
    sections: dict[str, tuple[ProjectItem, ...]]
    suggestions: dict[str, int]
    questions: tuple[ProjectItem, ...]
    chats: tuple[ProjectChat, ...]
    related: tuple[RelatedLink, ...] = field(default=())


def find_project(session: Session, name: str) -> ProjectRow:
    """The one approved project a name means.

    Args:
        session: A read session.
        name: A project ID, name or alias, as typed.

    Returns:
        The approved project.

    Raises:
        ProjectLookupError: No project, only a proposal, or more than one.
    """
    direct = session.get(ProjectRow, name.strip())
    if direct is not None:
        found = _followed(session, direct)
        if found is not None:
            return found
    wanted = normalise_alias(name)
    if not wanted:
        raise ProjectLookupError("no_project", "a project name needs a letter or digit")
    candidates: dict[str, ProjectRow] = {}
    rows = session.scalars(select(ProjectRow)).all()
    alias_owners = set(
        session.scalars(
            select(ProjectAliasRow.project_id).where(ProjectAliasRow.norm_form == wanted)
        )
    )
    for row in rows:
        if row.project_id in alias_owners or normalise_alias(row.name) == wanted:
            target = _followed(session, row)
            if target is not None:
                candidates[target.project_id] = target
    if len(candidates) == 1:
        return next(iter(candidates.values()))
    if len(candidates) > 1:
        matches = tuple(sorted((p.project_id, p.name) for p in candidates.values()))
        raise ProjectLookupError(
            "ambiguous", f"{len(matches)} projects match {name!r}; use a project ID", matches
        )
    if _only_proposed(session, rows, alias_owners, wanted):
        raise ProjectLookupError(
            "not_yet_a_project",
            f"{name!r} is not yet a project: it is waiting for review (ke review)",
        )
    raise ProjectLookupError("no_project", f"no approved project called {name!r}")


def _followed(session: Session, row: ProjectRow) -> ProjectRow | None:
    """The approved project a row is or was merged into, else None."""
    seen: set[str] = set()
    current: ProjectRow | None = row
    while current is not None and current.status == TermStatus.MERGED.value:
        if current.project_id in seen or current.merged_into is None:
            return None  # a broken merge chain: refuse rather than guess
        seen.add(current.project_id)
        current = session.get(ProjectRow, current.merged_into)
    if current is None or current.status != TermStatus.APPROVED.value:
        return None
    return current


def _only_proposed(
    session: Session, rows: Sequence[ProjectRow], alias_owners: set[str], wanted: str
) -> bool:
    """True if the name is a project still waiting for review."""
    if any(
        r.status == TermStatus.PROPOSED.value
        and (r.project_id in alias_owners or normalise_alias(r.name) == wanted)
        for r in rows
    ):
        return True
    for payload in session.scalars(
        select(TaxonomyProposalRow.payload_json).where(TaxonomyProposalRow.status == "open")
    ):
        data = json.loads(payload)
        if not isinstance(data, dict) or data.get("kind") != "project":
            continue
        names = [data.get("label"), *(data.get("aliases") or [])]
        if any(isinstance(n, str) and normalise_alias(n) == wanted for n in names):
            return True
    return False


def show_project(session: Session, project: ProjectRow) -> ProjectView:
    """Lay out one approved project's knowledge, with re-checked quotes. Reads only.

    Args:
        session: A read session.
        project: An approved project (from ``find_project``).

    Returns:
        The project's view.
    """
    document = build_document(session, DocumentKind.PROJECT, project.project_id)
    by_key = {s.key: s.items for s in document.sections}
    records = {
        row.record_id: KnowledgeRecord.model_validate_json(row.record_json)
        for row in session.scalars(
            select(KnowledgeRecordRow).where(KnowledgeRecordRow.record_id.in_(document.record_ids))
        )
    }
    chat_of = chats_of(session, document.revision_ids)

    def item(doc_item: DocItem) -> ProjectItem:
        record = records.get(doc_item.record_id)
        refs = record.evidence if record is not None else ()
        return ProjectItem(
            record_id=doc_item.record_id,
            record_type=doc_item.record_type,
            status=doc_item.status,
            assertion=doc_item.assertion,
            quotes=tuple(_quote(session, ref, chat_of) for ref in refs[:MAX_QUOTES]),
            more_quotes=max(0, len(refs) - MAX_QUOTES),
            superseded_by=doc_item.superseded_by,
            conflicts_with=doc_item.conflicts_with,
        )

    sections = {key: tuple(item(i) for i in by_key[key]) for key in LISTED if key in by_key}
    # Outcomes are "accepted", "rejected" or "open" (REC-006). All three are
    # always present so "0 never answered" is said, not left to be guessed.
    counted = Counter(i.status for i in by_key.get("proposals", ()))
    suggestions = {outcome: counted.get(outcome, 0) for outcome in ("accepted", "rejected", "open")}
    questions = tuple(
        item(i) for i in by_key.get("other", ()) if i.record_type == RecordType.QUESTION.value
    )
    chat_ids = sorted(set(chat_of.values()))
    rows = session.execute(
        select(
            ConversationRow.conversation_id, ConversationRow.title, ConversationRow.create_time
        ).where(ConversationRow.conversation_id.in_(chat_ids))
    ).all()
    chats = tuple(
        sorted(
            (ProjectChat(c, t, created) for c, t, created in rows),
            key=lambda c: (c.created if c.created is not None else float("inf"), c.conversation_id),
        )
    )
    aliases = tuple(
        sorted(
            a
            for a in session.scalars(
                select(ProjectAliasRow.alias).where(
                    ProjectAliasRow.project_id == project.project_id
                )
            )
            if a != project.name
        )
    )
    return ProjectView(
        project_id=project.project_id,
        name=project.name,
        aliases=aliases,
        sections=sections,
        suggestions=suggestions,
        questions=questions,
        chats=chats,
        related=tuple(related_links(session, chat_ids)),
    )


def _quote(session: Session, ref: EvidenceRef, chat_of: dict[str, str]) -> Quote:
    """Re-check one evidence reference and return it as a Quote."""
    found = resolve(session, ref.revision_id, ref.start, ref.end, ref.quote_sha256, actor=ref.actor)
    if not isinstance(found, Citation):
        return Quote(
            chat_of.get(ref.revision_id), None, None, ref.actor.value, None, found.problem.value
        )
    return Quote(
        found.conversation_id,
        found.native_node_id,
        found.create_time,
        found.actor,
        quote(session, found),
    )
