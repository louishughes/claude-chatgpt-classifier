"""Open questions checked across the parts of a long chat (NOTE-032).

A long chat is digested in parts, and each part lists the questions it
leaves open. An earlier part can't see a later one, so the merged digest
listed the same question twice and called offers "not answered" that the
user accepted in a later part (the NOTE-013 step 2 score: 23 listed, 7 real).
This runs on the parts' answers **before** they are merged (so before the
merge's cap on questions), and only does what one part could not:

* **Same question from two parts:** two questions from *different* parts,
  cited from messages of the same role, with the same key words, become
  one that keeps both citations. The key keeps numbers and negations, so
  "port 8080" and "port 9090", or "keep" and "not keep", stay apart. A
  question with no key words is never joined.
* **Answered in a later part:** a question whose latest citation is an
  assistant offer ("Want me to draft the letter?") is set aside when a user
  message *after the question's part* accepts or declines it. The reply
  must start with a clear yes or no ("Yes, go ahead", "No thanks"; a bare
  "ok", "perfect", "sure" or "thanks" is not one), must not hedge ("but")
  or ask back ("?"), and must be about this offer: any words it adds beyond
  the yes or no must include one of the question's. It must be the user's
  next message after the offer, sharing a word with the question when that
  message held more than one offer, or else share at least two of the
  question's words.

A one-part chat is left exactly as the model wrote it. A question the user
asked stays: only the assistant can answer it, and whether it did is the
model's reading. An unanswered question always stays.

Talking points:
    - "Each part of a long chat only sees itself, so the questions are
      checked once more across the parts."
    - "An offer the user said yes to later isn't open, and the note keeps
      the 'yes' as proof. A 'yes, but...' doesn't count."
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from knowledge_engine.digest.contract import DigestAnswer, DigestItemAnswer
from knowledge_engine.domain.enums import Role
from knowledge_engine.extraction.text import ExtractionMessage
from knowledge_engine.graph.offsets import Span
from knowledge_engine.reconciliation.equivalence import content_words

QUESTIONS_VERSION = "note-032-v2"
SAME_OVERLAP = 0.75
# A reply that doesn't follow the offer directly must share this many words.
LATER_SHARED = 2

_WORD = re.compile(r"[a-z0-9']+")
_KEPT = frozenset("no not never without don't dont won't wont isn't isnt".split())
# Polite openers that are not a yes on their own: "OK so...", "Perfect, thanks!".
_OPENER = re.compile(r"^\W*(?:(?:ok(?:ay)?|sure|perfect|great|thanks|thank you)\b\W*)*", re.I)
_ANSWER = re.compile(
    r"(yes|yeah|yep|yup|go ahead|please do|do it|let'?s do (?:it|that)|sounds good|"
    r"no thanks|no,? thank you|not now|no need|let'?s not)\b",
    re.IGNORECASE,
)
_HEDGE = re.compile(r"\bbut\b|\?", re.IGNORECASE)
_CUE_WORDS = frozenset(
    "yes yeah yep yup go ahead please do it let's lets sounds good thanks thank now need "
    "ok okay sure perfect great".split()
)


def question_key(text: str) -> frozenset[str]:
    """The words two questions must share to be the same question, numbers and negations kept."""
    tokens = _WORD.findall(text.lower().replace("’", "'"))
    return content_words(text) | {t for t in tokens if t.isdigit() or t in _KEPT}


def _marks(key: frozenset[str]) -> frozenset[str]:
    return frozenset(w for w in key if w.isdigit() or w in _KEPT)


def _same(a: frozenset[str], b: frozenset[str]) -> bool:
    # Numbers and negations must match exactly: they change what is asked.
    if not a or not b or _marks(a) != _marks(b):
        return False
    return len(a & b) / len(a | b) >= SAME_OVERLAP


@dataclass(frozen=True)
class Answered:
    """A question set aside, and the user reply that answered it."""

    part: int
    question: DigestItemAnswer
    reply: ExtractionMessage
    span: Span


@dataclass(frozen=True)
class Reconciled:
    """The parts' answers after reconciling, and what changed."""

    answers: list[DigestAnswer]
    joined: dict[str, int]  # kept question's text -> questions joined into it
    answered: list[Answered]


