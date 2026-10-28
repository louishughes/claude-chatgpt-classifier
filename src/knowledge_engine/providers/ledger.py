"""The model ledger and stage runner: cache, repair, review (FND-009).

Two tables:

* ``model_requests``: one row per stage key that was ever sent, with its
  state (``pending``, ``done`` or ``review_required``), how many attempts it
  took, the last validation error and which batches it went into. This is
  also the usage ledger: characters sent and provider per request.
* ``model_outputs``: one row per stage key with a **validated** answer, the
  served model and the session that produced it. Nothing invalid is ever
  written here, and a stored answer is never overwritten.

``ModelStageRunner`` is the only way a stage talks to a provider:

1. ``submit``: a request whose stage key already has an output is answered
   from the cache with **zero** provider calls; one already waiting is not
   sent again; anything else is submitted and recorded as ``pending``.
2. ``collect``: valid answers are stored; an invalid first answer gets **one**
   repair request (same question plus the validation error); an invalid
   repair marks the request ``review_required`` for a person. Nothing loops.

Talking points:
    - "Same stage key, same answer: the cache is checked before any model is
      asked, so re-running costs nothing."
    - "One repair, then a person. A model that can't fit the schema twice
      doesn't get a third try."
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

from pydantic import BaseModel
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from knowledge_engine.infrastructure.db import Base
from knowledge_engine.providers.base import (
    BatchHandle,
    ModelRequest,
    ResultState,
    StructuredModelProvider,
)
from knowledge_engine.settings import EgressPolicy

PENDING = "pending"
DONE = "done"
REVIEW_REQUIRED = "review_required"


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ModelRequestRow(Base):
    """One stage key sent to a provider, and where it stands."""

    __tablename__ = "model_requests"
    __table_args__ = (
        CheckConstraint(f"state IN ('{PENDING}','{DONE}','{REVIEW_REQUIRED}')", name="state_valid"),
        CheckConstraint("attempts IN (1, 2)", name="attempts_bounded"),
    )

    stage_key: Mapped[str] = mapped_column(String(70), primary_key=True)
    stage_id: Mapped[str] = mapped_column(String(100), index=True)
    provider_id: Mapped[str] = mapped_column(String(40))
    state: Mapped[str] = mapped_column(String(16), index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    # The request ID currently waiting: the stage key, or its repair's ID.
    waiting_id: Mapped[str] = mapped_column(String(70))
    batch_ids_json: Mapped[str] = mapped_column(Text, default="[]")
    characters: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


class ModelOutputRow(Base):
    """One validated answer. Written once, never updated."""

    __tablename__ = "model_outputs"

    stage_key: Mapped[str] = mapped_column(ForeignKey("model_requests.stage_key"), primary_key=True)
    stage_id: Mapped[str] = mapped_column(String(100), index=True)
    prompt_version: Mapped[str] = mapped_column(String(50))
    schema_version: Mapped[str] = mapped_column(String(50))
    provider_id: Mapped[str] = mapped_column(String(40))
    provider_version: Mapped[str] = mapped_column(String(40))
    served_model: Mapped[str | None] = mapped_column(String(100), default=None)
    session_ref: Mapped[str | None] = mapped_column(String(200), default=None)
    output_json: Mapped[str] = mapped_column(Text)
    stored_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


def repair_id(stage_key: str) -> str:
    """The request ID of a stage key's single repair (also a ``stg_`` key)."""
    return "stg_" + hashlib.sha256(f"repair:{stage_key}".encode()).hexdigest()


@dataclass
class StageReport:
    """What one ``submit`` or ``collect`` did, by stage key.

    Attributes:
        outputs: Stage key -> validated answer (from cache or just stored).
        cached: Stage keys answered from the cache, with no provider call.
        submitted: Stage keys sent to the provider in this call.
        pending: Stage keys still waiting.
        repairs: Stage keys that got their one repair request.
        review_required: Stage keys that failed twice and need a person.
    """

    outputs: dict[str, BaseModel] = field(default_factory=dict)
    cached: list[str] = field(default_factory=list)
    submitted: list[str] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)
    repairs: list[str] = field(default_factory=list)
    review_required: list[str] = field(default_factory=list)


