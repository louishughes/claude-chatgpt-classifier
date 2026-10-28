"""Read the per-chat answer key into a golden set that ``ke gold score`` can use (EVAL-014).

The real answer key (REV-003, then v2 from REV-010) was written in the
classification spike's own shape: one JSON file per chat, holding the
native ``conversation_id``, the spike's ``segments`` and a list of
``items`` (type, text, message number, speaker, decision state...). The
scorer reads one ``gold-v1`` ``GoldSet`` file. This module converts the
first into the second, **reading only**: the key folder is never written.

What is converted, and what is reported instead of guessed:

* **Records.** ``idea``, ``requirement``, ``preference``, ``artefact`` and
  ``open_question`` map one to one. A ``decision`` maps by its state:
  accepted or superseded is a user decision, rejected is a user rejection,
  both at the user's deciding message; proposed is a proposal by whoever
  made it. ``fact``, ``task``, ``fact_about_owner``, ``problem_fix`` and an
  ``unclear`` decision have no exact engine equivalent: they are counted
  as unmapped and left out.
* **Messages.** An item with a native ``message_id`` (v2) is placed by it,
  and its number is checked against the engine's numbering. An item with
  only a number (v1) is placed by that number, and then its quote must be
  found in that message, so an off-by-one shows up as a skipped item rather
  than a wrong one. A deciding message must be the user's.
* **Unverified** items (``unverified: true``) are left out and counted.
* **Segments** carry the spike's labels, not taxonomy IDs, so they are
  counted and not converted; the result scores extraction only.

Talking points:
    - "The converter reads the answer key and never writes to it; anything
      it can't map exactly is counted, not guessed."
    - "Every converted item is placed by its message ID, or its quote has to
      be found in the message its number points at."
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from knowledge_engine.domain.enums import Role
from knowledge_engine.evaluation.gold import GoldConversation, GoldRecord, GoldSet
from knowledge_engine.extraction.records import Acceptance, RecordType
from knowledge_engine.graph.offsets import find_quote
from knowledge_engine.rendering.transcript import (
    StoredConversation,
    find_conversation,
    load_conversation,
)

# Item types that mean the same thing in the engine.
_SAME = {
    "idea": RecordType.IDEA,
    "requirement": RecordType.REQUIREMENT,
    "preference": RecordType.PREFERENCE,
    "artefact": RecordType.ARTEFACT,
    "open_question": RecordType.QUESTION,
}
# A decision's state -> the engine record it is, held by the user at the
# deciding message. ``proposed`` is handled apart: it stays with its proposer.
_DECIDED = {
    "accepted": RecordType.DECISION,
    "superseded": RecordType.DECISION,
    "rejected": RecordType.REJECTION,
}


@dataclass
class ConversionReport:
    """What the conversion did, in counts only (no chat text).

    Attributes:
        files: Key files read.
        found: Of those, chats found in this workspace.
        records: Items converted into expected records.
        unmapped: Item type (``decision:<state>`` for decisions) -> count.
        unverified: Items marked ``unverified`` and left out.
        skipped: Reason -> count, for items that couldn't be placed.
        segments: Spike segments counted and not converted.
        number_mismatch: Items placed by ``message_id`` whose number disagreed.
        missing_chats: Native IDs of key chats not in this workspace.
    """

    files: int = 0
    found: int = 0
    records: int = 0
    unmapped: Counter[str] = field(default_factory=Counter)
    unverified: int = 0
    skipped: Counter[str] = field(default_factory=Counter)
    segments: int = 0
    number_mismatch: int = 0
    missing_chats: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        """The report as plain JSON-ready data."""
        return {
            "files": self.files,
            "found": self.found,
            "records": self.records,
            "unmapped": dict(sorted(self.unmapped.items())),
            "unverified": self.unverified,
            "skipped": dict(sorted(self.skipped.items())),
            "segments_not_converted": self.segments,
            "number_mismatch": self.number_mismatch,
            "missing_chats": len(self.missing_chats),
        }


class _Numbers:
    """One chat's message numbers both ways, and quote checks."""

    def __init__(self, chat: StoredConversation) -> None:
        self.chat = chat
        self.by_number: dict[int, str] = {}
        for native in chat.node_keys:
            number = chat.graph.message_number(native)
            if number is not None:
                self.by_number[number] = native

    def role(self, native: str) -> str | None:
        node = self.chat.messages.get(native)
        return None if node is None or node.role is None else str(node.role)

    def quoted(self, native: str, quote: str | None) -> bool:
        node = self.chat.messages.get(native)
        return bool(quote) and node is not None and bool(find_quote(node.text, quote or ""))


