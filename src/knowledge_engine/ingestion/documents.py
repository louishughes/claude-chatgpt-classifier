"""Markdown and plain-text files as located blocks (ING-008).

A note or a text file is read into **blocks** (headings, paragraphs,
lists, quotes, code, tables, rules), and every block knows exactly where
it came from:

* ``start``/``end``: character offsets into the decoded text, so
  ``text[start:end]`` is the block, byte-for-byte as written (line endings
  and Unicode untouched);
* ``line_start``/``line_end``: 1-based line numbers;
* ``heading_path``: the headings it sits under, outermost first;
* ``locator``: a short stable name (``L12-L15``) for citations.

Frontmatter (the ``---`` block at the top) is parsed as YAML when it can
be. When it can't, the raw text is kept and a warning says why; nothing is
guessed. Bytes are decoded as UTF-8 (with or without a BOM) or UTF-16 by
its BOM; otherwise Windows-1252, and as a last resort Latin-1, which
always decodes. A fallback is always reported, so a file is never read
"wrong" silently.

Image references (``![alt](path)`` and ``![[embed]]``) are listed with the
block they're in. They are references only: nothing here opens them.

Talking points:
    - "Every block of a note keeps its exact character range and line
      numbers, so a quote can always be traced back to the file."
    - "If the encoding or the frontmatter is odd, it says so with a warning
      code instead of quietly guessing."
"""

from __future__ import annotations

import codecs
import hashlib
import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

import yaml

DOCUMENT_PARSER_VERSION = "ing-008-v1"


class BlockKind(StrEnum):
    """What a block is."""

    FRONTMATTER = "frontmatter"
    HEADING = "heading"
    PARAGRAPH = "paragraph"
    LIST = "list"
    QUOTE = "quote"
    CODE = "code"
    TABLE = "table"
    RULE = "rule"


@dataclass(frozen=True)
class Block:
    """One located block.

    Attributes:
        index: Position in the document, from 0.
        kind: What it is.
        text: The block's exact text (``document.text[start:end]`` for
            text formats; the extracted text for converted files).
        start: Character offset of the first character.
        end: Character offset just after the last character.
        line_start: 1-based first line (None for converted files).
        line_end: 1-based last line (None for converted files).
        heading_path: Headings above it, outermost first (a heading's own
            path ends with itself).
        level: Heading level 1-6, else None.
        locator: Stable short name used in citations.
    """

    index: int
    kind: BlockKind
    text: str
    start: int
    end: int
    line_start: int | None
    line_end: int | None
    heading_path: tuple[str, ...] = ()
    level: int | None = None
    locator: str = ""


@dataclass(frozen=True)
class AssetReference:
    """An image or file a block points at (never opened here)."""

    target: str
    block_index: int
    style: str  # "markdown" (![alt](x)), "wikilink" (![[x]]) or "docx" (embedded part)


@dataclass(frozen=True)
class ParsedDocument:
    """A file read into located blocks.

    Attributes:
        format: ``markdown``, ``text``, ``docx`` or ``pdf``.
        sha256: SHA-256 of the file's bytes.
        size: Size in bytes.
        encoding: The encoding used to read it (None for binary formats).
        text: The decoded text the offsets point into.
        frontmatter: Parsed frontmatter mapping, or None.
        frontmatter_raw: The frontmatter text as written, or None.
        blocks: In document order.
        assets: Image and file references.
        warnings: Problem codes (never content).
        parser: Which parser (and version) made it.
        pages: Page count, where the format has pages and it is known.
    """

    format: str
    sha256: str
    size: int
    encoding: str | None
    text: str
    frontmatter: dict[str, Any] | None
    frontmatter_raw: str | None
    blocks: tuple[Block, ...]
    assets: tuple[AssetReference, ...] = ()
    warnings: tuple[str, ...] = ()
    parser: str = DOCUMENT_PARSER_VERSION
    pages: int | None = None

    def headings(self) -> list[Block]:
        """The heading blocks, in order."""
        return [b for b in self.blocks if b.kind is BlockKind.HEADING]


# --- Decoding -----------------------------------------------------------------

_BOMS = (
    (codecs.BOM_UTF8, "utf-8-sig"),
    (codecs.BOM_UTF16_LE, "utf-16"),
    (codecs.BOM_UTF16_BE, "utf-16"),
)


