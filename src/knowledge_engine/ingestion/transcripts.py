"""Transcript files (WebVTT, SRT, plain text) as timed cues (ING-010).

A transcript is someone's words with times attached: subtitles for a video,
or a pasted transcript. This module reads one file into a list of cues and
keeps exactly what the file says:

* times are kept to the millisecond as written. A cue with no time gets
  ``None``, never a guessed time;
* a speaker is taken only from an explicit WebVTT voice tag (``<v Name>``).
  "Name: text" inside a line is left as text, because it might not be a
  speaker at all;
* out-of-order cues, an end before its start, and timing lines that can't
  be read are kept and reported as warnings, not fixed;
* the file's SHA-256 and the optional source URL travel with the result,
  so every cue can be traced to the exact file it came from.

Nothing here fetches anything. Getting a transcript (from the user, or an
authorised source) is YTB-002's job; this only reads bytes it's given.

Talking points:
    - "A transcript cue keeps the time the file gave it, or says it has
      none. It never makes one up."
    - "Speaker names come only from explicit tags, so I never turn a line of
      dialogue into a fake speaker."
"""

from __future__ import annotations

import hashlib
import html
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import StrEnum

TRANSCRIPT_PARSER_VERSION = "ing-010-v1"


class TranscriptFormat(StrEnum):
    """Which kind of file a transcript came from."""

    VTT = "vtt"
    SRT = "srt"
    TEXT = "text"


class TranscriptWarning(StrEnum):
    """Something odd in a transcript file, kept and reported, never fixed."""

    OUT_OF_ORDER = "cue_out_of_order"  # starts before the previous cue
    END_BEFORE_START = "cue_end_before_start"
    MALFORMED_TIMING = "cue_timing_unreadable"  # kept as an untimed cue
    EMPTY_CUE = "cue_empty"  # a timing with no text; skipped
    DECODE_REPLACED = "text_not_utf8"  # unreadable bytes replaced with U+FFFD
    NO_CUES = "no_cues"


class TranscriptTooLargeError(ValueError):
    """The transcript file is over the size limit."""


@dataclass(frozen=True)
class Cue:
    """One piece of a transcript.

    Attributes:
        index: Position in the file, from 0, in file order (never re-sorted).
        start_ms: Start time in milliseconds, or None if the file gives none.
        end_ms: End time in milliseconds, or None.
        speaker: From a WebVTT ``<v>`` tag only, else None.
        text: The words, with markup removed and entities decoded.
        line: The 1-based line in the file where the cue's text starts.
    """

    index: int
    start_ms: int | None
    end_ms: int | None
    speaker: str | None
    text: str
    line: int


@dataclass(frozen=True)
class TranscriptDocument:
    """A parsed transcript file and where it came from.

    Attributes:
        format: The file's kind.
        cues: In file order.
        sha256: Fingerprint of the exact bytes read.
        source_url: Where it came from, if the caller knows (kept as given).
        language: A language tag, if the caller knows; never guessed.
        warnings: Warning code -> count.
        parser_version: Which version of this parser read it.
    """

    format: TranscriptFormat
    cues: tuple[Cue, ...]
    sha256: str
    source_url: str | None = None
    language: str | None = None
    warnings: dict[str, int] = field(default_factory=dict)
    parser_version: str = TRANSCRIPT_PARSER_VERSION

    @property
    def timed(self) -> bool:
        """True if at least one cue has a start time."""
        return any(cue.start_ms is not None for cue in self.cues)


# 01:02:03.456, 02:03.456 (VTT) or 01:02:03,456 (SRT). Hours may be long.
_TIME = r"(?:(\d+):)?([0-5]?\d):([0-5]\d)[.,](\d{3})"
_TIMING_RE = re.compile(rf"^\s*{_TIME}\s*-->\s*{_TIME}(?:\s+.*)?$")
_LOOKS_LIKE_TIMING_RE = re.compile(r"-->")
# Plain text: "[1:02] words", "01:02:03 words" or a time alone on its line.
_TEXT_TIME_RE = re.compile(r"^\s*\[?((?:\d+:)?[0-5]?\d:[0-5]\d)(?:[.,](\d{1,3}))?\]?\s*(.*)$")
_VOICE_RE = re.compile(r"<v(?:\.[^\s>]*)?\s+([^>]+)>")
_TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>|<\d+:\d{2}(?::\d{2})?\.\d{3}>")


def parse_transcript(
    data: bytes,
    *,
    format: TranscriptFormat | None = None,  # noqa: A002 - mirrors the CLI flag
    source_url: str | None = None,
    language: str | None = None,
    max_bytes: int | None = None,
) -> TranscriptDocument:
    """Read a transcript file into cues.

    Args:
        data: The file's bytes.
        format: Force a format; None detects it (``WEBVTT`` header -> VTT,
            ``-->`` timing lines -> SRT, otherwise plain text).
        source_url: Where the file came from, if known.
        language: Its language tag, if known.
        max_bytes: Refuse larger files.

    Returns:
        The parsed document. Untimed cues have ``None`` times.

    Raises:
        TranscriptTooLargeError: If ``data`` is over ``max_bytes``.
    """
    if max_bytes is not None and len(data) > max_bytes:
        raise TranscriptTooLargeError("transcript is over the size limit")
    warnings: dict[str, int] = {}
    text = _decode(data, warnings)
    lines = text.splitlines()
    kind = format or _detect(lines)
    if kind == TranscriptFormat.TEXT:
        cues = list(_text_cues(lines))
    else:
        cues = list(_block_cues(lines, kind, warnings))
    _check_order(cues, warnings)
    if not cues:
        _warn(warnings, TranscriptWarning.NO_CUES)
    return TranscriptDocument(
        format=kind,
        cues=tuple(cues),
        sha256=hashlib.sha256(data).hexdigest(),
        source_url=source_url,
        language=language,
        warnings=dict(sorted(warnings.items())),
    )


