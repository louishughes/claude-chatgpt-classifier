"""Open questions checked against the whole chat, not one part of it (NOTE-032).

A long chat is digested in parts, and each part lists the questions it
leaves open. An earlier part can't see a later one, so the merged digest
listed the same question twice and called offers "not answered" that the
user accepted in a later part (the NOTE-013 step 2 score: 23 listed, 7 real).
Two rules, run once on the merged digest, by code a person can read:

* **Same question twice:** two questions whose content words are the same,
  or overlap by at least ``SAME_OVERLAP``, become one. The kept question
  takes both questions' citations, so no evidence is lost.
* **Answered later:** a question whose latest citation is an **assistant**
  message ("Want me to draft the letter?") is answered when a later user
  message starts by accepting or declining ("Yes, go ahead", "No thanks")
  and is either the user's very next message or shares a word with the
  question. It moves to ``resolved_questions`` with that answer as
  evidence and is flagged, so it is never silently dropped.

A question the user asked stays: only the assistant can answer it, and
whether it did is the model's reading. An unanswered question always stays.

Talking points:
    - "Each part of a long chat only sees itself, so the questions are
      checked once more against the whole chat."
    - "An offer the user said yes to later isn't open, and the note keeps
      the 'yes' as proof."
"""

from __future__ import annotations

import re

from knowledge_engine.digest.contract import (
    ConversationDigest,
    DigestFlag,
    DigestItem,
    ResolvedQuestion,
)
from knowledge_engine.domain.enums import Role
from knowledge_engine.extraction.text import ExtractionMessage, quote
from knowledge_engine.graph.offsets import Span
from knowledge_engine.reconciliation.equivalence import content_words

QUESTIONS_VERSION = "note-032-v1"
SAME_OVERLAP = 0.75

# An acceptance or refusal, at the very start of the user's message.
_ANSWER = re.compile(
    r"^\W*(yes|yeah|yep|yup|sure|ok(?:ay)?|go ahead|please do|do it|"
    r"let'?s do (?:it|that)|sounds good|perfect|no thanks|no,? thank you|"
    r"not now|no need|let'?s not)\b",
    re.IGNORECASE,
)


def _same(a: frozenset[str], b: frozenset[str]) -> bool:
    if not a or not b:
        return a == b
    return len(a & b) / len(a | b) >= SAME_OVERLAP


def _merge_duplicates(items: tuple[DigestItem, ...]) -> tuple[tuple[DigestItem, ...], int]:
    kept: list[DigestItem] = []
    words: list[frozenset[str]] = []
    joined = 0
    for item in items:
        mine = content_words(item.text)
        home = next((n for n, w in enumerate(words) if _same(w, mine)), None)
        if home is None:
            kept.append(item)
            words.append(mine)
            continue
        earlier = kept[home]
        kept[home] = earlier.model_copy(
            update={
                "message_ids": tuple(dict.fromkeys((*earlier.message_ids, *item.message_ids))),
                "evidence": tuple(dict.fromkeys((*earlier.evidence, *item.evidence))),
            }
        )
        joined += 1
    return tuple(kept), joined


def _answer(
    item: DigestItem, messages: list[ExtractionMessage], order: dict[str, int]
) -> ExtractionMessage | None:
    cited = [order[i] for i in item.message_ids if i in order]
    if not cited:
        return None
    latest = max(cited)
    if messages[latest].role is not Role.ASSISTANT:
        return None
    asked = content_words(item.text)
    later_users = [m for m in messages[latest + 1 :] if m.role is Role.USER]
    for position, message in enumerate(later_users):
        if not _ANSWER.match(message.text):
            continue
        if position == 0 or asked & content_words(message.text):
            return message
    return None


def reconcile_questions(
    digest: ConversationDigest, messages: list[ExtractionMessage]
) -> ConversationDigest:
    """The open questions with duplicates joined and later-answered ones set aside.

    Args:
        digest: The merged, quote-checked digest.
        messages: The chat's active-path messages, in order.

    Returns:
        The digest with each question once, and answered ones in
        ``resolved_questions`` with a flag each; unchanged when nothing applies.
    """
    if not digest.open_questions:
        return digest
    questions, joined = _merge_duplicates(digest.open_questions)
    order = {m.native_id: n for n, m in enumerate(messages)}
    still: list[DigestItem] = []
    resolved: list[ResolvedQuestion] = []
    flags: list[DigestFlag] = []
    for item in questions:
        answer = _answer(item, messages, order)
        if answer is None:
            still.append(item)
            continue
        found = _ANSWER.match(answer.text)
        assert found is not None
        evidence = quote(answer, Span(found.start(1), found.end(1)))
        resolved.append(ResolvedQuestion(question=item, resolved_by=evidence))
        flags.append(
            DigestFlag(
                field="open_questions",
                index=len(still) + len(resolved) - 1,
                reason=f"answered later by the user in {answer.native_id} ({QUESTIONS_VERSION})",
            )
        )
    if not joined and not resolved:
        return digest
    if joined:
        flags.insert(
            0,
            DigestFlag(
                field="open_questions",
                index=0,
                reason=f"{joined} repeated question(s) joined ({QUESTIONS_VERSION})",
            ),
        )
    return digest.model_copy(
        update={
            "open_questions": tuple(still),
            "resolved_questions": (*digest.resolved_questions, *resolved),
            "flags": (*digest.flags, *flags),
        }
    )