@dataclass
class ModelStageRunner:
    """Runs requests through one provider with the cache and repair rules."""

    session: Session
    provider: StructuredModelProvider
    egress: EgressPolicy

    def _send(self, requests: Sequence[ModelRequest]) -> BatchHandle:
        # The one place requests leave for a provider: the switch is checked
        # here for every provider, not trusted to each adapter.
        identity = self.provider.identity
        if identity.sends_data:
            self.egress.require(identity.capability)
        return self.provider.submit(requests)

    def submit(self, requests: Sequence[ModelRequest]) -> StageReport:
        """Answer from cache where possible and submit the rest.

        Args:
            requests: First-attempt requests, keyed by stage key.

        Returns:
            Cached outputs and what was submitted or is still waiting.
        """
        report = StageReport()
        fresh: list[ModelRequest] = []
        for request in requests:
            cached = self._cached(request)
            if cached is not None:
                report.outputs[request.request_id] = cached
                report.cached.append(request.request_id)
                continue
            row = self.session.get(ModelRequestRow, request.request_id)
            if row is None:
                fresh.append(request)
            elif row.state == PENDING:
                report.pending.append(request.request_id)
            elif row.state == REVIEW_REQUIRED:
                report.review_required.append(request.request_id)
        if fresh:
            handle = self._send(fresh)
            for request in fresh:
                self.session.add(
                    ModelRequestRow(
                        stage_key=request.request_id,
                        stage_id=request.stage_id,
                        provider_id=self.provider.identity.provider_id,
                        state=PENDING,
                        attempts=1,
                        waiting_id=request.request_id,
                        batch_ids_json=json.dumps(list(handle.batch_ids)),
                        characters=request.characters,
                    )
                )
                report.submitted.append(request.request_id)
            self.session.flush()
        return report

    def collect(self, requests: Sequence[ModelRequest]) -> StageReport:
        """Collect answers for waiting requests; store, repair or flag them.

        Args:
            requests: The same first-attempt requests given to ``submit``.

        Returns:
            Stored outputs, repairs sent, and what still waits or needs review.
        """
        report = StageReport()
        waiting: dict[str, ModelRequest] = {}
        rows: dict[str, ModelRequestRow] = {}
        batches: list[str] = []
        for request in requests:
            row = self.session.get(ModelRequestRow, request.request_id)
            if row is None or row.state != PENDING:
                continue
            rows[request.request_id] = row
            asked = request if row.attempts == 1 else self._repair(request, row.last_error)
            waiting[asked.request_id] = asked
            batches.extend(b for b in json.loads(row.batch_ids_json) if b not in batches)
        if not waiting:
            return report
        handle = BatchHandle(tuple(batches), tuple(waiting))
        repairs: list[ModelRequest] = []
        for result in self.provider.collect(handle, waiting):
            original = next(r for r in requests if result.request_id in _ids(r))
            row = rows[original.request_id]
            if result.state is ResultState.PENDING:
                report.pending.append(original.request_id)
            elif result.state is ResultState.OK and result.output is not None:
                self._store(original, row, result.output, result.served_model, result.session_ref)
                report.outputs[original.request_id] = result.output
            elif row.attempts == 1:
                row.last_error = result.error
                repairs.append(original)
            else:
                row.state = REVIEW_REQUIRED
                row.last_error = result.error
                row.updated_at = _utc_now()
                report.review_required.append(original.request_id)
        if repairs:
            repair_requests = [self._repair(r, rows[r.request_id].last_error) for r in repairs]
            repair_handle = self._send(repair_requests)
            for request in repairs:
                row = rows[request.request_id]
                row.attempts = 2
                row.waiting_id = repair_id(request.request_id)
                row.batch_ids_json = json.dumps(list(repair_handle.batch_ids))
                row.characters += len(row.last_error or "") + request.characters
                row.updated_at = _utc_now()
                report.repairs.append(request.request_id)
        self.session.flush()
        return report

    def _repair(self, request: ModelRequest, error: str | None) -> ModelRequest:
        return replace(
            request,
            request_id=repair_id(request.request_id),
            attempt=2,
            repair_of_error=error or "the previous answer did not fit the schema",
        )

    def _cached(self, request: ModelRequest) -> BaseModel | None:
        row = self.session.get(ModelOutputRow, request.request_id)
        if row is None:
            return None
        return request.output_model.model_validate_json(row.output_json)

    def _store(
        self,
        request: ModelRequest,
        row: ModelRequestRow,
        output: BaseModel,
        served_model: str | None,
        session_ref: str | None,
    ) -> None:
        identity = self.provider.identity
        self.session.add(
            ModelOutputRow(
                stage_key=request.request_id,
                stage_id=request.stage_id,
                prompt_version=request.prompt_version,
                schema_version=request.schema_version,
                provider_id=identity.provider_id,
                provider_version=identity.version,
                served_model=served_model,
                session_ref=session_ref,
                output_json=output.model_dump_json(),
            )
        )
        row.state = DONE
        row.updated_at = _utc_now()


def _ids(request: ModelRequest) -> tuple[str, str]:
    return request.request_id, repair_id(request.request_id)


def usage(session: Session) -> Mapping[str, int]:
    """Return the usage ledger's totals: requests by state, and characters sent."""
    totals: dict[str, int] = {}
    for row in session.scalars(select(ModelRequestRow)):
        totals[row.state] = totals.get(row.state, 0) + 1
        totals["characters"] = totals.get("characters", 0) + row.characters
    return totals
