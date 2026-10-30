"""NOTE-002: the conversation digest contract refuses what isn't backed by the chat."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from knowledge_engine.digest.contract import (
    FIELD_PROVENANCE,
    ChatStatus,
    DigestAnswer,
    Intent,
    Provenance,
    resolve_digest,
)
from knowledge_engine.domain.enums import Role
from knowledge_engine.extraction.text import ExtractionMessage
from knowledge_engine.graph.offsets import Span, verify

CHAT = [
    ExtractionMessage("m1", f"rev_{1:032x}", Role.USER, "I want a cheap NAS for photo backups."),
    ExtractionMessage(
        "m2", f"rev_{2:032x}", Role.ASSISTANT, "A two-bay unit with mirrored drives fits."
    ),
    ExtractionMessage("m3", f"rev_{3:032x}", Role.USER, "Which drives are quiet enough?"),
]


def _q(message_id: str, text: str) -> dict[str, str]:
    return {"message_id": message_id, "text": text}


def _answer(**changes: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "summary": [
            {"text": "Louis looked for a cheap NAS.", "quotes": [_q("m1", "a cheap NAS")]},
            {
                "text": "A mirrored two-bay unit was suggested.",
                "quotes": [_q("m2", "two-bay unit")],
            },
        ],
        "purpose": {"text": "Back up photos.", "quotes": [_q("m1", "photo backups")]},
        "status": {"value": "open", "quotes": [_q("m3", "Which drives are quiet enough?")]},
        "intent": {
            "value": "decide",
            "text": "Pick hardware.",
            "quotes": [_q("m1", "I want a cheap NAS")],
        },
        "topics": [{"text": "NAS", "quotes": [_q("[m:m1]", "cheap NAS")]}],
        "open_questions": [
            {"text": "Which drives are quiet?", "quotes": [_q("m3", "quiet enough")]}
        ],
        "next_steps": [{"text": "Compare drive noise.", "quotes": [_q("m3", "Which drives")]}],
    }
    data.update(changes)
    return data


def test_a_good_answer_resolves_to_exact_evidence() -> None:
    digest = resolve_digest(DigestAnswer.model_validate(_answer()), CHAT)

    assert digest.usable and not digest.flags
    assert len(digest.summary) == 2
    assert digest.status is ChatStatus.OPEN and digest.intent is Intent.DECIDE
    # The [m:...] tag form of a message ID is accepted and stripped.
    assert digest.topics[0].message_ids == ("m1",)
    evidence = digest.summary[0].evidence[0]
    assert evidence.revision_id == CHAT[0].revision_id and evidence.actor is Role.USER
    assert verify(CHAT[0].text, Span(evidence.start, evidence.end), evidence.quote_sha256)


@pytest.mark.parametrize(
    "bad",
    [
        {"mood": "happy"},  # invented top-level field
        {"summary": [{"text": "x", "quotes": [_q("m1", "NAS")], "confidence": 0.9}]},
        {"summary": [{"text": "No citation.", "quotes": []}]},  # uncited item
        {"summary": []},  # no summary at all
        {"status": {"value": "certified", "quotes": [_q("m1", "NAS")]}},  # unknown status
        {"summary": [{"text": "x", "quotes": [_q("m1", "y" * 301)]}]},  # quote too long
    ],
)
def test_the_schema_refuses_invented_or_uncited_content(bad: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        DigestAnswer.model_validate(_answer(**bad))


def test_a_quote_not_in_the_chat_drops_the_whole_item_and_flags_it() -> None:
    insights = [
        # One good quote and one invented one: the item still goes.
        {"text": "Noise matters.", "quotes": [_q("m3", "quiet enough"), _q("m3", "silent drives")]},
        {"text": "Mirroring protects photos.", "quotes": [_q("m2", "mirrored drives")]},
    ]
    digest = resolve_digest(DigestAnswer.model_validate(_answer(insights=insights)), CHAT)

    assert [i.text for i in digest.insights] == ["Mirroring protects photos."]
    assert [(f.field, f.index, f.reason) for f in digest.flags] == [
        ("insights", 0, "quote not found in the cited message")
    ]


def test_a_wrong_message_id_is_refused() -> None:
    # Right words, wrong message; and a message that isn't in the chat.
    summary = [
        {"text": "Cheap NAS.", "quotes": [_q("m2", "a cheap NAS")]},
        {"text": "Ghost.", "quotes": [_q("m9", "NAS")]},
    ]
    digest = resolve_digest(DigestAnswer.model_validate(_answer(summary=summary)), CHAT)

    assert not digest.usable
    assert {f.reason for f in digest.flags} == {
        "quote not found in the cited message",
        "cites a message that is not in the chat",
    }


def test_a_status_without_backing_becomes_unknown_not_guessed() -> None:
    status = {"value": "settled", "quotes": [_q("m3", "we are done")]}
    digest = resolve_digest(DigestAnswer.model_validate(_answer(status=status)), CHAT)

    assert digest.status is None and digest.status_item is None
    assert digest.flags[0].field == "status"


def test_provenance_is_fixed_by_the_contract_not_the_model() -> None:
    digest = resolve_digest(DigestAnswer.model_validate(_answer()), CHAT)

    assert digest.open_questions[0].provenance is Provenance.FROM_CHAT
    assert digest.next_steps[0].provenance is Provenance.GENERATED
    # Every answer field has a fixed label, and there are no others.
    assert set(FIELD_PROVENANCE) == set(DigestAnswer.model_fields)
    with pytest.raises(ValidationError):
        DigestAnswer.model_validate(
            _answer(
                next_steps=[{"text": "x", "quotes": [_q("m1", "NAS")], "provenance": "from_chat"}]
            )
        )
