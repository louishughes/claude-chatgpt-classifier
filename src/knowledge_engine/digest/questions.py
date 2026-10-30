"""Open questions checked across the parts of a long chat (NOTE-032).

A long chat is digested in parts, and each part lists the questions it
leaves open. An earlier part can't see a later one, so the merged digest
listed the same question twice and called offers "not answered" that the
user accepted in a later part (the NOTE-013 step 2 score: 23 listed, 7 real).
This runs on the parts' answers **before** they are merged (so before the
merge's cap on questions), and only does what one part could not. Both
rules are deliberately strict: a question wrongly kept costs a line, a
question wrongly dropped hides something the user still has to do.

* **Same question from two parts:** two questions from *different* parts,
  cited from messages of the same role, become one only when their keys
  are **identical**. The key is every word but filler, so a negation
  ("can" / "can't"), a stance ("prefer" / "avoid"), an action ("draft" /
  "send") or a number (any script's digits) keeps them apart. Symbols that
  change the meaning are part of the key too, so "C++" / "C#", "$50" /
  "50%" and "1,500" / "1.500" stay apart (NOTE-038). A question with an
  empty key is never joined. The kept question takes the other copy's
  citations, but only those whose quote is really in the cited message:
  one bad quote would otherwise get the whole question dropped later by
  the quote check. At most ``MAX_QUOTES_PER_ITEM`` are kept, the latest.
* **Answered in a later part:** a question whose latest citation is an
  **assistant** offer ("Want me to draft the letter?") is set aside only
  when all of these hold:
  - the reply is the user's very next message after the offer;
  - that reply is after the **last** part that listed the question, so no
    part's model saw it and kept the question anyway;
  - the question really is one of the offers: a single offer sentence
    holds at least two of the question's words and misses at most one, so
    "yes" to "Shall I draft the letter?" doesn't close "Is the letter's
    deadline Friday?" (NOTE-039);
  - it starts with a clear yes or no: "yes", "yes please", "go ahead",
    "do it", "let's do that", "no thanks", "no need";
  - it doesn't say both: "Yes, no hotel" or "No thanks, book it" is mixed,
    so it answers nothing (NOTE-039);
  - it has no hedge ("but", "if", "after", "later", "unless", "when",
    "maybe", "actually", "wait", "as if", "yeah right") and no "?";
  - any other words in it are the question's own ("Yes, book the hotel"),
    so "Yes, the hotel is too expensive" is not an answer;
  - the offer's message held only that offer, or the reply shares at least
    two words with this question.

A one-part chat is left exactly as the model wrote it. A question the user
asked stays: only the assistant can answer it, and whether it did is the
model's reading. An unanswered question always stays.

Talking points:
    - "Each part of a long chat only sees itself, so the questions are
      checked once more across the parts, strictly."
    - "Only a plain 'yes' or 'no thanks' right after the offer closes it.
      'Yes, but...' or 'yeah right' never does."
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass

from knowledge_engine.digest.contract import (
    MAX_QUOTES_PER_ITEM,
    DigestAnswer,
    DigestItemAnswer,
    DigestQuote,
)
from knowledge_engine.domain.enums import Role
from knowledge_engine.extraction.text import ExtractionMessage
from knowledge_engine.graph.offsets import Span, find_quote
from knowledge_engine.reconciliation.equivalence import STOP_WORDS

QUESTIONS_VERSION = "note-039-v2"
# A reply naming one of several offers must share this many of its words.
NAMED_SHARED = 2
# An offer sentence "is" the question when it shares at least this many of
# the question's words and leaves out at most OFFER_MISSING of them.
OFFER_SHARED = 2
OFFER_MISSING = 1

_WORD = re.compile(r"[^\W_]+(?:['’][^\W_]+)?")
# For the join key: a word, or a symbol that changes what is asked. Only a
# short list of symbols counts ("+", "#", "$", "%", "<", ">", "/", "=", ...),
# plus a minus sign before a number ("-5"), and a "." or "," inside a number
# or name ("1,500", "1.500") or starting one (".NET"). Everything else, such
# as emoji, dashes, "**" bold markers and quote marks, is wording, not
# meaning, so it is left out and the same question still joins.
_KEY_TOKEN = re.compile(
    r"[^\W_]+(?:['’][^\W_]+)?"
    r"|[+#$%<>/=&@€£¥^~|]"
    r"|(?<!\w)-(?=\d)"
    r"|(?<=\w)[.,](?=\w)|(?<!\w)\.(?=\w)"
)
_ANSWER = re.compile(
    r"^\W*(yes please|yes|go ahead|do it|let'?s do (?:it|that)|no thanks|no,? thank you|no need)"
    r"(?![\w'])",
    re.IGNORECASE,
)
_HEDGE = re.compile(
    r"\?|\b(?:but|if|after|later|unless|when|maybe|actually|wait|yeah,? right)\b",
    re.IGNORECASE,
)
# A sentence that offers to do something ("Want me to draft it?").
_OFFER = re.compile(
    r"\b(?:want me to|would you like|do you want|shall i|should i|i can|i could|"
    r"let me know if)\b|\?\s*$",
    re.IGNORECASE,
)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_CHOICE = re.compile(r"\bor\b", re.IGNORECASE)
_ARTICLES = frozenset({"a", "an", "the"})
_CUE_WORDS = frozenset("yes please go ahead do it let's lets that no thanks thank you need".split())
# The digest's wording for who asks ("Should the assistant book it?", "Does
# the user want a summary?") and an offer's ("Do you want me to...", "Would
# you like..."). These say who, not what, so they don't count when matching.
_ROLE_WORDS = frozenset({"assistant", "user", "does", "do", "want", "like", "me", "you"})
# Saying no inside a yes ("Yes, no hotel") or yes inside a no makes a reply mixed.
_NO_WORD = re.compile(r"\b(?:no|not|never|nah|nope)\b|n['’]t\b", re.IGNORECASE)
_DECLINE = re.compile(r"^(?:no\b)", re.IGNORECASE)
_YES_WORD = re.compile(r"\b(?:yes|yeah|yep|sure|ok|okay|go ahead)\b", re.IGNORECASE)
# "book it" after a no is a request; "no need to book it" is not.
_DO_IT = re.compile(
    r"(?<!\bto )(?<!\bnot )(?<!n't )(?<!n’t )\b([^\W_]+)\s+(?:it|that|them)\b", re.IGNORECASE
)


def _token(word: str) -> str:
    word = word.lower().replace("’", "'")
    # isdecimal, not isdigit: ٨٠٨٠ and 8080 are the same number, but the
    # superscript in "10²" is not a plain 2, so "10²" and "102" stay apart.
    if word.isdecimal():
        return "".join(str(unicodedata.decimal(c)) for c in word)
    return word


def question_key(text: str) -> tuple[str, ...]:
    """A question's words in order, lowercased, digits in any script read as numbers.

    Only articles are left out: pronouns, modals, "this"/"that", "and"/"or"
    and word order all change what is asked. Symbols that change the
    meaning are kept (see ``_KEY_TOKEN``). Articles are dropped in any
    case ("The"), except a capital "A" after the first word, which is a
    grade or a name ("A+ or A-"), not an article.
    """
    tokens = _KEY_TOKEN.findall(text)
    return tuple(
        _token(t)
        for n, t in enumerate(tokens)
        if not (t.lower() in _ARTICLES and (t != "A" or n == 0))
    )


def _words(text: str) -> frozenset[str]:
    return frozenset(t for t in map(_token, _WORD.findall(text)) if t not in STOP_WORDS)


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


@dataclass
class _Kept:
    part: int  # the first part that listed it; it stays in that part's answer
    last: int  # the last part that listed it
    item: DigestItemAnswer
    key: tuple[str, ...]
    role: Role | None
    joined: int = 0


def _latest(item: DigestItemAnswer, order: dict[str, int]) -> int | None:
    cited = [order[q.message_id] for q in item.quotes if q.message_id in order]
    return max(cited) if cited else None


def _role(
    item: DigestItemAnswer, order: dict[str, int], messages: Sequence[ExtractionMessage]
) -> Role | None:
    """The assistant's question only when every citation is an assistant message."""
    roles = {messages[order[q.message_id]].role for q in item.quotes if q.message_id in order}
    if not roles:
        return None
    return Role.ASSISTANT if roles == {Role.ASSISTANT} else Role.USER


