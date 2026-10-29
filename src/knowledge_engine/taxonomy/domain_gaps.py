"""Subjects with no domain become one proposal each, for a reviewer (TAX-009).

Reviewers kept finding chats that no domain fits: cooking and food, or
garden and room makeovers. The classifier can only use approved terms,
so those segments come out with no domain, run after run, and nothing
turned the repeated miss into a suggestion. This closes that gap with
rules a person can read:

1. **Answered and uncovered**: only segments with an answer under the
   run's taxonomy version count (a ``pending`` one has none yet). An
   answered segment is *uncovered* when it has no domain: its latest
   reviewer decision on the domain, under this version, is "none fits",
   or nobody reviewed it and its newest machine answer isn't ``done``
   with a domain.
2. **Each segment's words**: its tokens (letters and digits kept whole,
   so ``covid19`` is one word), minus stop words, words in more than half
   of all answered segments ("help", "thanks"), and words no other
   uncovered segment uses (they can't connect anything; they only dilute).
   At most ``SIGNATURE`` words are kept, the most widely shared first.
3. **Groups by whole-segment similarity**: two uncovered segments are
   connected when their word sets' Jaccard similarity (shared words over
   all words) is at least ``LINK`` (0.4). A group is a connected set; one
   of at least ``min_segments`` (default 3) becomes **one** TAX-004 ``add``
   proposal for a new domain. A filler word such as "weekend" shared by
   cooking and garden chats is one word out of three in each, so it
   doesn't link them; cooking chats that share "cooking" and "recipe" do
   link, whether they bake or grill.
4. **A label, after the group exists**: the group's word with the highest
   *lift* (its share of the group over its share of all answered
   segments), among words in at least half of the group, that doesn't look
   like a name. A word looks like a name when most of its mid-sentence uses
   are capitalised, or when it is never written in lower case. If no word
   qualifies, the label is "Unnamed group N" and the reviewer names it.
5. **Never twice**: a group is passed over when its label already names
   an approved domain or an open, rejected or approved proposal, or when
   it is mostly the same segments as such a proposal (at least half of the
   group, and more than half of that proposal's segments). The comparison
   uses each proposal's full member list, not the capped display list.

Evidence is IDs and spans only: the full member list (and its SHA-256),
a capped display list, and one anchor per displayed segment (message ID
and character span of the label word, never text).

Grid-like cases are ambiguous by nature: three chats each about "cooking
bake ..." and three about "cooking grill ..." look exactly like three
"cooking ... weekend" and three "garden ... weekend" chats. With only one
shared word in three, both come out as two groups; one more shared word
("recipe") joins the cooking chats.

The vocabulary never moves here: the only rows written are proposals. A
new domain exists only after a separate reviewer approves it and the owner
publishes the next version (NOTE-014).

Talking points:
    - "Chats my vocabulary didn't cover don't just sit unlabelled: when
      three or more are alike, a reviewer gets one suggestion, with the
      exact places it came from."
    - "Chats are grouped by how much of their wording they share, so one
      common word like 'weekend' can't lump cooking and gardening together."
    - "Suggesting never changes the vocabulary mid-run. A person approves,
      and the next version picks it up."
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
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
from knowledge_engine.taxonomy.review import APPROVED, OPEN, REJECTED, Operation, propose

GAP_VERSION = "tax-009-v4"
GAP_PROPOSER = "tax-009-domain-gaps"
MIN_SEGMENTS = 3
COMMON_SHARE = 0.5
SIGNATURE = 20
LINK = 0.4
UNNAMED = "Unnamed group"
# One tokenizer for words, signatures and anchors, so an anchor always
# points at a word that was counted. Letters and digits stay together.
_TOKEN = re.compile(r"[^\W_]{3,}")
_SENTENCE_END = frozenset(".!?\n")


@dataclass
class GapReport:
    """What one look at the uncovered segments found (labels and counts, no text).

    Attributes:
        answered: Segments with an answer under the version.
        uncovered: Answered segments with no domain.
        proposed: New proposal IDs.
        known: Groups whose label or segments match an approved domain or proposal.
        waiting: Groups that match an open proposal.
        rejected: Groups that match a rejected proposal.
        unnamed: New proposals with no usable label word.
        leftover: Uncovered segments in no new proposal.
    """

    answered: int = 0
    uncovered: int = 0
    proposed: list[str] = field(default_factory=list)
    known: list[str] = field(default_factory=list)
    waiting: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    unnamed: int = 0
    leftover: int = 0


def domain_status(session: Session, version: str) -> tuple[set[str], set[str]]:
    """(answered, covered) segment IDs under ``version``.

    A reviewer's latest domain decision wins over any machine answer: a
    chosen domain covers the segment, "none fits" uncovers it. Without one,
    the newest machine answer decides: ``done`` with a domain label covers.
    A segment whose newest answer is still ``pending`` is not answered.
    Only answers and reviews made under ``version`` count: a decision taken
    against an older vocabulary doesn't carry forward.
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
            select(ClassificationLabelRow.classification_id)
            .join(
                ClassificationRow,
                ClassificationRow.classification_id == ClassificationLabelRow.classification_id,
            )
            .where(
                ClassificationLabelRow.field == domain,
                ClassificationRow.taxonomy_version == version,
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
        .where(
            ClassificationReviewRow.field == domain,
            ClassificationReviewRow.taxonomy_version == version,
        )
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
    """An open, rejected or approved domain proposal: its label and all its segments."""

    status: str
    label: str
    segments: frozenset[str]


def _earlier(session: Session) -> list[_Earlier]:
    found = []
    for row in session.scalars(
        select(TaxonomyProposalRow)
        .where(
            TaxonomyProposalRow.status.in_((OPEN, REJECTED, APPROVED)),
            TaxonomyProposalRow.operation == Operation.ADD.value,
        )
        .order_by(TaxonomyProposalRow.created_at, TaxonomyProposalRow.proposal_id)
    ):
        payload = json.loads(row.payload_json)
        if payload.get("dimension") == Dimension.DOMAIN.value:
            evidence = json.loads(row.evidence_json or "{}")
            # "members" is the full list; other proposers only have "segments".
            members = evidence.get("members", evidence.get("segments", ()))
            found.append(
                _Earlier(row.status, normalise_alias(payload.get("label", "")), frozenset(members))
            )
    return found


def _same_group(group: frozenset[str], earlier: frozenset[str]) -> bool:
    """Mostly the same segments: at least half of the group, more than half of the earlier one."""
    shared = len(group & earlier)
    return bool(earlier) and 2 * shared >= len(group) and 2 * shared > len(earlier)


def members_sha256(segment_ids: Sequence[str]) -> str:
    """A stable fingerprint of a group: the SHA-256 of its sorted segment IDs."""
    return hashlib.sha256("\n".join(sorted(segment_ids)).encode("utf-8")).hexdigest()


_Token = tuple[str, str, str, int, int]


def _tokens(conversation: StoredConversation, segment: Segment) -> list[_Token]:
    """Every counted word: (folded word, message ID, message text, start, end)."""
    found = []
    for message in segment_messages(conversation, segment):
        for match in _TOKEN.finditer(message.text):
            word = match.group().casefold()
            if not word.isdigit():
                found.append((word, message.message_id, message.text, match.start(), match.end()))
    return found


def _looks_like_a_name(uses: Sequence[tuple[str, str, int]]) -> bool:
    """True when most mid-sentence uses are capitalised, or it is never written in lower case.

    ``uses`` are (message ID, text, start). A capital at a sentence start
    says nothing, so it only decides when there are no other uses.
    """

    def mid_sentence(text: str, start: int) -> bool:
        before = text[:start].rstrip(" \t\"'(")
        return bool(before) and before[-1] not in _SENTENCE_END

    mid = [text[start].isupper() for _, text, start in uses if mid_sentence(text, start)]
    if mid:
        return 2 * sum(mid) > len(mid)
    return bool(uses) and all(text[start].isupper() for _, text, start in uses)


def _components(signatures: dict[int, frozenset[str]]) -> list[list[int]]:
    """Connected groups of segments whose word sets overlap by at least ``LINK`` (Jaccard)."""
    parent = {i: i for i in signatures}

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    by_word: dict[str, list[int]] = defaultdict(list)
    for i, words in signatures.items():
        for word in words:
            by_word[word].append(i)
    checked: set[tuple[int, int]] = set()
    for members in by_word.values():
        for x, a in enumerate(members):
            for b in members[x + 1 :]:
                if (a, b) in checked:
                    continue
                checked.add((a, b))
                one, two = signatures[a], signatures[b]
                if len(one & two) >= LINK * len(one | two):
                    parent[root(b)] = root(a)
    groups: dict[int, list[int]] = defaultdict(list)
    for i in sorted(signatures):
        groups[root(i)].append(i)
    return sorted(groups.values(), key=lambda g: (-len(g), g[0]))


def propose_domains(
    session: Session,
    snapshot: TaxonomySnapshot,
    items: Sequence[tuple[StoredConversation, Segment]],
    *,
    min_segments: int = MIN_SEGMENTS,
    proposer: str = GAP_PROPOSER,
) -> GapReport:
    """File one new-domain proposal per group of alike uncovered segments.

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
    tokens = [_tokens(c, s) for c, s in pairs]
    bags = [frozenset(t[0] for t in found) for found in tokens]
    spread: Counter[str] = Counter()
    for bag in bags:
        spread.update(bag)
    total = len(pairs)
    usable = {w for w, df in spread.items() if df <= total * COMMON_SHARE and w not in STOP_WORDS}
    uncovered = [i for i, (_, s) in enumerate(pairs) if s.segment_id not in covered]
    report = GapReport(answered=total, uncovered=len(uncovered))
    pool: Counter[str] = Counter()
    for i in uncovered:
        pool.update(bags[i] & usable)
    signatures = {}
    for i in uncovered:
        shared = sorted((w for w in bags[i] & usable if pool[w] >= 2), key=lambda w: (-pool[w], w))
        if shared:
            signatures[i] = frozenset(shared[:SIGNATURE])
    known = _approved_aliases(session, Dimension.DOMAIN)
    earlier = _earlier(session)
    taken: set[int] = set()
    for group in _components(signatures):
        if len(group) < min_segments:
            continue
        ids = frozenset(pairs[i][1].segment_id for i in group)
        word = _label_word(group, bags, tokens, spread, total)
        label = word.capitalize() if word else f"{UNNAMED} {report.unnamed + 1}"
        norm = normalise_alias(label) if word else None
        if norm is not None and norm in known:
            report.known.append(label)
            continue
        match = next(
            (
                e
                for e in earlier
                if (norm is not None and e.label == norm) or _same_group(ids, e.segments)
            ),
            None,
        )
        if match is not None:
            bucket = {OPEN: report.waiting, REJECTED: report.rejected, APPROVED: report.known}
            bucket[match.status].append(label)
            continue
        members = sorted(group, key=lambda i: pairs[i][1].segment_id)
        segment_ids = [pairs[i][1].segment_id for i in members]
        anchors = []
        for i in members[:MAX_EVIDENCE] if word else ():
            hit = next((t for t in tokens[i] if t[0] == word), None)
            if hit is not None:
                anchors.append({"segment_id": pairs[i][1].segment_id, "message_id": hit[1],
                                "start": hit[3], "end": hit[4]})  # fmt: skip
        row = propose(
            session,
            Operation.ADD,
            {"dimension": Dimension.DOMAIN.value, "label": label},
            proposer=proposer,
            evidence={
                "rule": GAP_VERSION,
                "taxonomy_version": snapshot.version,
                "size": len(segment_ids),
                "members": segment_ids,
                "members_sha256": members_sha256(segment_ids),
                "segments": segment_ids[:MAX_EVIDENCE],
                "anchors": anchors,
            },
        )
        if word is None:
            report.unnamed += 1
        earlier.append(_Earlier(OPEN, norm or "", ids))
        report.proposed.append(row.proposal_id)
        taken.update(group)
    report.leftover = len(uncovered) - len(taken)
    return report


def _label_word(
    group: Sequence[int],
    bags: Sequence[frozenset[str]],
    tokens: Sequence[list[_Token]],
    spread: Counter[str],
    total: int,
) -> str | None:
    """The group's highest-lift word in at least half of it that isn't name-like, or None."""
    inside: Counter[str] = Counter()
    for i in group:
        inside.update(w for w in bags[i] if w not in STOP_WORDS)
    ranked = sorted(
        (
            (-(n / len(group)) / (spread[w] / total), -n, w)
            for w, n in inside.items()
            if 2 * n >= len(group) and spread[w] <= total * COMMON_SHARE
        ),
    )
    for _, _, word in ranked:
        uses = [(t[1], t[2], t[3]) for i in group for t in tokens[i] if t[0] == word]
        if not _looks_like_a_name(uses):
            return word
    return None
