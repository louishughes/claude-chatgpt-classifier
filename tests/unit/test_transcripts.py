"""ING-010: transcript files become cues with exact (or no) timing."""

from __future__ import annotations

import hashlib

from hypothesis import given
from hypothesis import strategies as st

from knowledge_engine.ingestion.transcripts import (
    TranscriptFormat,
    TranscriptTooLargeError,
    TranscriptWarning,
    parse_transcript,
)

VTT = """WEBVTT Kind: captions

NOTE synthetic fixture, not real speech

intro
00:00:01.000 --> 00:00:04.250 align:start
<v Ada Lovelace>Hello &amp; welcome</v>

00:04.250 --> 00:06.000
<c.yellow>Second</c> <00:00:05.000>cue
with two lines

01:00:00.000 --> 01:00:01.500
<v.loud Narrator>Much later
"""

SRT = """1
00:00:01,000 --> 00:00:02,000
First

2
00:00:03,500 --> 00:00:04,000
Second: not a speaker

"""


def test_vtt_keeps_exact_times_voices_and_text() -> None:
    doc = parse_transcript(VTT.encode(), source_url="https://example.invalid/v", language="en")
    assert doc.format == TranscriptFormat.VTT
    assert [(c.start_ms, c.end_ms) for c in doc.cues] == [
        (1000, 4250),
        (4250, 6000),
        (3_600_000, 3_601_500),
    ]
    assert [c.speaker for c in doc.cues] == ["Ada Lovelace", None, "Narrator"]
    assert doc.cues[0].text == "Hello & welcome"
    assert doc.cues[1].text == "Second cue\nwith two lines"
    assert doc.sha256 == hashlib.sha256(VTT.encode()).hexdigest()
    assert doc.source_url == "https://example.invalid/v"
    assert doc.language == "en"
    assert doc.warnings == {}


def test_srt_never_invents_speakers() -> None:
    doc = parse_transcript(SRT.encode())
    assert doc.format == TranscriptFormat.SRT
    assert [(c.index, c.start_ms, c.end_ms, c.text) for c in doc.cues] == [
        (0, 1000, 2000, "First"),
        (1, 3500, 4000, "Second: not a speaker"),
    ]
    assert all(c.speaker is None for c in doc.cues)
    assert doc.cues[0].line == 3


def test_out_of_order_and_reversed_cues_are_kept_and_reported() -> None:
    srt = (
        "1\n00:00:05,000 --> 00:00:06,000\nlater first\n\n"
        "2\n00:00:01,000 --> 00:00:00,500\nearlier, reversed\n"
    )
    doc = parse_transcript(srt.encode())
    # File order is kept: nothing is re-sorted or corrected.
    assert [c.text for c in doc.cues] == ["later first", "earlier, reversed"]
    assert doc.cues[1].start_ms == 1000 and doc.cues[1].end_ms == 500
    assert doc.warnings == {
        TranscriptWarning.OUT_OF_ORDER.value: 1,
        TranscriptWarning.END_BEFORE_START.value: 1,
    }


def test_unreadable_timing_becomes_an_untimed_cue() -> None:
    srt = "1\n00:00:01,000 --> 00:00:02,000\nok\n\n2\n00:00:xx --> soon\nwords stay\n"
    doc = parse_transcript(srt.encode(), format=TranscriptFormat.SRT)
    assert doc.cues[1].text == "words stay"
    assert doc.cues[1].start_ms is None and doc.cues[1].end_ms is None
    assert doc.warnings == {TranscriptWarning.MALFORMED_TIMING.value: 1}


def test_plain_text_has_no_made_up_times() -> None:
    doc = parse_transcript(b"First paragraph\ncontinues.\n\nSecond paragraph.\n")
    assert doc.format == TranscriptFormat.TEXT
    assert [(c.start_ms, c.end_ms, c.text) for c in doc.cues] == [
        (None, None, "First paragraph continues."),
        (None, None, "Second paragraph."),
    ]
    assert not doc.timed


def test_pasted_youtube_style_text_keeps_written_times_only() -> None:
    pasted = "0:00\nintro words\n1:02\nnext bit\n[1:01:03] bracketed\n\nno time here\n"
    doc = parse_transcript(pasted.encode())
    assert [(c.start_ms, c.end_ms, c.text) for c in doc.cues] == [
        (0, None, "intro words"),
        (62_000, None, "next bit"),
        (3_663_000, None, "bracketed"),
        (None, None, "no time here"),
    ]


def test_bad_bytes_are_replaced_and_reported() -> None:
    doc = parse_transcript(b"caf\xe9 au lait\n")
    assert doc.cues[0].text == "caf� au lait"
    assert doc.warnings == {TranscriptWarning.DECODE_REPLACED.value: 1}


def test_empty_and_oversized_files() -> None:
    assert parse_transcript(b"WEBVTT\n\n").warnings == {TranscriptWarning.NO_CUES.value: 1}
    try:
        parse_transcript(b"x" * 11, max_bytes=10)
    except TranscriptTooLargeError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected TranscriptTooLargeError")


@given(
    st.lists(
        st.tuples(
            st.integers(0, 10 * 3600 * 1000),
            st.integers(0, 60_000),
            st.text(
                alphabet=st.characters(blacklist_categories=("Cs", "Cc", "Zl", "Zp")),
                min_size=1,
                max_size=40,
            ).filter(lambda t: t.strip() and "-->" not in t and "<" not in t and "&" not in t),
        ),
        min_size=1,
        max_size=15,
    )
)
def test_srt_round_trip_keeps_every_time_exactly(
    rows: list[tuple[int, int, str]],
) -> None:
    def stamp(ms: int) -> str:
        h, rest = divmod(ms, 3_600_000)
        m, rest = divmod(rest, 60_000)
        s, milli = divmod(rest, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{milli:03d}"

    srt = "".join(
        f"{i + 1}\n{stamp(a)} --> {stamp(a + d)}\n{text.strip()}\n\n"
        for i, (a, d, text) in enumerate(rows)
    )
    doc = parse_transcript(srt.encode(), format=TranscriptFormat.SRT)
    assert [(c.start_ms, c.end_ms) for c in doc.cues] == [(a, a + d) for a, d, _ in rows]
    assert [c.text for c in doc.cues] == [text.strip() for _, _, text in rows]
