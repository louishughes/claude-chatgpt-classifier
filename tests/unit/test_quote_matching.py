"""LEG-004: finding a cited quote in real text, and only the real one."""

from __future__ import annotations

import pytest

from knowledge_engine.graph.offsets import OffsetError, Span, find_quote, normalise_for_match


def _found(text: str, quote: str) -> list[str]:
    return [s.of(text) for s in find_quote(text, quote)]


def test_exact_quotes_still_match_exactly() -> None:
    assert find_quote("Synthetic: use cedar.", "use cedar") == [Span(11, 20)]


@pytest.mark.parametrize(
    ("text", "quote", "original"),
    [
        ("Synthetic: it’s Anna’s shed.", "it's Anna's shed", "it’s Anna’s shed"),  # possessive
        ("Synthetic: it's Anna's shed.", "it’s Anna’s shed", "it's Anna's shed"),
        ("Synthetic: he said “go”.", 'he said "go"', "he said “go”"),  # curly vs straight
        ("Synthetic: ‘fine’ then", "'fine' then", "‘fine’ then"),
    ],
)
def test_quote_styles_and_possessives(text: str, quote: str, original: str) -> None:
    assert _found(text, quote) == [original]


def test_line_endings_match_and_are_preserved_on_read_back() -> None:
    text = "Synthetic one.\r\nSynthetic two.\rSynthetic three."
    [span] = find_quote(text, "one.\nSynthetic two.\nSynthetic")
    assert span.of(text) == "one.\r\nSynthetic two.\rSynthetic"  # original endings kept
    folded, origin = normalise_for_match(text)
    assert "\r" not in folded and len(origin) == len(folded)


def test_escaped_newlines_in_the_quote() -> None:
    text = "Synthetic first line\nsecond line"
    assert _found(text, "first line\\nsecond line") == ["first line\nsecond line"]
    # Text that really contains a backslash-n is still matched literally.
    code = r"print('Synthetic\n')"
    assert _found(code, r"Synthetic\n") == [r"Synthetic\n"]


@pytest.mark.parametrize(
    ("text", "quote"),
    [
        ("Synthetic: concatenate them.", "cat"),
        ("Synthetic: I chose cedar.", "chose ced"),
        ("Synthetic: preprocessing", "processing"),
        ("Synthetic: it’s Anna’s", "Ann"),
        ("Synthetic: use cedar.", "use  cedar"),  # spacing is not folded
        ("Synthetic: Use Cedar.", "use cedar"),  # nor case
    ],
)
def test_partial_words_and_other_differences_never_match(text: str, quote: str) -> None:
    assert find_quote(text, quote) == []


def test_empty_quote_is_refused() -> None:
    with pytest.raises(OffsetError):
        find_quote("Synthetic", "")
