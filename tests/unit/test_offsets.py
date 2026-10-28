"""NRM-003: emoji, newlines and Unicode round-trip substrings exactly."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from knowledge_engine.graph.offsets import (
    OffsetError,
    Span,
    cite,
    find_all,
    from_utf8,
    from_utf16,
    quote_hash,
    to_utf8,
    to_utf16,
    verify,
)

TEXT = "Synthetic: café 👩‍💻 ok\r\nline two 🎉\n\nend"


def test_emoji_and_newlines_select_exactly() -> None:
    start = TEXT.index("👩")
    span = Span(start, TEXT.index(" ok"))
    assert span.of(TEXT) == "👩‍💻"  # a ZWJ sequence: three code points, kept whole
    assert Span(TEXT.index("\r"), TEXT.index("line")).of(TEXT) == "\r\n"


def test_cite_and_verify() -> None:
    span = find_all(TEXT, "line two 🎉")[0]
    quote, digest = cite(TEXT, span)

    assert quote == "line two 🎉"
    assert verify(TEXT, span, digest)
    assert not verify(TEXT.replace("two", "2"), span, digest)
    assert not verify(TEXT[:10], span, digest)


def test_utf16_and_utf8_conversions_match_their_encodings() -> None:
    span = find_all(TEXT, "🎉")[0]
    utf16 = to_utf16(TEXT, span)
    utf8 = to_utf8(TEXT, span)

    assert TEXT.encode("utf-16-le")[utf16.start * 2 : utf16.end * 2].decode("utf-16-le") == "🎉"
    assert TEXT.encode("utf-8")[utf8.start : utf8.end].decode("utf-8") == "🎉"
    assert from_utf16(TEXT, utf16) == span
    assert from_utf8(TEXT, utf8) == span


def test_boundaries_inside_a_character_are_refused() -> None:
    party = TEXT.index("🎉")
    utf8_start = to_utf8(TEXT, Span(party, party)).start
    with pytest.raises(OffsetError):
        from_utf8(TEXT, Span(utf8_start + 1, utf8_start + 4))
    utf16_start = to_utf16(TEXT, Span(party, party)).start
    with pytest.raises(OffsetError):
        from_utf16(TEXT, Span(utf16_start + 1, utf16_start + 2))


def test_bad_spans_are_refused() -> None:
    with pytest.raises(OffsetError):
        Span(3, 2)
    with pytest.raises(OffsetError):
        Span(0, len(TEXT) + 1).of(TEXT)
    with pytest.raises(OffsetError):
        find_all(TEXT, "")


def test_quote_hash_is_versioned_and_exact() -> None:
    assert quote_hash("a") != quote_hash("a ")
    assert quote_hash("é") != quote_hash("é")  # no silent normalisation
    assert len(quote_hash("")) == 64


@given(st.text(), st.data())
def test_any_span_round_trips_through_every_encoding(text: str, data: st.DataObject) -> None:
    start = data.draw(st.integers(0, len(text)))
    end = data.draw(st.integers(start, len(text)))
    span = Span(start, end)

    assert from_utf16(text, to_utf16(text, span)) == span
    assert from_utf8(text, to_utf8(text, span)) == span
    quote, digest = cite(text, span)
    assert quote == text[start:end] and verify(text, span, digest)