def _latest(item: DigestItemAnswer, order: dict[str, int]) -> int | None:
    cited = [order[q.message_id] for q in item.quotes if q.message_id in order]
    return max(cited) if cited else None


def _reply_span(
    reply: ExtractionMessage, asked: frozenset[str], *, adjacent: bool, several: bool
) -> Span | None:
    """Where the reply accepts or declines this question, or None if it doesn't."""
    if _HEDGE.search(reply.text):
        return None
    start = _OPENER.match(reply.text)
    found = _ANSWER.match(reply.text, start.end() if start else 0)
    if found is None:
        return None
    extra = content_words(reply.text) - _CUE_WORDS
    shared = len(extra & asked)
    if extra and not shared:
        return None  # "No thanks to the chart" is about the chart, not this offer
    if adjacent:
        if several and not shared:
            return None
    elif shared < LATER_SHARED:
        return None
    return Span(found.start(1), found.end(1))


def reconcile_parts(
    answers: Sequence[DigestAnswer],
    parts: Sequence[tuple[str, ...]],
    messages: Sequence[ExtractionMessage],
) -> Reconciled:
    """The parts' open questions joined and answered across parts.

    Args:
        answers: One answer per part, in chat order.
        parts: The message IDs each part was shown, in the same order.
        messages: The chat's active-path messages, in order.

    Returns:
        The answers with joined and answered questions taken out; one
        answer (or answers without matching parts) are returned as they are.
    """
    if len(answers) < 2 or len(parts) != len(answers):
        return Reconciled(list(answers), {}, [])
    order = {m.native_id: n for n, m in enumerate(messages)}

    # Join: (part, question) pairs kept so far, with each one's key and role.
    kept: list[tuple[int, DigestItemAnswer, frozenset[str], Role | None]] = []
    joined: dict[int, int] = {}
    for p, answer in enumerate(answers):
        for item in answer.open_questions:
            latest = _latest(item, order)
            role = messages[latest].role if latest is not None else None
            key = question_key(item.text)
            home = next(
                (
                    n
                    for n, (kp, _, kk, kr) in enumerate(kept)
                    if kp != p and kr == role and role is not None and _same(kk, key)
                ),
                None,
            )
            if home is None:
                kept.append((p, item, key, role))
                continue
            hp, hitem, hkey, hrole = kept[home]
            quotes = list(
                {(q.message_id, q.text): q for q in (*hitem.quotes, *item.quotes)}.values()
            )
            kept[home] = (hp, hitem.model_copy(update={"quotes": quotes}), hkey, hrole)
            joined[home] = joined.get(home, 0) + 1

    # Answer: offers the user replied to after the question's part ended.
    ends = [max((order[i] for i in part if i in order), default=-1) for part in parts]
    offers_in: dict[int, int] = {}
    for _, item, _, _ in kept:
        latest = _latest(item, order)
        if latest is not None:
            offers_in[latest] = offers_in.get(latest, 0) + 1
    answered: list[Answered] = []
    still: list[tuple[int, DigestItemAnswer]] = []
    joined_text: dict[str, int] = {}
    for n, (p, item, _, role) in enumerate(kept):
        reply = None
        latest = _latest(item, order)
        if role is Role.ASSISTANT and latest is not None:
            offer = messages[latest]
            several = offers_in[latest] > 1 or offer.text.count("?") > 1
            asked = content_words(item.text)
            users = [i for i in range(latest + 1, len(messages)) if messages[i].role is Role.USER]
            for k, i in enumerate(users):
                if i <= ends[p]:
                    continue  # the part's own model saw this reply
                span = _reply_span(messages[i], asked, adjacent=k == 0, several=several)
                if span is not None:
                    reply = Answered(p, item, messages[i], span)
                    break
        if reply is not None:
            answered.append(reply)
            continue
        still.append((p, item))
        if n in joined:
            joined_text[item.text] = joined[n]
    out = [
        a.model_copy(update={"open_questions": [it for q, it in still if q == p]})
        for p, a in enumerate(answers)
    ]
    return Reconciled(out, joined_text, answered)
