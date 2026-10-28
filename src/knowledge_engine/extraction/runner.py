"""Running every extractor over segments, with caching and bounded retries (EXT-008).

One *extraction run* is (segment, extractor). Its stage key covers the
segment's exact text and every version that can change the result: the
extractor's version, the record contract's version, and the taxonomy
version when the extractor reads the vocabulary. ``extraction_runs`` keeps
one row per stage key:

* ``done`` with the record IDs it produced: a re-run skips it entirely
  (zero work, zero model requests);
* ``pending``: a model extractor is still waiting for its answer;
* ``failed`` with the error's **type name** (never message text) and the
  attempt count. A failed run is retried on later calls, up to
  ``MAX_ATTEMPTS`` in total, then left failed for a person.

One extractor failing never stops the others. Each run commits on its own
(a SAVEPOINT), so a crash halfway keeps every run that already finished.
Every new candidate goes straight through the EXT-007 gate.

Model extractors fit the same shape: ``ModelExtractor`` sends one FND-009
request per segment through ``ModelStageRunner`` (cache, egress switch, one
repair). The model quotes text; the adapter finds each quote in the
segment and builds the exact, fingerprinted evidence itself. A quote that
isn't there is dropped and the record is flagged.

Talking points:
    - "Each extractor on each segment is its own small job with its own
      fingerprint: done once, skipped after, retried at most three times."
    - "One extractor crashing doesn't throw away what the others found."
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, Session, mapped_column

from knowledge_engine.domain.enums import Role
from knowledge_engine.extraction.records import (
    RECORD_SCHEMA_VERSION,
    Acceptance,
    CandidateRecord,
    Provenance,
    RecordType,
    Scope,
)
from knowledge_engine.extraction.store import add_candidates, gate
from knowledge_engine.extraction.text import ExtractionMessage, exchanges_of, quote
from knowledge_engine.graph.offsets import find_quote
from knowledge_engine.infrastructure.db import Base
from knowledge_engine.infrastructure.logs import EventLog, null_log
from knowledge_engine.orchestration.limits import Deadline
from knowledge_engine.orchestration.stage_keys import stage_key
from knowledge_engine.providers.base import ModelRequest, quote_untrusted
from knowledge_engine.providers.ledger import ModelStageRunner
from knowledge_engine.segmentation.segmenter import SegmenterSettings, split_parts

RUNNER_VERSION = "ext-008-v1"
MAX_ATTEMPTS = 3
DONE = "done"
PENDING = "pending"
FAILED = "failed"


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ExtractionRunRow(Base):
    """One extractor over one segment."""

    __tablename__ = "extraction_runs"

    stage_key: Mapped[str] = mapped_column(String(70), primary_key=True)
    extractor: Mapped[str] = mapped_column(String(40))
    segment_id: Mapped[str] = mapped_column(String(40), index=True)
    state: Mapped[str] = mapped_column(String(10))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(String(100), default=None)
    record_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    versions_json: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


class PendingAnswer(Exception):
    """A model extractor's answer hasn't arrived yet (not a failure)."""


class Extractor(Protocol):
    """Anything that turns a segment's messages into candidates."""

    name: str
    version: str
    prompt_version: str | None
    taxonomy_version: str | None

    def extract(
        self, messages: Sequence[ExtractionMessage], *, segment_id: str
    ) -> list[CandidateRecord]:
        """Candidates for one segment; may raise ``PendingAnswer``."""
        ...


@dataclass
class RuleExtractor:
    """Wraps a rule function (EXT-003..006) as an ``Extractor``."""

    name: str
    version: str
    function: Callable[..., list[CandidateRecord]]
    taxonomy_version: str | None = None
    prompt_version: str | None = None

    def extract(
        self, messages: Sequence[ExtractionMessage], *, segment_id: str
    ) -> list[CandidateRecord]:
        """Call the rule function."""
        return self.function(messages, segment_id=segment_id)


@dataclass
class RunReport:
    """What one ``run`` call did, counted by stage key."""

    done: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    gave_up: list[str] = field(default_factory=list)
    deferred: list[str] = field(default_factory=list)
    records: int = 0


