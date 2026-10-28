"""Type equivalences when scoring (owner decision 2026-10-28: `proposal` counts for a key `idea`).

The answer key calls an assistant's suggestion an ``idea``; the extractor
records it as a ``proposal``. The rule is opt-in and printed on the report,
so a strict score and a mapped score are never confused.
"""

from __future__ import annotations

import pytest

from knowledge_engine.domain.enums import Role
from knowledge_engine.evaluation.extraction_eval import (
    ScoredRecord,
    evaluate_extraction,
    parse_count_as,
)
from knowledge_engine.evaluation.gold import GoldSet
from knowledge_engine.extraction.records import (
    Acceptance,
    KnowledgeRecord,
    RecordType,
    Trust,
)

GOLD = GoldSet.model_validate(
    {
        "name": "count-as",
        "synthetic": True,
        "taxonomy_version": "t",
        "conversations": [
            {
                "native_conversation_id": "c",
                "annotator": "a",
                "records_annotated": True,
                "records": [
                    {"record_type": "idea", "actor": "assistant", "message_id": "a1"},
                    {"record_type": "decision", "actor": "user", "message_id": "u1"},
                ],
            }
        ],
    }
)


def _item(record_type: RecordType, actor: Role, message: str, n: int) -> ScoredRecord:
    record = KnowledgeRecord.model_construct(
        record_id=f"krec_{n:032x}",
        record_type=record_type,
        assertion="x",
        actor=actor,
        trust=Trust.SUPPORTED,
        acceptance=Acceptance.NOT_APPLICABLE,
    )
    return ScoredRecord(record, "c", (message,), anchors_valid=True, user_words=True)


PRODUCED = [
    _item(RecordType.PROPOSAL, Role.ASSISTANT, "a1", 1),  # the same suggestion, other name
    _item(RecordType.PROPOSAL, Role.ASSISTANT, "u1", 2),  # a proposal never answers a decision
]


def test_strict_by_default() -> None:
    report = evaluate_extraction(GOLD, PRODUCED, {})
    assert report.total.true_pos == 0 and report.count_as == {}
    assert "strict (types must be equal)" in report.as_markdown()


def test_proposal_counts_for_a_key_idea_only() -> None:
    report = evaluate_extraction(GOLD, PRODUCED, {}, count_as=parse_count_as(["idea=proposal"]))
    scores = {k: (s.true_pos, s.false_pos, s.false_neg) for k, s in report.by_type.items()}
    assert scores["idea"] == (1, 0, 0)
    assert scores["decision"] == (0, 0, 1)  # the mapping never widens other types
    assert scores["proposal"] == (0, 1, 0)
    assert report.count_as == {"idea": ["proposal"]}
    assert "key `idea` also matched by `proposal`" in report.as_markdown()


@pytest.mark.parametrize("bad", ["idea", "idea=nonsense", "=proposal"])
def test_bad_pairs_are_refused(bad: str) -> None:
    with pytest.raises(ValueError):
        parse_count_as([bad])
