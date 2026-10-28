"""Where an action stands, and what it waits for, from the user's own words (EXT-009, EXT-010).

An action record (EXT-005) says what someone said they would do. Two
questions follow, and both are answered only from later **user** messages
in the same chat, by rules a person can read:

* **Status** (``action_status``): ``open`` unless the user later says so.
  - ``reported_done``: a later user sentence says it is done ("done",
    "finished", "did it", "sorted", "fixed"), is not a question, is not
    negated ("not done yet", "haven't finished"), is not a condition
    ("after the roof is fixed"), and shares a content word with the action.
  - ``dropped``: a later user sentence explicitly lets it go ("not doing",
    "skip it", "forget it"), is neither negated ("don't forget it") nor
    asked, and shares a content word with the action, or, with no words
    of its own ("Forget it."), is the very next user message.
  An assistant saying "done" never changes a status; it can't speak for
  the user. No evidence means ``open``, never ``done``.
* **Dependencies** (``propose_dependencies``): when one user sentence names
  two of the chat's actions with "after", "once", "before" or
  "first ... then", the later one ``depends_on`` the earlier one, with that
  sentence as evidence. "Paint the shed after I fix the roof" means painting
  waits for the roof. These are proposals, never trusted: REC-002 stores
  them as candidates for review.

Talking points:
    - "An action is open until the user says it's done. The assistant saying
      'done' doesn't count, and silence doesn't either."
    - "'Paint it after I fix the roof' is a dependency in the user's own
      words, so it's proposed with that sentence as proof."
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from knowledge_engine.domain.enums import Role
from knowledge_engine.domain.models import EvidenceRef
from knowledge_engine.extraction.records import CandidateRecord, KnowledgeRecord
from knowledge_engine.extraction.text import ExtractionMessage, quote, sentences
from knowledge_engine.graph.offsets import Span
from knowledge_engine.reconciliation.equivalence import content_words

STATUS_VERSION = "ext-009-rules-v1"
DEPENDENCY_VERSION = "ext-010-rules-v1"

_DONE = re.compile(r"\b(?:done|finished|did it|sorted|fixed)\b", re.IGNORECASE)
_NOT = re.compile(r"\b(?:not|never|no|yet)\b|n'?t\b", re.IGNORECASE)
# "Paint it after the roof is fixed" sets a condition; it reports nothing.
_CONDITION = re.compile(r"\b(?:after|once|before|until|when|if|then)\b", re.IGNORECASE)
_DROPPED = re.compile(
    r"\b(?:not doing|not going to do|won'?t do|skip it|skip that|forget it|forget about)\b",
    re.IGNORECASE,
)
# The cue words themselves never count as the shared subject.
_CUE_WORDS = frozenset(
    "done finished did it sorted fixed not doing going do won't wont skip that forget about".split()
)


class ActionStatus(StrEnum):
    """Where an action stands."""

    OPEN = "open"
    REPORTED_DONE = "reported_done"
    DROPPED = "dropped"


@dataclass(frozen=True)
class StatusFinding:
    """A status and the user sentence that decided it (None for ``open``)."""

    status: ActionStatus
    evidence: EvidenceRef | None = None


def _subject(text: str) -> frozenset[str]:
    return content_words(text) - _CUE_WORDS


def action_status(
    record: CandidateRecord,
    later_user_messages: Sequence[ExtractionMessage],
    *,
    others: Sequence[CandidateRecord] = (),
) -> StatusFinding:
    """The action's status from the user messages after it, in chat order.

    Args:
        record: An action record.
        later_user_messages: The chat's messages after the action's own
            message; anything not written by the user is ignored.
        others: The chat's other actions. A sentence counts for this action
            only if no other action shares as many of its words: "the shed
            roof is fixed" is about fixing the roof, not painting the shed.

    Returns:
        The last deciding sentence's status, or ``open`` with no evidence.
    """
    subject = _subject(record.assertion)
    rivals = [_subject(o.assertion) for o in others if o.assertion != record.assertion]
    found = StatusFinding(ActionStatus.OPEN)
    users = [m for m in later_user_messages if m.role is Role.USER]
    for position, message in enumerate(users):
        for span in sentences(message.text):
            said = span.of(message.text)
            # "Is the roof done?" asks; it reports nothing and drops nothing.
            if said.rstrip().endswith("?"):
                continue
            words = _subject(said)
            mine = len(subject & words)
            shared = mine > 0 and all(len(r & words) < mine for r in rivals)
            if _DROPPED.search(said):
                # "Don't forget it" keeps the action; the cue's own "not" doesn't count.
                if _NOT.search(_DROPPED.sub("", said)):
                    continue
                bare = not _subject(said)
                if shared or (bare and position == 0):
                    found = StatusFinding(ActionStatus.DROPPED, quote(message, span))
            elif (
                _DONE.search(said)
                and not _NOT.search(said)
                and not _CONDITION.search(_IDIOM.sub("", said))
                and shared
            ):
                found = StatusFinding(ActionStatus.REPORTED_DONE, quote(message, span))
    return found


@dataclass(frozen=True)
class DependencyProposal:
    """``dependent`` waits for ``prerequisite``, as one user sentence says.

    Attributes:
        dependent: The record ID of the action that comes later.
        prerequisite: The record ID of the action it waits for.
        evidence: The sentence that names both.
        cue: The word that set the order ("after", "once", "before", "then").
    """

    dependent: str
    prerequisite: str
    evidence: EvidenceRef
    cue: str


# (pattern, cue, which group comes first, which comes later). Sentence-
# opening forms are tried before mid-sentence ones: "After I sand it, I'll
# paint" and "I'll paint after I sand it" both make painting wait.
_ORDERS: tuple[tuple[re.Pattern[str], str, int, int], ...] = (
    (re.compile(r"^\W*(?:after|once)\b(.+?),(.+)$", re.IGNORECASE | re.S), "after", 1, 2),
    (re.compile(r"^\W*before\b(.+?),(.+)$", re.IGNORECASE | re.S), "before", 2, 1),
    (re.compile(r"\bfirst\b(.+?)\bthen\b(.+)$", re.IGNORECASE | re.S), "then", 1, 2),
    (re.compile(r"^(.+?)\b(?:after|once)\b(.+)$", re.IGNORECASE | re.S), "after", 2, 1),
    (re.compile(r"^(.+?)\bbefore\b(.+)$", re.IGNORECASE | re.S), "before", 1, 2),
)
# "once again", "after all": the words, not an order.
_IDIOM = re.compile(r"\b(?:once (?:again|more)|after all|before long)\b", re.IGNORECASE)


def _best(clause: str, actions: Sequence[KnowledgeRecord]) -> KnowledgeRecord | None:
    # The one action sharing the most content words with the clause; a tie
    # names no action, because guessing would invent a dependency.
    words = content_words(clause)
    scored = sorted(
        ((len(words & content_words(a.assertion)), a.record_id, a) for a in actions),
        key=lambda s: (-s[0], s[1]),
    )
    if not scored or scored[0][0] == 0:
        return None
    if len(scored) > 1 and scored[1][0] == scored[0][0]:
        return None
    return scored[0][2]


def propose_dependencies(
    actions: Sequence[KnowledgeRecord], messages: Sequence[ExtractionMessage]
) -> list[DependencyProposal]:
    """Dependencies between one chat's actions, from its user sentences.

    Args:
        actions: The chat's action records.
        messages: The chat's messages; only the user's are read.

    Returns:
        One proposal per sentence that names two different actions in order.
    """
    found: dict[tuple[str, str], DependencyProposal] = {}
    for message in messages:
        if message.role is not Role.USER:
            continue
        for span in sentences(message.text):
            said = span.of(message.text)
            if _IDIOM.search(said):
                continue
            # An action recorded from this very sentence names both sides
            # and would match either clause; it is not one of the two.
            others = [a for a in actions if not _cites(a, message.revision_id, span)]
            for pattern, cue, first_group, later_group in _ORDERS:
                match = pattern.search(said)
                if match is None:
                    continue
                first = _best(match.group(first_group), others)
                later = _best(match.group(later_group), others)
                if first is not None and later is not None and first is not later:
                    key = (later.record_id, first.record_id)
                    found.setdefault(
                        key,
                        DependencyProposal(
                            later.record_id, first.record_id, quote(message, span), cue
                        ),
                    )
                break  # one reading per sentence
    return [found[key] for key in sorted(found)]


def _cites(record: KnowledgeRecord, revision_id: str, span: Span) -> bool:
    return any(
        e.revision_id == revision_id and e.start < span.end and span.start < e.end
        for e in record.evidence
    )
