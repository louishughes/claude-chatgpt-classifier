"""Subjects with no domain become one proposal each, for a reviewer (TAX-009).

Reviewers kept finding chats that no domain fits: cooking and food, or
garden and room makeovers. The classifier can only use approved terms,
so those segments come out with no domain, run after run, and nothing
turned the repeated miss into a suggestion. This closes that gap with
rules a person can read:

1. **Answered and uncovered**: only segments with an answer under the
   run's taxonomy version count (a ``pending`` one has none yet). An
   answered segment is *uncovered* when it has no domain: its latest
   reviewer decision on the domain is "none fits", or nobody reviewed the
   domain and its newest machine answer isn't ``done`` with a domain.
2. **Telling words**: a word counts for a subject only if it is *more
   common among the uncovered segments than among all answered ones*.
   Its *lift* is its share of the uncovered segments divided by its share
   of all answered segments; the highest lift wins, then the word in more
   uncovered segments, then the alphabetically first. A word that covered
   chats use too ("weekend") has a lower lift than one only the subject's
   own chats use ("cooking"), so it can't glue two subjects together.
   Stop words, words in more than half of all answered segments, and
   words that look like a name (every use capitalised mid-sentence) never
   count.
3. **One proposal per subject**: the best word with at least
   ``min_segments`` (default 3) uncovered segments becomes **one** TAX-004
   ``add`` proposal for a new domain. Its evidence is segment IDs, one
   quote anchor per segment (message ID and character span, never text)
   and the version. Those segments then leave the pool, and the next best
   word is tried.
4. **Never twice**: a word is passed over, without taking its segments,
   when its label already names an approved domain, waits as an open
   proposal or was rejected. The same goes for a group made of mostly the
   same segments as an open or rejected proposal (at least half of the
   group, and more than half of that proposal's segments). So a re-run
   adds nothing, and a rejected subject stays rejected even when a few
   new chats join it or another word names it.

When no segment has a domain at all, no word is more typical of the
uncovered ones than of the rest, so nothing is proposed: that is the first
vocabulary's job (NOTE-006), not this one.

The vocabulary never moves here: the only rows written are proposals. A
new domain exists only after a separate reviewer approves it and the owner
publishes the next version (NOTE-014).

Talking points:
    - "Chats my vocabulary didn't cover don't just sit unlabelled: when
      three or more share a subject, a reviewer gets one suggestion, with
      the exact places it came from."
    - "A word only counts if it's typical of the uncovered chats, so
      'weekend' can't lump cooking and gardening together."
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

from knowledge_engine.classification.classifier import DONE, REVIEW_REQUIRED, segment_messages
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

GAP_VERSION = "tax-009-v2"
GAP_PROPOSER = "tax-009-domain-gaps"
MIN_SEGMENTS = 3
COMMON_SHARE = 0.5
_WORD = re.compile(r"[^\W\d_]{3,}")
_SENTENCE_END = frozenset(".!?\n")


@dataclass
class GapReport:
    """What one look at the uncovered segments found (labels and counts, no text).

    Attributes:
        answered: Segments with an answer under the version.
        uncovered: Answered segments with no domain.
        proposed: New proposal IDs.
        known: Words that already name an approved domain.
        waiting: Words (or groups) already waiting as open proposals.
        rejected: Words (or groups) a reviewer already turned down.
        names: Words passed over because they look like a name.
        leftover: Uncovered segments in no new proposal.
    """

    answered: int = 0
    uncovered: int = 0
    proposed: list[str] = field(default_factory=list)
    known: list[str] = field(default_factory=list)
    waiting: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    names: int = 0
    leftover: int = 0


def domain_status(session: Session, version: str) -> tuple[set[str], set[str]]:
    """(answered, covered) segment IDs under ``version``.

    A reviewer's latest domain decision wins over any machine answer: a
    chosen domain covers the segment, "none fits" uncovers it. Without one,
    the newest machine answer decides: ``done`` with a domain label covers.
    A segment whose newest answer is still ``pending`` is not answered.
    """
    domain = Dimension.DOMAIN.value
    newest: dict[str, ClassificationRow] = {}
    for row in session.scalars(
        select(ClassificationRow)
        .where(ClassificationRow.taxonomy_version == version)
        .order_by(ClassificationRow.updated_at, ClassificationRow.classification_id)
    ):
        newest[row.segment_id] = row
    with_domain = set(
        session.scalars(
            select(ClassificationLabelRow.classification_id).where(
                ClassificationLabelRow.field == domain
            )
        )
    )
    answered = {s for s, r in newest.items() if r.state in (DONE, REVIEW_REQUIRED)}
    covered = {
        s for s, r in newest.items() if r.state == DONE and r.classification_id in with_domain
    }
    latest: dict[str, ClassificationReviewRow] = {}
    for review in session.scalars(
        select(ClassificationReviewRow)
        .where(ClassificationReviewRow.field == domain)
        .order_by(ClassificationReviewRow.sequence)
    ):
        latest[review.segment_id] = review
    for segment_id, review in latest.items():
        answered.add(segment_id)
        if review.primary_id is None:
            covered.discard(segment_id)
        else:
            covered.add(segment_id)
    return answered, covered


@dataclass(frozen=True)
class _Earlier:
    """An open or rejected domain proposal: its label and its segments."""

    status: str
    label: str
    segments: frozenset[str]


def _earlier(session: Session) -> list[_Earlier]:
    found = []
    for row in session.scalars(
        select(TaxonomyProposalRow)
        .where(
            TaxonomyProposalRow.status.in_((OPEN, REJECTED)),
            TaxonomyProposalRow.operation == Operation.ADD.value,
        )
        .order_by(TaxonomyProposalRow.created_at, TaxonomyProposalRow.proposal_id)
    ):
        payload = json.loads(row.payload_json)
        if payload.get("dimension") == Dimension.DOMAIN.value:
            evidence = json.loads(row.evidence_json or "{}")
            found.append(
                _Earlier(
                    row.status,
                    normalise_alias(payload.get("label", "")),
                    frozenset(evidence.get("segments", ())),
                )
            )
    return found


def _same_group(group: set[str], earlier: frozenset[str]) -> bool:
    """Mostly the same segments: at least half of the group, more than half of the earlier one."""
    shared = len(group & earlier)
    return bool(earlier) and 2 * shared >= len(group) and 2 * shared > len(earlier)


def _words(conversation: StoredConversation, segment: Segment) -> frozenset[str]:
    return frozenset(
        w.casefold() for m in segment_messages(conversation, segment) for w in _WORD.findall(m.text)
    )


def _uses(
    conversation: StoredConversation, segment: Segment, word: str
) -> list[tuple[str, str, int, int]]:
    """Every use of ``word`` in the segment: (message ID, text, start, end)."""
    pattern = re.compile(rf"(?<!\w){re.escape(word)}(?!\w)", re.IGNORECASE)
    return [
        (m.message_id, m.text, found.start(), found.end())
        for m in segment_messages(conversation, segment)
        for found in pattern.finditer(m.text)
    ]


def _looks_like_a_name(uses: Sequence[tuple[str, str, int, int]]) -> bool:
    """True when every use is capitalised and not at a sentence start ("Priya", "Bramble")."""

    def mid_sentence_capital(text: str, start: int) -> bool:
        before = text[:start].rstrip(" \t\"'(")
        return text[start].isupper() and bool(before) and before[-1] not in _SENTENCE_END

    return bool(uses) and all(mid_sentence_capital(text, start) for _, text, start, _ in uses)


def propose_domains(
    session: Session,
    snapshot: TaxonomySnapshot,
    items: Sequence[tuple[StoredConversation, Segment]],
    *,
    min_segments: int = MIN_SEGMENTS,
    proposer: str = GAP_PROPOSER,
) -> GapReport:
    """File one new-domain proposal per subject that uncovered segments share.

    Args:
        session: The caller commits. Only proposal rows are written.
        snapshot: The frozen version the run classified against.
        items: Every segment classified under that version, not only the
            queued ones: word shares are measured against all of them.
            Segments without an answer are ignored.
        min_segments: The smallest group worth a proposal.
        proposer: Recorded on each proposal; a reviewer must be someone else.

    Returns:
        What was proposed and what was passed over, and why.
    """
    answered, covered = domain_status(session, snapshot.version)
    pairs = [(c, s) for c, s in items if s.segment_id in answered]
    bags = [_words(c, s) for c, s in pairs]
    spread: Counter[str] = Counter()
    for bag in bags:
        spread.update(bag)
    total = len(pairs)
    usable = {w for w, df in spread.items() if df <= total * COMMON_SHARE and w not in STOP_WORDS}
    remaining = {i for i, (_, s) in enumerate(pairs) if s.segment_id not in covered}
    report = GapReport(answered=total, uncovered=len(remaining))
    known = _approved_aliases(session, Dimension.DOMAIN)
    earlier = _earlier(session)
    passed: set[str] = set()
    while remaining:
        counts: Counter[str] = Counter()
        for index in remaining:
            counts.update(bags[index] & usable)
        pool = len(remaining)
        scored = [
            (-((u / pool) / (spread[w] / total)), -u, w)
            for w, u in counts.items()
            if u >= min_segments and w not in passed
        ]
        best = min(scored, default=None)
        if best is None or -best[0] <= 1:  # no word is more typical of the uncovered ones
            break
        word = best[2]
        passed.add(word)
        group = sorted(i for i in remaining if word in bags[i])
        ids = {pairs[i][1].segment_id for i in group}
        label = word.capitalize()
        norm = normalise_alias(label)
        uses = [use for i in group for use in _uses(*pairs[i], word)]
        if norm in known:
            report.known.append(label)
            continue
        match = next((e for e in earlier if e.label == norm or _same_group(ids, e.segments)), None)
        if match is not None:
            (report.waiting if match.status == OPEN else report.rejected).append(label)
            continue
        if _looks_like_a_name(uses):
            report.names += 1
            continue
        members = sorted(group, key=lambda i: pairs[i][1].segment_id)
        anchors = []
        for i in members:
            first = _uses(*pairs[i], word)[0]
            anchors.append({"segment_id": pairs[i][1].segment_id, "message_id": first[0],
                            "start": first[2], "end": first[3]})  # fmt: skip
        segment_ids = [pairs[i][1].segment_id for i in members]
        row = propose(
            session,
            Operation.ADD,
            {"dimension": Dimension.DOMAIN.value, "label": label},
            proposer=proposer,
            evidence={
                "rule": GAP_VERSION,
                "taxonomy_version": snapshot.version,
                "size": len(members),
                "segments": segment_ids[:MAX_EVIDENCE],
                "anchors": anchors[:MAX_EVIDENCE],
            },
        )
        earlier.append(_Earlier(OPEN, norm, frozenset(segment_ids)))
        report.proposed.append(row.proposal_id)
        remaining.difference_update(group)
    report.leftover = len(remaining)
    return report
