"""Subjects with no domain become one proposal each, for a reviewer (TAX-009).

Reviewers kept finding chats that no domain fits: cooking and food, or
garden and room makeovers. The classifier can only use approved terms,
so those segments come out with no domain, run after run, and nothing
turned the repeated miss into a suggestion. This closes that gap with
rules a person can read:

1. **Uncovered**: a segment is uncovered when, under the run's taxonomy
   version, it has no domain label. That means no ``done`` machine answer
   gives it a domain, and no reviewer chose one. A reviewer's "none fits"
   leaves it uncovered.
2. **Grouped**: take the word found in the most uncovered segments, make
   those segments a group, remove them, and repeat (ties go to the
   alphabetically first word). Filler words never count: the TAX-006 stop
   words, and any word in more than half of *all* the run's segments
   ("help", "thanks"). The share is taken over the whole run, not just the
   uncovered part, so one subject that most uncovered chats share is still
   found. The same segments always give the same groups.
3. **Proposed once**: a group of at least ``min_segments`` (default 3)
   becomes **one** TAX-004 ``add`` proposal for a new domain. The proposal
   is labelled with the shared word and carries as evidence the segment
   IDs, one quote anchor per segment (message ID and character span of the
   shared word, never the text) and the version the run used. No proposal
   is made when the word already names an approved domain, waits as an
   open proposal, or was rejected before. A rejected suggestion stays
   rejected, so re-running adds nothing.

The vocabulary never moves here: the only rows written are proposals. A
new domain exists only after a separate reviewer approves it and the owner
publishes the next version (NOTE-014).

Talking points:
    - "Chats nobody's vocabulary covers don't just sit unlabelled: when
      three or more share a subject, a reviewer gets one suggestion, with
      the exact places it came from."
    - "Suggesting never changes the vocabulary mid-run. A person approves,
      and the next version picks it up."
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.classification.classifier import DONE, segment_messages
from knowledge_engine.classification.store import (
    ClassificationLabelRow,
    ClassificationReviewRow,
    ClassificationRow,
)
from knowledge_engine.rendering.transcript import StoredConversation
from knowledge_engine.segmentation.segmenter import Segment
from knowledge_engine.taxonomy.discovery import (
    MAX_EVIDENCE,
    STOP_WORDS,
    _approved_aliases,
)
from knowledge_engine.taxonomy.registry import (
    Dimension,
    TaxonomyProposalRow,
    TaxonomySnapshot,
    normalise_alias,
)
from knowledge_engine.taxonomy.review import OPEN, REJECTED, Operation, propose

GAP_VERSION = "tax-009-v1"
GAP_PROPOSER = "tax-009-domain-gaps"
MIN_SEGMENTS = 3
COMMON_SHARE = 0.5
KEYWORDS = 3
_WORD = re.compile(r"[^\W\d_]{3,}")


@dataclass
class GapReport:
    """What one look at the uncovered segments found (labels and counts, no text).

    Attributes:
        uncovered: Segments with no domain under the version.
        proposed: New proposal IDs.
        known: Shared words that already name an approved domain.
        waiting: Shared words already waiting as open proposals.
        rejected: Shared words a reviewer already turned down.
        leftover: Uncovered segments in no group of ``min_segments`` or more.
    """

    uncovered: int = 0
    proposed: list[str] = field(default_factory=list)
    known: list[str] = field(default_factory=list)
    waiting: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    leftover: int = 0


def domain_covered(session: Session, version: str) -> set[str]:
    """Segments with a domain under ``version``, from a done answer or a reviewer's choice."""
    domain = Dimension.DOMAIN.value
    machine = session.scalars(
        select(ClassificationRow.segment_id)
        .join(
            ClassificationLabelRow,
            ClassificationLabelRow.classification_id == ClassificationRow.classification_id,
        )
        .where(
            ClassificationRow.taxonomy_version == version,
            ClassificationRow.state == DONE,
            ClassificationLabelRow.field == domain,
        )
    )
    reviewed = session.scalars(
        select(ClassificationReviewRow.segment_id).where(
            ClassificationReviewRow.taxonomy_version == version,
            ClassificationReviewRow.field == domain,
            ClassificationReviewRow.primary_id.is_not(None),
        )
    )
    return set(machine) | set(reviewed)