def _offers(window: Sequence[ExtractionMessage]) -> list[str]:
    """The offer sentences in the assistant messages a reply answers."""
    return [
        sentence
        for m in window
        for sentence in _SENTENCE_END.split(m.text.strip())
        if _OFFER.search(sentence)
    ]


def _reply_span(reply: str, asked: frozenset[str], *, several: bool) -> Span | None:
    """Where the reply plainly accepts or declines this question, or None."""
    found = _ANSWER.match(reply)
    if found is None or _HEDGE.search(reply):
        return None
    rest = reply[found.end(1) :]
    if _DECLINE.match(found.group(1)):
        # "No thanks, book it": a no that then says yes, or tells the
        # assistant to do the question's action ("book it", "No thanks,
        # book the hotel"), is mixed.
        # "No thanks to the sales chart" only names what it declines.
        words = [_token(w) for w in _WORD.findall(rest)]
        told = {_token(m) for m in _DO_IT.findall(rest)} | set(words[:1])
        if _YES_WORD.search(rest) or told & asked:
            return None
    elif _NO_WORD.search(rest):
        return None  # "Yes, no hotel": a yes that says no as well
    said = {_token(w) for w in _WORD.findall(reply)} - _CUE_WORDS - STOP_WORDS
    if not said <= asked:
        return None  # it talks about something else as well
    if several and len(said & asked) < NAMED_SHARED:
        return None
    return Span(found.start(1), found.end(1))


