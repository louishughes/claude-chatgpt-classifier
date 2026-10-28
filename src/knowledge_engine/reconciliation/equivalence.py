"""The same claim stated twice: equivalence proposals, never automatic merges (REC-001).

People repeat themselves across chats ("let's use SQLite" in March and again
in May). Retrieval and documents should show that as one claim with two
pieces of evidence, but only once someone has checked. So this module:

1. **Finds candidates.** Two records are only compared when they could be
   the same claim at all: same record type, same actor, same reported
   speaker, same for/against and the same projects (a decision for
   project A is never "the same" as one for project B), and neither is
   rejected. Records scoped to the whole corpus are only compared with
   each other.
2. **Scores them.** Assertions are reduced to their content words; the
   score is the share of words they have in common (Jaccard). Equal word
   sets are ``exact``; a score of at least ``threshold`` is ``similar``.
3. **Flags near misses.** If one says "not" and the other doesn't, the
   numbers differ, or one is firm and the other soft, the pair is a
   ``near_miss`` with those differences listed. "Use port 8080" and "use
   port 8081" share almost every word and are different decisions.
4. **Stores a proposal and stops.** Every pair, even an exact one, stays
   ``proposed`` until a named reviewer confirms or rejects it. Confirming a
   near miss needs a reason. Every review is kept in an append-only log.
   A re-run never re-opens or changes a reviewed pair.

Confirmed pairs form groups (``equivalence_groups``) that later stages read.
The records themselves are never edited, merged or promoted.

Talking points:
    - "Two records are only compared if they could be the same claim: same
      kind, same person, same project, same direction."
    - "Nothing is merged by the machine. Even a word-for-word repeat waits
      for a reviewer, and 'port 8080' versus 'port 8081' is flagged as a
      near miss."
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from itertools import combinations

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, Integer, String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from knowledge_engine.extraction.records import KnowledgeRecord, Scope, Trust
from knowledge_engine.extraction.store import KnowledgeRecordRow
from knowledge_engine.infrastructure.db import Base

DETECTOR_VERSION = "rec-001-v1"
THRESHOLD = 0.6

_WORD = re.compile(r"[^\W_]+(?:['’][^\W_]+)?")
_NUMBER = re.compile(r"\d+(?:[.,]\d+)?")
# Words that carry no claim of their own. Negations are deliberately not
# here: they are compared separately, because they flip a claim.
_STOP = frozenset(
    "a an and are as at be but by for from has have i i'm in is it its it's let's lets of on or "
    "our so that the their them then there these they this to us was we we'll were will with "
    "you your should would could can just also use using".split()
)
_NEGATIONS = frozenset(
    "no not never none nothing without don't doesn't didn't won't can't shouldn't isn't "
    "aren't dont doesnt didnt wont cant shouldnt isnt arent".split()
)


class Basis(StrEnum):
    """Why two records were proposed as the same claim."""

    EXACT = "exact"
    SIMILAR = "similar"
    NEAR_MISS = "near_miss"


class State(StrEnum):
    """Where a proposal stands."""

    PROPOSED = "proposed"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"


def _utc_now() -> datetime:
    return datetime.now(UTC)


class RecordEquivalenceRow(Base):
    """A proposed pair of records that may state the same claim."""

    __tablename__ = "record_equivalences"
    __table_args__ = (
        CheckConstraint("basis IN ('exact','similar','near_miss')", name="basis_valid"),
        CheckConstraint("state IN ('proposed','confirmed','rejected')", name="state_valid"),
        CheckConstraint("record_a < record_b", name="pair_ordered"),
    )

    pair_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    record_a: Mapped[str] = mapped_column(ForeignKey("knowledge_records.record_id"), index=True)
    record_b: Mapped[str] = mapped_column(ForeignKey("knowledge_records.record_id"), index=True)
    basis: Mapped[str] = mapped_column(String(10))
    score: Mapped[float] = mapped_column(Float)
    differences_json: Mapped[str] = mapped_column(Text, default="[]")
    detector: Mapped[str] = mapped_column(String(40))
    state: Mapped[str] = mapped_column(String(10), default=State.PROPOSED.value)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


class RecordEquivalenceReviewRow(Base):
    """One review decision on a pair. Append-only."""

    __tablename__ = "record_equivalence_reviews"

    review_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pair_id: Mapped[str] = mapped_column(ForeignKey("record_equivalences.pair_id"), index=True)
    from_state: Mapped[str] = mapped_column(String(10))
    to_state: Mapped[str] = mapped_column(String(10))
    reviewer: Mapped[str] = mapped_column(String(100))
    note: Mapped[str | None] = mapped_column(Text, default=None)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


# Created by migration 0022. Kept here so tests that build the schema
# without Alembic can install the same guard.
APPEND_ONLY_TRIGGERS = (
    "CREATE TRIGGER IF NOT EXISTS record_equivalence_reviews_no_update "
    "BEFORE UPDATE ON record_equivalence_reviews "
    "BEGIN SELECT RAISE(ABORT, 'record_equivalence_reviews is append-only'); END",
    "CREATE TRIGGER IF NOT EXISTS record_equivalence_reviews_no_delete "
    "BEFORE DELETE ON record_equivalence_reviews "
    "BEGIN SELECT RAISE(ABORT, 'record_equivalence_reviews is append-only'); END",
)


class EquivalenceError(ValueError):
    """A review the store refuses."""


@dataclass(frozen=True)
class Candidate:
    """Two records that may state the same claim.

    Attributes:
        record_a: The smaller record ID.
        record_b: The larger record ID.
        basis: Exact, similar or near miss.
        score: Share of content words in common, 0..1.
        differences: What differs although the words match (negation,
            numbers, strength).
    """

    record_a: str
    record_b: str
    basis: Basis
    score: float
    differences: tuple[str, ...]

    @property
    def pair_id(self) -> str:
        """``req_`` + hash of the two record IDs: the same pair, the same ID."""
        return pair_id(self.record_a, self.record_b)


def pair_id(record_a: str, record_b: str) -> str:
    """The stable ID of a pair, whichever order the records are given in."""
    first, second = sorted((record_a, record_b))
    return "req_" + hashlib.sha256(f"{first}\x00{second}".encode()).hexdigest()[:32]


def _tokens(text: str) -> list[str]:
    return [w.lower().replace("’", "'") for w in _WORD.findall(text)]


def content_words(text: str) -> frozenset[str]:
    """The words of an assertion that carry its claim.

    Numbers are left out here and compared on their own, so "port 8080"
    and "port 8081" score as a match and are then flagged as a near miss
    instead of quietly not matching.
    """
    return frozenset(
        w
        for w in _tokens(text)
        if w not in _STOP and w not in _NEGATIONS and not _NUMBER.fullmatch(w)
    )


def _comparable_key(record: KnowledgeRecord) -> tuple[object, ...] | None:
    # Records with different keys can never be the same claim.
    if record.trust is Trust.REJECTED:
        return None
    corpus_wide = record.scope is Scope.GLOBAL
    return (
        record.record_type,
        record.actor,
        record.attributed_to,
        record.polarity,
        tuple(sorted(record.project_ids)),
        corpus_wide,
    )


def _differences(a: KnowledgeRecord, b: KnowledgeRecord) -> tuple[str, ...]:
    found = []
    if bool(_NEGATIONS & set(_tokens(a.assertion))) != bool(_NEGATIONS & set(_tokens(b.assertion))):
        found.append("negation")
    if sorted(_NUMBER.findall(a.assertion)) != sorted(_NUMBER.findall(b.assertion)):
        found.append("numbers")
    if a.strength != b.strength:
        found.append("strength")
    return tuple(found)


def compare(
    a: KnowledgeRecord, b: KnowledgeRecord, threshold: float = THRESHOLD
) -> Candidate | None:
    """Return a candidate if ``a`` and ``b`` may be the same claim, else None."""
    if a.record_id == b.record_id:
        return None
    key_a, key_b = _comparable_key(a), _comparable_key(b)
    if key_a is None or key_a != key_b:
        return None
    words_a, words_b = content_words(a.assertion), content_words(b.assertion)
    if not words_a or not words_b:
        return None
    score = len(words_a & words_b) / len(words_a | words_b)
    if score < threshold:
        return None
    differences = _differences(a, b)
    if differences:
        basis = Basis.NEAR_MISS
    elif words_a == words_b:
        basis = Basis.EXACT
    else:
        basis = Basis.SIMILAR
    first, second = sorted((a, b), key=lambda r: r.record_id)
    return Candidate(first.record_id, second.record_id, basis, round(score, 4), differences)


def find_candidates(
    records: Sequence[KnowledgeRecord], threshold: float = THRESHOLD
) -> list[Candidate]:
    """Every candidate pair among ``records``, sorted by pair ID.

    Records are first grouped by everything that must match, and only
    records sharing at least one content word are scored, so the work grows
    with the number of plausible pairs, not with every pair.
    """
    groups: dict[tuple[object, ...], list[KnowledgeRecord]] = defaultdict(list)
    for record in records:
        key = _comparable_key(record)
        if key is not None:
            groups[key].append(record)
    found: dict[str, Candidate] = {}
    for members in groups.values():
        by_word: dict[str, list[int]] = defaultdict(list)
        for index, record in enumerate(members):
            for word in content_words(record.assertion):
                by_word[word].append(index)
        pairs = {pair for indexes in by_word.values() for pair in combinations(indexes, 2)}
        for i, j in sorted(pairs):
            candidate = compare(members[i], members[j], threshold)
            if candidate is not None:
                found[candidate.pair_id] = candidate
    return [found[key] for key in sorted(found)]


def _all_records(session: Session) -> list[KnowledgeRecord]:
    rows = session.scalars(select(KnowledgeRecordRow).order_by(KnowledgeRecordRow.record_id))
    return [KnowledgeRecord.model_validate_json(row.record_json) for row in rows]


@dataclass(frozen=True)
class ProposalReport:
    """What one detection run did.

    Attributes:
        added: Pair IDs newly proposed.
        known: Pairs already stored (left exactly as they were).
    """

    added: tuple[str, ...]
    known: tuple[str, ...]


def propose_equivalences(session: Session, threshold: float = THRESHOLD) -> ProposalReport:
    """Store every new candidate pair as ``proposed``. The caller commits.

    Pairs already stored are untouched, whatever their state, so a re-run
    cannot re-open a rejection or undo a confirmation.
    """
    added, known = [], []
    for candidate in find_candidates(_all_records(session), threshold):
        if session.get(RecordEquivalenceRow, candidate.pair_id) is not None:
            known.append(candidate.pair_id)
            continue
        session.add(
            RecordEquivalenceRow(
                pair_id=candidate.pair_id,
                record_a=candidate.record_a,
                record_b=candidate.record_b,
                basis=candidate.basis.value,
                score=candidate.score,
                differences_json=json.dumps(list(candidate.differences)),
                detector=DETECTOR_VERSION,
            )
        )
        added.append(candidate.pair_id)
    session.flush()
    return ProposalReport(tuple(added), tuple(known))


def review(
    session: Session, pair: str, decision: State, *, reviewer: str, note: str | None = None
) -> RecordEquivalenceReviewRow:
    """Confirm or reject a pair (or change an earlier decision). The caller commits.

    Raises:
        KeyError: No such pair.
        EquivalenceError: No reviewer; ``proposed`` as a decision; the
            pair is already in that state; a near miss confirmed without a
            reason; or a confirmation where either record has since been
            rejected.
    """
    row = session.get(RecordEquivalenceRow, pair)
    if row is None:
        raise KeyError("no such pair")
    if not reviewer.strip():
        raise EquivalenceError("a decision needs a named reviewer")
    if decision is State.PROPOSED:
        raise EquivalenceError("a decision is confirmed or rejected")
    if row.state == decision.value:
        raise EquivalenceError(f"the pair is already {decision.value}")
    if decision is State.CONFIRMED:
        if row.basis == Basis.NEAR_MISS and not (note or "").strip():
            raise EquivalenceError("say why a near miss is the same claim")
        for record_id in (row.record_a, row.record_b):
            current = session.get(KnowledgeRecordRow, record_id)
            if current is None or current.trust == Trust.REJECTED:
                raise EquivalenceError("a rejected record can't be the same as another")
    entry = RecordEquivalenceReviewRow(
        pair_id=pair, from_state=row.state, to_state=decision.value, reviewer=reviewer, note=note
    )
    session.add(entry)
    row.state = decision.value
    session.flush()
    return entry


def equivalence_groups(session: Session) -> list[tuple[str, ...]]:
    """Records joined by confirmed pairs, each group sorted, groups sorted.

    Only confirmed pairs count; a record in no confirmed pair is in no group.
    """
    parent: dict[str, str] = {}

    def root(node: str) -> str:
        while parent.setdefault(node, node) != node:
            parent[node] = parent[parent[node]]
            node = parent[node]
        return node

    for a, b in session.execute(
        select(RecordEquivalenceRow.record_a, RecordEquivalenceRow.record_b).where(
            RecordEquivalenceRow.state == State.CONFIRMED.value
        )
    ):
        parent[root(a)] = root(b)
    members: dict[str, list[str]] = defaultdict(list)
    for node in parent:
        members[root(node)].append(node)
    return sorted(tuple(sorted(group)) for group in members.values())


def pairs(session: Session, states: Iterable[State] = tuple(State)) -> list[RecordEquivalenceRow]:
    """Stored pairs in the given states, best score first."""
    return list(
        session.scalars(
            select(RecordEquivalenceRow)
            .where(RecordEquivalenceRow.state.in_([s.value for s in states]))
            .order_by(RecordEquivalenceRow.score.desc(), RecordEquivalenceRow.pair_id)
        )
    )