def _add_labels(session: Session, status: str) -> set[str]:
    """Normalised labels of domain ``add`` proposals in ``status``."""
    labels = set()
    for row in session.scalars(
        select(TaxonomyProposalRow).where(
            TaxonomyProposalRow.status == status,
            TaxonomyProposalRow.operation == Operation.ADD.value,
        )
    ):
        payload = json.loads(row.payload_json)
        if payload.get("dimension") == Dimension.DOMAIN.value:
            labels.add(normalise_alias(payload.get("label", "")))
    return labels


def _anchor(
    conversation: StoredConversation, segment: Segment, word: str
) -> dict[str, object] | None:
    """Where the shared word first appears in the segment: message and span, no text."""
    pattern = re.compile(rf"(?<!\w){re.escape(word)}(?!\w)", re.IGNORECASE)
    for message in segment_messages(conversation, segment):
        found = pattern.search(message.text)
        if found:
            return {
                "segment_id": segment.segment_id,
                "message_id": message.message_id,
                "start": found.start(),
                "end": found.end(),
            }
    return None


def _words(conversation: StoredConversation, segment: Segment) -> frozenset[str]:
    return frozenset(
        w.casefold() for m in segment_messages(conversation, segment) for w in _WORD.findall(m.text)
    )


def _keywords(word: str, bags: Sequence[frozenset[str]], usable: set[str]) -> list[str]:
    """The shared word first, then the words most often beside it (ties alphabetical)."""
    beside: Counter[str] = Counter()
    for bag in bags:
        beside.update(bag & usable - {word})
    ranked = sorted(beside.items(), key=lambda pair: (-pair[1], pair[0]))
    return [word, *(w for w, _ in ranked[: KEYWORDS - 1])]


def propose_domains(
    session: Session,
    snapshot: TaxonomySnapshot,
    items: Sequence[tuple[StoredConversation, Segment]],
    *,
    min_segments: int = MIN_SEGMENTS,
    proposer: str = GAP_PROPOSER,
) -> GapReport:
    """File one new-domain proposal per group of uncovered segments that share a subject.

    Args:
        session: The caller commits. Only proposal rows are written.
        snapshot: The frozen version the run classified against.
        items: The run's (conversation, segment) pairs.
        min_segments: The smallest group worth a proposal.
        proposer: Recorded on each proposal; a reviewer must be someone else.

    Returns:
        What was proposed and what was skipped, and why.
    """
    covered = domain_covered(session, snapshot.version)
    bags = [_words(c, s) for c, s in items]
    spread: Counter[str] = Counter()
    for bag in bags:
        spread.update(bag)
    limit = len(items) * COMMON_SHARE
    usable = {w for w, df in spread.items() if df <= limit and w not in STOP_WORDS}
    uncovered = [i for i, (_, s) in enumerate(items) if s.segment_id not in covered]
    report = GapReport(uncovered=len(uncovered))
    known = _approved_aliases(session, Dimension.DOMAIN)
    waiting = _add_labels(session, OPEN)
    rejected = _add_labels(session, REJECTED)
    remaining = set(uncovered)
    while remaining:
        counts: Counter[str] = Counter()
        for index in remaining:
            counts.update(bags[index] & usable)
        best = min(counts.items(), key=lambda pair: (-pair[1], pair[0]), default=None)
        if best is None or best[1] < min_segments:
            break
        word = best[0]
        group = sorted(i for i in remaining if word in bags[i])
        remaining.difference_update(group)
        label = word.capitalize()
        norm = normalise_alias(label)
        for seen, bucket in ((known, report.known), (waiting, report.waiting),
                             (rejected, report.rejected)):  # fmt: skip
            if norm in seen:
                bucket.append(label)
                break
        else:
            members = sorted((items[i] for i in group), key=lambda p: p[1].segment_id)
            anchors = [a for c, s in members if (a := _anchor(c, s, word)) is not None]
            row = propose(
                session,
                Operation.ADD,
                {"dimension": Dimension.DOMAIN.value, "label": label},
                proposer=proposer,
                evidence={
                    "rule": GAP_VERSION,
                    "taxonomy_version": snapshot.version,
                    "keywords": _keywords(word, [bags[i] for i in group], usable),
                    "size": len(members),
                    "segments": [s.segment_id for _, s in members][:MAX_EVIDENCE],
                    "anchors": anchors[:MAX_EVIDENCE],
                },
            )
            waiting.add(norm)
            report.proposed.append(row.proposal_id)
    report.leftover = len(remaining)
    return report
