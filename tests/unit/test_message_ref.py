"""#255 follow-up: a cited ``[m:ID]`` tag counts as the message ID it wraps.

In the one paid run every citation came back as ``[m:<id>]``, copied from
how the request shows each message, and the evidence check compared that
whole string with bare IDs: 53 of 67 answers went to review as "outside the
segment" although every cited message was real.
"""

from __future__ import annotations

import pytest

from knowledge_engine.classification.schema import answer_problems, output_model
from knowledge_engine.evaluation.semantic_smoke import smoke_taxonomy
from knowledge_engine.extraction.runner import ModelQuote
from knowledge_engine.providers.base import bare_message_id


@pytest.mark.parametrize(
    ("cited", "bare"),
    [
        ("[m:aaaa-1111-xx]", "aaaa-1111-xx"),
        ("m:aaaa", "aaaa"),
        (" [m: aaaa ] ", "aaaa"),
        ("aaaa", "aaaa"),
        ("[3]", "[3]"),  # numbered evidence is someone else's format: left alone
        ("m:", "m:"),
        ("[m:a b]", "[m:a b]"),  # not one ID: left for the check to refuse
    ],
)
def test_the_tag_is_stripped_and_nothing_else(cited: str, bare: str) -> None:
    assert bare_message_id(cited) == bare


def test_a_tagged_citation_inside_the_segment_is_not_a_problem() -> None:
    snapshot = smoke_taxonomy()
    model = output_model(snapshot)
    [term] = [t.term_id for t in snapshot.terms][:1]
    answer = model.model_validate(
        {"topic": [{"term_id": term, "rank": "primary", "confidence": 0.9, "evidence": ["[m:n1]"]}]}
    )
    assert answer_problems(answer, ["n1", "n2"]) == []
    outside = model.model_validate(
        {"topic": [{"term_id": term, "rank": "primary", "confidence": 0.9, "evidence": ["[m:n9]"]}]}
    )
    assert answer_problems(outside, ["n1", "n2"]) == [
        f"topic.{term}: evidence outside the segment: ['n9']"
    ]


def test_an_extraction_quote_cites_the_bare_id() -> None:
    assert ModelQuote(message_id="[m:n1]", text="words").message_id == "n1"
