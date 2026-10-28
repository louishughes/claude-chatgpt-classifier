"""Code checks for a rich note: the part of the NOTE-011 rubric a program can judge.

A rich note (NOTE-001, with a NOTE-003 digest) makes claims about a chat.
Before anyone scores how *good* a note is, these checks make sure it is
*honest*, by reading the rendered Markdown the way a reader would and
comparing it with the stored chat:

* ``citations_real``: every ``[m12]`` link points at a message of this
  chat, and the number is the one the transcript shows for that message
  (``alt`` for a message on another branch);
* ``claims_cited``: every summary sentence and every item under a claim
  section (decisions, suggestions, actions, questions, requirements,
  insights, tensions, next steps) cites at least one message;
* ``decisions_user_held``: every decision or "ruled out" record is held by
  the user and quotes the user's own words, so an assistant suggestion
  was never promoted to the user's decision;
* ``tensions_next_steps``: no next step repeats something the chat ruled
  out or lists a tension as the thing to do (a word-overlap test, so it
  warns rather than fails);
* ``empty_sections``: a section with nothing in it is one sentence, never
  an evidence box;
* ``budget``: the body stays under ``body_budget`` for the chat's length.

These checks never judge whether a summary is *right*; that is the
independent reference set and scorer in the PC thread (NOTE-011's other
half). No model is called.

Talking points:
    - "Before asking whether a note is good, check it isn't making things
      up: every claim has a message number, and every number is real."
    - "The checks read the Markdown, not the renderer's internals, so they
      catch a bug in the renderer too."
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.documents.model import DocumentKind, build_document
from knowledge_engine.documents.render import transcript_stem
from knowledge_engine.documents.rich_note import WAITING, body_budget, body_of
from knowledge_engine.domain.enums import Role
from knowledge_engine.extraction.records import KnowledgeRecord
from knowledge_engine.extraction.store import KnowledgeRecordRow
from knowledge_engine.rendering.transcript import (
    StoredConversation,
    load_conversation,
    node_key_for_anchor,
)

NOTE_CHECKS_VERSION = "note-011-v1"

# Sections whose bullets are claims about the chat, so each must cite.
CLAIM_SECTIONS = (
    "Decisions",
    "Suggestions",
    "Action items",
    "Open questions",
    "Requirements and preferences",
    "Insights",
    "Tensions and trade-offs",
    "Next steps",
)
# Two lines this similar (shared content words over the shorter's words)
# are taken to say the same thing.
SAME_THING = 0.6

# ``[[stem#^anchor|m12]]``; inside a table cell the pipe is escaped as a backslash-pipe.
_LINK = re.compile(r"\[\[([^#\]|]+)#\^([^|\]\\]+)\\?\|([^\]]+)\]\]")
_HEADING = re.compile(r"^## (.+)$", re.MULTILINE)
_WORDS = re.compile(r"[^\W\d_]{3,}")
_COMMON = frozenset(
    """
    the and for with that this from into your you are was were will would
    should could can not but also then than them they their there about
    """.split()
)


class CheckStatus(StrEnum):
    """One check's outcome."""

    PASS = "pass"
    WARN = "warn"
    FAIL = "fail"


@dataclass(frozen=True)
class Finding:
    """One check's result, with the problems it found (no chat text)."""

    check: str
    status: CheckStatus
    problems: tuple[str, ...] = ()


@dataclass(frozen=True)
class NoteCheckReport:
    """Every check for one note."""

    conversation_id: str
    findings: tuple[Finding, ...]
    version: str = NOTE_CHECKS_VERSION

    @property
    def passed(self) -> bool:
        """True when no check failed (warnings are allowed)."""
        return all(f.status is not CheckStatus.FAIL for f in self.findings)


def check_note(session: Session, conversation_id: str, text: str) -> NoteCheckReport:
    """Run every code check on one rendered rich note.

    Args:
        session: A read session.
        conversation_id: The chat the note is about.
        text: The note as written (front matter and all).
    """
    chat = load_conversation(session, conversation_id)
    body = body_of(text)
    sections = split_sections(body)
    findings = (
        _citations_real(chat, body),
        _claims_cited(body, sections),
        _decisions_user_held(session, conversation_id),
        _tensions_next_steps(sections),
        _empty_sections(sections),
        _budget(chat, body),
    )
    return NoteCheckReport(conversation_id, findings)


def split_sections(body: str) -> dict[str, str]:
    """``## Heading`` -> its text, plus ``""`` for what comes before the first."""
    parts = _HEADING.split(body)
    sections = {"": parts[0]}
    for title, content in zip(parts[1::2], parts[2::2], strict=True):
        sections[title.strip()] = content
    return sections


def _finding(name: str, problems: Sequence[str], *, warn: bool = False) -> Finding:
    if not problems:
        return Finding(name, CheckStatus.PASS)
    return Finding(name, CheckStatus.WARN if warn else CheckStatus.FAIL, tuple(problems))


