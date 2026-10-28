"""Per-chat keyword and topic candidates, without a model (NOTE-007).

A note needs a short list of the words a chat is really about, and the
reasons for each. This module works it out from the text alone, the same
way every time, in three tiers (the old v1 pre-pass, kept because it
worked):

* **must**: words in the chat's title, named things (capitalised phrases
  such as "Unreal Engine"), and approved taxonomy terms found in the text;
* **should**: the 20 phrases (one to three words) that score highest by
  TF-IDF: said often in this chat, rare in the others;
* **optional**: the next ones, up to 50 in all.

Each candidate keeps its reasons and the messages it appears in. Four
things keep the list honest:

1. **Corpus calibration.** A phrase found in most chats (over 65% once
   there are at least 5) is left out as "not specific to this chat", and
   every score is weighted by how rare the phrase is across the corpus.
2. **Spelling.** A word one typing slip away from a word used at least
   three times as often (``engnie`` beside ``engine``) is read as that
   word, and the spelling seen is kept under ``variants``. With a
   published taxonomy, an approved alias ("UE5") is shown as its term.
3. **Pasted setup text.** Words found only in a pasted setup prompt ("You
   are a pirate captain...", see ``is_preamble``) describe the role-play,
   not the subject. They are listed under ``excluded`` with that reason.
4. **Exclusions with a reason.** A title word too general to describe a
   chat ("help", "question") is excluded and says why, rather than
   silently dropped.

Topics (from the digest) are matched to approved topic terms. A topic that
matches nothing is a *candidate*: ``propose_topics`` files it as a TAX-004
proposal for a reviewer. It never becomes a label on its own.

Talking points:
    - "Same chats in, same keywords out: there's no model in this step."
    - "Every keyword says why it's there; every left-out word says why not."
    - "A new topic is a suggestion to the reviewer, never a tag."
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy.orm import Session

from knowledge_engine.extraction.model_knowledge import is_preamble
from knowledge_engine.extraction.text import ExtractionMessage
from knowledge_engine.taxonomy.aliases import AliasResolver, MatchStatus
from knowledge_engine.taxonomy.discovery import STOP_WORDS
from knowledge_engine.taxonomy.registry import Dimension, normalise_alias
from knowledge_engine.taxonomy.review import OPEN, Operation, proposals, propose

KEYWORDS_VERSION = "note-007-v1"
SHOULD_COUNT = 20
MAX_KEYWORDS = 50
# A phrase in more than this share of chats is not specific to any one,
# judged only once the corpus has enough chats for a share to mean much.
COMMON_SHARE = 0.65
COMMON_MIN_CHATS = 5
# A spelling is read as another word only when that word is used at least
# this many times as often, and at least this many times in all.
SPELLING_RATIO = 3
SPELLING_MIN_COUNT = 3
SPELLING_MIN_LENGTH = 5
MAX_MESSAGE_IDS = 5
MAX_EXCLUDED = 10

# Chat filler: words that are common in conversation but never a subject.
FILLER = frozenset(
    """
    actually maybe thing things stuff really basically probably kind sort lot
    lots okay yeah yes sure great good nice right well even still already
    something anything everything nothing someone anyone way ways bit able
    let lets know think going look looks looking help idea ideas example
    examples here's there's it's that's i'm i've you're don't can't won't
    one two first next new also may might every each many few
    """.split()
)
# Title words that say nothing about what a chat is about.
GENERIC_TITLE_WORDS = frozenset(
    """
    help question questions request advice info information chat conversation
    untitled quick query issue problem discussion new
    """.split()
)
_IGNORED = STOP_WORDS | FILLER
_SETUP_REASON = "only in pasted setup text (role-play wording, not a subject)"
# Phrases never cross a sentence or a clause mark.
_CLAUSE = re.compile(r"[^.!?;:,()\[\]{}\n\"]+")
_WORD = re.compile(r"[^\W\d_][\w'-]*[^\W_]|[^\W\d_]")
# A run of capitalised words, e.g. "Unreal Engine" or "Blender".
_CAPITALISED = re.compile(r"\b[A-Z][\w-]*(?:\s+[A-Z][\w-]*)*")


class Tier(StrEnum):
    """How strongly a keyword is suggested."""

    MUST = "must"
    SHOULD = "should"
    OPTIONAL = "optional"


@dataclass(frozen=True)
class ChatInput:
    """What the keyword step reads for one chat.

    Attributes:
        conversation_id: The ``conv_`` ID.
        title: The chat's title ("" if none).
        messages: The active path's messages, in order.
        topics: Topic phrases from the digest (NOTE-002), if any.
    """

    conversation_id: str
    title: str
    messages: tuple[ExtractionMessage, ...]
    topics: tuple[str, ...] = ()


@dataclass(frozen=True)
class KeywordCandidate:
    """One suggested keyword.

    Attributes:
        term: How to show it (the canonical spelling).
        tier: must, should or optional.
        reasons: Why it is suggested, in plain words.
        message_ids: Native IDs of the first messages it appears in.
        score: TF-IDF in this chat (0 for a title-only word).
        specificity: How rare it is across chats (higher is rarer).
        variants: Other spellings in the chat that were read as this term.
        term_id: The approved taxonomy term, when it names one.
    """

    term: str
    tier: Tier
    reasons: tuple[str, ...]
    message_ids: tuple[str, ...]
    score: float
    specificity: float
    variants: tuple[str, ...] = ()
    term_id: str | None = None


@dataclass(frozen=True)
class Excluded:
    """A word or phrase deliberately left out, and why."""

    term: str
    reason: str


@dataclass(frozen=True)
class TopicCandidate:
    """A digest topic and whether it names an approved topic term."""

    text: str
    status: MatchStatus
    term_id: str | None = None


@dataclass(frozen=True)
class ChatKeywords:
    """The keyword and topic candidates for one chat."""

    conversation_id: str
    keywords: tuple[KeywordCandidate, ...]
    excluded: tuple[Excluded, ...]
    topics: tuple[TopicCandidate, ...]
    version: str = KEYWORDS_VERSION

    def tier(self, tier: Tier) -> list[KeywordCandidate]:
        """The keywords in one tier, best first."""
        return [k for k in self.keywords if k.tier is tier]


class _Phrase:
    """Running totals for one phrase in one chat (slots: there are many)."""

    __slots__ = ("count", "messages", "spellings")

    def __init__(self) -> None:
        self.count = 0
        self.messages: list[str] = []
        self.spellings: dict[str, int] = {}

    def seen(self, message_id: str, spelling: str) -> None:
        self.count += 1
        self.spellings[spelling] = self.spellings.get(spelling, 0) + 1
        if not self.messages or self.messages[-1] != message_id:
            if message_id not in self.messages:
                self.messages.append(message_id)


def keyword_candidates(
    chats: Sequence[ChatInput], *, resolver: AliasResolver | None = None
) -> dict[str, ChatKeywords]:
    """Work out keyword and topic candidates for every chat in a corpus.

    Args:
        chats: The whole corpus (or the batch being noted). Rarity is
            judged across exactly these chats.
        resolver: A published taxonomy's aliases; without one every topic
            is ``unmatched`` and no keyword carries a ``term_id``.

    Returns:
        ``ChatKeywords`` by conversation ID.
    """
    spelling = _spelling_fixes(chats)
    found = {chat.conversation_id: _phrases(chat, spelling) for chat in chats}
    spread: Counter[str] = Counter()
    for content, _setup, title in found.values():
        spread.update(set(content) | set(title))
    total = len(chats)
    results = {}
    for chat in chats:
        content, setup, title = found[chat.conversation_id]
        results[chat.conversation_id] = _rank(
            chat, content, setup, title, spread, total, spelling, resolver
        )
    return results


def _rank(
    chat: ChatInput,
    content: Mapping[str, _Phrase],
    setup: Mapping[str, _Phrase],
    title: Mapping[str, str],
    spread: Counter[str],
    total: int,
    spelling: Mapping[str, str],
    resolver: AliasResolver | None,
) -> ChatKeywords:
    def specificity(phrase: str) -> float:
        # Smoothed IDF, so a corpus of one chat still gives positive scores.
        return math.log((total + 1) / (spread[phrase] + 1)) + 1

    def common(phrase: str) -> bool:
        return total >= COMMON_MIN_CHATS and spread[phrase] / total > COMMON_SHARE

    excluded: dict[str, Excluded] = {}
    kept: dict[str, KeywordCandidate] = {}

    def exclude(phrase: str, reason: str) -> None:
        excluded.setdefault(phrase, Excluded(phrase, reason))

    def keep(phrase: str, tier: Tier, reason: str, *, display: str | None = None) -> None:
        if common(phrase):
            exclude(phrase, f"used in {spread[phrase]} of {total} chats, not specific to this one")
            return
        seen = content.get(phrase)
        variants = _variants(seen, phrase) if seen else ()
        term_id, shown = None, display or _display(seen, phrase)
        if resolver is not None:
            match = resolver.resolve(phrase, scope=Dimension.TOPIC)
            if match.status is MatchStatus.MATCHED:
                term_id, shown = match.target_id, match.candidates[0].label
        if phrase in kept:
            old = kept[phrase]
            kept[phrase] = KeywordCandidate(
                old.term,
                old.tier,
                (*old.reasons, reason),
                old.message_ids,
                old.score,
                old.specificity,
                old.variants,
                old.term_id,
            )
            return
        kept[phrase] = KeywordCandidate(
            term=shown,
            tier=tier,
            reasons=(reason,),
            message_ids=tuple(seen.messages[:MAX_MESSAGE_IDS]) if seen else (),
            score=round(seen.count * specificity(phrase), 4) if seen else 0.0,
            specificity=round(specificity(phrase), 4),
            variants=variants,
            term_id=term_id,
        )

    # Must: the title's words, then named things, then approved terms.
    for phrase, shown in title.items():
        if phrase in GENERIC_TITLE_WORDS:
            exclude(phrase, "a title word too general to describe the chat")
        else:
            keep(phrase, Tier.MUST, "in the title", display=shown)
    for phrase, seen in _named(chat, content, spelling).items():
        keep(phrase, Tier.MUST, f"a named thing, mentioned {seen} time(s)")
    if resolver is not None:
        for message in chat.messages:
            if is_preamble(message):
                continue
            for mention in resolver.find(message.text, scope=Dimension.TOPIC):
                if mention.resolution.status is MatchStatus.MATCHED:
                    phrase = mention.norm_form
                    keep(phrase, Tier.MUST, "an approved topic term")

    # Should / optional: repeated phrases by TF-IDF, longest kept where a
    # shorter one only ever appears inside it.
    ranked = sorted(
        (
            (seen.count * specificity(phrase), phrase)
            for phrase, seen in content.items()
            if seen.count >= 2 and phrase not in kept
        ),
        key=lambda pair: (-pair[0], pair[1]),
    )
    covered = _covered(content)
    room = MAX_KEYWORDS - len(kept)
    should = 0
    for _, phrase in ranked:
        if room <= 0:
            break
        if content[phrase].count in covered.get(phrase, ()):
            continue  # only ever said as part of a longer phrase
        if common(phrase):
            exclude(phrase, f"used in {spread[phrase]} of {total} chats, not specific to this one")
            continue
        tier = Tier.SHOULD if should < SHOULD_COUNT else Tier.OPTIONAL
        should += tier is Tier.SHOULD
        reason = f"said {content[phrase].count} times; in {spread[phrase]} of {total} chat(s)"
        keep(phrase, tier, reason)
        room -= 1

    # Words that only the pasted setup prompt uses.
    for phrase, said in sorted(setup.items(), key=lambda pair: (-pair[1].count, pair[0])):
        if phrase in content or phrase in kept or phrase in title:
            continue
        if said.count >= 2 or " " in phrase:
            exclude(phrase, _SETUP_REASON)

    order = {Tier.MUST: 0, Tier.SHOULD: 1, Tier.OPTIONAL: 2}
    keywords = sorted(kept.values(), key=lambda k: (order[k.tier], -k.score, k.term.casefold()))
    # Setup-text exclusions stay in order of how often they were said.
    setup_gone = [e for e in excluded.values() if e.reason == _SETUP_REASON][:MAX_EXCLUDED]
    other_gone = sorted(
        (e for e in excluded.values() if e.reason != _SETUP_REASON), key=lambda e: e.term
    )
    return ChatKeywords(
        conversation_id=chat.conversation_id,
        keywords=tuple(keywords),
        excluded=tuple(other_gone + setup_gone),
        topics=tuple(_topics(chat.topics, resolver)),
    )


def _covered(content: Mapping[str, _Phrase]) -> dict[str, set[int]]:
    """For each phrase, the counts of the longer repeated phrases containing it."""
    covered: dict[str, set[int]] = defaultdict(set)
    for phrase, seen in content.items():
        words = phrase.split()
        if seen.count < 2 or len(words) < 2:
            continue
        for size in range(1, len(words)):
            for start in range(len(words) - size + 1):
                covered[" ".join(words[start : start + size])].add(seen.count)
    return covered


def _topics(texts: Iterable[str], resolver: AliasResolver | None) -> list[TopicCandidate]:
    found: dict[str, TopicCandidate] = {}
    for text in texts:
        norm = normalise_alias(text)
        if not norm or norm in found:
            continue
        if resolver is None:
            found[norm] = TopicCandidate(text, MatchStatus.UNMATCHED)
            continue
        match = resolver.resolve(text, scope=Dimension.TOPIC)
        found[norm] = TopicCandidate(text, match.status, match.target_id)
    return list(found.values())


def propose_topics(
    session: Session, results: Iterable[ChatKeywords], *, proposer: str
) -> list[str]:
    """File every unmatched topic as a TAX-004 ``add`` proposal, once.

    A topic already waiting as an open proposal (same label, any spelling
    of it) is not filed again. Nothing becomes a term until a reviewer
    approves it; the caller commits.

    Returns:
        The new proposal IDs.
    """
    waiting = {
        normalise_alias(str(json.loads(row.payload_json).get("label", "")))
        for row in proposals(session, OPEN)
        if row.operation == Operation.ADD.value
    }
    chats: dict[str, list[str]] = defaultdict(list)
    labels: dict[str, str] = {}
    for result in results:
        for topic in result.topics:
            norm = normalise_alias(topic.text)
            if topic.status is MatchStatus.UNMATCHED and norm and norm not in waiting:
                labels.setdefault(norm, topic.text)
                chats[norm].append(result.conversation_id)
    created = []
    for norm in sorted(labels):
        row = propose(
            session,
            Operation.ADD,
            {"label": labels[norm], "dimension": Dimension.TOPIC.value},
            proposer=proposer,
            evidence={"conversation_ids": sorted(set(chats[norm])), "source": KEYWORDS_VERSION},
        )
        created.append(row.proposal_id)
    return created


# ---- reading the text ----


def _words(text: str) -> list[list[str]]:
    """The text's clauses, each as a list of words in their original case."""
    return [_WORD.findall(clause) for clause in _CLAUSE.findall(text)]


