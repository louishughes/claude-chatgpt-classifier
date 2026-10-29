"""NOTE-032: open questions reconciled across the parts of a long chat.

Each case is a synthetic chat split into parts by hand. The two clean
reviews' probes are kept here as regression cases: hedged, sarcastic or
off-topic replies, a part that saw the reply and still listed the question,
and questions that differ by a negation, stance, action or number.
"""

from __future__ import annotations

from collections.abc import Sequence

from knowledge_engine.digest.contract import DigestAnswer, DigestQuote
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
        ("u", "No thanks to the sales chart."),
    ]
    asked = [("Should the assistant email the board?", 2), ("Should the assistant chart sales?", 1)]
    result = _run(turns, [asked, []], [range(0, 3), range(2, 4)])
    assert _open(result) == ["Should the assistant email the board?"]


def test_only_the_very_next_user_turn_can_answer() -> None:
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


KEEP_REPLIES = [
    "Yeah right.",
    "Yeah right, book the hotel, as if.",
    "Yeah, right, like I'd trust you to book the hotel.",
    "Yes, the hotel is too expensive.",
    "Yes the hotel looks nice in the photos.",
    "Yes, I love that hotel's pool.",
    "No, the hotel can wait while I think.",
    "Yep, hotel.",
    "Yes, I'll book the hotel myself later maybe.",
    "Do it later, hotel first needs thinking.",
    "Not now, hotel.",
    "Yes. Wait, actually no.",
    "Yes, after I check the hotel reviews.",
    "Yes, if the hotel is cheap.",
    "Yes, unless it rains.",
    "Yes when you can.",
    "Yesterday I booked it.",
]


def test_only_a_plain_yes_or_no_closes_an_offer() -> None:
    question = [[("Should the assistant book the hotel?", 1)], []]
    for reply in KEEP_REPLIES:
        assert _open(_run([*HOTEL, ("u", reply)], question, TWO)) != [], reply
    for reply in ("Yes!", "yes.", "Yes please.", "Yes — the hotel.", "No thanks.", "Go ahead."):
        assert _open(_run([*HOTEL, ("u", reply)], question, TWO)) == [], reply


def test_a_part_that_saw_the_reply_and_still_listed_the_question_wins() -> None:
    q = "Should the assistant book the hotel?"
    turns = [
        ("u", "Plan trip."),
        ("a", "Want me to book the hotel?"),
        ("u", "Other topic."),
        ("a", "Want me to book the hotel?"),
        ("u", "Yes, book the hotel."),
    ]
    result = _run(turns, [[(q, 1)], [(q, 3)]], [range(0, 2), range(1, 5)])
    assert _open(result) == [q] and result.answered == [] and result.joined == {q: 1}


def test_a_reply_in_the_listing_parts_overlap_is_left_to_that_part() -> None:
    q = "Should the assistant book the hotel?"
    turns = [*HOTEL, ("u", "Yes, go ahead."), ("a", "Booked.")]
    assert _open(_run(turns, [[], [(q, 1)]], [range(0, 1), range(1, 4)])) == [q]


DIFFERENT = [
    ("Can the app run offline?", "Can't the app run offline?"),
    (
        "Does the synthetic script delete old backups?",
        "Doesn't the synthetic script delete old backups?",
    ),
    ("Do you prefer the toll road route?", "Do you avoid the toll road route?"),
    (
        "Should the assistant draft the synthetic letter to the council about the hedge?",
        "Should the assistant send the synthetic letter to the council about the hedge?",
    ),
    ("Use port ٨٠٨٠ for the server?", "Use port ٩٠٩٠ for the server?"),
    ("Use two replicas for the database cluster?", "Use three replicas for the database cluster?"),
    ("Is nothing left in the synthetic budget?", "Is something left in the synthetic budget?"),
    ("Keep the old API?", "Remove the old API?"),
]


def test_questions_join_only_on_identical_keys() -> None:
    for a, b in DIFFERENT:
        result = _run(
            [("u", "Synthetic."), ("a", f"{a} {b}")], [[(a, 1)], [(b, 1)]], [range(0, 2)] * 2
        )
        assert result.joined == {}, (a, b)
    assert question_key("Use port ٨٠٨٠?") == question_key("Use port 8080?")


def test_odd_text_and_mismatched_parts_never_crash_or_drop() -> None:
    turns = [
        ("u", "Synthetic 🙂."),
        ("a", "Want me to book the hotel? 的问题？"),
        ("u", "Yes, book the hotel."),
    ]
    for text in ("?", "...", "的问题？", "¿Reservar el hotel?", "🙂?"):
        result = _run(turns, [[(text, 1)], [(text, 1)]], TWO)
        assert _open(result), text
    messages = _messages([*HOTEL, ("u", "Yes, book the hotel.")])
    asked = _answer(messages, [("Should the assistant book the hotel?", 1)])
    for parts in ([(), ()], [("zz",), ("yy",)]):
        result = reconcile_parts([asked, _answer(messages, [])], parts, messages)
        assert _open(result) == ["Should the assistant book the hotel?"], parts