def _is_offer(asked: frozenset[str], offer: str) -> bool:
    """Whether one offer sentence is this question, not just near it.

    One shared word was too loose: "Shall I draft the letter to the
    council?" shares "letter" and "council" with "Is the council letter
    deadline Friday?", but the deadline was never offered. So the offer must
    hold the question's words with at most one missing.
    """
    wanted = asked - _ROLE_WORDS
    shared = wanted & _words(offer)
    return len(shared) >= min(OFFER_SHARED, len(wanted)) > 0 and (
        len(wanted - shared) <= OFFER_MISSING
    )


def _backed(quote: DigestQuote, by_id: dict[str, ExtractionMessage]) -> bool:
    """Whether a quote is really in the message it cites (the later check's rule)."""
    message = by_id.get(quote.message_id)
    return message is not None and bool(find_quote(message.text, quote.text))


def _joined_quotes(
    home: Sequence[DigestQuote],
    extra: Sequence[DigestQuote],
    order: dict[str, int],
    by_id: dict[str, ExtractionMessage],
) -> list[DigestQuote]:
    """Both copies' backed quotes, without repeats, at most the latest few, in chat order."""
    seen: dict[tuple[str, str], DigestQuote] = {}
    for q in (*home, *extra):
        if _backed(q, by_id):
            seen.setdefault((q.message_id, q.text), q)
    quotes = sorted(seen.values(), key=lambda q: order.get(q.message_id, -1))
    return quotes[-MAX_QUOTES_PER_ITEM:]


def _answers(
    kept: _Kept,
    latest: int,
    reply: ExtractionMessage,
    messages: Sequence[ExtractionMessage],
    order: dict[str, int],
    listed_at: Sequence[int | None],
) -> Span | None:
    """Where ``reply`` answers this offer, or None.

    The reply answers everything the assistant said since the user last
    spoke, so every offer in that stretch counts: with more than one, or an
    offer of a choice ("this or that?"), a bare yes or no answers none.
    """
    start = max((i for i in range(latest) if messages[i].role is Role.USER), default=-1) + 1
    end = order[reply.native_id]
    window = [m for m in messages[start:end] if m.role is Role.ASSISTANT]
    offers = _offers(window)
    asked = _words(kept.item.text)
    if not any(_is_offer(asked, o) for o in offers):
        return None  # the question isn't one of the offers made
    listed = sum(1 for i in listed_at if i is not None and start <= i < end)
    several = max(len(offers), listed) > 1 or any(_CHOICE.search(o) for o in offers)
    return _reply_span(reply.text, asked, several=several)


def _join(
    answers: Sequence[DigestAnswer],
    order: dict[str, int],
    messages: Sequence[ExtractionMessage],
) -> list[_Kept]:
    kept: list[_Kept] = []
    by_id = {m.native_id: m for m in messages}
    for p, answer in enumerate(answers):
        for item in answer.open_questions:
            role = _role(item, order, messages)
            key = question_key(item.text)
            home = next(
                (
                    k
                    for k in kept
                    if k.part != p and k.last != p and role is not None
                    and k.role == role and key and k.key == key
                ),
                None,
            )  # fmt: skip
            if home is not None and not any(_backed(q, by_id) for q in item.quotes):
                # A repeat with no good quote adds no citations (one bad quote
                # would get the whole question dropped later), but it still
                # shows this part listed the question: a reply this part saw
                # must not then count as answering it.
                home.last = p
                home.joined += 1
                continue
            if home is None:
                kept.append(_Kept(p, p, item, key, role))
                continue
            # Never empty: this copy has a backed quote (checked just above).
            quotes = _joined_quotes(home.item.quotes, item.quotes, order, by_id)
            home.item = home.item.model_copy(update={"quotes": quotes})
            home.last = p
            home.joined += 1
    return kept


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
        The answers with joined and answered questions taken out. One
        answer, or answers that don't match the parts, are returned as they are.
    """
    if len(answers) < 2 or len(parts) != len(answers):
        return Reconciled(list(answers), {}, [])
    order = {m.native_id: n for n, m in enumerate(messages)}
    if any(not part or any(i not in order for i in part) for part in parts):
        return Reconciled(list(answers), {}, [])  # parts of some other chat: leave it be
    kept = _join(answers, order, messages)
    ends = [max(order[i] for i in part) for part in parts]
    listed_at = [_latest(k.item, order) for k in kept]

    answered: list[Answered] = []
    still: list[_Kept] = []
    for k in kept:
        latest = _latest(k.item, order)
        if k.role is Role.ASSISTANT and latest is not None:
            reply = next((m for m in messages[latest + 1 :] if m.role is Role.USER), None)
            if reply is not None and order[reply.native_id] > ends[k.last]:
                span = _answers(k, latest, reply, messages, order, listed_at)
                if span is not None:
                    answered.append(Answered(k.part, k.item, reply, span))
                    continue
        still.append(k)
    out = [
        a.model_copy(update={"open_questions": [k.item for k in still if k.part == p]})
        for p, a in enumerate(answers)
    ]
    joined = {k.item.text: k.joined for k in still if k.joined}
    return Reconciled(out, joined, answered)
