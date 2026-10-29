"""NOTE-032: open questions reconciled across the parts of a long chat.

Each case is a synthetic chat split into parts by hand. The clean review's
probes are kept here as regression cases: a hedged "yes, but", a bare
"perfect" or "ok", a reply about another offer, and questions that differ
only by a number or a negation.
"""

from __future__ import annotations

from collections.abc import Sequence

from knowledge_engine.digest.contract import DigestAnswer
from knowledge_engine.digest.questions import Reconciled, question_key, reconcile_parts
from knowledge_engine.domain.enums import Role
from knowledge_engine.extraction.text import ExtractionMessage


def _messages(turns: Sequence[tuple[str, str]]) -> list[ExtractionMessage]:
    roles = {"u": Role.USER, "a": Role.ASSISTANT}
    return [
        ExtractionMessage(f"m{i}", f"rev_{i:032d}", roles[r], text)
        for i, (r, text) in enumerate(turns)
    ]


def _answer(
    messages: list[ExtractionMessage], questions: Sequence[tuple[str, int]]
) -> DigestAnswer:
    first = {"message_id": messages[0].native_id, "text": messages[0].text.split()[0]}
    return DigestAnswer.model_validate(
        {
            "summary": [{"text": "Synthetic summary.", "quotes": [first]}],
            "status": {"value": "open", "quotes": [first]},
            "intent": {"value": "plan", "text": "Plan.", "quotes": [first]},
            "open_questions": [
                {
                    "text": text,
                    "quotes": [
                        {"message_id": messages[i].native_id, "text": messages[i].text.split()[0]}
                    ],
                }
                for text, i in questions
            ],
        }
    )


def _run(
    turns: Sequence[tuple[str, str]],
    per_part: Sequence[Sequence[tuple[str, int]]],
    split: Sequence[range],
) -> Reconciled:
    messages = _messages(turns)
    parts = [tuple(messages[i].native_id for i in r) for r in split]
    return reconcile_parts([_answer(messages, q) for q in per_part], parts, messages)


def _open(result: Reconciled) -> list[str]:
    return [q.text for a in result.answers for q in a.open_questions]


# Part 1 holds the offer; the reply is the first message of part 2.
HOTEL = [("u", "Plan my synthetic trip."), ("a", "Want me to book the hotel?")]
TWO = [range(0, 2), range(1, 3)]


def test_a_later_part_saying_yes_answers_the_offer() -> None:
    result = _run(
        [*HOTEL, ("u", "Yes, go ahead.")], [[("Should the assistant book the hotel?", 1)], []], TWO
    )
    assert _open(result) == []
    [found] = result.answered
    assert found.reply.native_id == "m2"
    assert found.reply.text[found.span.start : found.span.end] == "Yes"


def test_a_one_part_chat_is_left_as_the_model_wrote_it() -> None:
    messages = _messages([*HOTEL, ("u", "Yes, go ahead.")])
    answer = _answer(messages, [("Book the hotel?", 1), ("Book the hotel?", 1)])
    result = reconcile_parts([answer], [tuple(m.native_id for m in messages)], messages)
    assert result.answers == [answer] and result.answered == [] and result.joined == {}


def test_a_reply_inside_the_questions_own_part_is_left_to_that_part() -> None:
    turns = [*HOTEL, ("u", "Yes, go ahead."), ("a", "Booked."), ("u", "Thanks.")]
    result = _run(
        turns, [[("Should the assistant book the hotel?", 1)], []], [range(0, 3), range(2, 5)]
    )
    assert _open(result) == ["Should the assistant book the hotel?"]


def test_hedged_or_bare_replies_never_count() -> None:
    for reply in (
        "Yes but what about the flights?",
        "Perfect, thanks!",
        "OK so how long will it take?",
        "Sure.",
        "Thanks!",
        "Yes, the hotel?",
    ):
        result = _run(
            [*HOTEL, ("u", reply)], [[("Should the assistant book the hotel?", 1)], []], TWO
        )
        assert _open(result) == ["Should the assistant book the hotel?"], reply


