"""FND-007: the provider contract, offline, rejecting bad answers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

import pytest
from pydantic import BaseModel, ConfigDict, Field

from knowledge_engine.orchestration.stage_keys import stage_key
from knowledge_engine.providers.base import (
    FakeProvider,
    ModelRequest,
    ReplayProvider,
    ResultState,
    validate_output,
)


class Label(BaseModel):
    model_config = ConfigDict(extra="forbid")

    domain: Literal["work", "home"]
    confidence: float = Field(ge=0, le=1)


class Loose(BaseModel):
    domain: str


def request(text: str) -> ModelRequest:
    key = stage_key(
        "test.label.v1",
        hashlib.sha256(text.encode()).hexdigest(),
        {"code": "1", "prompt": "p1", "schema": "s1"},
    )
    return ModelRequest(key, "test.label.v1", "Label it.", text, Label, "p1", "s1")


@pytest.mark.parametrize(
    ("raw", "error"),
    [
        ("{not json", "not JSON"),
        ("[1, 2]", "must be a JSON object"),
        ({"domain": "garden", "confidence": 0.5}, "domain: literal_error"),
        ({"domain": "work", "confidence": 2}, "confidence: less_than_equal"),
        ({"domain": "work", "confidence": 0.5, "extra": 1}, "extra: extra_forbidden"),
        ({"domain": "work"}, "confidence: missing"),
    ],
)
def test_invalid_answers_are_refused_with_a_reason(raw: Any, error: str) -> None:
    checked = validate_output(raw, Label)
    assert isinstance(checked, str) and error in checked


def test_errors_never_echo_the_answer() -> None:
    checked = validate_output({"domain": "Synthetic secret words", "confidence": 0.5}, Label)
    assert isinstance(checked, str) and "secret" not in checked


def test_requests_must_be_keyed_and_strict() -> None:
    good = request("Synthetic text")
    with pytest.raises(ValueError, match="stage key"):
        ModelRequest("abc", "s", "i", "t", Label, "p", "s")
    with pytest.raises(ValueError, match="extra='forbid'"):
        ModelRequest(good.request_id, "s", "i", "t", Loose, "p", "s")
    with pytest.raises(ValueError, match="attempt"):
        ModelRequest(good.request_id, "s", "i", "t", Label, "p", "s", attempt=3)


def test_fake_provider_validates_and_can_leave_things_pending() -> None:
    a, b, c = request("Synthetic a"), request("Synthetic b"), request("Synthetic c")
    answers: dict[str, Any] = {
        a.request_id: {"domain": "work", "confidence": 0.9},
        b.request_id: '{"domain": "nope", "confidence": 0.9}',
    }
    fake = FakeProvider(lambda r: answers.get(r.request_id))
    handle = fake.submit([a, b, c])
    results = fake.collect(handle, {r.request_id: r for r in (a, b, c)})
    assert [r.state for r in results] == [ResultState.OK, ResultState.INVALID, ResultState.PENDING]
    assert isinstance(results[0].output, Label) and results[0].served_model == "fake-model"
    assert results[1].output is None and results[1].error


def test_replay_provider_reads_first_complete_line(tmp_path: Path) -> None:
    a, b = request("Synthetic a"), request("Synthetic b")
    lines = [
        json.dumps({"request_id": a.request_id, "output": {"domain": "home", "confidence": 1}}),
        json.dumps({"request_id": a.request_id, "output": {"domain": "work", "confidence": 1}}),
        '{"request_id": "' + b.request_id + '", "output": {"dom',  # cut off
    ]
    (tmp_path / "x.response.jsonl").write_text("\n".join(lines), encoding="utf-8")
    replay = ReplayProvider(tmp_path)
    assert replay.identity.sends_data is False
    handle = replay.submit([a, b])
    first, second = replay.collect(handle, {a.request_id: a, b.request_id: b})
    assert first.state is ResultState.OK and isinstance(first.output, Label)
    assert first.output.domain == "home"  # the first line wins, never replaced
    assert second.state is ResultState.PENDING