def _usable(word: str) -> bool:
    return len(word) >= 3 and word not in _IGNORED


def _ngrams(fixed: Sequence[str], written: Sequence[str]) -> Iterable[tuple[str, str]]:
    """(comparison form, as written) for each 1-3 word phrase worth counting.

    ``fixed`` is the clause with spellings corrected, ``written`` as typed.
    A phrase may contain a filler word in the middle ("game of life") but
    never start or end with one.
    """
    folded = [w.casefold() for w in fixed]
    usable = [_usable(w) for w in folded]
    for i, ok in enumerate(usable):
        if not ok:
            continue
        for size in (1, 2, 3):
            end = i + size
            if end > len(folded):
                break
            if usable[end - 1]:
                yield " ".join(folded[i:end]), " ".join(written[i:end])


def _phrases(
    chat: ChatInput, spelling: Mapping[str, str]
) -> tuple[dict[str, _Phrase], dict[str, _Phrase], dict[str, str]]:
    """Phrase counts in the chat's own messages, in pasted setup text, and the title."""
    content: dict[str, _Phrase] = defaultdict(_Phrase)
    setup: dict[str, _Phrase] = defaultdict(_Phrase)
    for message in chat.messages:
        into = setup if is_preamble(message) else content
        for clause in _words(message.text):
            fixed = [spelling.get(w.casefold(), w) for w in clause]
            for phrase, written in _ngrams(fixed, clause):
                into[phrase].seen(message.native_id, written)
    title: dict[str, str] = {}
    for clause in _words(chat.title):
        for word in clause:
            folded = spelling.get(word.casefold(), word.casefold())
            if len(folded) >= 3 and folded not in STOP_WORDS:
                title.setdefault(folded, word if word.casefold() == folded else folded)
    return dict(content), dict(setup), title