def test_a_yes_to_one_of_two_offers_answers_only_that_one() -> None:
    turns = [
        ("u", "Synthetic letter?"),
        ("a", "Want me to draft the letter? Or should I summarise the case file?"),
        ("u", "Yes, draft the letter."),
    ]
    asked = [
        ("Should the assistant draft the letter?", 1),
        ("Should the assistant summarise the case file?", 1),
    ]
    result = _run(turns, [asked, []], TWO)
    assert _open(result) == ["Should the assistant summarise the case file?"]
    assert [a.question.text for a in result.answered] == ["Should the assistant draft the letter?"]


def test_a_bare_yes_after_two_offers_answers_neither() -> None:
    turns = [
        ("u", "Synthetic letter?"),
        ("a", "Draft the letter? Or summarise the case file?"),
        ("u", "Yes."),
    ]
    asked = [("Draft the letter?", 1), ("Summarise the case file?", 1)]
    assert len(_open(_run(turns, [asked, []], TWO))) == 2


def test_a_reply_about_another_offer_does_not_answer_this_one() -> None:
    turns = [
        ("u", "Synthetic sales."),
        ("a", "Want a chart of sales?"),
        ("a", "Also want me to email the board?"),
        ("u", "No thanks to the chart."),
    ]
    asked = [("Should the assistant email the board?", 2), ("Should the assistant chart sales?", 1)]
    result = _run(turns, [asked, []], [range(0, 3), range(2, 4)])
    assert _open(result) == ["Should the assistant email the board?"]


def test_a_later_reply_needs_two_shared_words() -> None:
    turns = [
        ("u", "Synthetic tenancy."),
        ("a", "Want me to email the landlord about the deposit?"),
        ("u", "Tell me about tenancy law."),
        ("a", "Do you want the deposit rules?"),
        ("u", "Yes, the deposit rules please."),
    ]
    asked = [("Should the assistant email the landlord about the deposit?", 1)]
    result = _run(turns, [asked, []], [range(0, 2), range(1, 5)])
    assert _open(result) == ["Should the assistant email the landlord about the deposit?"]


def test_numbers_negations_and_empty_keys_keep_questions_apart() -> None:
    assert question_key("Use port 8080?") != question_key("Use port 9090?")
    assert question_key("Keep the old API?") != question_key("Not keep the old API?")
    turns = [("u", "Why? How?"), ("a", "Port 8080 or port 9090? Keep or not keep the API?")]
    first = [("Use port 8080?", 1), ("Keep the old API?", 1), ("Why?", 0)]
    second = [("Use port 9090?", 1), ("Not keep the old API?", 1), ("How?", 0)]
    result = _run(turns, [first, second], [range(0, 2), range(0, 2)])
    assert len(_open(result)) == 6 and result.joined == {}


def test_the_same_question_from_two_parts_is_joined_but_never_across_roles() -> None:
    turns = [("u", "Should I sell the synthetic car?"), ("a", "Do you want me to list the car?")]
    first = [("Should the user sell the car?", 0), ("Should the assistant list the car?", 1)]
    second = [("Should the user sell the car", 1), ("Should the assistant list the car", 1)]
    result = _run(turns, [first, second], [range(0, 2), range(0, 2)])
    # The assistant-cited copy of the user's question stays separate.
    assert _open(result) == [
        "Should the user sell the car?",
        "Should the assistant list the car?",
        "Should the user sell the car",
    ]
    assert result.joined == {"Should the assistant list the car?": 1}
    joined = result.answers[0].open_questions[1]
    assert len(joined.quotes) == 1  # both cite the same words of the same message


def test_questions_within_one_part_are_not_joined() -> None:
    turns = [("u", "Synthetic."), ("a", "Want me to book the hotel?")]
    asked = [("Book the hotel?", 1), ("Book the hotel?", 1)]
    result = _run(turns, [asked, []], TWO[:1] + [range(1, 2)])
    assert len(_open(result)) == 2