def _citations_real(chat: StoredConversation, body: str) -> Finding:
    stem = transcript_stem(chat.conversation_id, chat.title)
    natives = {key: native for native, key in chat.node_keys.items()}
    problems = []
    for target, anchor, label in _LINK.findall(body):
        if target != stem:
            continue  # a link to another note (a related chat), not a citation
        native = natives.get(node_key_for_anchor(anchor))
        if native is None:
            problems.append(f"{label} points at no message of this chat ({anchor})")
            continue
        number = chat.graph.message_number(native)
        expected = f"m{number}" if number is not None else "alt"
        if label != expected:
            problems.append(f"{label} should read {expected} ({anchor})")
    return _finding("citations_real", problems)


def _cited(line: str) -> bool:
    return _LINK.search(line) is not None


def _bullets(content: str) -> list[str]:
    return [line[2:] for line in content.splitlines() if line.startswith("- ")]


def _claims_cited(body: str, sections: dict[str, str]) -> Finding:
    problems = []
    summary = [
        line[2:]
        for line in sections[""].splitlines()
        if line.startswith("> ") and not line.startswith("> [!")
    ]
    for n, line in enumerate(summary, start=1):
        if line.strip() != WAITING and not _cited(line):
            problems.append(f"summary sentence {n} cites no message")
    for title in CLAIM_SECTIONS:
        for n, line in enumerate(_bullets(sections.get(title, "")), start=1):
            if not _cited(line):
                problems.append(f"{title}: item {n} cites no message")
    for row in ("Purpose", "Outcome"):
        match = re.search(rf"^\| \*\*{row}\*\* \| (.*) \|$", body, re.MULTILINE)
        if match and match.group(1) not in ("not written yet", "not stated"):
            if not _cited(match.group(1)):
                problems.append(f"card {row} cites no message")
    return _finding("claims_cited", problems)


def _decisions_user_held(session: Session, conversation_id: str) -> Finding:
    document = build_document(session, DocumentKind.CONVERSATION, conversation_id)
    wanted = sorted(
        item.record_id
        for section in document.sections
        for item in section.items
        if item.record_type in ("decision", "rejection")
    )
    rows = session.scalars(
        select(KnowledgeRecordRow).where(KnowledgeRecordRow.record_id.in_(wanted))
    )
    problems = []
    for row in rows:
        record = KnowledgeRecord.model_validate_json(row.record_json)
        if record.actor is not Role.USER:
            problems.append(f"{row.record_id}: a {record.record_type} held by {record.actor}")
        elif not any(ref.actor is Role.USER for ref in record.evidence):
            problems.append(f"{row.record_id}: no quote of the user's own words")
    return _finding("decisions_user_held", problems)


def _content_words(line: str) -> set[str]:
    plain = _LINK.sub(" ", line)
    return {w.casefold() for w in _WORDS.findall(plain)} - _COMMON


def _same_thing(a: set[str], b: set[str]) -> bool:
    shorter = min(len(a), len(b))
    return shorter > 0 and len(a & b) / shorter >= SAME_THING


def _tensions_next_steps(sections: dict[str, str]) -> Finding:
    steps = [(line, _content_words(line)) for line in _bullets(sections.get("Next steps", ""))]
    ruled_out = [
        _content_words(line.split(" Ruled out.", 1)[0])
        for line in _bullets(sections.get("Decisions", ""))
        if " Ruled out." in line
    ]
    tensions = [
        _content_words(line) for line in _bullets(sections.get("Tensions and trade-offs", ""))
    ]
    problems = []
    for n, (_, words) in enumerate(steps, start=1):
        if any(_same_thing(words, other) for other in ruled_out):
            problems.append(f"next step {n} repeats something the chat ruled out")
        if any(_same_thing(words, other) for other in tensions):
            problems.append(f"next step {n} restates a tension instead of a step")
    return _finding("tensions_next_steps", problems, warn=True)


def _empty_sections(sections: dict[str, str]) -> Finding:
    problems = []
    for title, content in sections.items():
        if title and not _bullets(content) and "[!quote]" in content:
            problems.append(f"{title}: evidence box with no item")
    return _finding("empty_sections", problems)


def _budget(chat: StoredConversation, body: str) -> Finding:
    limit = body_budget(len(chat.graph.active_messages))
    if len(body) <= limit:
        return Finding("budget", CheckStatus.PASS)
    return Finding("budget", CheckStatus.FAIL, (f"{len(body)} characters, budget {limit}",))


def summarise(reports: Iterable[NoteCheckReport]) -> dict[str, dict[str, int]]:
    """Per check: how many notes passed, warned and failed."""
    counts: dict[str, dict[str, int]] = {}
    for report in reports:
        for finding in report.findings:
            row = counts.setdefault(finding.check, {s.value: 0 for s in CheckStatus})
            row[finding.status.value] += 1
    return counts