def _decode(data: bytes, warnings: dict[str, int]) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        _warn(warnings, TranscriptWarning.DECODE_REPLACED)
        return data.decode("utf-8-sig", errors="replace")


def _detect(lines: list[str]) -> TranscriptFormat:
    if lines and lines[0].strip().startswith("WEBVTT"):
        return TranscriptFormat.VTT
    if any(_TIMING_RE.match(line) for line in lines[:50]):
        return TranscriptFormat.SRT
    return TranscriptFormat.TEXT


def _blocks(lines: list[str]) -> Iterator[tuple[int, list[str]]]:
    # Blank-line separated blocks, with the 1-based line number of each.
    block: list[str] = []
    first = 0
    for number, line in enumerate(lines, start=1):
        if line.strip():
            if not block:
                first = number
            block.append(line)
        elif block:
            yield first, block
            block = []
    if block:
        yield first, block


def _block_cues(
    lines: list[str], kind: TranscriptFormat, warnings: dict[str, int]
) -> Iterator[Cue]:
    index = 0
    for first, block in _blocks(lines):
        head = block[0].strip()
        if kind == TranscriptFormat.VTT and (
            head.startswith(("WEBVTT", "NOTE", "STYLE", "REGION"))
        ):
            continue
        # Find the timing line: first or second line (after a cue ID / SRT number).
        timing_at = next(
            (i for i, line in enumerate(block[:2]) if _LOOKS_LIKE_TIMING_RE.search(line)), None
        )
        start = end = None
        body = block
        body_line = first
        if timing_at is not None:
            match = _TIMING_RE.match(block[timing_at])
            if match:
                start, end = _ms(*match.groups()[:4]), _ms(*match.groups()[4:])
            else:
                _warn(warnings, TranscriptWarning.MALFORMED_TIMING)
            body = block[timing_at + 1 :]
            body_line = first + timing_at + 1
        elif kind == TranscriptFormat.SRT and head.isdigit() and len(block) == 1:
            continue  # a stray cue number with nothing else
        speaker, words = _clean(body, kind)
        if not words:
            _warn(warnings, TranscriptWarning.EMPTY_CUE)
            continue
        if start is not None and end is not None and end < start:
            _warn(warnings, TranscriptWarning.END_BEFORE_START)
        yield Cue(index, start, end, speaker, words, body_line)
        index += 1


def _text_cues(lines: list[str]) -> Iterator[Cue]:
    # A plain transcript: each paragraph is a cue. A line that starts with a
    # time ("[1:02] words", or "1:02" alone above the words, as in pasted
    # YouTube transcripts) starts a new cue at that time. There is no end
    # time in plain text, so ``end_ms`` stays None.
    index = 0
    start: int | None = None
    words: list[str] = []
    first_line = 0
    for number, line in enumerate(lines, start=1):
        match = _TEXT_TIME_RE.match(line) if line.strip() else None
        if not line.strip() or match:
            if words:
                yield Cue(index, start, None, None, " ".join(words), first_line)
                index += 1
                words = []
                start = None
            if match:
                start = _clock_ms(match.group(1), match.group(2))
                if match.group(3).strip():
                    words, first_line = [match.group(3).strip()], number
            continue
        if not words:
            first_line = number
        words.append(line.strip())
    if words:
        yield Cue(index, start, None, None, " ".join(words), first_line)


def _clean(body: list[str], kind: TranscriptFormat) -> tuple[str | None, str]:
    raw = "\n".join(line.rstrip() for line in body).strip()
    speaker = None
    if kind == TranscriptFormat.VTT:
        voice = _VOICE_RE.search(raw)
        if voice:
            speaker = html.unescape(voice.group(1).strip()) or None
    words = html.unescape(_TAG_RE.sub("", raw)).strip()
    return speaker, words


def _check_order(cues: list[Cue], warnings: dict[str, int]) -> None:
    previous: int | None = None
    for cue in cues:
        if cue.start_ms is None:
            continue
        if previous is not None and cue.start_ms < previous:
            _warn(warnings, TranscriptWarning.OUT_OF_ORDER)
        previous = cue.start_ms


def _ms(hours: str | None, minutes: str, seconds: str, millis: str) -> int:
    return ((int(hours or 0) * 60 + int(minutes)) * 60 + int(seconds)) * 1000 + int(millis)


def _clock_ms(clock: str, fraction: str | None) -> int:
    parts = [int(p) for p in clock.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    hours, minutes, seconds = parts
    millis = int((fraction or "0").ljust(3, "0"))
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + millis


def _warn(warnings: dict[str, int], code: TranscriptWarning) -> None:
    warnings[code.value] = warnings.get(code.value, 0) + 1
