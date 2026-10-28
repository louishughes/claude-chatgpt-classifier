r"""Exact text positions and quote fingerprints (NRM-003).

Every later claim ("the user decided X") must point at the exact words it
came from. This module fixes the convention once:

* positions are **half-open ranges of Unicode code points** ``[start, end)``
  in a message's canonical text (``CanonicalNode.text``), i.e. plain Python
  string indices. An emoji is one position; ``\r\n`` is two;
* the canonical text is never normalised (no NFC, no newline changes), so a
  range taken today still selects the same characters tomorrow;
* a quote is fingerprinted with ``quote_hash``, so a stored range can be
  checked against the text before it's trusted.

Editors and browsers count in UTF-16 units and files in UTF-8 bytes, so
converters to and from both are here too, and they're exact.

Talking points:
    - "Every quote is a start and end position plus a fingerprint of the
      words, so a citation can always be checked against the source."
    - "Positions count characters the way Python does, and I convert at the
      edges for tools that count differently."
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

OFFSET_UNIT = "unicode_code_point"
QUOTE_HASH_VERSION = "ke-quote-v1"


class OffsetError(ValueError):
    """A range doesn't fit the text, or the text no longer matches."""


@dataclass(frozen=True)
class Span:
    """A half-open range ``[start, end)`` of code points.

    Attributes:
        start: First code point (inclusive), 0 or more.
        end: End (exclusive); at least ``start``.
    """

    start: int
    end: int

    def __post_init__(self) -> None:
        """Reject negative or reversed ranges."""
        if self.start < 0 or self.end < self.start:
            raise OffsetError("a span needs 0 <= start <= end")

    def of(self, text: str) -> str:
        """Return the exact substring this span selects.

        Raises:
            OffsetError: If the span runs past the end of ``text``.
        """
        if self.end > len(text):
            raise OffsetError("span runs past the end of the text")
        return text[self.start : self.end]