def _named(
    chat: ChatInput, content: Mapping[str, _Phrase], spelling: Mapping[str, str]
) -> dict[str, int]:
    """Capitalised phrases not at the start of a sentence: named things.

    One-word names must appear twice (a capitalised word in a heading is
    common); two words or more once is enough.
    """
    counts: Counter[str] = Counter()
    for message in chat.messages:
        if is_preamble(message):
            continue
        for clause in _CLAUSE.findall(message.text):
            for match in _CAPITALISED.finditer(clause):
                words = [spelling.get(w.casefold(), w.casefold()) for w in match.group().split()]
                if not clause[: match.start()].strip():
                    words = words[1:]  # the first word is capitalised anyway
                while words and not _usable(words[0]):
                    words.pop(0)
                while words and not _usable(words[-1]):
                    words.pop()
                if words and len(words) <= 3:
                    counts[" ".join(words)] += 1
    return {
        phrase: count
        for phrase, count in counts.items()
        if phrase in content and (count >= 2 or " " in phrase)
    }


def _display(seen: _Phrase | None, phrase: str) -> str:
    """The phrase as most often written with the canonical spelling."""
    if seen is None:
        return phrase
    canonical = [s for s in seen.spellings if s.casefold() == phrase]
    if not canonical:
        return phrase
    return min(canonical, key=lambda s: (-seen.spellings[s], s))


