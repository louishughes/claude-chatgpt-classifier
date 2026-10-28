"""When a later decision really replaces an earlier one (REC-005).

"Later" is not "instead". Wondering "what if we switched to Godot?" after
deciding on Unity replaces nothing. So a later decision supersedes an
earlier one only when **every** test below passes, and each failing test
is named in the verdict:

1. **kinds**: both are decisions or both requirements, by the same person,
   and neither is rejected;
2. **scope**: their scopes overlap the way REC-003 defines it (a shared
   project, or the same chat when neither names a project). A decision in
   project A never replaces one in project B;
3. **subject**: they are about the same thing: a shared taxonomy term, or
   at least one shared content word (Unity and "Godot instead of Unity");
4. **order**: the replacing record is strictly later by source time;
   unknown times can't decide anything;
5. **accepted**: the later one is the user's explicit, evidence-checked
   decision (``supported`` or ``confirmed``, acceptance ``explicit``); a
   conditional or inferred acceptance can't replace a firm decision;
6. **not hypothetical**: the later quote has no "what if", "maybe",
   "should we", question mark and the like;
7. **intent**: the later quote says it replaces something: "instead",
   "switch to", "change of plan", "no longer", "scrap that"...

All seven: ``supersedes``, recorded as a REC-004 event (later -> earlier).
Tests 1-3 pass but a later one fails: ``review_required``, listed for a
reviewer and never recorded as a replacement. Otherwise: ``unrelated``.

The quotes are read from the stored messages with the exact offsets the
record's evidence gives, only the user's own words count, and the text is
never stored in the verdict.

Talking points:
    - "A newer decision only replaces an older one if it's the same thing,
      in the same project, firmly decided, and the words say 'instead'."
    - "'What if we used Godot?' never overrides 'we're using Unity'."
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.domain.enums import Role
from knowledge_engine.extraction.evidence import revision_text
from knowledge_engine.extraction.records import Acceptance, KnowledgeRecord, Trust
from knowledge_engine.extraction.store import KnowledgeRecordRow
from knowledge_engine.reconciliation.conflicts import overlap
from knowledge_engine.reconciliation.equivalence import content_words
from knowledge_engine.reconciliation.relations import Placed, place
from knowledge_engine.reconciliation.timeline import CHOICES, Transition, record_event

DETECTOR_VERSION = "rec-005-v1"

_INTENT = re.compile(
    r"\b(?:instead|switch(?:ing|ed)? (?:over )?to|change of plan|changed my mind|no longer|"
    r"not any ?more|scrap (?:that|the)|replac(?:e|es|ed|ing)\b|from now on|"
    r"mov(?:e|ing|ed) (?:away from|over to)|rather than|drop(?:ping)? \w+ (?:for|in favou?r of))",
    re.IGNORECASE,
)
_HYPOTHETICAL = re.compile(
    r"\b(?:what if|maybe|perhaps|might|could we|should we|would it|wonder|thinking about|"
    r"considering|hypothetically|suppose|in theory|if we)\b|\?",
    re.IGNORECASE,
)


class Outcome(StrEnum):
    """The verdict on one earlier/later pair."""

    SUPERSEDES = "supersedes"
    REVIEW_REQUIRED = "review_required"
    UNRELATED = "unrelated"


@dataclass(frozen=True)
class Verdict:
    """Whether ``later`` replaces ``earlier``, and which tests failed.

    Attributes:
        later: The record that might replace.
        earlier: The record that might be replaced.
        outcome: Supersedes, review required, or unrelated.
        failed: The names of the failed tests (empty for ``supersedes``).
    """

    later: str
    earlier: str
    outcome: Outcome
    failed: tuple[str, ...]


Quotes = Callable[[KnowledgeRecord], str]


def stored_quotes(session: Session) -> Quotes:
    """Read a record's user quotes from the stored messages, exactly as cited."""

    def quotes(record: KnowledgeRecord) -> str:
        found = []
        for ref in record.evidence:
            if ref.actor is not Role.USER:
                continue  # the proposal it answers is the assistant's words
            stored = revision_text(session, ref.revision_id)
            if stored is not None:
                found.append(stored[0][ref.start : ref.end])
        return "\n".join(found)

    return quotes