def quote_hash(quote: str) -> str:
    """Fingerprint a quote: SHA-256 of a versioned, unambiguous encoding.

    Args:
        quote: The exact quoted text.

    Returns:
        64 lowercase hex characters.
    """
    payload = json.dumps([QUOTE_HASH_VERSION, quote], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def cite(text: str, span: Span) -> tuple[str, str]:
    """Return the quote a span selects and its fingerprint.

    Args:
        text: Canonical message text.
        span: The range to quote.

    Returns:
        ``(quote, quote_hash)``.
    """
    quote = span.of(text)
    return quote, quote_hash(quote)


def verify(text: str, span: Span, expected_hash: str) -> bool:
    """Check that a stored range still selects the quote it was made from.

    Args:
        text: Canonical message text now.
        span: The stored range.
        expected_hash: The stored ``quote_hash``.

    Returns:
        True if the span fits and the quote's hash matches.
    """
    if span.end > len(text):
        return False
    return quote_hash(span.of(text)) == expected_hash


def find_all(text: str, quote: str) -> list[Span]:
    """Return every span where ``quote`` occurs exactly (overlaps included).

    Args:
        text: Text to search.
        quote: Non-empty exact text.

    Returns:
        Spans in order.

    Raises:
        OffsetError: If ``quote`` is empty.
    """
    if not quote:
        raise OffsetError("cannot search for an empty quote")
    spans: list[Span] = []
    index = text.find(quote)
    while index != -1:
        spans.append(Span(index, index + len(quote)))
        index = text.find(quote, index + 1)
    return spans


# Characters that mean the same in a quote but are often typed differently
# (LEG-004). Nothing else is folded: no case, accents or spacing.
_FOLD = str.maketrans(
    {
        "\u2018": "'",  # ‘
        "\u2019": "'",  # ’ (also the curly apostrophe in "X’s")
        "\u201a": "'",  # ‚
        "\u201b": "'",  # ‛
        "\u201c": '"',  # “
        "\u201d": '"',  # ”
        "\u201e": '"',  # „
        "\u201f": '"',  # ‟
    }
)
_ESCAPES = {"\\n": "\n", "\\r": "\r", "\\t": "\t", '\\"': '"', "\\'": "'"}


def normalise_for_match(text: str) -> tuple[str, list[tuple[int, int]]]:
    r"""Fold quote styles and line endings, keeping a map back to the original.

    The single normalisation used to find a cited quote in real text
    (LEG-004): curly quotes and apostrophes become straight ones, and
    ``\r\n`` or a lone ``\r`` becomes ``\n``. Nothing else changes.

    Returns:
        The folded text, and for each folded character the ``[start, end)``
        it came from in ``text``, so a match maps back to exact original
        positions (line endings and all).
    """
    folded: list[str] = []
    origin: list[tuple[int, int]] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char == "\r":
            width = 2 if text[index + 1 : index + 2] == "\n" else 1
            folded.append("\n")
            origin.append((index, index + width))
            index += width
            continue
        folded.append(char.translate(_FOLD))
        origin.append((index, index + 1))
        index += 1
    return "".join(folded), origin


def _unescape(quote: str) -> str:
    for escaped, plain in _ESCAPES.items():
        quote = quote.replace(escaped, plain)
    return quote


def find_quote(text: str, quote: str) -> list[Span]:
    r"""Find a cited quote in real text; spans point at the **original** text.

    Tries, in order, and stops at the first that matches:

    1. the quote exactly (``find_all``);
    2. both sides through ``normalise_for_match`` (curly vs straight
       quotes, possessives like X’s / X's, line endings);
    3. the same with escape sequences in the quote undone (a model writing
       ``\n`` as backslash + n).

    Every match must start and end on a word boundary, so a quote never
    matches part of a word ("cat" is not found in "concatenate").

    Raises:
        OffsetError: If ``quote`` is empty.
    """
    exact = [s for s in find_all(text, quote) if _whole_words(text, s)]
    if exact:
        return exact
    folded, origin = normalise_for_match(text)
    for needle in dict.fromkeys([quote, _unescape(quote)]):
        wanted, _ = normalise_for_match(needle)
        if not wanted:
            continue
        spans = [
            Span(origin[s.start][0], origin[s.end - 1][1])
            for s in find_all(folded, wanted)
            if _whole_words(folded, s)
        ]
        if spans:
            return spans
    return []


def _whole_words(text: str, span: Span) -> bool:
    first, last = text[span.start], text[span.end - 1]
    before = text[span.start - 1] if span.start > 0 else ""
    after = text[span.end] if span.end < len(text) else ""
    starts_clean = not (_word(first) and _word(before))
    ends_clean = not (_word(last) and _word(after))
    return starts_clean and ends_clean


def _word(char: str) -> bool:
    return bool(char) and (char.isalnum() or char == "_")


def to_utf16(text: str, span: Span) -> Span:
    """Convert a code-point span to UTF-16 code units (JavaScript, editors)."""
    span.of(text)
    return Span(_utf16_len(text[: span.start]), _utf16_len(text[: span.end]))


def from_utf16(text: str, span: Span) -> Span:
    """Convert a UTF-16 span back to code points.

    Raises:
        OffsetError: If a boundary falls inside a surrogate pair or past
            the end of the text.
    """
    return Span(_from_units(text, span.start, 2), _from_units(text, span.end, 2))


def to_utf8(text: str, span: Span) -> Span:
    """Convert a code-point span to UTF-8 byte offsets (files, SQLite)."""
    span.of(text)
    return Span(len(text[: span.start].encode("utf-8")), len(text[: span.end].encode("utf-8")))


def from_utf8(text: str, span: Span) -> Span:
    """Convert a UTF-8 byte span back to code points.

    Raises:
        OffsetError: If a boundary falls inside a character or past the end.
    """
    return Span(_from_units(text, span.start, 8), _from_units(text, span.end, 8))


def _utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def _from_units(text: str, target: int, bits: int) -> int:
    count = 0
    for index, char in enumerate(text):
        if count == target:
            return index
        if count > target:
            break
        count += _units(char, bits)
    if count == target:
        return len(text)
    raise OffsetError("offset falls inside a character or past the end of the text")


def _units(char: str, bits: int) -> int:
    if bits == 8:
        return len(char.encode("utf-8"))
    return 2 if ord(char) > 0xFFFF else 1
