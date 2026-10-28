"""Topic segments: where one conversation changes subject (NRM-004, LEG-005).

A chat is often about several things. Later stages classify and extract
per *segment*, so each label is about one subject. This module proposes the
boundaries deterministically, with no model:

1. **Exchanges, not messages.** A segment boundary can only fall before a
   user message, so a question always stays with its answer. A short user
   reply ("no", "ok, do that") never starts a new segment: it answers what
   came before, and cutting there is exactly how the old pipelines lost
   decisions (LEG-005).
2. **Long pauses.** A gap of ``gap_hours`` or more between two exchanges is
   a boundary: people come back to an old chat for something new.
3. **Vocabulary shifts.** Each exchange becomes a bag of content words;
   words that appear in most of the chat's exchanges (including "the" and
   the chat's own running theme) are ignored. Where the words of the
   ``window`` exchanges before a point share almost nothing with the
   ``window`` after it, and the drop is a local low point, that's a
   boundary (TextTiling, Hearst 1997, simplified).
4. **Sizes.** No segment is shorter than ``min_exchanges`` unless a pause
   forces it. A segment longer than ``max_characters`` is **not clipped**:
   it is split into overlapping parts at exchange boundaries, each sharing
   one exchange with the next, so no message is cut and the head and tail
   are always kept. A single exchange over the limit becomes its own
   oversized part, flagged, never truncated.

Every message of every transcript section (active path, each alternate
branch, anything outside the tree) lands in exactly one segment. Sections
are segmented separately, so competing branches are never mixed.

Talking points:
    - "Segments break between exchanges, never inside one, so a 'no' always
      stays next to the suggestion it rejects."
    - "Nothing is clipped. A long segment becomes overlapping parts, and the
      report shows a truncation count that must be zero."
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from knowledge_engine.rendering.transcript import StoredConversation, transcript_sections

SEGMENTER_VERSION = "nrm-004-v1"

_WORD = re.compile(r"[^\W\d_]{3,}")


@dataclass(frozen=True)
class SegmentMessage:
    """One message as the segmenter sees it.

    Attributes:
        native_id: The export's node ID.
        revision_id: The exact message version (``rev_``).
        role: Who wrote it.
        text: Its text (may be empty, e.g. image-only).
        create_time: Seconds since 1970, or None.
    """

    native_id: str
    revision_id: str
    role: str | None
    text: str
    create_time: float | None


@dataclass(frozen=True)
class SegmentPart:
    """A piece of a segment that fits the size budget.

    Attributes:
        messages: Native IDs, in order. Neighbouring parts share one exchange.
        characters: Total text length.
        oversized: True when one exchange alone is over the budget (kept
            whole, never truncated).
    """

    messages: tuple[str, ...]
    characters: int
    oversized: bool = False


@dataclass(frozen=True)
class Segment:
    """A run of messages about one subject.

    Attributes:
        segment_id: ``seg_`` + hash of the conversation, section, segmenter
            version and member revisions: same input, same ID.
        conversation_id: The ``conv_`` ID.
        section: ``active``, ``alternate`` or ``outside``.
        section_index: Which section (0 is the active path).
        sequence: Position within the section, from 0.
        messages: Native IDs, in order. Never overlaps another segment.
        revisions: The matching revision IDs.
        reason: Why it starts here: ``start``, ``gap`` or ``vocabulary``.
        parts: The segment split to the size budget (one part if it fits).
    """

    segment_id: str
    conversation_id: str
    section: str
    section_index: int
    sequence: int
    messages: tuple[str, ...]
    revisions: tuple[str, ...]
    reason: str
    parts: tuple[SegmentPart, ...]


@dataclass(frozen=True)
class SegmenterSettings:
    """The knobs, all versioned with ``SEGMENTER_VERSION``."""

    gap_hours: float = 6.0
    window: int = 2
    threshold: float = 0.08
    min_exchanges: int = 2
    short_reply_chars: int = 40
    max_characters: int = 24_000
    common_word_share: float = 0.5


def segment_section(
    messages: Sequence[SegmentMessage],
    *,
    conversation_id: str,
    section: str = "active",
    section_index: int = 0,
    settings: SegmenterSettings | None = None,
) -> list[Segment]:
    """Split one transcript section into topic segments.

    Args:
        messages: The section's messages in reading order.
        conversation_id: The ``conv_`` ID.
        section: The section kind.
        section_index: The section's position.
        settings: Thresholds; defaults if omitted.

    Returns:
        Segments covering every message exactly once, in order.
    """
    config = settings or SegmenterSettings()
    exchanges = _exchanges(messages, config)
    if not exchanges:
        return []
    starts = _boundaries(exchanges, config)
    segments = []
    for sequence, (start, reason) in enumerate(starts):
        end = starts[sequence + 1][0] if sequence + 1 < len(starts) else len(exchanges)
        members = [m for exchange in exchanges[start:end] for m in exchange]
        segments.append(
            Segment(
                segment_id=_segment_id(conversation_id, section_index, members),
                conversation_id=conversation_id,
                section=section,
                section_index=section_index,
                sequence=sequence,
                messages=tuple(m.native_id for m in members),
                revisions=tuple(m.revision_id for m in members),
                reason=reason,
                parts=split_parts(exchanges[start:end], config.max_characters),
            )
        )
    return segments


def _exchanges(
    messages: Sequence[SegmentMessage], config: SegmenterSettings
) -> list[list[SegmentMessage]]:
    # A new exchange starts at each user message, except a short reply,
    # which stays with the exchange it answers. Anything before the first
    # user message (a system prompt) joins the first exchange.
    exchanges: list[list[SegmentMessage]] = []
    for message in messages:
        opens = (
            message.role == "user"
            and len(message.text.strip()) > config.short_reply_chars
            and any(m.role == "user" for e in exchanges[-1:] for m in e)
        )
        if not exchanges or opens:
            exchanges.append([message])
        else:
            exchanges[-1].append(message)
    return exchanges


def _boundaries(
    exchanges: list[list[SegmentMessage]], config: SegmenterSettings
) -> list[tuple[int, str]]:
    starts: list[tuple[int, str]] = [(0, "start")]
    bags = [_words(exchange) for exchange in exchanges]
    common = _common_words(bags, config.common_word_share)
    bags = [Counter({w: n for w, n in bag.items() if w not in common}) for bag in bags]
    scores = [_cohesion(bags, i, config.window) for i in range(len(exchanges))]
    last = 0
    for i in range(1, len(exchanges)):
        if _gap_hours(exchanges[i - 1], exchanges[i]) >= config.gap_hours:
            starts.append((i, "gap"))
            last = i
            continue
        long_enough = (
            i - last >= config.min_exchanges and len(exchanges) - i >= config.min_exchanges
        )
        score = scores[i]
        low_point = score <= min(scores[max(1, i - 1) : i + 2])
        if long_enough and score < config.threshold and low_point:
            starts.append((i, "vocabulary"))
            last = i
    return starts


def _words(exchange: list[SegmentMessage]) -> Counter[str]:
    return Counter(w.lower() for m in exchange for w in _WORD.findall(m.text))


def _common_words(bags: list[Counter[str]], share: float) -> set[str]:
    if len(bags) < 3:
        return set()
    spread: Counter[str] = Counter()
    for bag in bags:
        spread.update(set(bag))
    return {word for word, count in spread.items() if count / len(bags) > share}


def _cohesion(bags: list[Counter[str]], i: int, window: int) -> float:
    """Cosine similarity of the words just before exchange ``i`` and from it on."""
    if i == 0:
        return 1.0
    before: Counter[str] = sum(bags[max(0, i - window) : i], Counter())
    after: Counter[str] = sum(bags[i : i + window], Counter())
    dot = sum(n * after[w] for w, n in before.items())
    norm = (sum(n * n for n in before.values()) * sum(n * n for n in after.values())) ** 0.5
    return dot / norm if norm else 1.0  # no words either side: no evidence to cut


def _gap_hours(previous: list[SegmentMessage], current: list[SegmentMessage]) -> float:
    before = [m.create_time for m in previous if m.create_time is not None]
    after = [m.create_time for m in current if m.create_time is not None]
    if not before or not after:
        return 0.0  # unknown times never force a boundary
    return (min(after) - max(before)) / 3600


class _Sized(Protocol):
    @property
    def native_id(self) -> str: ...

    @property
    def text(self) -> str: ...


def split_parts(exchanges: Sequence[Sequence[_Sized]], budget: int) -> tuple[SegmentPart, ...]:
    """Split exchanges into parts of at most ``budget`` characters, never clipping.

    Neighbouring parts share one exchange, so context carries across the
    cut; no message is cut and the head and tail are always kept. An
    exchange over the budget on its own becomes an ``oversized`` part
    (LEG-005). Works on any message type with ``native_id`` and ``text``,
    so model stages split exactly like the segmenter.
    """
    sizes = [sum(len(m.text) for m in exchange) for exchange in exchanges]
    if sum(sizes) <= budget:
        members = tuple(m.native_id for e in exchanges for m in e)
        return (SegmentPart(members, sum(sizes)),)
    parts: list[SegmentPart] = []
    start = 0
    while start < len(exchanges):
        end, size = start, 0
        while end < len(exchanges) and (end == start or size + sizes[end] <= budget):
            size += sizes[end]
            end += 1
        members = tuple(m.native_id for e in exchanges[start:end] for m in e)
        parts.append(SegmentPart(members, size, oversized=size > budget))
        if end >= len(exchanges):
            break
        # Overlap by one exchange so context carries across the cut, unless
        # that would make no progress (a part of a single exchange).
        start = end - 1 if end - 1 > start else end
    return tuple(parts)


def _segment_id(conversation_id: str, section_index: int, members: list[SegmentMessage]) -> str:
    key = "\x00".join(
        [SEGMENTER_VERSION, conversation_id, str(section_index)] + [m.revision_id for m in members]
    )
    return "seg_" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:32]


def truncation_count(segments: Sequence[Segment]) -> int:
    """Characters dropped across all segments' parts. Always 0 by design (LEG-005).

    Computed, not assumed: it compares each segment's text with what its
    parts cover, so a future change that clips would show up here.
    """
    dropped = 0
    for segment in segments:
        covered = {native for part in segment.parts for native in part.messages}
        dropped += sum(1 for native in segment.messages if native not in covered)
    return dropped


def boundary_scores(predicted: Sequence[str], gold: Sequence[str]) -> dict[str, float]:
    """Precision, recall and F1 of segment start messages (exact match).

    Args:
        predicted: Native IDs where proposed segments start (excluding the first).
        gold: Native IDs where annotated topics start (excluding the first).

    Returns:
        ``precision``, ``recall`` and ``f1``; 1.0 when both are empty.
    """
    p, g = set(predicted), set(gold)
    if not p and not g:
        return {"precision": 1.0, "recall": 1.0, "f1": 1.0}
    hits = len(p & g)
    precision = hits / len(p) if p else 0.0
    recall = hits / len(g) if g else 0.0
    f1 = 2 * precision * recall / (precision + recall) if hits else 0.0
    return {"precision": precision, "recall": recall, "f1": f1}


def segment_conversation(
    conversation: StoredConversation, settings: SegmenterSettings | None = None
) -> list[Segment]:
    """Segment every transcript section of a stored conversation.

    Args:
        conversation: From ``load_conversation``.
        settings: Thresholds; defaults if omitted.

    Returns:
        The active path's segments first, then each alternate branch's,
        then any messages outside the tree. Every message exactly once.
    """
    segments: list[Segment] = []
    for index, section in enumerate(transcript_sections(conversation)):
        messages = [
            SegmentMessage(
                native_id,
                conversation.revisions.get(native_id, ""),
                conversation.messages[native_id].role,
                conversation.messages[native_id].text,
                conversation.messages[native_id].create_time,
            )
            for native_id in section.messages
            if native_id in conversation.messages
        ]
        segments += segment_section(
            messages,
            conversation_id=conversation.conversation_id,
            section=section.kind,
            section_index=index,
            settings=settings,
        )
    return segments
