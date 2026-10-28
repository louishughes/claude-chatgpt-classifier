"""The corpus at segment level: an inventory, a summary and a fair sample (NRM-006).

Taxonomy discovery (TAX-006) and the people reviewing it need to see what
the chats are *about* before any category exists. This module reads every
stored conversation, segments it (NRM-004) and offers three things:

* ``corpus_inventory``: each segment with its text and a few keywords, in
  memory only. Nothing is written and no classification changes.
* ``summarise``: counts only (conversations, segments, characters, sections,
  length bands, how many themes), safe to print because it holds no text.
* ``sample``: a deterministic sample for a given seed that **includes rare
  themes**. A plain random sample of 100 from a corpus that is 90% one
  subject would miss the small subjects entirely, and then nobody would
  ever propose a category for them.

How "theme" is decided, without any model: each segment's *theme word* is
its most distinctive word by TF-IDF (frequent in this segment, rare across
the corpus). Segments sharing a theme word form a theme. Sampling takes one
segment from every theme, rarest themes first, then a second from each, and
so on until the sample is full. Inside a theme, the order comes from a hash
of the seed and the segment ID, so the same seed always gives the same sample.

Talking points:
    - "Same seed, same sample, every time: the order is a hash, not a
      random number generator's state."
    - "Round-robin over themes, rarest first, so a subject that appears in
      two chats out of a thousand still gets looked at."
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.rendering.transcript import StoredConversation, load_conversation
from knowledge_engine.segmentation.segmenter import segment_conversation

INVENTORY_VERSION = "nrm-006-v1"
_WORD = re.compile(r"[^\W\d_]{3,}")
# Segment length bands, in characters (upper bounds; the last is open).
LENGTH_BANDS = (("short", 2_000), ("medium", 8_000), ("long", 24_000), ("very_long", None))


@dataclass(frozen=True)
class SegmentText:
    """One segment's text and size, for discovery and sampling.

    Attributes:
        segment_id: The ``seg_`` ID (stable for the same messages).
        conversation_id: Its ``conv_`` ID.
        section: ``active``, ``alternate`` or ``outside``.
        messages: How many messages it covers.
        text: The messages' text joined with blank lines (private).
    """

    segment_id: str
    conversation_id: str
    section: str
    messages: int
    text: str

    @property
    def characters(self) -> int:
        """Text length."""
        return len(self.text)


@dataclass(frozen=True)
class CorpusSummary:
    """Counts only: safe to show, holds no text."""

    version: str
    conversations: int
    segments: int
    characters: int
    sections: dict[str, int]
    length_bands: dict[str, int]
    themes: int


def segment_texts(
    conversation: StoredConversation, overrides: Mapping[str, str] | None = None
) -> list[SegmentText]:
    """Segment one stored conversation and attach each segment's text.

    ``overrides`` are the reviewer splits and merges in force (NRM-005).
    """
    found = []
    for segment in segment_conversation(conversation, overrides=overrides):
        text = "\n\n".join(
            conversation.messages[native].text
            for native in segment.messages
            if native in conversation.messages
        )
        found.append(
            SegmentText(
                segment.segment_id,
                conversation.conversation_id,
                segment.section,
                len(segment.messages),
                text,
            )
        )
    return found


def corpus_inventory(session: Session, workspace_id: str | None = None) -> Iterator[SegmentText]:
    """Every segment of every stored conversation, in conversation-ID order.

    Args:
        session: A read session. Nothing is written.
        workspace_id: Only this workspace, optionally.

    Yields:
        Segments with text, one conversation at a time (memory stays small).
    """
    from knowledge_engine.importer.records import ConversationRow
    from knowledge_engine.segmentation.overrides import active_overrides

    query = select(ConversationRow.conversation_id).order_by(ConversationRow.conversation_id)
    if workspace_id is not None:
        query = query.where(ConversationRow.workspace_id == workspace_id)
    for conversation_id in session.scalars(query).all():
        overrides = active_overrides(session, conversation_id)
        yield from segment_texts(load_conversation(session, conversation_id), overrides or None)


def theme_words(items: Sequence[SegmentText]) -> dict[str, str]:
    """Each segment's most distinctive word (TF-IDF), or ``""`` if it has none.

    A word in every segment (like a shared boilerplate word) scores zero and
    is never a theme. Ties go to the alphabetically first word, so the
    result never depends on dictionary order.
    """
    bags = [Counter(w.casefold() for w in _WORD.findall(item.text)) for item in items]
    spread: Counter[str] = Counter()
    for bag in bags:
        spread.update(set(bag))
    total = len(items)
    themes = {}
    for item, bag in zip(items, bags, strict=True):
        scored = [
            (count * math.log(total / spread[word]), word)
            for word, count in bag.items()
            if spread[word] < total
        ]
        best = max(scored, key=lambda pair: (pair[0], _reverse(pair[1])), default=(0.0, ""))
        themes[item.segment_id] = best[1] if best[0] > 0 else ""
    return themes


def _reverse(word: str) -> tuple[int, ...]:
    # Lets ``max`` prefer the alphabetically *first* word on equal scores.
    return tuple(-ord(ch) for ch in word)


def summarise(items: Sequence[SegmentText]) -> CorpusSummary:
    """Count conversations, segments, characters, sections, length bands and themes."""
    bands = {name: 0 for name, _ in LENGTH_BANDS}
    for item in items:
        for name, limit in LENGTH_BANDS:
            if limit is None or item.characters <= limit:
                bands[name] += 1
                break
    sections = Counter(item.section for item in items)
    return CorpusSummary(
        version=INVENTORY_VERSION,
        conversations=len({item.conversation_id for item in items}),
        segments=len(items),
        characters=sum(item.characters for item in items),
        sections=dict(sorted(sections.items())),
        length_bands=bands,
        themes=len({t for t in theme_words(items).values() if t}),
    )


def sample(items: Sequence[SegmentText], size: int, *, seed: str) -> list[SegmentText]:
    """A deterministic sample that reaches every theme before repeating one.

    Args:
        items: The inventory.
        size: How many segments to return (at most ``len(items)``).
        seed: Any text; the same seed and items always give the same sample.

    Returns:
        The sample, in the order it was drawn (rarest themes first).
    """
    if size <= 0:
        return []
    themes = theme_words(items)
    groups: dict[str, list[SegmentText]] = defaultdict(list)
    for item in items:
        groups[themes[item.segment_id]].append(item)
    for members in groups.values():
        members.sort(key=lambda item: _rank(seed, item.segment_id))
    # Rarest themes first; segments with no theme word go last.
    order = sorted(groups, key=lambda t: (t == "", len(groups[t]), _rank(seed, t)))
    drawn: list[SegmentText] = []
    depth = 0
    while len(drawn) < min(size, len(items)):
        for theme in order:
            if depth < len(groups[theme]):
                drawn.append(groups[theme][depth])
                if len(drawn) == size:
                    break
        depth += 1
    return drawn


def _rank(seed: str, key: str) -> str:
    return hashlib.sha256(f"{seed}\x00{key}".encode()).hexdigest()


def sample_ids(items: Iterable[SegmentText]) -> list[str]:
    """Segment IDs only, for printing a sample without its text."""
    return [item.segment_id for item in items]
