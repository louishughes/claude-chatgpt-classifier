"""Narrowing a word search by date, speaker and vocabulary term (RET-009).

The PRD asks for search "filters over approved concepts, exact terms,
source type and dates" (FR-15). The word index (RET-001) already narrows by
conversation; this module adds three more filters that combine with AND:

* **dates**: ``since`` and ``until`` are calendar days in UTC, both
  included. A message's own time is used, not the chat's. A message with
  no time can't be placed in a range, so it is left out whenever a date
  filter is set, and the search reports how many were left out that way:
  saying nothing would look like "no such message".
* **speaker**: ``user``, ``assistant``, ``tool`` or ``system``.
* **term**: an approved taxonomy term or project ID. Only messages inside a
  segment whose labels in force carry that ID (in any field, primary or
  secondary) are kept. "In force" means ``effective_labels``: a reviewer's
  choice beats the machine's, the same rule the topic master uses, so a
  search and a topic note always agree on what is "about" a term.

An ID that is not approved in the chosen published version is refused with
``UnknownFilterTerm``. Ignoring it would silently widen the search to
everything, which is the opposite of what the person asked for.

Talking points:
    - "A filter on a word the vocabulary doesn't know is an error, not a
      no-op: silently searching everything would be the worst answer."
    - "Messages without a date aren't quietly dropped; the search says how
      many it couldn't place in the range."
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.classification.store import effective_labels
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.rendering.transcript import load_conversation
from knowledge_engine.segmentation.overrides import load_segments
from knowledge_engine.taxonomy.registry import TaxonomyRegistry, TaxonomySnapshot

ROLES = ("user", "assistant", "tool", "system")
# fromisoformat also takes "20240105" and week dates; only the plain form is accepted.
_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")


class UnknownFilterTerm(ValueError):
    """The term or project ID is not approved in the published version."""


class BadFilterDate(ValueError):
    """A date that isn't ``YYYY-MM-DD``, or a range that ends before it starts."""


class BadFilterRole(ValueError):
    """A speaker that isn't one of ``ROLES``."""


@dataclass(frozen=True)
class SearchFilters:
    """What a search must also satisfy, beyond containing the words.

    Attributes:
        since: Earliest message time kept, epoch seconds (included).
        until: Message times must be before this, epoch seconds (excluded).
        role: Only messages by this speaker.
        node_keys: Only these messages (from a term filter); None = any.
    """

    since: float | None = None
    until: float | None = None
    role: str | None = None
    node_keys: frozenset[str] | None = None

    @property
    def dated(self) -> bool:
        """True when a date filter is set, so undated messages are left out."""
        return self.since is not None or self.until is not None


def day_bounds(since: str | None, until: str | None) -> tuple[float | None, float | None]:
    """Turn two inclusive UTC days into ``[start, end)`` epoch seconds.

    ``until`` is moved to the start of the next day, so a message at
    23:59 on that day is still inside.

    Raises:
        BadFilterDate: A day isn't ``YYYY-MM-DD``, or ``until`` is before ``since``.
    """

    def start_of(day: str) -> float:
        try:
            if not _DAY.fullmatch(day):
                raise ValueError(day)
            parsed = date.fromisoformat(day)
        except ValueError:
            # The input isn't echoed: API errors never repeat what was sent.
            raise BadFilterDate("dates must be YYYY-MM-DD") from None
        return datetime(parsed.year, parsed.month, parsed.day, tzinfo=UTC).timestamp()

    start = start_of(since) if since else None
    end = start_of(until) + timedelta(days=1).total_seconds() if until else None
    if start is not None and end is not None and end <= start:
        raise BadFilterDate("the end date is before the start date")
    return start, end


def term_node_keys(session: Session, term_id: str, snapshot: TaxonomySnapshot) -> frozenset[str]:
    """Every message inside a segment whose labels in force carry ``term_id``.

    Raises:
        UnknownFilterTerm: ``term_id`` is neither an approved term nor an
            approved project in ``snapshot``.
    """
    known = {t.term_id for t in snapshot.terms} | set(snapshot.project_ids())
    if term_id not in known:
        raise UnknownFilterTerm(f"that term or project ID is not approved in {snapshot.version}")
    found: set[str] = set()
    for conversation_id in session.scalars(
        select(ConversationRow.conversation_id).order_by(ConversationRow.conversation_id)
    ):
        chat = load_conversation(session, conversation_id)
        for segment in load_segments(session, chat):
            labels = effective_labels(session, segment.segment_id, snapshot)
            if any(term_id == f.primary or term_id in f.secondary for f in labels.values()):
                found.update(chat.node_keys[native] for native in segment.messages)
    return frozenset(found)


def build_filters(
    session: Session,
    *,
    since: str | None = None,
    until: str | None = None,
    role: str | None = None,
    term: str | None = None,
    taxonomy: str | None = None,
) -> SearchFilters | None:
    """Check what the person asked for and turn it into ``SearchFilters``.

    Shared by ``ke search``, ``GET /search`` and the search page, so all
    three accept and refuse exactly the same things.

    Args:
        session: A read session on the archive.
        since: First day, ``YYYY-MM-DD`` (UTC, included).
        until: Last day, ``YYYY-MM-DD`` (UTC, included).
        role: A speaker from ``ROLES``.
        term: An approved term or project ID.
        taxonomy: The published version the term is checked in; default the newest.

    Returns:
        The filters, or None when none was asked for (search as before).

    Raises:
        BadFilterDate, BadFilterRole, UnknownFilterTerm: see their docs.
            A term with no published taxonomy at all is ``UnknownFilterTerm``.
    """
    if not (since or until or role or term):
        return None
    start, end = day_bounds(since, until)
    if role is not None and role not in ROLES:
        raise BadFilterRole(f"speaker must be one of {', '.join(ROLES)}")
    keys = None
    if term:
        registry = TaxonomyRegistry(session)
        published = registry.versions()
        version = taxonomy or (published[-1] if published else None)
        if version is None or version not in published:
            raise UnknownFilterTerm("no such published taxonomy version")
        keys = term_node_keys(session, term, registry.snapshot(version))
    return SearchFilters(since=start, until=end, role=role, node_keys=keys)
