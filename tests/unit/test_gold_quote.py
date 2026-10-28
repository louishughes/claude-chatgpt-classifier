"""REV-011: gold records and forbidden items may carry a verbatim quote."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from knowledge_engine.evaluation.gold import GoldForbidden, GoldRecord

BASE = {"record_type": "decision", "actor": "user", "message_id": "m-5"}


def test_a_quote_is_accepted_and_kept() -> None:
    record = GoldRecord.model_validate({**BASE, "quote": "yes, use that"})
    assert record.quote == "yes, use that"
    forbidden = GoldForbidden.model_validate(
        {**BASE, "actor": "assistant", "reason": "a suggestion", "quote": "you could"}
    )
    assert forbidden.quote == "you could"


def test_keys_written_before_the_rule_stay_valid() -> None:
    assert GoldRecord.model_validate(BASE).quote is None


def test_an_empty_quote_is_refused() -> None:
    with pytest.raises(ValidationError):
        GoldRecord.model_validate({**BASE, "quote": ""})