def run_key(
    extractor: Extractor, messages: Sequence[ExtractionMessage]
) -> tuple[str, dict[str, str]]:
    """The stage key of one extractor over one segment, and the versions in it."""
    content = json.dumps(
        [[m.revision_id, m.role.value, m.text] for m in messages], ensure_ascii=False
    )
    versions = {
        "code": RUNNER_VERSION,
        "extractor": extractor.version,
        "record_schema": RECORD_SCHEMA_VERSION,
    }
    if extractor.prompt_version:
        versions["prompt"] = extractor.prompt_version
    if extractor.taxonomy_version:
        versions["taxonomy"] = extractor.taxonomy_version
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return stage_key(f"extract.{extractor.name}.v1", digest, versions), versions


def run(
    session: Session,
    segments: Sequence[tuple[str, Sequence[ExtractionMessage]]],
    extractors: Sequence[Extractor],
    *,
    log: EventLog | None = None,
    deadline: Deadline | None = None,
) -> RunReport:
    """Run every extractor over every segment; skip done work; bound retries.

    Args:
        session: The caller commits at the end; each run is its own
            savepoint, so one failure doesn't undo another run's records.
        segments: (segment ID, its messages) pairs.
        extractors: Rule or model extractors.
        log: Where to write one ``extract.run`` event per run (OPS-001).
        deadline: The stage's time budget (OPS-002). Once it has passed, no
            new run starts; the rest are reported ``deferred`` and done by
            the next call, which skips everything already done.
    """
    log = log or null_log()
    report = RunReport()
    for segment_id, messages in segments:
        for extractor in extractors:
            key, versions = run_key(extractor, messages)
            if deadline is not None and deadline.passed:
                if not report.deferred:
                    log.emit(
                        "limit.reached",
                        limit_name="stage_deadline_s",
                        limit=deadline.seconds,
                        stage_id="extract",
                    )
                report.deferred.append(key)
                continue
            row = session.get(ExtractionRunRow, key)
            if row is not None and row.state == DONE:
                report.skipped.append(key)
                continue
            if row is not None and row.state == FAILED and row.attempts >= MAX_ATTEMPTS:
                report.gave_up.append(key)
                continue
            if row is None:
                row = ExtractionRunRow(
                    stage_key=key,
                    extractor=extractor.name,
                    segment_id=segment_id,
                    state=PENDING,
                    attempts=0,
                    versions_json=json.dumps(versions, sort_keys=True),
                )
                session.add(row)
                session.flush()
            with log.timed(
                "extract.run",
                stage_key=key,
                segment_id=segment_id,
                extractor=extractor.name,
                version=extractor.version,
            ) as fields:
                before = report.records
                _one(session, row, extractor, messages, segment_id, report)
                fields.update(
                    attempts=row.attempts,
                    records=report.records - before,
                    error_type=row.error,
                    state=row.state,
                )
    return report


def _one(
    session: Session,
    row: ExtractionRunRow,
    extractor: Extractor,
    messages: Sequence[ExtractionMessage],
    segment_id: str,
    report: RunReport,
) -> None:
    provenance = Provenance(
        stage_id=f"extract.{extractor.name}.v1",
        stage_key=row.stage_key,
        extractor_version=extractor.version,
        prompt_version=extractor.prompt_version,
        taxonomy_version=extractor.taxonomy_version,
    )
    savepoint = session.begin_nested()
    try:
        candidates = extractor.extract(messages, segment_id=segment_id)
        records = add_candidates(session, candidates, provenance)
        for record in records:
            gate(session, record.record_id)
    except PendingAnswer:
        savepoint.rollback()
        report.pending.append(row.stage_key)
        return
    except Exception as error:  # noqa: BLE001 - one extractor must not stop the rest
        savepoint.rollback()
        row.attempts += 1
        row.state = FAILED
        row.error = type(error).__name__  # never the message: it may quote private text
        row.updated_at = _utc_now()
        session.flush()
        report.failed.append(row.stage_key)
        return
    savepoint.commit()
    row.attempts += 1
    row.state = DONE
    row.error = None
    row.record_ids_json = json.dumps([r.record_id for r in records])
    row.updated_at = _utc_now()
    session.flush()
    report.done.append(row.stage_key)
    report.records += len(records)


# ---------------------------------------------------------------- model extractors


class ModelQuote(BaseModel):
    """A quote the model cites: which message, and the exact words."""

    model_config = ConfigDict(extra="forbid")

    message_id: str = Field(min_length=1)
    text: str = Field(min_length=1, max_length=1000)


