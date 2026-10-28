"""LNK-001: URLs are found with exact spans and grouped by canonical target."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from knowledge_engine.links.extract import (
    CITATION_METADATA,
    MESSAGE_TEXT,
    canonical_url,
    context,
    find_in_metadata,
    find_in_text,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("See https://example.org/a.", "https://example.org/a"),
        ("(see https://example.org/a)", "https://example.org/a"),
        ("[docs](https://example.org/a)", "https://example.org/a"),
        ("<https://example.org/a>", "https://example.org/a"),
        ("**https://example.org/a**", "https://example.org/a"),
        (
            "Wiki: https://en.wikipedia.org/wiki/Python_(language)!",
            "https://en.wikipedia.org/wiki/Python_(language)",
        ),
        ('"https://example.org/q?a=1&b=2", then', "https://example.org/q?a=1&b=2"),
        ("emoji 🎉 then https://example.org/x, ok", "https://example.org/x"),
        ("HTTP://Example.ORG/Path", "HTTP://Example.ORG/Path"),
    ],
)
def test_spans_select_exactly_the_url(text: str, expected: str) -> None:
    [link] = find_in_text(text)
    assert link.origin == MESSAGE_TEXT
    assert link.span.of(text) == expected == link.original


def test_canonical_form_groups_spellings_of_one_page() -> None:
    a = canonical_url("HTTPS://Example.ORG:443#top")
    b = canonical_url("https://example.org/")
    assert a == b == ("https://example.org/", "example.org")
    # The query is kept exactly: it can point at a different page.
    assert canonical_url("https://example.org/?b=2&a=1") == (
        "https://example.org/?b=2&a=1",
        "example.org",
    )
    assert canonical_url("http://example.org:8080/x") == (
        "http://example.org:8080/x",
        "example.org",
    )
    assert canonical_url("ftp://example.org/") is None
    assert canonical_url("https:///nohost") is None
    assert canonical_url("https://example.org:99999/") is None


def test_no_scheme_no_guess() -> None:
    assert find_in_text("visit example.org or www.example.org") == []


def test_repeated_urls_are_separate_mentions() -> None:
    text = "https://a.org and https://a.org/ again"
    links = find_in_text(text)
    assert [link.span.of(text) for link in links] == ["https://a.org", "https://a.org/"]
    assert {link.canonical_url for link in links} == {"https://a.org/"}


def test_context_is_taken_around_the_span() -> None:
    text = "before https://a.org after"
    [link] = find_in_text(text)
    assert context(text, link.span, width=7) == ("before ", " after")


def test_citation_metadata_urls_by_list_position() -> None:
    message = {
        "metadata": {
            "citations": [
                {"start_ix": 5, "end_ix": 9, "metadata": {"url": "https://a.org/x", "title": "t"}},
                {"metadata": {"type": "file"}},
                "junk",
            ],
            "content_references": [
                {"url": "https://b.org"},
                {"items": [{"url": "https://c.org/1"}, {"title": "no url"}]},
                {"url": "javascript:alert(1)"},
            ],
        }
    }
    links = find_in_metadata(message)
    assert [(link.origin, link.span.start, link.original) for link in links] == [
        (CITATION_METADATA, 0, "https://a.org/x"),
        (CITATION_METADATA, 1, "https://b.org"),
        (CITATION_METADATA, 2, "https://c.org/1"),
    ]
    assert find_in_metadata({"metadata": "odd"}) == []
    assert find_in_metadata(None) == []


@given(
    st.text(alphabet=st.characters(codec="utf-8"), max_size=30),
    st.from_regex(r"https://[a-z]{1,10}\.(org|com)(/[a-z0-9_-]{1,10}){0,3}", fullmatch=True),
    st.sampled_from(["", ".", ",", ")", " ", "!"]),
)
def test_any_url_in_any_prose_is_found_exactly(prefix: str, url: str, suffix: str) -> None:
    text = f"{prefix} {url}{suffix} tail"
    links = [link for link in find_in_text(text) if link.span.start == len(prefix) + 1]
    assert len(links) == 1
    assert links[0].span.of(text) == url
