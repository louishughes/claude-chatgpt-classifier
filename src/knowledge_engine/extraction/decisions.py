"""Proposals, decisions and rejections, by rule (EXT-003).

The hard part of a decision is *who* decided. An assistant suggesting
SQLite and a user asking "how does SQLite handle concurrent writes?" is a
curious user, not a decision. This extractor reads the segment in order
and keeps those apart:

1. **Proposals.** An assistant sentence with a suggestion cue ("I suggest",
   "I recommend", "you could", "how about"...) becomes a ``proposal`` held
   by the assistant. It is never the user's decision on its own.
2. **Replies.** The user message straight after a proposal is read as:
   - a **rejection** ("no", "let's not", "I'd rather not"...);
   - a **conditional** acceptance ("ok, as long as it doesn't leak");
   - an **explicit** acceptance ("yes, let's do that", "sounds good");
   - otherwise nothing: a question, a hedge or a change of subject accepts
     nothing.

   An accepted or rejected proposal gives a ``decision`` or ``rejection``
   held by the user. Its evidence is the user's sentence **and** the
   proposal sentence it answers (the antecedent). If the assistant made
   several proposals, the record is flagged because it is unclear which
   one was taken. Acceptance mixed with a question is flagged too.
3. **The user's own decisions.** A user sentence such as "I've decided to
   use cedar cladding" or "I've ruled out pine" is a decision or rejection
   with explicit acceptance, even with no proposal before it. A negation
   just before the cue ("I haven't decided") cancels it.

Every output is a ``CandidateRecord``: a proposal for EXT-002 and EXT-007
to check, never a trusted fact.

Talking points:
    - "An assistant's suggestion only becomes the user's decision when the
      user's own next words accept it."
    - "Each decision cites both sides: the user's yes and the suggestion it
      said yes to."
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from knowledge_engine.domain.enums import Role
from knowledge_engine.domain.models import EvidenceRef
from knowledge_engine.extraction.records import (
    Acceptance,
    CandidateRecord,
    RecordType,
    Scope,
)
from knowledge_engine.extraction.text import ExtractionMessage, quote, sentences
from knowledge_engine.graph.offsets import Span

EXTRACTOR_VERSION = "ext-003-rules-v1"
_PROPOSAL = re.compile(
    r"\b(?:i (?:would |'d )?(?:suggest|recommend)|you (?:could|should|might want to|may want "
    r"to)|how about|one option is|i'?d go with|my recommendation)\b",
    re.IGNORECASE,
)
_REJECT = re.compile(
    r"^\W*(?:no|nope|nah)\b|\b(?:not that|i don'?t want (?:that|it)|let'?s not|"
    r"(?:i'?d )?rather not|i'?ll pass|skip (?:that|it))\b",
    re.IGNORECASE,
)
_ACCEPT = re.compile(
    r"^\W*(?:yes|yeah|yep|sure|ok(?:ay)?|sounds good|great|perfect|agreed|deal)\b|"
    r"\b(?:let'?s do (?:that|it)|do that|go with (?:that|it)|i'?ll do that|that works)\b",
    re.IGNORECASE,
)
_CONDITION = re.compile(
    r"\b(?:as long as|only if|provided(?: that)?|on condition that|so long as)\b", re.I
)
_QUESTION_OR_HEDGE = re.compile(r"\?|\b(?:maybe|perhaps|not sure|might)\b", re.IGNORECASE)
_OWN_DECISION = re.compile(
    r"\b(?:i'?ve decided|i have decided|i decided|we'?ve decided|we decided|i'?ll go with|"
    r"we'?ll go with|i'?m going with|we'?re going with|i'?ve settled on|decided to)\b",
    re.IGNORECASE,
)
_OWN_REJECTION = re.compile(
    r"\b(?:decided against|ruled out|i won'?t use|we won'?t use|not going to use|"
    r"i'?m dropping|we'?re dropping)\b",
    re.IGNORECASE,
)
_NEGATED = re.compile(r"\b(?:not|never|haven'?t|hasn'?t|didn'?t|don'?t)\s+$", re.IGNORECASE)
_MAX_ASSERTION = 300


def _text(message: ExtractionMessage, span: Span) -> str:
    return span.of(message.text)[:_MAX_ASSERTION]


def extract_decisions(
    messages: Sequence[ExtractionMessage], *, segment_id: str
) -> list[CandidateRecord]:
    """Proposals, decisions and rejections in one segment, in text order.

    Args:
        messages: The segment's messages, in order.
        segment_id: Used as the records' scope.

    Returns:
        Candidate records (never trusted; EXT-007 decides).
    """
    found: list[CandidateRecord] = []
    pending: list[tuple[ExtractionMessage, Span]] = []  # the last assistant proposals
    for message in messages:
        if message.role is Role.ASSISTANT:
            pending = [
                (message, span)
                for span in sentences(message.text)
                if _PROPOSAL.search(span.of(message.text))
            ]
            for proposal, span in pending:
                found.append(
                    _record(
                        RecordType.PROPOSAL,
                        Role.ASSISTANT,
                        Acceptance.ABSENT,
                        _text(proposal, span),
                        [quote(proposal, span)],
                        segment_id,
                    )
                )
            continue
        if message.role is not Role.USER:
            continue
        replied: set[Span] = set()
        if pending:
            reply = _reply(message, pending, segment_id)
            if reply is not None:
                record, span = reply
                found.append(record)
                replied.add(span)
        pending = []
        found += _own_decisions(message, segment_id, skip=replied)
    return found


def _reply(
    message: ExtractionMessage,
    proposals: list[tuple[ExtractionMessage, Span]],
    segment_id: str,
) -> tuple[CandidateRecord, Span] | None:
    first = next(iter(sentences(message.text)), None)
    if first is None:
        return None
    said = first.of(message.text)
    antecedents = [quote(m, s) for m, s in proposals]
    reason = None
    if len(proposals) > 1:
        reason = "several proposals; which one the reply answers is unclear"
    if _REJECT.search(said):
        kind, acceptance = RecordType.REJECTION, Acceptance.EXPLICIT
    elif _ACCEPT.search(said) and _CONDITION.search(message.text):
        kind, acceptance = RecordType.DECISION, Acceptance.CONDITIONAL
        # The condition may sit in a later sentence; cite the whole reply then.
        first = Span(first.start, len(message.text.rstrip()))
    elif _ACCEPT.search(said):
        kind, acceptance = RecordType.DECISION, Acceptance.EXPLICIT
        if _QUESTION_OR_HEDGE.search(message.text):
            reason = "acceptance mixed with a question or hedge"
    else:
        return None  # a question, a hedge or something else: nothing accepted
    proposal_text = proposals[0][1].of(proposals[0][0].text)[:_MAX_ASSERTION]
    record = _record(
        kind,
        Role.USER,
        acceptance,
        proposal_text,
        [quote(message, first), *antecedents],
        segment_id,
        reason,
    )
    return record, first


def _own_decisions(
    message: ExtractionMessage, segment_id: str, *, skip: set[Span]
) -> list[CandidateRecord]:
    found = []
    for span in sentences(message.text):
        if any(span.start < s.end and s.start < span.end for s in skip):
            continue
        said = span.of(message.text)
        for pattern, kind in (
            (_OWN_REJECTION, RecordType.REJECTION),
            (_OWN_DECISION, RecordType.DECISION),
        ):
            match = pattern.search(said)
            if match and not _NEGATED.search(said[: match.start()]):
                reason = "phrased as a question" if said.rstrip().endswith("?") else None
                found.append(
                    _record(
                        kind,
                        Role.USER,
                        Acceptance.EXPLICIT,
                        _text(message, span),
                        [quote(message, span)],
                        segment_id,
                        reason,
                    )
                )
                break
    return found


def _record(
    kind: RecordType,
    actor: Role,
    acceptance: Acceptance,
    assertion: str,
    evidence: list[EvidenceRef],
    segment_id: str,
    reason: str | None = None,
) -> CandidateRecord:
    return CandidateRecord.model_validate(
        {
            "record_type": kind,
            "assertion": assertion,
            "actor": actor,
            "acceptance": acceptance,
            "scope": Scope.SEGMENT,
            "scope_id": segment_id,
            "evidence": evidence,
            "review_reason": reason,
        }
    )
