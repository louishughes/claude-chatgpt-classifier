"""Requests you keep making: the same ask, reworded, in different chats (RCL-002).

``recall history repeats`` looks only at **your own** messages (never the
assistant's) and groups the ones that ask much the same thing in two or
more different chats. It is local code with no model: nothing leaves the
machine and the same history always gives the same groups.

**How two requests are compared.** Each message is reduced to its
*content words*: lower-cased, stemmed ("structuring" -> "structur"), with
filler like "the", "how", "please" removed. Two requests match when the
words they share carry most of the weight of all their words, where a word
weighs more the rarer it is across your messages (IDF weighting: "save"
counts for more than "game" if "game" is in half your chats). This is a
weighted Jaccard score from 0 (nothing shared) to 1 (same words).

Why not the meaning embedder that ``recall history find --meaning`` uses?
On the test fixture it scored "write a cover letter for a junior Python
developer role" as closer to "rewrite my CV summary for a junior Python
developer role" than some true rewordings were to each other: it counts
every shared word, so long shared phrases swamp the one word that changes
the ask. Weighting by rarity lets "cover letter" versus "CV summary"
decide it.

**How groups form.** Pairs are joined strongest first, and two groups only
merge when *every* pair of members from different chats still matches
(complete linkage). That stops a chain A~B, B~C from pulling in a C that
has little to do with A.

**What never counts.**

* Messages with fewer than ``MIN_CONTENT_WORDS`` content words ("continue",
  "thanks"): they repeat everywhere and say nothing.
* Two messages in the *same* chat: an edited request or a regenerated
  branch is a revision, not a repeat. A group needs ``min_chats`` chats.
* A re-exported chat: it is the same logical chat (IMP-002), so its
  messages are stored once and can't match themselves.

**Known limits.** Synonyms are invisible ("GDD" and "design document"
share nothing), and a request that shares only very common words with its
repeat isn't compared (see ``BLOCKING_MAX_SHARE``). The threshold was set
on synthetic fixtures; how well it holds on real chats is measured against
an independently made answer key, not judged here.

Talking points:
    - "It finds what I keep asking across chats, with no AI: rare shared
      words count for more than common ones, so 'cover letter' and 'CV
      summary' aren't mistaken for the same request."
    - "Every member of a group has to match every other member from another
      chat, so one loose link can't drag in an unrelated message."
"""

from __future__ import annotations

import math
import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.reconciliation.equivalence import STOP_WORDS
from knowledge_engine.retrieval.embeddings import stem
from knowledge_engine.retrieval.filters import SearchFilters
from knowledge_engine.retrieval.lexical import passages

# Written into every report, so a later change to the rules is visible.
REPEATS_VERSION = "rcl-002-v1"
# Two requests from different chats match at or above this weighted
# Jaccard score. On the repeat_requests fixture, true rewordings score
# 0.48 and above, and the closest look-alike scores 0.36.
MATCH_THRESHOLD = 0.42
# Fewer content words than this and a message is too short to compare.
MIN_CONTENT_WORDS = 3
# Words that appear in more than this share of messages aren't used to
# *find* candidate pairs (they would pair almost everything with
# everything and make the run quadratic). They still count in the score.
BLOCKING_MAX_SHARE = 0.05
# ...but in a small history every word is "common", so always allow this many.
BLOCKING_MIN_COUNT = 50

# Words that frame a request rather than say what it is about. Added to
# the shared STOP_WORDS (NOTE-032), which are about statements.
REQUEST_WORDS = frozenset(
    "how what what's whats why when where which who whom do does did doing done me my mine "
    "myself please pls hi hey hello ok okay thanks thank cheers help good best way give get "
    "make need want something anything any some all".split()
)
_WORD = re.compile(r"[^\W_]+(?:'[^\W_]+)?", re.UNICODE)


@dataclass(frozen=True)
class Request:
    """One of your messages, ready to compare.

    Attributes:
        revision_id: The exact stored version of the message.
        conversation_id: Its chat (``conv_`` ID).
        native_node_id: The message's ID in the export.
        title: The chat's title, for display (private; may be None).
        created: When it was sent, epoch seconds, if known.
        text: The message text.
    """

    revision_id: str
    conversation_id: str
    native_node_id: str
    title: str | None
    created: float | None
    text: str


@dataclass(frozen=True)
class RepeatGroup:
    """Requests that ask much the same thing, from two or more chats.

    Attributes:
        members: The requests, oldest first.
        chats: How many different chats they come from.
        weakest: The lowest match score between two members from
            different chats (every pair is at least this similar).
    """

    members: tuple[Request, ...]
    chats: int
    weakest: float


@dataclass(frozen=True)
class RepeatReport:
    """The result of one run.

    Attributes:
        groups: Repeated requests, most chats first.
        checked: Messages compared.
        too_short: Messages skipped as too short to compare.
    """

    groups: tuple[RepeatGroup, ...]
    checked: int
    too_short: int


def content_words(text: str) -> frozenset[str]:
    """The stemmed words that say what a request is about.

    Args:
        text: A message.

    Returns:
        Its content words: no filler, no request framing, no single letters.
    """
    found = set()
    for word in _WORD.findall(text.lower()):
        if len(word) < 2 or word in STOP_WORDS or word in REQUEST_WORDS:
            continue
        found.add(stem(word))
    return frozenset(found)


