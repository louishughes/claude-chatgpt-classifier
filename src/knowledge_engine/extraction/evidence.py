"""Checking a record's evidence against the stored messages (EXT-002).

A record is only as good as the quotes it rests on. ``check_record`` looks
at every piece of evidence and gives one of three verdicts:

* ``invalid``: a reference is **malformed**. The message revision doesn't
  exist, the range runs past the text, the quote fingerprint doesn't match
  (wrong offsets, or the text changed), the speaker named on the evidence
  isn't who wrote that message, the same quote is cited twice, an asset
  occurrence doesn't exist, or the record misstates which ones are missing. Such a
  record is refused, never stored as knowledge.
* ``review_required``: the references are sound but the **meaning is
  ambiguous**:
  - a user commitment (decision, preference, requirement, task) or a
    rejection that cites only the assistant's words: a suggestion is not
    the user's decision;
  - acceptance claimed but no user words cited;
  - the user's quote is hedged ("maybe", "might", "not sure") or a
    question;
  - the quote sits inside a quotation (a ``>`` line or quotation marks), so
    the speaker may be repeating someone else;
  - an artefact whose image or file bytes are missing (reported, so a
    person sees it, but not refused: the reference itself is real);
  - the record is ``inferred``, reports someone else's view
    (``attributed_to``), or its extractor already flagged it.
* ``valid``: everything checks. A valid record may become ``supported``
  (EXT-007); it is never ``confirmed`` without a person.

Only IDs and short problem codes are reported, never message text.

Talking points:
    - "Broken references are rejected outright; doubtful meanings are
      parked for a person. Those are different failures."
    - "If the only words behind a 'user decision' are the assistant's, it
      isn't the user's decision."
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.domain.enums import AssetAvailability, Role
from knowledge_engine.domain.models import EvidenceRef
from knowledge_engine.extraction.records import (
    COMMITMENTS,
    Acceptance,
    CandidateRecord,
    Origin,
    RecordType,
)
from knowledge_engine.graph.nodes import canonical_node
from knowledge_engine.graph.offsets import Span, verify
from knowledge_engine.importer.media import AssetOccurrenceRow
from knowledge_engine.importer.records import MessageNodeRow, MessageRevisionRow

VALIDATOR_VERSION = "ext-002-v1"
_HEDGES = re.compile(
    r"\b(?:maybe|perhaps|might|possibly|not sure|unsure|thinking about|considering|"
    r"could (?:try|use|go)|what if|should i|should we)\b",
    re.IGNORECASE,
)
_QUOTE_PAIRS = (('"', '"'), ("“", "”"))
_NEEDS_USER_WORDS = COMMITMENTS | {RecordType.REJECTION}


class Verdict(StrEnum):
    """The outcome of checking one record."""

    VALID = "valid"
    INVALID = "invalid"  # malformed reference: refuse
    REVIEW_REQUIRED = "review_required"  # sound references, unclear meaning


@dataclass(frozen=True)
class EvidenceProblem:
    """One thing wrong or doubtful.

    Attributes:
        code: e.g. ``quote_mismatch``, ``assistant_words_only``.
        evidence_index: Which evidence item, or None for the record as a whole.
    """

    code: str
    evidence_index: int | None = None


@dataclass(frozen=True)
class EvidenceCheck:
    """The verdict and its reasons."""

    verdict: Verdict
    problems: tuple[EvidenceProblem, ...]
    validator_version: str = VALIDATOR_VERSION


# Problems that make a reference malformed (the rest are about meaning).
_MALFORMED = frozenset(
    {
        "revision_missing",
        "span_out_of_range",
        "quote_mismatch",
        "actor_mismatch",
        "duplicate",
        "occurrence_missing",
        "availability_mismatch",
    }
)


def revision_text(session: Session, revision_id: str) -> tuple[str, Role] | None:
    """The canonical text and speaker of a stored message revision, or None."""
    row = session.execute(
        select(
            MessageRevisionRow.role,
            MessageRevisionRow.content_json,
            MessageRevisionRow.create_time,
            MessageNodeRow.native_node_id,
        )
        .join(MessageNodeRow, MessageNodeRow.node_key == MessageRevisionRow.node_key)
        .where(MessageRevisionRow.revision_id == revision_id)
    ).first()
    if row is None:
        return None
    role, content, created, native = row
    message = {
        "id": native,
        "author": {"role": role},
        "content": json.loads(content),
        "create_time": created,
    }
    node = canonical_node(native, {"id": native, "message": message})
    if node is None:
        return None
    try:
        speaker = Role(role) if role else Role.UNKNOWN
    except ValueError:
        speaker = Role.UNKNOWN
    return node.text, speaker


def check_record(session: Session, record: CandidateRecord) -> EvidenceCheck:
    """Check every evidence reference, then what the evidence can support.

    Args:
        session: Read only.
        record: A candidate (or stored) record.

    Returns:
        ``invalid`` if any reference is malformed; otherwise
        ``review_required`` if the meaning is doubtful; otherwise ``valid``.
    """
    problems: list[EvidenceProblem] = []
    seen: set[tuple[str, int, int]] = set()
    user_quotes: list[str] = []
    for index, ref in enumerate(record.evidence):
        key = (ref.revision_id, ref.start, ref.end)
        if key in seen:
            problems.append(EvidenceProblem("duplicate", index))
            continue
        seen.add(key)
        found = revision_text(session, ref.revision_id)
        if found is None:
            problems.append(EvidenceProblem("revision_missing", index))
            continue
        text, speaker = found
        if ref.end > len(text):
            problems.append(EvidenceProblem("span_out_of_range", index))
            continue
        if not verify(text, Span(ref.start, ref.end), ref.quote_sha256):
            problems.append(EvidenceProblem("quote_mismatch", index))
            continue
        if ref.actor is not speaker:
            problems.append(EvidenceProblem("actor_mismatch", index))
            continue
        if inside_quotation(text, ref):
            problems.append(EvidenceProblem("inside_quotation", index))
        if speaker is Role.USER:
            quote = text[ref.start : ref.end]
            user_quotes.append(quote)
            if record.record_type in _NEEDS_USER_WORDS and _hedged(quote):
                problems.append(EvidenceProblem("hedged_or_question", index))
    problems += _occurrence_problems(session, record)
    if any(p.code in _MALFORMED for p in problems):
        return EvidenceCheck(Verdict.INVALID, tuple(problems))
    problems += _meaning_problems(record, user_quotes)
    verdict = Verdict.REVIEW_REQUIRED if problems else Verdict.VALID
    return EvidenceCheck(verdict, tuple(problems))


def _meaning_problems(record: CandidateRecord, user_quotes: list[str]) -> list[EvidenceProblem]:
    found = []
    if record.actor is Role.USER and record.record_type in _NEEDS_USER_WORDS and not user_quotes:
        found.append(EvidenceProblem("assistant_words_only"))
    accepted = record.acceptance in (Acceptance.EXPLICIT, Acceptance.CONDITIONAL)
    if accepted and not user_quotes:
        found.append(EvidenceProblem("acceptance_without_user_words"))
    if record.origin is Origin.INFERRED:
        found.append(EvidenceProblem("inferred"))
    if record.review_reason:
        found.append(EvidenceProblem("extractor_flagged"))
    if record.attributed_to:
        found.append(EvidenceProblem("someone_elses_view"))
    return found


def _occurrence_problems(session: Session, record: CandidateRecord) -> list[EvidenceProblem]:
    # An artefact's images must be real occurrences, and the record must
    # say truthfully which of them have no bytes.
    found = []
    missing = set(record.missing_occurrences)
    for occurrence_id in record.asset_occurrences:
        row = session.get(AssetOccurrenceRow, occurrence_id)
        if row is None:
            found.append(EvidenceProblem("occurrence_missing"))
        elif (row.availability != AssetAvailability.AVAILABLE) != (occurrence_id in missing):
            found.append(EvidenceProblem("availability_mismatch"))
    if missing:
        found.append(EvidenceProblem("artefact_bytes_missing"))
    return found


def _hedged(quote: str) -> bool:
    return bool(_HEDGES.search(quote)) or quote.rstrip().endswith("?")


def inside_quotation(text: str, ref: EvidenceRef) -> bool:
    """True if the quote starts in a ``>`` line or inside quotation marks on its line."""
    return quoted_at(text, ref.start)


def quoted_at(text: str, offset: int) -> bool:
    """True if position ``offset`` is in a ``>`` line or inside quotation marks on its line."""
    line_start = text.rfind("\n", 0, offset) + 1
    if text[line_start:].lstrip().startswith(">"):
        return True
    before = text[line_start:offset]
    for opening, closing in _QUOTE_PAIRS:
        if opening == closing:
            # Straight quotes: inside if an odd number come before on the line.
            if before.count(opening) % 2 == 1:
                return True
        elif before.rfind(opening) > before.rfind(closing):
            return True
    return False


# The EXT-002 tests use the earlier private name; kept so they stay unchanged.
_inside_quotation = inside_quotation
