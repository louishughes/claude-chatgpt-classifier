"""LEG-003: provider failure cases the old runs got wrong, replayed with the fake provider."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from knowledge_engine.infrastructure.db import create_sqlite_engine
from knowledge_engine.infrastructure.logs import EventLog, search
from knowledge_engine.infrastructure.migrations import upgrade_to_head
from knowledge_engine.providers.base import TRUNCATED, FakeProvider, ModelRequest, RawResponse
from knowledge_engine.providers.ledger import (
    MAX_TRANSIENT_FAILURES,
    ModelRequestRow,
    ModelStageRunner,
    not_answered,
    schema_failures,
)
from knowledge_engine.settings import EgressPolicy


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool
    items: list[int] = Field(default_factory=list, max_length=2)


REQUEST = ModelRequest(
    "stg_" + "e" * 64, "test.stage.v1", "Synthetic.", "Synthetic.", Answer, "p1", "s1"
)
GOOD = '{"ok": true}'


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    engine = create_sqlite_engine(tmp_path / "k.db")
    upgrade_to_head(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _runner(
    session: Session, replies: list[object], log: EventLog | None = None
) -> ModelStageRunner:
    queue = list(replies)
    provider = FakeProvider(lambda _r: queue.pop(0))  # type: ignore[arg-type,return-value]
    kwargs = {"log": log} if log else {}
    return ModelStageRunner(session, provider, EgressPolicy(text_llm=True), **kwargs)  # type: ignore[arg-type]


def _row(session: Session) -> ModelRequestRow:
    row = session.get(ModelRequestRow, REQUEST.request_id)
    assert row is not None
    return row


def test_an_error_envelope_inside_http_200_is_transient_not_an_answer(session: Session) -> None:
    runner = _runner(session, [RawResponse(200, body=None, error_type="overloaded_error"), GOOD])
    runner.submit([REQUEST])
    first = runner.collect([REQUEST])
    assert first.resent == [REQUEST.request_id] and not first.repairs  # repair not used up
    assert (_row(session).attempts, _row(session).last_error) == (1, None)
    second = runner.collect([REQUEST])
    assert REQUEST.request_id in second.outputs
    assert schema_failures(session)["first_try_failure_rate"] == 0.0


def test_a_rate_limit_keeps_the_repair_context(session: Session) -> None:
    runner = _runner(session, ['{"ok": "Synthetic not a bool"}', RawResponse(429), GOOD])
    runner.submit([REQUEST])
    runner.collect([REQUEST])  # invalid answer: the one repair goes out
    error = _row(session).last_error
    assert error and "ok" in error
    runner.collect([REQUEST])  # the repair is rate limited...
    assert _row(session).last_error == error  # ...and the context survives
    provider = runner.provider
    assert isinstance(provider, FakeProvider)
    resent = provider.submitted[-1]
    assert resent.attempt == 2 and resent.repair_of_error == error
    assert REQUEST.request_id in runner.collect([REQUEST]).outputs
    assert (_row(session).attempts, _row(session).last_transient) == (2, "rate_limit")


def test_finish_reason_length_is_a_recorded_format_error(session: Session) -> None:
    # The cut-off text even parses: it still mustn't be trusted.
    runner = _runner(session, [RawResponse(200, body=GOOD, finish_reason="length"), GOOD])
    runner.submit([REQUEST])
    report = runner.collect([REQUEST])
    assert report.repairs == [REQUEST.request_id] and not report.outputs
    assert _row(session).last_error == TRUNCATED


def test_a_list_overflow_is_trimmed_and_logged_not_retried(
    session: Session, tmp_path: Path
) -> None:
    log = EventLog(tmp_path / "logs")
    runner = _runner(session, ['{"ok": true, "items": [1, 2, 3, 4, 5]}'], log)
    runner.submit([REQUEST])
    report = runner.collect([REQUEST])
    answer = report.outputs[REQUEST.request_id]
    assert isinstance(answer, Answer) and answer.items == [1, 2]
    assert not report.repairs and _row(session).attempts == 1
    [event] = search(tmp_path / "logs", event="model.trimmed")
    assert event["count"] == 1 and event["stage_key"] == REQUEST.request_id


def test_provider_failures_are_bounded(session: Session) -> None:
    runner = _runner(session, [RawResponse(503)] * 10)
    runner.submit([REQUEST])
    for _ in range(MAX_TRANSIENT_FAILURES + 2):
        runner.collect([REQUEST])
    provider = runner.provider
    assert isinstance(provider, FakeProvider)
    assert len(provider.submitted) == MAX_TRANSIENT_FAILURES  # three tries, never a fourth
    assert _row(session).state == "review_required"
    assert not_answered(session)["provider_failed"] == 1
    assert schema_failures(session)["requests"] == 0  # says nothing about the schema