def find_repeats(
    requests: Sequence[Request], *, min_chats: int = 2, threshold: float = MATCH_THRESHOLD
) -> RepeatReport:
    """Group requests asked again in other chats.

    Pure and deterministic: the same requests in any order give the same
    groups (ties break on revision ID).

    Args:
        requests: Your messages, one per logical message.
        min_chats: Keep a group only if it spans at least this many chats.
        threshold: The weighted Jaccard score a pair must reach.

    Returns:
        The groups, most chats first, then most members, then oldest.
    """
    ordered = sorted(requests, key=lambda r: r.revision_id)
    words = [content_words(r.text) for r in ordered]
    usable = [i for i, w in enumerate(words) if len(w) >= MIN_CONTENT_WORDS]
    too_short = len(ordered) - len(usable)
    weights = _idf(words[i] for i in usable)

    def score(i: int, j: int) -> float:
        shared = sum(weights[w] for w in words[i] & words[j])
        total = sum(weights[w] for w in words[i] | words[j])
        return shared / total if total else 0.0

    pairs = sorted(
        (
            (s, i, j)
            for i, j in _candidate_pairs(ordered, words, usable)
            if (s := score(i, j)) >= threshold
        ),
        key=lambda p: (-p[0], p[1], p[2]),
    )

    # Complete-linkage merging, strongest pair first. Each message starts
    # in its own group; `group_of` maps a message to its group's members.
    group_of: dict[int, list[int]] = {i: [i] for i in usable}
    for _, i, j in pairs:
        left, right = group_of[i], group_of[j]
        if left is right:
            continue
        if all(
            score(a, b) >= threshold
            for a in left
            for b in right
            if ordered[a].conversation_id != ordered[b].conversation_id
        ):
            merged = left + right
            for member in merged:
                group_of[member] = merged

    seen: set[int] = set()
    groups: list[RepeatGroup] = []
    for members in group_of.values():
        if id(members) in seen:
            continue
        seen.add(id(members))
        chats = {ordered[m].conversation_id for m in members}
        if len(chats) < min_chats:
            continue
        cross = [
            score(a, b)
            for a in members
            for b in members
            if a < b and ordered[a].conversation_id != ordered[b].conversation_id
        ]
        groups.append(
            RepeatGroup(
                members=tuple(sorted((ordered[m] for m in members), key=_oldest_first)),
                chats=len(chats),
                weakest=round(min(cross), 4),
            )
        )
    groups.sort(key=lambda g: (-g.chats, -len(g.members), _oldest_first(g.members[0])))
    return RepeatReport(groups=tuple(groups), checked=len(usable), too_short=too_short)


def _oldest_first(request: Request) -> tuple[float, str]:
    # Undated messages sort last, then by ID so the order never wobbles.
    return (request.created if request.created is not None else math.inf, request.revision_id)


def _idf(word_sets: Iterable[frozenset[str]]) -> dict[str, float]:
    """Inverse document frequency: rarer words weigh more."""
    counts: dict[str, int] = defaultdict(int)
    total = 0
    for words in word_sets:
        total += 1
        for word in words:
            counts[word] += 1
    # +1 on both sides keeps every weight finite; a word in every message
    # gets weight 0 and so can't make two messages match on its own.
    return {word: math.log((total + 1) / (count + 1)) for word, count in counts.items()}


def _candidate_pairs(
    requests: Sequence[Request], words: Sequence[frozenset[str]], usable: Sequence[int]
) -> set[tuple[int, int]]:
    """Pairs from different chats that share at least one not-too-common word.

    Comparing every message with every other is quadratic; this only
    compares messages that could plausibly match (an inverted index, the
    same idea as a search engine's).
    """
    postings: dict[str, list[int]] = defaultdict(list)
    for i in usable:
        for word in words[i]:
            postings[word].append(i)
    cap = max(BLOCKING_MIN_COUNT, int(len(usable) * BLOCKING_MAX_SHARE))
    pairs: set[tuple[int, int]] = set()
    for members in postings.values():
        if len(members) > cap:
            continue
        for x, i in enumerate(members):
            for j in members[x + 1 :]:
                if requests[i].conversation_id != requests[j].conversation_id:
                    pairs.add((i, j) if i < j else (j, i))
    return pairs


def load_requests(session: Session, filters: SearchFilters | None = None) -> list[Request]:
    """Your messages from the archive, one per logical message.

    A message edited in the export has several stored versions; the newest
    one stands for it, so an edit can't make a message repeat itself.

    Args:
        session: A read session on the archive.
        filters: Dates and a term or project filter (speaker is always the
            user). Undated messages are left out when a date is set.

    Returns:
        The requests, in no particular order.
    """
    titles: dict[str, str | None] = {
        conversation_id: title
        for conversation_id, title in session.execute(
            select(ConversationRow.conversation_id, ConversationRow.title)
        )
    }
    newest: dict[str, Request] = {}
    for passage in passages(session, set()):
        if passage.role != "user" or not passage.text.strip():
            continue
        if filters is not None and not _kept(filters, passage.node_key, passage.create_time):
            continue
        request = Request(
            revision_id=passage.revision_id,
            conversation_id=passage.conversation_id,
            native_node_id=passage.native_node_id,
            title=titles.get(passage.conversation_id),
            created=passage.create_time,
            text=passage.text,
        )
        current = newest.get(passage.node_key)
        if current is None or _newer(request, current):
            newest[passage.node_key] = request
    return list(newest.values())


def _kept(filters: SearchFilters, node_key: str, created: float | None) -> bool:
    if filters.node_keys is not None and node_key not in filters.node_keys:
        return False
    if filters.dated:
        if created is None:
            return False
        if filters.since is not None and created < filters.since:
            return False
        if filters.until is not None and created >= filters.until:
            return False
    return True


def _newer(candidate: Request, current: Request) -> bool:
    a = candidate.created if candidate.created is not None else -math.inf
    b = current.created if current.created is not None else -math.inf
    return (a, candidate.revision_id) > (b, current.revision_id)