class ModelCandidate(BaseModel):
    """One record as a model proposes it. No trust: models only propose."""

    model_config = ConfigDict(extra="forbid")

    record_type: RecordType
    assertion: str = Field(min_length=1, max_length=2000)
    actor: Literal["user", "assistant"]
    acceptance: Acceptance
    quotes: list[ModelQuote] = Field(min_length=1, max_length=10)
    unsure: bool = False


class ModelAnswer(BaseModel):
    """A model extractor's whole answer for one segment."""

    model_config = ConfigDict(extra="forbid")

    records: list[ModelCandidate] = Field(max_length=50)


@dataclass
class ModelExtractor:
    """An extractor answered by a model through the FND-009 stage runner."""

    name: str
    version: str
    prompt_version: str | None
    instructions: str
    runner: ModelStageRunner
    taxonomy_version: str | None = None
    max_characters: int = SegmenterSettings().max_characters

    def request(self, messages: Sequence[ExtractionMessage]) -> ModelRequest:
        """The request for one segment (or one part of it), keyed like the run."""
        text = "\n\n".join(
            f"[m:{m.native_id}] {m.role.value}:\n{quote_untrusted(m.text)}" for m in messages
        )
        key, _ = run_key(self, messages)
        return ModelRequest(
            request_id=key,
            stage_id=f"extract.{self.name}.v1",
            instructions=self.instructions,
            input_text=text,
            output_model=ModelAnswer,
            prompt_version=self.prompt_version or "none",
            schema_version=RECORD_SCHEMA_VERSION,
        )

    def extract(
        self, messages: Sequence[ExtractionMessage], *, segment_id: str
    ) -> list[CandidateRecord]:
        """Ask (or read the cache), then turn quotes into exact evidence.

        The model sees the whole segment. A segment over ``max_characters``
        is never clipped: it is split into overlapping parts at exchange
        boundaries (the segmenter's own rule), one request each, and the
        records of all parts are merged (LEG-005).
        """
        by_id = {m.native_id: m for m in messages}
        parts = split_parts(exchanges_of(messages), self.max_characters)
        requests = [self.request([by_id[i] for i in part.messages]) for part in parts]
        first = self.runner.submit(requests)
        outputs = dict(first.outputs)
        failed = set(first.review_required)
        if len(outputs) < len(requests):
            later = self.runner.collect(requests)
            outputs.update(later.outputs)
            failed |= set(later.review_required)
        if failed:
            raise ValueError("model answer failed validation twice")
        missing = [r.request_id for r in requests if r.request_id not in outputs]
        if missing:
            raise PendingAnswer(missing[0])
        found: list[CandidateRecord] = []
        seen: set[str] = set()
        for part, request in zip(parts, requests, strict=True):
            answer = outputs[request.request_id]
            assert isinstance(answer, ModelAnswer)
            part_messages = [by_id[i] for i in part.messages]
            for record in _from_model(answer, part_messages, segment_id):
                # The exchange two parts share can yield the same record twice.
                fingerprint = record.model_dump_json()
                if fingerprint not in seen:
                    seen.add(fingerprint)
                    found.append(record)
        return found


def _from_model(
    answer: ModelAnswer, messages: Sequence[ExtractionMessage], segment_id: str
) -> list[CandidateRecord]:
    by_id: Mapping[str, ExtractionMessage] = {m.native_id: m for m in messages}
    found = []
    for item in answer.records:
        evidence = []
        dropped = 0
        for cited in item.quotes:
            message = by_id.get(cited.message_id)
            spans = find_quote(message.text, cited.text) if message else []
            if message is None or not spans:
                dropped += 1  # not in this segment, or not the same words (LEG-004)
                continue
            evidence.append(quote(message, spans[0]))
        if not evidence:
            continue  # nothing it said could be found: not even a candidate
        reasons = []
        if dropped:
            reasons.append(f"{dropped} quote(s) not found in the segment")
        if item.unsure:
            reasons.append("the model was unsure")
        try:
            found.append(
                CandidateRecord.model_validate(
                    {
                        "record_type": item.record_type,
                        "assertion": item.assertion,
                        "actor": Role(item.actor),
                        "acceptance": item.acceptance,
                        "scope": Scope.SEGMENT,
                        "scope_id": segment_id,
                        "evidence": evidence,
                        "review_reason": "; ".join(reasons) or None,
                    }
                )
            )
        except ValidationError:
            continue  # breaks the record contract: not stored at all
    return found