def decode_text(data: bytes) -> tuple[str, str, tuple[str, ...]]:
    """Decode bytes without ever replacing a character: (text, encoding, warnings)."""
    for bom, name in _BOMS:
        if data.startswith(bom):
            try:
                return data.decode(name), name, ()
            except UnicodeDecodeError:
                break  # a BOM followed by bad bytes: fall through to the fallbacks
    try:
        return data.decode("utf-8"), "utf-8", ()
    except UnicodeDecodeError:
        pass
    try:
        return data.decode("cp1252"), "cp1252", ("encoding_fallback_cp1252",)
    except UnicodeDecodeError:
        # Latin-1 maps every byte, so this always succeeds; the warning says
        # some characters may be wrong.
        return data.decode("latin-1"), "latin-1", ("encoding_fallback_latin1",)


# --- Lines ----------------------------------------------------------------------


@dataclass(frozen=True)
class _Line:
    number: int  # 1-based
    start: int
    end: int  # without the line ending
    text: str


def _lines(text: str) -> list[_Line]:
    found, offset = [], 0
    for number, raw in enumerate(text.splitlines(keepends=True), start=1):
        body = raw.rstrip("\r\n")
        found.append(_Line(number, offset, offset + len(body), body))
        offset += len(raw)
    return found


_ATX = re.compile(r"^ {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t]*#*[ \t]*$")
_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_RULE = re.compile(r"^ {0,3}([-*_])(?:[ \t]*\1){2,}[ \t]*$")
_SETEXT = re.compile(r"^ {0,3}(=+|-+)[ \t]*$")
_LIST = re.compile(r"^ {0,3}(?:[-*+]|\d{1,9}[.)])(?:[ \t]|$)")
_QUOTE = re.compile(r"^ {0,3}>")
_TABLE_SEPARATOR = re.compile(r"^ {0,3}\|?[ \t]*:?-+:?[ \t]*(\|[ \t]*:?-+:?[ \t]*)+\|?[ \t]*$")
_MD_IMAGE = re.compile(r"!\[[^\]]*\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
_WIKI_EMBED = re.compile(r"!\[\[([^\]|#]+)(?:[#|][^\]]*)?\]\]")


def _blank(line: _Line) -> bool:
    return not line.text.strip()


def _frontmatter(
    lines: list[_Line],
) -> tuple[int, dict[str, Any] | None, str | None, tuple[str, ...]]:
    """(lines used, parsed mapping, raw text, warnings)."""
    if not lines or lines[0].text != "---":
        return 0, None, None, ()
    for i in range(1, len(lines)):
        if lines[i].text in ("---", "..."):
            raw = "\n".join(line.text for line in lines[1:i])
            try:
                loaded = yaml.safe_load(raw) if raw.strip() else {}
            except yaml.YAMLError:
                return i + 1, None, raw, ("frontmatter_invalid",)
            if not isinstance(loaded, dict):
                return i + 1, None, raw, ("frontmatter_not_mapping",)
            return i + 1, {str(k): v for k, v in loaded.items()}, raw, ()
    return 0, None, None, ("frontmatter_unclosed",)  # read as ordinary text


def parse_markdown(data: bytes) -> ParsedDocument:
    """Read Markdown bytes into located blocks."""
    text, encoding, warnings = decode_text(data)
    lines = _lines(text)
    used, front, front_raw, front_warnings = _frontmatter(lines)
    blocks: list[Block] = []
    assets: list[AssetReference] = []
    heads: list[tuple[int, str]] = []  # (level, title) of the open headings
    problems = list(warnings) + list(front_warnings)

    def add(kind: BlockKind, first: _Line, last: _Line, level: int | None = None) -> None:
        index = len(blocks)
        body = text[first.start : last.end]
        if kind is BlockKind.HEADING and level is not None:
            title = _heading_title(first.text, last is not first)
            while heads and heads[-1][0] >= level:
                heads.pop()
            heads.append((level, title))
        path = tuple(title for _, title in heads)
        blocks.append(
            Block(
                index=index,
                kind=kind,
                text=body,
                start=first.start,
                end=last.end,
                line_start=first.number,
                line_end=last.number,
                heading_path=path,
                level=level,
                locator=f"L{first.number}" + ("" if last is first else f"-L{last.number}"),
            )
        )
        if kind is not BlockKind.CODE:
            for match in _MD_IMAGE.finditer(body):
                assets.append(AssetReference(match.group(1), index, "markdown"))
            for match in _WIKI_EMBED.finditer(body):
                assets.append(AssetReference(match.group(1).strip(), index, "wikilink"))

    if used:
        add(BlockKind.FRONTMATTER, lines[0], lines[used - 1])
    i = used
    while i < len(lines):
        line = lines[i]
        if _blank(line):
            i += 1
            continue
        fence = _FENCE.match(line.text)
        if fence:
            marker = fence.group(1)
            j = i + 1
            while j < len(lines) and not lines[j].text.lstrip(" ").startswith(marker):
                j += 1
            if j >= len(lines):
                problems.append("unclosed_code_fence")
                j = len(lines) - 1
            add(BlockKind.CODE, line, lines[j])
            i = j + 1
            continue
        atx = _ATX.match(line.text)
        if atx:
            add(BlockKind.HEADING, line, line, level=len(atx.group(1)))
            i += 1
            continue
        if _RULE.match(line.text):
            add(BlockKind.RULE, line, line)
            i += 1
            continue
        if _QUOTE.match(line.text) or _LIST.match(line.text):
            kind = BlockKind.QUOTE if _QUOTE.match(line.text) else BlockKind.LIST
            j = i
            while j + 1 < len(lines) and not _blank(lines[j + 1]):
                following = lines[j + 1].text
                if _ATX.match(following) or _FENCE.match(following):
                    break
                if kind is BlockKind.QUOTE and not _QUOTE.match(following):
                    break
                j += 1
            add(kind, line, lines[j])
            i = j + 1
            continue
        if "|" in line.text and i + 1 < len(lines) and _TABLE_SEPARATOR.match(lines[i + 1].text):
            j = i + 1
            while j + 1 < len(lines) and "|" in lines[j + 1].text and not _blank(lines[j + 1]):
                j += 1
            add(BlockKind.TABLE, line, lines[j])
            i = j + 1
            continue
        # A paragraph runs to a blank line or the start of another block. A
        # "===" or "---" line right under it turns it into a heading instead.
        j, level = i, None
        while j + 1 < len(lines):
            nxt = lines[j + 1]
            setext = _SETEXT.match(nxt.text)
            if setext:
                level = 1 if setext.group(1).startswith("=") else 2
                j += 1
                break
            if _blank(nxt) or any(p.match(nxt.text) for p in (_ATX, _FENCE, _QUOTE, _LIST, _RULE)):
                break
            j += 1
        if level is None:
            add(BlockKind.PARAGRAPH, line, lines[j])
        else:
            add(BlockKind.HEADING, line, lines[j], level=level)
        i = j + 1
    return ParsedDocument(
        format="markdown",
        sha256=hashlib.sha256(data).hexdigest(),
        size=len(data),
        encoding=encoding,
        text=text,
        frontmatter=front,
        frontmatter_raw=front_raw,
        blocks=tuple(blocks),
        assets=tuple(assets),
        warnings=tuple(dict.fromkeys(problems)),
    )


def _heading_title(line: str, setext: bool) -> str:
    if setext:
        return line.strip()  # a two-line heading's title is its first line
    atx = _ATX.match(line)
    return (atx.group(2) or "").strip() if atx else line.strip()


def parse_text(data: bytes) -> ParsedDocument:
    """Read plain text: paragraphs separated by blank lines, nothing else assumed."""
    text, encoding, warnings = decode_text(data)
    lines = _lines(text)
    blocks: list[Block] = []
    i = 0
    while i < len(lines):
        if _blank(lines[i]):
            i += 1
            continue
        j = i
        while j + 1 < len(lines) and not _blank(lines[j + 1]):
            j += 1
        first, last = lines[i], lines[j]
        blocks.append(
            Block(
                index=len(blocks),
                kind=BlockKind.PARAGRAPH,
                text=text[first.start : last.end],
                start=first.start,
                end=last.end,
                line_start=first.number,
                line_end=last.number,
                locator=f"L{first.number}" + ("" if j == i else f"-L{last.number}"),
            )
        )
        i = j + 1
    return ParsedDocument(
        format="text",
        sha256=hashlib.sha256(data).hexdigest(),
        size=len(data),
        encoding=encoding,
        text=text,
        frontmatter=None,
        frontmatter_raw=None,
        blocks=tuple(blocks),
        warnings=warnings,
    )


@dataclass
class TextBuilder:
    """Joins extracted blocks into one text, so converted files get offsets too."""

    parts: list[str] = field(default_factory=list)
    length: int = 0

    def add(self, piece: str) -> tuple[int, int]:
        """Append one block (after a blank line); return its (start, end)."""
        if self.parts:
            self.parts.append("\n\n")
            self.length += 2
        start = self.length
        self.parts.append(piece)
        self.length += len(piece)
        return start, self.length

    def text(self) -> str:
        """The whole text the offsets point into."""
        return "".join(self.parts)
