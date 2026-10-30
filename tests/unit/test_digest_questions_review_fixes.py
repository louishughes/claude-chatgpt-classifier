"""NOTE-038 and NOTE-039: fixes from the clean review of NOTE-032.

Each test is one probe from that review, run against the real code:
a duplicate with a bad quote must not delete the real question, symbols
like "C++" / "C#" keep questions apart, a joined question stays within the
quote limit, a "yes" to one offer doesn't close a different question, and
a mixed reply ("Yes, no hotel") answers nothing.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from knowledge_engine.digest.contract import (
    MAX_QUOTES_PER_ITEM,
    DigestAnswer,
    resolve_digest,
)
from knowledge_engine.digest.questions import Reconciled, question_key, reconcile_parts
from knowledge_engine.digest.stage import _record_reconciled, merge_answers
from knowledge_engine.domain.enums import Role
from knowledge_engine.extraction.text import ExtractionMessage


def _messages(turns: Sequence[tuple[str, str]]) -> list[ExtractionMessage]:
    roles = {"u": Role.USER, "a": Role.ASSISTANT}
    return [
        ExtractionMessage(f"m{i}", f"rev_{i:032d}", roles[r], text)
        for i, (r, text) in enumerate(turns)
    ]


def _answer(
    messages: list[ExtractionMessage], questions: Sequence[tuple[str, str, str]]
) -> DigestAnswer:
    """An answer whose open questions are (text, cited message ID, quote)."""
    first = {"message_id": messages[0].native_id, "text": " ".join(messages[0].text.split()[:4])}
    return DigestAnswer.model_validate(
        {
            "summary": [{"text": "Synthetic summary.", "quotes": [first]}],
            "status": {"value": "open", "quotes": [first]},
            "intent": {"value": "plan", "text": "Plan.", "quotes": [first]},
            "open_questions": [
                {"text": text, "quotes": [{"message_id": mid, "text": quote}]}
                for text, mid, quote in questions
            ],
        }
    )


def _open(result: Reconciled) -> list[str]:
    return [q.text for a in result.answers for q in a.open_questions]


@pytest.mark.parametrize(
    ("one", "two"),
    [
        ("Should I learn C++?", "Should I learn C#?"),
        ("Raise the price by $50?", "Raise the price by 50%?"),
        ("Use -5 degrees?", "Use 5 degrees?"),
        ("Is x > y?", "Is x < y?"),
        ("Set limit to 1,500?", "Set limit to 1.500?"),
        ("Is it 10²?", "Is it 102?"),
        ("Should I use .NET?", "Should I use NET?"),
        ("Is it A+ or A-?", "Is it A- or A+?"),
    ],
)
def test_symbols_that_change_the_meaning_keep_questions_apart(one: str, two: str) -> None:
    assert question_key(one) != question_key(two)


def test_the_same_question_still_has_the_same_key() -> None:
    assert question_key("Book the hotel?") == question_key("Book the hotel")
    assert question_key("Can’t I go?") == question_key("Can't I go?")


def test_c_plus_plus_and_c_sharp_from_two_parts_stay_two_questions() -> None:
    m = _messages(
        [("u", "Should I learn C++?"), ("a", "Fine."), ("u", "Should I learn C#?"), ("a", "Ok.")]
    )
    answers = [
        _answer(m, [("Should I learn C++?", "m0", "learn C++")]),
        _answer(m, [("Should I learn C#?", "m2", "learn C#")]),
    ]
    result = reconcile_parts(answers, [("m0", "m1"), ("m2", "m3")], m)
    assert _open(result) == ["Should I learn C++?", "Should I learn C#?"]


def test_a_repeat_with_a_bad_quote_does_not_delete_the_real_question() -> None:
    m = _messages(
        [("u", "Should I learn C++?"), ("a", "Fine."), ("u", "Again: C++?"), ("a", "Ok.")]
    )
    answers = [
        _answer(m, [("Should I learn C++?", "m0", "learn C++")]),
        _answer(m, [("Should I learn C++?", "m2", "NOT IN THE MESSAGE")]),
    ]
    result = reconcile_parts(answers, [("m0", "m1"), ("m2", "m3")], m)
    digest = resolve_digest(merge_answers(result.answers), m)
    assert [q.text for q in digest.open_questions] == ["Should I learn C++?"]
    assert digest.open_questions[0].message_ids == ("m0",)


def test_a_question_joined_from_many_parts_keeps_at_most_the_quote_limit() -> None:
    turns: list[tuple[str, str]] = []
    for i in range(MAX_QUOTES_PER_ITEM + 1):
        turns += [("u", f"Synthetic {i}: shall we paint the fence?"), ("a", "Maybe.")]
    m = _messages(turns)
    parts = [(f"m{2 * i}", f"m{2 * i + 1}") for i in range(MAX_QUOTES_PER_ITEM + 1)]
    answers = [
        _answer(m, [("Shall we paint the fence?", f"m{2 * i}", "paint the fence")])
        for i in range(MAX_QUOTES_PER_ITEM + 1)
    ]
    result = reconcile_parts(answers, parts, m)
    [question] = [q for a in result.answers for q in a.open_questions]
    assert len(question.quotes) == MAX_QUOTES_PER_ITEM
    assert question.quotes[-1].message_id == f"m{2 * MAX_QUOTES_PER_ITEM}"  # the latest kept
    DigestAnswer.model_validate(merge_answers(result.answers).model_dump())  # still valid


COUNCIL = (
    "Shall I draft the letter to the council? It needs to say whether the deadline "
    "is Friday, which you haven't confirmed."
)


@pytest.mark.parametrize("reply", ["Yes please.", "Go ahead."])
def test_a_yes_to_one_offer_does_not_close_a_different_question(reply: str) -> None:
    m = _messages([("u", "Synthetic council letter."), ("a", COUNCIL), ("u", reply)])
    answers = [
        _answer(m, [("Is the council letter deadline Friday?", "m1", "deadline")]),
        _answer(m, []),
    ]
    result = reconcile_parts(answers, [("m0", "m1"), ("m1", "m2")], m)
    assert _open(result) == ["Is the council letter deadline Friday?"]
    assert result.answered == []


def test_the_offer_itself_is_still_answered_by_that_yes() -> None:
    m = _messages([("u", "Synthetic council letter."), ("a", COUNCIL), ("u", "Yes please.")])
    question = "Should the assistant draft the letter to the council?"
    answers = [_answer(m, [(question, "m1", "draft the letter")]), _answer(m, [])]
    result = reconcile_parts(answers, [("m0", "m1"), ("m1", "m2")], m)
    assert [a.question.text for a in result.answered] == [question]


@pytest.mark.parametrize(
    "reply",
    [
        "Yes, no hotel",
        "Yes — no hotel",
        "Yes. No.",
        "No thanks, book it",
        "No thanks — book the hotel",
    ],
)
def test_a_mixed_reply_answers_nothing(reply: str) -> None:
    m = _messages(
        [("u", "Plan my synthetic trip."), ("a", "Want me to book the hotel?"), ("u", reply)]
    )
    answers = [
        _answer(m, [("Should the assistant book the hotel?", "m1", "book the hotel")]),
        _answer(m, []),
    ]
    result = reconcile_parts(answers, [("m0", "m1"), ("m1", "m2")], m)
    assert _open(result) == ["Should the assistant book the hotel?"]


def test_an_answered_question_with_a_bad_quote_still_leaves_a_flag() -> None:
    m = _messages(
        [
            ("u", "Plan my synthetic trip."),
            ("a", "Want me to book the hotel?"),
            ("u", "Yes, go ahead."),
        ]
    )
    answers = [
        _answer(m, [("Should the assistant book the hotel?", "m1", "Want me to book a villa")]),
        _answer(m, []),
    ]
    result = reconcile_parts(answers, [("m0", "m1"), ("m1", "m2")], m)
    assert len(result.answered) == 1
    digest = _record_reconciled(resolve_digest(merge_answers(result.answers), m), result, m)
    assert digest.resolved_questions == ()
    assert [f.field for f in digest.flags] == ["resolved_questions"]
    assert "quote is not in the cited message" in digest.flags[0].reason


# The second clean review (of this fix) found these; each is one of its probes.


@pytest.mark.parametrize(
    ("one", "two"),
    [
        ("Book the hotel? 🙂", "Book the hotel?"),
        ("**Book the hotel?**", "Book the hotel?"),
        ("Book hotel — today?", "Book hotel today?"),
        ("Is it «fine»?", "Is it fine?"),
        ("Book The Hotel?", "Book the hotel?"),
    ],
)
def test_wording_that_does_not_change_the_meaning_still_joins(one: str, two: str) -> None:
    assert question_key(one) == question_key(two)


def test_a_repeat_with_a_bad_quote_still_counts_as_listing_the_question() -> None:
    # Part 2 saw the user's reply and still listed the question (with a bad
    # quote), so that reply must not close it.
    m = _messages(
        [
            ("u", "Plan my synthetic trip."),
            ("a", "Want me to book the hotel?"),
            ("u", "Yes, book the hotel."),
            ("a", "Before I book the hotel: which dates?"),
            ("u", "Synthetic dates."),
        ]
    )
    question = "Should the assistant book the hotel?"
    answers = [
        _answer(m, [(question, "m1", "book the hotel")]),
        _answer(m, [(question, "m3", "book the villa")]),
    ]
    result = reconcile_parts(answers, [("m0", "m1"), ("m2", "m3", "m4")], m)
    assert _open(result) == [question]
    assert result.answered == []


@pytest.mark.parametrize("reply", ["No need to book it", "No need to book the hotel"])
def test_no_need_to_do_it_is_a_clean_decline(reply: str) -> None:
    m = _messages(
        [("u", "Plan my synthetic trip."), ("a", "Want me to book the hotel?"), ("u", reply)]
    )
    answers = [
        _answer(m, [("Should the assistant book the hotel?", "m1", "book the hotel")]),
        _answer(m, []),
    ]
    result = reconcile_parts(answers, [("m0", "m1"), ("m1", "m2")], m)
    assert _open(result) == []


def test_the_digest_wording_does_not_hide_an_offer() -> None:
    m = _messages(
        [("u", "Synthetic code."), ("a", "Would you like a Python version?"), ("u", "Yes please.")]
    )
    question = "Does the user want a Python version?"
    answers = [_answer(m, [(question, "m1", "Python version")]), _answer(m, [])]
    result = reconcile_parts(answers, [("m0", "m1"), ("m1", "m2")], m)
    assert [a.question.text for a in result.answered] == [question]