def _variants(seen: _Phrase, phrase: str) -> tuple[str, ...]:
    """Spellings of this phrase in the chat that were corrected to it."""
    return tuple(sorted({s for s in seen.spellings if s.casefold() != phrase}))


# ---- spelling ----


def _spelling_fixes(chats: Sequence[ChatInput]) -> dict[str, str]:
    """Map a rare spelling to a common word one typing slip away.

    Only words of 5+ letters, never filler, and only when the common word
    is used at least ``SPELLING_RATIO`` times as often (and at least
    ``SPELLING_MIN_COUNT`` times) across the corpus.
    """
    counts: Counter[str] = Counter()
    for chat in chats:
        for message in chat.messages:
            for clause in _words(message.text):
                counts.update(w.casefold() for w in clause)
        for clause in _words(chat.title):
            counts.update(w.casefold() for w in clause)
    words = [w for w in counts if len(w) >= SPELLING_MIN_LENGTH - 1 and w not in _IGNORED]
    # Index each common word under itself and every one-letter deletion of
    # it; a word one slip away shares at least one key (symmetric delete),
    # so only those few pairs are compared.
    keys: dict[str, set[str]] = defaultdict(set)
    for word in words:
        if counts[word] >= SPELLING_MIN_COUNT and len(word) >= SPELLING_MIN_LENGTH:
            for key in _deletions(word):
                keys[key].add(word)
    fixes = {}
    for word in sorted(words):
        if len(word) < SPELLING_MIN_LENGTH:
            continue
        near = set().union(*(keys.get(key, set()) for key in _deletions(word)))
        best = None
        for other in near:
            if (
                counts[other] >= SPELLING_RATIO * counts[word]
                and _one_slip(word, other)
                and (best is None or (-counts[other], other) < (-counts[best], best))
            ):
                best = other
        if best is not None:
            fixes[word] = best
    return fixes


def _deletions(word: str) -> set[str]:
    return {word} | {word[:i] + word[i + 1 :] for i in range(len(word))}


def _one_slip(a: str, b: str) -> bool:
    """True if one letter added, dropped, changed or swapped with its neighbour."""
    if a == b or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        diff = [i for i in range(len(a)) if a[i] != b[i]]
        if len(diff) == 1:
            return True
        return (
            len(diff) == 2
            and diff[1] == diff[0] + 1
            and a[diff[0]] == b[diff[1]]
            and a[diff[1]] == b[diff[0]]
        )
    short, long_ = (a, b) if len(a) < len(b) else (b, a)
    for i in range(len(long_)):
        if long_[:i] + long_[i + 1 :] == short:
            return True
    return False
