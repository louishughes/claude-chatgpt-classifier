"""NOTE-037: a digest quote of one trivial word proves nothing, so it is refused."""

from __future__ import annotations

from typing import Any

import pytest

from knowledge_engine.digest.contract import (
    MIN_QUOTE_CHARS,
    MIN_QUOTE_CONTENT_WORDS,
    QUOTE_CHECK_VERSION,
    DigestAnswer,
    is_trivial_quote,
    resolve_digest,
)
from knowledge_engine.domain.enums import Role
from knowledge_engine.extraction.text import ExtractionMessage

CHAT = [
    ExtractionMessage(
        "m1", f"rev_{1:032x}", Role.USER, "I set it up. Use port 8080 and v2.3 of the tool?"
    ),
    ExtractionMessage(
        "m2", f"rev_{2:032x}", Role.ASSISTANT, "Yes. See https://example.test/setup for 5GB."
    ),
]


def _q(message_id: str, text: str) -> dict[str, str]:
    return {"message_id": message_id, "text": text}


def _answer(**changes: Any) -> DigestAnswer:
    good = [_q("m1", "Use port 8080")]
    data: dict[str, Any] = {
        "summary": [{"text": "A synthetic tool was set up.", "quotes": good}],
        "status": {"value": "settled", "quotes": good},
        "intent": {"value": "build", "text": "Set up a tool.", "quotes": good},
    }
    data.update(changes)
    return DigestAnswer.model_validate(data)


@pytest.mark.parametrize("text", ["I", "Yes.", " yes ", "I want", "it", "8080"])
def test_one_trivial_word_is_refused(text: str) -> None:
    assert is_trivial_quote(text)


@pytest.mark.parametrize(
    "text",
    [
        "Use port 8080",  # two content words
        "v2.3",  # an identifier
        "5GB",  # a number with a unit
        "10%",
        "https://example.test/setup",  # a link
        "Reconfigured.",  # one content word, but 12+ characters
    ],
)
def test_a_real_span_or_a_distinctive_token_is_allowed(text: str) -> None:
    assert not is_trivial_quote(text)


def test_both_limits_must_fail_for_a_refusal() -> None:
    assert MIN_QUOTE_CONTENT_WORDS == 2 and MIN_QUOTE_CHARS == 12
    assert not is_trivial_quote("set port")  # two content words, short
    assert not is_trivial_quote("the nightlies")  # one content word, but 13 characters
    assert is_trivial_quote("the nightly")  # one content word and 11 characters


def test_an_item_whose_only_quote_is_trivial_is_dropped_with_a_flag() -> None:
    insights = [
        {"text": "The user agreed.", "quotes": [_q("m2", "Yes.")]},
        {"text": "The user set it up.", "quotes": [_q("m1", "I")]},
        {"text": "Version and link given.", "quotes": [_q("m1", "v2.3"), _q("m2", "5GB")]},
    ]
    digest = resolve_digest(_answer(insights=insights), CHAT)

    assert [i.text for i in digest.insights] == ["Version and link given."]
    reason = f"quote too short to prove anything ({QUOTE_CHECK_VERSION})"
    assert [(f.field, f.index, f.reason) for f in digest.flags] == [
        ("insights", 0, reason),
        ("insights", 1, reason),
    ]


def test_one_trivial_quote_sinks_the_item_like_a_missing_one() -> None:
    topics = [{"text": "port", "quotes": [_q("m1", "Use port 8080"), _q("m2", "Yes.")]}]
    digest = resolve_digest(_answer(topics=topics), CHAT)

    assert digest.topics == ()
    assert "too short" in digest.flags[0].reason


def test_a_missing_quote_still_says_not_found() -> None:
    # The length rule only runs on quotes that were found: "No." is short and
    # also not in the chat, and the reason must say what is really wrong.
    topics = [{"text": "x", "quotes": [_q("m1", "No.")]}]
    digest = resolve_digest(_answer(topics=topics), CHAT)

    assert digest.flags[0].reason == "quote not found in the cited message"
