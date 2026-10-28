"""EVAL-012: the relationship answer key's rules and the precision scorer."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from knowledge_engine.evaluation.relationship_key import (
    Proposal,
    RelationshipKey,
    score,
)

BY = {"session": "test", "model": "none", "saw_engine_output": False}
EVIDENCE = [{"conversation": "b", "message_number": 2, "speaker": "user", "quote": "x"}]


def _key(links: list[dict[str, Any]], chats: tuple[str, ...] = ("a", "b", "c")) -> RelationshipKey:
    return RelationshipKey.model_validate(
        {"produced_by": BY, "synthetic": True, "conversations": chats, "links": links}
    )


def _link(from_id: str, kind: str, to_id: str) -> dict[str, Any]:
    evidence = [{**EVIDENCE[0], "conversation": from_id}]
    return {
        "from_conversation": from_id,
        "kind": kind,
        "to_conversation": to_id,
        "evidence": evidence,
    }


def test_each_proposal_gets_one_verdict() -> None:
    key = _key([_link("b", "forked_from", "a"), _link("c", "continues", "a")])
    result = score(
        key,
        [
            Proposal("b", "forked_from", "a"),  # right
            Proposal("a", "continues", "c"),  # backwards
            Proposal("c", "forked_from", "a"),  # the key says continues
            Proposal("b", "quotes", "c"),  # the key links b and c not at all
            Proposal("b", "quotes", "z"),  # z is outside the key: not judged
        ],
    )
    assert dict(result.verdicts) == {
        "correct": 1,
        "wrong_direction": 1,
        "wrong_kind": 1,
        "false_link": 1,
    }
    assert result.out_of_scope == 1
    assert result.precision == 0.25
    assert result.recall == 0.5
    assert not result.passed


def test_the_same_link_from_two_detectors_counts_once() -> None:
    key = _key([_link("b", "forked_from", "a")])
    result = score(key, [Proposal("b", "forked_from", "a")] * 2)
    assert result.proposed == result.scored == 1
    assert result.precision == 1.0
    assert result.passed


def test_undirected_kinds_match_either_way_round() -> None:
    key = _key([_link("a", "related_to", "b")])
    assert score(key, [Proposal("b", "related_to", "a")]).verdicts["correct"] == 1


def test_nothing_to_score_has_no_precision_and_does_not_pass() -> None:
    result = score(_key([]), [])
    assert result.precision is None
    assert not result.passed


def test_the_key_writer_must_not_have_seen_the_engine_output() -> None:
    with pytest.raises(ValidationError):
        RelationshipKey.model_validate(
            {
                "produced_by": {**BY, "saw_engine_output": True},
                "synthetic": True,
                "conversations": ["a", "b"],
            }
        )


@pytest.mark.parametrize(
    "links",
    [
        [_link("a", "forked_from", "z")],  # z is not a listed chat
        [_link("a", "forked_from", "a")],  # a chat can't link to itself
        [_link("a", "related_to", "b"), _link("b", "related_to", "a")],  # listed twice
        [{**_link("a", "quotes", "b"), "evidence": []}],  # no evidence
        [{**_link("a", "quotes", "b"), "evidence": [{**EVIDENCE[0], "conversation": "c"}]}],
    ],
)
def test_a_malformed_key_is_refused(links: list[dict[str, Any]]) -> None:
    with pytest.raises(ValidationError):
        _key(links)