def evaluate(earlier: Placed, later: Placed, quotes: Quotes) -> Verdict:
    """Run the seven tests (see the module text) on one ordered pair."""
    a, b = earlier.record, later.record
    pair = (b.record_id, a.record_id)
    if (
        a.record_type not in CHOICES
        or a.record_type is not b.record_type
        or a.actor is not b.actor
        or Trust.REJECTED in (a.trust, b.trust)
    ):
        return Verdict(*pair, Outcome.UNRELATED, ("kinds",))
    if overlap(earlier, later) is None:
        return Verdict(*pair, Outcome.UNRELATED, ("scope",))
    shared_terms = set(a.term_ids) & set(b.term_ids)
    if not shared_terms and not content_words(a.assertion) & content_words(b.assertion):
        return Verdict(*pair, Outcome.UNRELATED, ("subject",))
    failed = []
    if (
        later.first_time is None
        or earlier.first_time is None
        or later.first_time <= earlier.first_time
    ):
        failed.append("order")
    accepted = b.acceptance is Acceptance.EXPLICIT and b.trust in (Trust.SUPPORTED, Trust.CONFIRMED)
    if not accepted:
        failed.append("accepted")
    said = quotes(b)
    if _HYPOTHETICAL.search(said):
        failed.append("hypothetical")
    if not _INTENT.search(said):
        failed.append("intent")
    if failed:
        return Verdict(*pair, Outcome.REVIEW_REQUIRED, tuple(failed))
    return Verdict(*pair, Outcome.SUPERSEDES, ())


def find_verdicts(items: Sequence[Placed], quotes: Quotes) -> list[Verdict]:
    """Verdicts for every pair of choices that are at least about the same thing.

    Unrelated pairs are left out. Each pair is judged once, earlier record
    first by source time (record ID breaks ties and unknown times).
    """
    choices = sorted(
        (i for i in items if i.record.record_type in CHOICES and i.revisions),
        key=lambda p: (p.first_time is None, p.first_time or 0.0, p.record.record_id),
    )
    verdicts = []
    for index, earlier in enumerate(choices):
        for later in choices[index + 1 :]:
            verdict = evaluate(earlier, later, quotes)
            if verdict.outcome is not Outcome.UNRELATED:
                verdicts.append(verdict)
    return verdicts


@dataclass(frozen=True)
class SupersessionReport:
    """What one reconciler run found.

    Attributes:
        superseded: (later, earlier) pairs recorded as ``supersedes``.
        review_required: Verdicts a reviewer must look at.
    """

    superseded: tuple[tuple[str, str], ...]
    review_required: tuple[Verdict, ...]


def reconcile(session: Session) -> SupersessionReport:
    """Judge every candidate pair; record the clear replacements. The caller commits."""
    rows = session.scalars(select(KnowledgeRecordRow).order_by(KnowledgeRecordRow.record_id))
    placed = place(session, [KnowledgeRecord.model_validate_json(r.record_json) for r in rows])
    by_id = {p.record.record_id: p for p in placed}
    superseded, review = [], []
    for verdict in find_verdicts(placed, stored_quotes(session)):
        if verdict.outcome is Outcome.SUPERSEDES:
            record_event(
                session,
                Transition.SUPERSEDES,
                by_id[verdict.later],
                by_id[verdict.earlier],
                actor=DETECTOR_VERSION,
                evidence={"tests": "kinds,scope,subject,order,accepted,not_hypothetical,intent"},
            )
            superseded.append((verdict.later, verdict.earlier))
        else:
            review.append(verdict)
    return SupersessionReport(tuple(superseded), tuple(review))
