"""How much two chats share their *distinctive* words (REL-005).

The local hashed embedding (RET-002) counts every word, so two long chats
on different subjects still look alike: "the", "you" and "can" dominate
both. Here each chat becomes a TF-IDF vector over its content words and its
title. A word's weight falls with the number of chats that use it (IDF over
the workspace), so a word every chat uses counts for nothing, and a word
only two chats use counts for a lot.

Only the strongest ``TOP_TERMS`` words of each chat are kept. That keeps
the comparison fast (an inverted index only meets pairs that share a kept
word) and stops a long chat's tail of rare one-off words from swamping the
words it is actually about.

The words themselves never leave this module; callers get a score per pair.

Talking points:
    - "Each chat is described by the words that set it apart from the rest of
      the archive, and two chats match when those words overlap."
    - "Words that every chat uses are worth nothing, so long chats don't look
      alike just for being long."
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from collections.abc import Sequence

from knowledge_engine.retrieval.embeddings import stem

TOP_TERMS = 100
TITLE_WEIGHT = 3  # an auto-generated title names the subject in a few words
_WORD = re.compile(r"[^\W\d_]{3,}", re.UNICODE)
# Common words IDF would also discount on a large archive; listed so small
# ones behave the same way.
_STOP = frozenset(
    "the and are but for from has have had was were will with you your yours this that these "
    "those they them their there then than what when where which who whom why how can could "
    "should would shall may might must not just also into onto over under about after before "
    "here very more most some such only own same other each any all both few many much "
    "its it's i'm i've i'll let's sure okay yes thanks thank please help need want like make "
    "use using used one two get got does did doing done being been our ours out off now new "
    "way well good great really something anything everything nothing".split()
)


def _terms(title: str, text: str) -> Counter[str]:
    counts: Counter[str] = Counter()
    for words, weight in ((text, 1), (title, TITLE_WEIGHT)):
        for word in _WORD.findall(words.lower()):
            if word not in _STOP:
                counts[stem(word)] += weight
    return counts


def distinctive_similarity(
    docs: Sequence[tuple[str, str]], *, floor: float
) -> dict[tuple[int, int], float]:
    """Cosine of distinctive-word vectors for every pair scoring at least ``floor``.

    Args:
        docs: ``(title, text)`` per chat; pairs are reported by position.
        floor: Pairs below this are left out.

    Returns:
        ``{(i, j): score}`` with ``i < j``, rounded to 3 places.
    """
    counted = [_terms(title, text) for title, text in docs]
    df: Counter[str] = Counter()
    for counts in counted:
        df.update(counts.keys())
    total = len(docs)
    vectors: list[dict[str, float]] = []
    for counts in counted:
        weights = {
            term: (1.0 + math.log(n)) * math.log(total / df[term])
            for term, n in counts.items()
            if df[term] < total  # in every chat: worth nothing
        }
        top = dict(sorted(weights.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_TERMS])
        length = math.sqrt(sum(w * w for w in top.values()))
        vectors.append({t: w / length for t, w in top.items()} if length else {})
    holders: dict[str, list[tuple[int, float]]] = defaultdict(list)
    for index, vector in enumerate(vectors):
        for term, weight in vector.items():
            holders[term].append((index, weight))
    dots: dict[tuple[int, int], float] = defaultdict(float)
    for held in holders.values():
        for x in range(len(held)):
            i, wi = held[x]
            for j, wj in held[x + 1 :]:
                dots[(i, j)] += wi * wj
    return {pair: round(score, 3) for pair, score in dots.items() if score >= floor}