MOVING = [("u", "Synthetic: I'm moving flat and the landlord is slow about the deposit.")]
SPLIT = [range(0, 4), range(3, 6)]


def test_word_order_pronouns_modals_and_conjunctions_keep_questions_apart() -> None:
    turns = [
        *MOVING,
        ("a", "Here's a plan."),
        ("u", "Q one?"),
        ("a", "Depends."),
        ("u", "Q two?"),
        ("a", "Ok."),
    ]
    pairs = [
        (
            "Should I move money from savings to checking?",
            "Should I move money from checking to savings?",
        ),
        ("Should I call the letting agent?", "Should they call the letting agent?"),
        ("Can I cancel the tenancy early?", "Should I cancel the tenancy early?"),
        ("Should I use this removal company?", "Should I use that removal company?"),
        (
            "Should I pay the deposit and the first month?",
            "Should I pay the deposit or the first month?",
        ),
        ("Was the deposit protected?", "Will the deposit be protected?"),
    ]
    for a, b in pairs:
        result = _run(turns, [[(a, 2)], [(b, 4)]], SPLIT)
        assert _open(result) == [a, b] and result.joined == {}, (a, b)
    assert question_key("Should the user sell a car?") == question_key("should user sell car")


def test_a_yes_after_two_assistant_messages_answers_neither_offer() -> None:
    turns = [
        *MOVING,
        ("a", "Want me to draft the email to your landlord about the deposit?"),
        ("a", "Or I could look up the deposit protection rules. Should I check those?"),
        ("u", "Yes please."),
    ]
    asked = [
        ("Should the assistant draft the email to the landlord?", 1),
        ("Should the assistant check the deposit protection rules?", 2),
    ]
    result = _run(turns, [asked, []], [range(0, 3), range(2, 4)])
    assert len(_open(result)) == 2 and result.answered == []


def test_an_offer_of_a_choice_is_not_closed_by_a_bare_yes() -> None:
    turns = [
        *MOVING,
        ("a", "I can draft the email to your landlord, or I can write a formal letter instead?"),
        ("u", "Yes please."),
    ]
    asked = [("Should the assistant draft the email to the landlord?", 1)]
    assert len(_open(_run(turns, [asked, []], [range(0, 2), range(1, 3)]))) == 1


def test_a_users_own_question_is_never_closed_by_a_yes() -> None:
    turns = [
        *MOVING,
        ("u", "Is my deposit legally protected? I never got a certificate."),
        ("a", "Not sure. Want me to explain how to check?"),
        ("u", "Yes"),
    ]
    # Cited only at the assistant's reply, but it isn't the offer that was made.
    only_assistant = [("Is the deposit legally protected?", 2)]
    assert len(_open(_run(turns, [only_assistant, []], [range(0, 3), range(2, 4)]))) == 1
    # Cited at the user's own message as well: it is the user's question.
    messages = _messages(turns)
    both = _answer(messages, [("Should the assistant explain how to check?", 2)])
    item = both.open_questions[0]
    mixed = item.model_copy(
        update={"quotes": [*item.quotes, DigestQuote(message_id="m1", text="Is")]}
    )
    both = both.model_copy(update={"open_questions": [mixed]})
    parts = [tuple(m.native_id for m in messages[:3]), tuple(m.native_id for m in messages[2:])]
    result = reconcile_parts([both, _answer(messages, [])], parts, messages)
    assert _open(result) == ["Should the assistant explain how to check?"]


def test_a_single_offer_is_closed_by_a_plain_yes() -> None:
    offer = (
        "a",
        "The deposit is due back within 10 days. Would you like me to draft a polite email "
        "to your landlord asking for it?",
    )
    asked = [("Should the assistant draft an email to the landlord?", 1)]
    for reply in (
        "Yes, please do that.",
        "Yes please",
        "Yes - draft it.",
        "Do it, landlord email.",
    ):
        result = _run([*MOVING, offer, ("u", reply)], [asked, []], [range(0, 2), range(1, 3)])
        assert _open(result) == [], reply
    for reply in (
        "Sure, go for it.",
        "Yeah do it",
        "Ok",
        "Yep, that would be great thanks!",
        "Yes please, that would be really helpful.",
        "Yes, not the landlord though.",
        "No thanks, I'll draft the email to the landlord myself.",
        "Yes yes I know, the email to the landlord is overdue.",
    ):
        result = _run([*MOVING, offer, ("u", reply)], [asked, []], [range(0, 2), range(1, 3)])
        assert _open(result) != [], reply
