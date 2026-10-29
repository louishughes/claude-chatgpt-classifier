"""Reading relationships for people: notes, search results, the UI (REL-004).

One place decides which links a reader sees and how each is described, so
the conversation note, the project and topic masters, ``ke find`` and the
web pages all agree:

* **rejected links are hidden** (their history stays in
  ``relationship_reviews`` and ``ke related list --state rejected``);
* a link a person **retyped** (REL-006) is replaced by the new one;
* every other link keeps its **stored direction** (``from`` -> ``to``), so
  "B continues A" never turns into "A continues B";
* each carries its **reasons** (``because``, REL-003) and the **message
  revisions** its evidence cites, so a note can link to the exact words.

Talking points:
    - "Every view of a link reads it from here, so a rejected link can't
      show up in one place and not another."
    - "The arrow always points the way it was proposed and reviewed."
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from knowledge_engine.domain.enums import ReviewState
from knowledge_engine.relationships.store import ConversationRelationshipRow


@dataclass(frozen=True)
class RelatedLink:
    """One link as readers see it (rejected ones are never built).

    Attributes:
        relationship_id: The ``rel_`` ID.
        kind: ``continues``, ``forked_from``, ``related_to``...
        from_conversation_id: The chat the link starts from.
        to_conversation_id: The chat it points to.
        evidence_class: How it is known (native, structural, semantic, human...).
        confidence: The detector's own 0..1 measure.
        review_state: Candidate, accepted or superseded.
        because: Plain reasons, when the detector gave any.
        revisions: Message revisions the evidence cites, either chat.
        replaces: The link a person retyped into this one (REL-006), if any.
    """

    relationship_id: str
    kind: str
    from_conversation_id: str
    to_conversation_id: str
    evidence_class: str
    confidence: float
    review_state: str
    because: tuple[str, ...] = ()
    revisions: tuple[str, ...] = ()
    replaces: str | None = None

    def other(self, conversation_id: str) -> str:
        """The chat at the far end, seen from ``conversation_id``."""
        if conversation_id == self.from_conversation_id:
            return self.to_conversation_id
        return self.from_conversation_id

    def as_dict(self, viewpoint: str | None = None) -> dict[str, object]:
        """IDs, kind, state and reasons only (no titles or text): safe to print."""
        found: dict[str, object] = {
            "relationship_id": self.relationship_id,
            "kind": self.kind,
            "from": self.from_conversation_id,
            "to": self.to_conversation_id,
            "evidence_class": self.evidence_class,
            "confidence": self.confidence,
            "review_state": self.review_state,
            "because": list(self.because),
        }
        if viewpoint is not None:
            found["other"] = self.other(viewpoint)
            found["direction"] = "to" if viewpoint == self.from_conversation_id else "from"
        return found


def revision_ids_in(value: object) -> list[str]:
    """Every ``rev_`` ID anywhere in a JSON value (relationship evidence)."""
    if isinstance(value, str):
        return [value] if value.startswith("rev_") else []
    if isinstance(value, dict):
        return [r for v in value.values() for r in revision_ids_in(v)]
    if isinstance(value, list):
        return [r for v in value for r in revision_ids_in(v)]
    return []


def _link(row: ConversationRelationshipRow) -> RelatedLink:
    evidence = json.loads(row.evidence_json or "{}")
    because = evidence.get("because", []) if isinstance(evidence, dict) else []
    return RelatedLink(
        row.relationship_id,
        row.kind,
        row.from_conversation_id,
        row.to_conversation_id,
        row.evidence_class,
        row.confidence,
        row.review_state,
        tuple(str(b) for b in because),
        tuple(dict.fromkeys(revision_ids_in(evidence))),
        evidence.get("replaces") if isinstance(evidence, dict) else None,
    )


def related_links(session: Session, conversation_ids: Iterable[str]) -> list[RelatedLink]:
    """Links touching any of the chats, either direction, except rejected ones."""
    wanted = sorted(set(conversation_ids))
    found: dict[str, RelatedLink] = {}
    replaced: set[str] = set()
    for start in range(0, len(wanted), 500):
        chunk = wanted[start : start + 500]
        for row in session.scalars(
            select(ConversationRelationshipRow).where(
                or_(
                    ConversationRelationshipRow.from_conversation_id.in_(chunk),
                    ConversationRelationshipRow.to_conversation_id.in_(chunk),
                ),
            )
        ):
            link = _link(row)
            if link.replaces:
                replaced.add(link.replaces)
            if row.review_state != ReviewState.REJECTED.value:
                found[row.relationship_id] = link
    # A link a person retyped (REL-006) is shown once, as what they said: the
    # old one stays in the history, not next to its replacement. Rejected
    # replacements count too, so rejecting "B continues A" doesn't bring back
    # the "B forked_from A" the person had already overruled. Both rows touch
    # the same two chats, so the replacement is always in this query.
    return [found[key] for key in sorted(found) if key not in replaced]


def related_by_conversation(
    session: Session, conversation_ids: Iterable[str]
) -> dict[str, list[RelatedLink]]:
    """Chat -> the visible links touching it (for search results)."""
    wanted = set(conversation_ids)
    grouped: dict[str, list[RelatedLink]] = defaultdict(list)
    for link in related_links(session, wanted):
        for end in {link.from_conversation_id, link.to_conversation_id} & wanted:
            grouped[end].append(link)
    return dict(grouped)