def _place(item: dict[str, Any], numbers: _Numbers, report: ConversionReport) -> str | None:
    """The native ID of the item's own message, or None (and why, in the report)."""
    quote = item.get("quote") or item.get("evidence_quote")
    native = item.get("message_id")
    if native:
        if numbers.chat.graph.message_number(native) is None:
            report.skipped["message_id not on the active path"] += 1
            return None
        if item.get("message") is not None and (
            numbers.chat.graph.message_number(native) != item["message"]
        ):
            # The ID wins; the number is counted so the key can be fixed.
            report.number_mismatch += 1
        return str(native)
    number = item.get("message")
    found = numbers.by_number.get(number) if isinstance(number, int) else None
    if found is None:
        report.skipped["message number not in the chat"] += 1
        return None
    if not numbers.quoted(found, quote):
        report.skipped["quote not in the numbered message"] += 1
        return None
    return found


def _record(item: dict[str, Any], numbers: _Numbers, report: ConversionReport) -> GoldRecord | None:
    kind = str(item.get("type", ""))
    speaker = str(item.get("speaker", ""))
    if speaker not in (Role.USER.value, Role.ASSISTANT.value):
        report.skipped["speaker not user or assistant"] += 1
        return None
    quote = item.get("quote") or item.get("evidence_quote")
    if kind in _SAME:
        native = _place(item, numbers, report)
        if native is None:
            return None
        return GoldRecord(
            record_type=_SAME[kind], actor=Role(speaker), message_id=native, quote=quote
        )
    if kind != "decision":
        report.unmapped[kind or "(no type)"] += 1
        return None
    state = str(item.get("state", ""))
    if state == "proposed":
        native = _place(item, numbers, report)
        if native is None:
            return None
        return GoldRecord(
            record_type=RecordType.PROPOSAL,
            actor=Role(speaker),
            message_id=native,
            acceptance=Acceptance.ABSENT,
            quote=quote,
        )
    if state not in _DECIDED:
        report.unmapped[f"decision:{state or '(no state)'}"] += 1
        return None
    decided = item.get("decided_in")
    native = numbers.by_number.get(decided) if isinstance(decided, int) else None
    if native is None:
        report.skipped["decided_in not in the chat"] += 1
        return None
    if numbers.role(native) != Role.USER.value:
        # Only the user can accept or reject; a key pointing elsewhere is
        # off by one or wrong, and is not converted.
        report.skipped["decided_in is not a user message"] += 1
        return None
    return GoldRecord(
        record_type=_DECIDED[state],
        actor=Role.USER,
        message_id=native,
        acceptance=Acceptance.EXPLICIT,
        quote=quote if numbers.quoted(native, quote) else None,
    )


def convert_answer_key(
    session: Session,
    folder: Path,
    *,
    name: str,
    taxonomy_version: str,
    annotator: str,
) -> tuple[GoldSet, ConversionReport]:
    """Read every ``*.json`` key file in ``folder`` into one golden set.

    Args:
        session: A read session on the workspace holding the chats.
        folder: The per-chat key folder (read only).
        name: The golden set's name, e.g. ``answer-key-v2``.
        taxonomy_version: Recorded on the set (no labels are converted).
        annotator: Who wrote the key, as the scores should credit it.

    Returns:
        The golden set (chats found in this workspace only) and the report.
    """
    report = ConversionReport()
    conversations = []
    for path in sorted(folder.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        report.files += 1
        native_id = str(data["conversation_id"])
        report.segments += len(data.get("segments") or [])
        found = find_conversation(session, native_id)
        if found is None:
            report.missing_chats.append(native_id)
            continue
        report.found += 1
        numbers = _Numbers(load_conversation(session, found))
        records = []
        for item in data.get("items") or []:
            if item.get("unverified"):
                report.unverified += 1
                continue
            record = _record(item, numbers, report)
            if record is not None:
                records.append(record)
        report.records += len(records)
        conversations.append(
            GoldConversation(
                native_conversation_id=native_id,
                annotator=annotator,
                records_annotated=True,
                records=tuple(records),
            )
        )
    gold = GoldSet(
        name=name,
        synthetic=False,
        taxonomy_version=taxonomy_version,
        conversations=tuple(conversations),
    )
    return gold, report
