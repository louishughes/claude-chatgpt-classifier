"""A chat's categories, with how much of it each covers and why (NOTE-008).

The classifier labels *segments*, because one chat can cover several
subjects. A note needs the chat-level picture, and a reader needs to see
how sure it is. For the domain dimension (category › subcategory) this
module works out, for each term a segment was labelled with:

* its **share of the chat**: the messages in the segments where it is the
  primary label, over all labelled messages. The largest share is the
  chat's primary category; every other is a secondary. A term only ever
  given as a segment's *secondary* label is listed as a side subject,
  without a share;
* **where** it comes from: which segments (numbered in chat order) and
  the messages the classifier cited as evidence;
* the **reviewer verdict** per segment: agreed with the classifier,
  changed it, set it with no classifier answer, or not reviewed. A review
  made under an older vocabulary that no longer fits is "out of date".

``waiting_candidates`` lists open TAX-004 proposals whose evidence points
at this chat (its segments or its ID): new terms a reviewer hasn't decided
on. They are shown as candidates and never as labels.

Talking points:
    - "Primary means 'most of the chat', measured in messages, not the
      first label the model happened to give."
    - "Every label says who stands behind it: the classifier, a reviewer,
      or both."
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.classification.classifier import DONE
from knowledge_engine.classification.store import (
    ClassificationLabelRow,
    ClassificationRow,
    effective_labels,
)
from knowledge_engine.rendering.transcript import StoredConversation
from knowledge_engine.segmentation.overrides import load_segments
from knowledge_engine.taxonomy.registry import Dimension, TaxonomySnapshot, UnknownTermError
from knowledge_engine.taxonomy.review import OPEN, Operation, proposals

PRIMARY = "primary"
SECONDARY = "secondary"
SIDE = "side subject"


@dataclass(frozen=True)
class CategoryShare:
    """One domain term in one chat.

    Attributes:
        term_id: The approved term.
        label: ``Category › Subcategory`` (or the category alone).
        rank: ``primary``, ``secondary`` or ``side subject``.
        share: Its share of the labelled messages (0..1), or None for a
            side subject.
        segments: 1-based segment numbers, in chat order.
        evidence: Native message IDs the classifier cited for it.
        verdicts: One line per segment on who stands behind the label.
    """

    term_id: str
    label: str
    rank: str
    share: float | None
    segments: tuple[int, ...]
    evidence: tuple[str, ...]
    verdicts: tuple[str, ...]


def _label(snapshot: TaxonomySnapshot, term_id: str) -> str:
    try:
        term = snapshot.term(term_id)
    except UnknownTermError:
        return term_id
    if term.parent_id is None:
        return term.label
    try:
        return f"{snapshot.term(term.parent_id).label} › {term.label}"
    except UnknownTermError:
        return term.label


def _machine(session: Session, segment_id: str, snapshot: TaxonomySnapshot) -> dict[str, object]:
    """The classifier's domain answer for a segment: primary and evidence per term."""
    row = session.scalar(
        select(ClassificationRow)
        .where(
            ClassificationRow.segment_id == segment_id,
            ClassificationRow.taxonomy_version == snapshot.version,
            ClassificationRow.state == DONE,
        )
        .order_by(ClassificationRow.updated_at.desc(), ClassificationRow.classification_id)
    )
    primary: str | None = None
    evidence: dict[str, list[str]] = {}
    if row is not None:
        for label in session.scalars(
            select(ClassificationLabelRow)
            .where(
                ClassificationLabelRow.classification_id == row.classification_id,
                ClassificationLabelRow.field == Dimension.DOMAIN.value,
            )
            .order_by(ClassificationLabelRow.label_id)
        ):
            if label.rank == PRIMARY:
                primary = label.target_id
            evidence[label.target_id] = list(json.loads(label.evidence_json))
    return {"answered": row is not None, "primary": primary, "evidence": evidence}


def _verdict(number: int, source: str, chosen: str | None, machine: dict[str, object]) -> str:
    if source == "machine":
        return f"segment {number}: classifier, not reviewed"
    if source == "stale_review":
        return f"segment {number}: reviewed under an older vocabulary (out of date)"
    if not machine["answered"]:
        return f"segment {number}: set by a reviewer (no classifier answer)"
    if machine["primary"] == chosen:
        return f"segment {number}: reviewer agreed with the classifier"
    return f"segment {number}: reviewer changed the classifier's label"


def category_shares(
    session: Session, chat: StoredConversation, snapshot: TaxonomySnapshot
) -> list[CategoryShare]:
    """The chat's domain terms, primary first, then by share (see the module docstring)."""
    weight: dict[str, int] = defaultdict(int)
    side: set[str] = set()
    where: dict[str, list[int]] = defaultdict(list)
    cited: dict[str, list[str]] = defaultdict(list)
    verdicts: dict[str, list[str]] = defaultdict(list)
    total = 0
    for number, segment in enumerate(load_segments(session, chat), start=1):
        labels = effective_labels(session, segment.segment_id, snapshot)[Dimension.DOMAIN.value]
        if labels.source == "none" or labels.primary is None:
            continue
        machine = _machine(session, segment.segment_id, snapshot)
        size = len(segment.messages)
        total += size
        weight[labels.primary] += size
        evidence = machine["evidence"]
        assert isinstance(evidence, dict)
        for term in (labels.primary, *labels.secondary):
            where[term].append(number)
            if term != labels.primary:
                side.add(term)
            for native in evidence.get(term, []):
                if native not in cited[term]:
                    cited[term].append(native)
        verdicts[labels.primary].append(_verdict(number, labels.source, labels.primary, machine))
    ranked = sorted(weight, key=lambda t: (-weight[t], t))
    found = []
    for index, term in enumerate(ranked):
        found.append(
            CategoryShare(
                term,
                _label(snapshot, term),
                PRIMARY if index == 0 else SECONDARY,
                weight[term] / total,
                tuple(where[term]),
                tuple(cited[term]),
                tuple(verdicts[term]),
            )
        )
    for term in sorted(side - set(weight)):
        found.append(
            CategoryShare(
                term,
                _label(snapshot, term),
                SIDE,
                None,
                tuple(where[term]),
                tuple(cited[term]),
                (),
            )
        )
    return found


def waiting_candidates(session: Session, chat: StoredConversation) -> list[str]:
    """Labels of open ``add`` proposals whose evidence cites this chat."""
    segment_ids = {s.segment_id for s in load_segments(session, chat)}
    labels = []
    for row in proposals(session, OPEN):
        if row.operation != Operation.ADD.value:
            continue
        evidence = json.loads(row.evidence_json)
        hits = segment_ids & set(evidence.get("segments", []))
        if hits or chat.conversation_id in evidence.get("conversation_ids", []):
            label = str(json.loads(row.payload_json).get("label", "")).strip()
            if label and label not in labels:
                labels.append(label)
    return sorted(labels, key=str.casefold)
