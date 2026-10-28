"""Tasks, open questions and real artefacts, by rule (EXT-005).

Three kinds of candidate:

* **action**: a task.
  - The *user's* own commitment ("I'll repaint it tomorrow", "my next step
    is...") is an action held by the user, with explicit acceptance.
  - A task the *assistant* hands out ("you should sand it first", "make
    sure to...") is an action held by the **assistant** with no acceptance:
    a suggested task, never the user's commitment until the user takes it
    up (EXT-003 records a yes).
* **question**: an *open* question. That is a user question with no
  assistant answer after it in the segment, or one the assistant answered
  with "I don't know" or "I'm not sure".
* **artefact**: something the assistant or a tool actually produced.
  - An **image or file** in its message: the record lists the real asset
    occurrence IDs (``occ_``, MED-003). The ones whose bytes are missing
    are listed again as missing, so the gap is reported, never papered
    over.
  - A **fenced code block** in an assistant message, quoted exactly.

  Images the user uploaded are inputs, not artefacts.

Talking points:
    - "'You should sand it' is the assistant's suggestion. It only becomes
      my task if I take it on."
    - "An artefact points at the real image occurrences; if the bytes are
      gone, the record says so."
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.domain.enums import AssetAvailability, Role
from knowledge_engine.domain.models import EvidenceRef
from knowledge_engine.extraction.records import Acceptance, CandidateRecord, RecordType, Scope
from knowledge_engine.extraction.text import ExtractionMessage, quote, sentences
from knowledge_engine.graph.offsets import Span
from knowledge_engine.importer.media import AssetOccurrenceRow

EXTRACTOR_VERSION = "ext-005-rules-v1"
_USER_TASK = re.compile(
    r"\b(?:i'?ll|i will|i need to|i'?m going to|i am going to|let me|my next step is|"
    r"i have to|i must|todo:?|to do:)\b",
    re.IGNORECASE,
)
_SUGGESTED_TASK = re.compile(
    r"\b(?:you should|you'?ll need to|you need to|make sure to|be sure to|remember to|"
    r"next,? you|first,? you|step \d+)\b",
    re.IGNORECASE,
)
_NOT_KNOWN = re.compile(
    r"\b(?:i don'?t know|i'?m not sure|i am not sure|i can'?t tell|it'?s unclear|"
    r"no way to know)\b",
    re.IGNORECASE,
)
_FENCE = re.compile(r"```[^\n]*\n.*?```", re.DOTALL)
_PRODUCERS = (Role.ASSISTANT, Role.TOOL)


@dataclass(frozen=True)
class Occurrence:
    """One image or file use in a message (from MED-003's table)."""

    occurrence_id: str
    asset_id: str | None
    available: bool


def load_occurrences(session: Session, revision_ids: Sequence[str]) -> dict[str, list[Occurrence]]:
    """Asset occurrences by revision, in part order. Read only."""
    found: dict[str, list[Occurrence]] = {}
    for row in session.scalars(
        select(AssetOccurrenceRow)
        .where(AssetOccurrenceRow.revision_id.in_(list(revision_ids)))
        .order_by(AssetOccurrenceRow.revision_id, AssetOccurrenceRow.part_index)
    ):
        found.setdefault(row.revision_id, []).append(
            Occurrence(
                row.occurrence_id,
                row.asset_id,
                row.availability == AssetAvailability.AVAILABLE,
            )
        )
    return found


def extract_actions(
    messages: Sequence[ExtractionMessage],
    *,
    segment_id: str,
    occurrences: Mapping[str, list[Occurrence]] | None = None,
) -> list[CandidateRecord]:
    """Tasks, open questions and artefacts in one segment, in text order.

    Args:
        messages: The segment's messages, in order.
        segment_id: The records' scope.
        occurrences: From ``load_occurrences``; without it no image
            artefacts are found.
    """
    occurrences = occurrences or {}
    found: list[CandidateRecord] = []
    for index, message in enumerate(messages):
        if message.role is Role.USER:
            found += _user_sentences(message, messages[index + 1 :], segment_id)
        elif message.role in _PRODUCERS:
            found += _produced(message, occurrences.get(message.revision_id, []), segment_id)
    return found


def _user_sentences(
    message: ExtractionMessage, after: Sequence[ExtractionMessage], segment_id: str
) -> list[CandidateRecord]:
    found = []
    answer = next((m for m in after if m.role is Role.ASSISTANT), None)
    for span in sentences(message.text):
        said = span.of(message.text)
        if said.rstrip().endswith("?"):
            if answer is None:
                reason = None  # nobody answered it
            elif _NOT_KNOWN.search(answer.text):
                reason = None  # answered with "I don't know"
            else:
                continue  # answered: not open
            found.append(
                _record(
                    RecordType.QUESTION,
                    Role.USER,
                    Acceptance.NOT_APPLICABLE,
                    said,
                    [quote(message, span)],
                    segment_id,
                    reason,
                )
            )
        elif _USER_TASK.search(said):
            found.append(
                _record(
                    RecordType.ACTION,
                    Role.USER,
                    Acceptance.EXPLICIT,
                    said,
                    [quote(message, span)],
                    segment_id,
                )
            )
    return found


def _produced(
    message: ExtractionMessage, uses: list[Occurrence], segment_id: str
) -> list[CandidateRecord]:
    found = []
    fences = [Span(m.start(), m.end()) for m in _FENCE.finditer(message.text)]
    for span in sentences(message.text):
        if any(f.start <= span.start < f.end for f in fences):
            continue  # inside code, not prose
        said = span.of(message.text)
        if message.role is Role.ASSISTANT and _SUGGESTED_TASK.search(said):
            found.append(
                _record(
                    RecordType.ACTION,
                    Role.ASSISTANT,
                    Acceptance.ABSENT,
                    said,
                    [quote(message, span)],
                    segment_id,
                )
            )
    for fence in fences:
        found.append(
            _record(
                RecordType.ARTEFACT,
                message.role,
                Acceptance.NOT_APPLICABLE,
                "code block",
                [quote(message, fence)],
                segment_id,
            )
        )
    if uses:
        text = message.text.strip()
        caption = [quote(message, next(iter(sentences(message.text))))] if text else []
        missing = tuple(u.occurrence_id for u in uses if not u.available)
        found.append(
            CandidateRecord.model_validate(
                {
                    "record_type": RecordType.ARTEFACT,
                    "assertion": f"{len(uses)} produced image or file use(s)",
                    "actor": message.role,
                    "acceptance": Acceptance.NOT_APPLICABLE,
                    "scope": Scope.SEGMENT,
                    "scope_id": segment_id,
                    "evidence": caption,
                    "asset_occurrences": tuple(u.occurrence_id for u in uses),
                    "missing_occurrences": missing,
                    "review_reason": "bytes missing for some images" if missing else None,
                }
            )
        )
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
            "assertion": assertion[:300],
            "actor": actor,
            "acceptance": acceptance,
            "scope": Scope.SEGMENT,
            "scope_id": segment_id,
            "evidence": evidence,
            "review_reason": reason,
        }
    )
