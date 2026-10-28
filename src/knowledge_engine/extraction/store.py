"""The promotion gate, reviewer decisions and audit log for knowledge records (EXT-007).

Extractors only propose. This module is the one road from a proposal to
something the rest of the system may treat as true:

1. ``add_candidates`` stores candidates as ``candidate`` records, keyed by
   a fingerprint of the stage key and the candidate itself, so re-running
   the same extraction adds nothing.
2. ``gate`` runs the EXT-002 evidence check on a candidate:
   - a malformed reference -> ``rejected`` (by the validator);
   - a doubtful meaning -> ``review_required``;
   - all sound -> ``supported``, *if* the record rules allow it (a user
     decision without explicit acceptance, for example, can't be
     supported, so it goes to review instead).
3. ``decide`` records a reviewer's call on a record waiting for review or
   already supported: ``support``, ``confirm`` or ``reject``. Confirming
   always needs a named reviewer.
4. ``current_truth`` returns only ``supported`` and ``confirmed`` records.
   It is the **only** reader later stages (notes, projections) may use, so
   an unsupported candidate can't reach current truth or a materialised
   note.

Every trust change, by the validator or by a person, is appended to
``knowledge_record_events`` with who, from, to, when and why. Nothing is
deleted or rewritten; the record row only carries its current state.

Talking points:
    - "There's one gate. Candidates go in; only checked or reviewed records
      come out to the rest of the system."
    - "Every change of trust is logged with who did it and why."
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import ValidationError
from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from knowledge_engine.extraction.evidence import VALIDATOR_VERSION, Verdict, check_record
from knowledge_engine.extraction.records import (
    CandidateRecord,
    KnowledgeRecord,
    Provenance,
    RecordType,
    Trust,
    advance,
)
from knowledge_engine.infrastructure.db import Base

VALIDATOR = "validator"
_CURRENT = (Trust.SUPPORTED.value, Trust.CONFIRMED.value)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class KnowledgeRecordRow(Base):
    """A knowledge record and its current trust state."""

    __tablename__ = "knowledge_records"

    record_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    stage_key: Mapped[str] = mapped_column(String(70), index=True)
    record_type: Mapped[str] = mapped_column(String(20), index=True)
    scope_id: Mapped[str | None] = mapped_column(String(60), index=True, default=None)
    trust: Mapped[str] = mapped_column(String(20), index=True)
    record_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


class KnowledgeRecordEventRow(Base):
    """One trust change (append-only audit log)."""

    __tablename__ = "knowledge_record_events"

    event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    record_id: Mapped[str] = mapped_column(ForeignKey("knowledge_records.record_id"), index=True)
    from_trust: Mapped[str | None] = mapped_column(String(20), default=None)
    to_trust: Mapped[str] = mapped_column(String(20))
    actor: Mapped[str] = mapped_column(String(100))
    note: Mapped[str | None] = mapped_column(Text, default=None)
    problems_json: Mapped[str] = mapped_column(Text, default="[]")
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


class Decision(StrEnum):
    """What a reviewer can do with a record."""

    SUPPORT = "support"
    CONFIRM = "confirm"
    REJECT = "reject"


class GateError(ValueError):
    """A request the gate refuses (unknown record, reviewer missing...)."""


def record_id_for(stage_key: str, candidate: CandidateRecord) -> str:
    """``krec_`` + fingerprint of the stage key and the candidate's exact content."""
    payload = json.dumps(
        [stage_key, candidate.model_dump(mode="json")], sort_keys=True, ensure_ascii=False
    )
    return "krec_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def add_candidates(
    session: Session, candidates: Iterable[CandidateRecord], provenance: Provenance
) -> list[KnowledgeRecord]:
    """Store candidates; one already stored (same stage key and content) is returned as is."""
    stored = []
    for candidate in candidates:
        record_id = record_id_for(provenance.stage_key, candidate)
        row = session.get(KnowledgeRecordRow, record_id)
        if row is None:
            record = KnowledgeRecord.model_validate(
                {**candidate.model_dump(), "record_id": record_id, "provenance": provenance}
            )
            row = KnowledgeRecordRow(
                record_id=record_id,
                stage_key=provenance.stage_key,
                record_type=record.record_type.value,
                scope_id=record.scope_id,
                trust=record.trust.value,
                record_json=record.model_dump_json(),
            )
            session.add(row)
            session.flush()
            _log(session, record_id, None, record.trust, provenance.stage_id, "extracted", [])
        stored.append(load(session, record_id))
    session.flush()
    return stored


def load(session: Session, record_id: str) -> KnowledgeRecord:
    """A stored record. Raises ``GateError`` if there is none."""
    row = session.get(KnowledgeRecordRow, record_id)
    if row is None:
        raise GateError(f"no record {record_id}")
    return KnowledgeRecord.model_validate_json(row.record_json)


def gate(session: Session, record_id: str) -> KnowledgeRecord:
    """Check a candidate's evidence and move it on; anything else is returned unchanged."""
    record = load(session, record_id)
    if record.trust is not Trust.CANDIDATE:
        return record
    check = check_record(session, record)
    problems = [p.code for p in check.problems]
    if check.verdict is Verdict.INVALID:
        return _save(session, record, advance(record, Trust.REJECTED), VALIDATOR, problems)
    if check.verdict is Verdict.VALID:
        try:
            moved = advance(record, Trust.SUPPORTED, evidence_checked_by=check.validator_version)
        except ValidationError:
            # Sound quotes, but the record rules forbid trusting it (a user
            # commitment with no acceptance): a person decides.
            problems.append("record_rules")
        else:
            return _save(session, record, moved, VALIDATOR, problems)
    moved = advance(record, Trust.REVIEW_REQUIRED, evidence_checked_by=check.validator_version)
    return _save(session, record, moved, VALIDATOR, problems)


def decide(
    session: Session, record_id: str, decision: Decision, *, reviewer: str, note: str | None = None
) -> KnowledgeRecord:
    """Record a reviewer's call.

    ``support`` moves a reviewed record to ``supported``; ``confirm`` moves
    a supported one (or a reviewed one, via supported) to ``confirmed``;
    ``reject`` rejects it.

    Raises:
        GateError: No reviewer, or a record not waiting for this decision.
        pydantic.ValidationError: The result would break a record rule.
    """
    if not reviewer.strip() or reviewer == VALIDATOR:
        raise GateError("a decision needs a named reviewer")
    record = load(session, record_id)
    if record.trust in (Trust.CANDIDATE,):
        raise GateError("run the evidence gate first")
    if decision is Decision.REJECT:
        return _save(
            session, record, advance(record, Trust.REJECTED, reviewer=reviewer), reviewer, [], note
        )
    current = record
    if current.trust is Trust.REVIEW_REQUIRED:
        current = _save(
            session,
            current,
            advance(
                current, Trust.SUPPORTED, evidence_checked_by=VALIDATOR_VERSION, reviewer=reviewer
            ),
            reviewer,
            [],
            note,
        )
    if decision is Decision.CONFIRM:
        current = _save(
            session,
            current,
            advance(current, Trust.CONFIRMED, reviewer=reviewer),
            reviewer,
            [],
            note,
        )
    return current


def current_truth(
    session: Session,
    *,
    scope_id: str | None = None,
    types: Sequence[RecordType] = (),
) -> list[KnowledgeRecord]:
    """Supported and confirmed records only: the one reader for notes and projections."""
    query = select(KnowledgeRecordRow).where(KnowledgeRecordRow.trust.in_(_CURRENT))
    if scope_id is not None:
        query = query.where(KnowledgeRecordRow.scope_id == scope_id)
    if types:
        query = query.where(KnowledgeRecordRow.record_type.in_([t.value for t in types]))
    rows = session.scalars(query.order_by(KnowledgeRecordRow.record_id))
    return [KnowledgeRecord.model_validate_json(row.record_json) for row in rows]


def review_queue(session: Session) -> list[KnowledgeRecord]:
    """Records waiting for a person, oldest first."""
    rows = session.scalars(
        select(KnowledgeRecordRow)
        .where(KnowledgeRecordRow.trust == Trust.REVIEW_REQUIRED.value)
        .order_by(KnowledgeRecordRow.created_at, KnowledgeRecordRow.record_id)
    )
    return [KnowledgeRecord.model_validate_json(row.record_json) for row in rows]


def history(session: Session, record_id: str) -> list[KnowledgeRecordEventRow]:
    """Every trust change of one record, in order."""
    return list(
        session.scalars(
            select(KnowledgeRecordEventRow)
            .where(KnowledgeRecordEventRow.record_id == record_id)
            .order_by(KnowledgeRecordEventRow.event_id)
        )
    )


def _save(
    session: Session,
    before: KnowledgeRecord,
    after: KnowledgeRecord,
    actor: str,
    problems: list[str],
    note: str | None = None,
) -> KnowledgeRecord:
    row = session.get(KnowledgeRecordRow, after.record_id)
    assert row is not None
    row.trust = after.trust.value
    row.record_json = after.model_dump_json()
    row.updated_at = _utc_now()
    _log(session, after.record_id, before.trust, after.trust, actor, note, problems)
    session.flush()
    return after


def _log(
    session: Session,
    record_id: str,
    before: Trust | None,
    after: Trust,
    actor: str,
    note: str | None,
    problems: list[str],
) -> None:
    session.add(
        KnowledgeRecordEventRow(
            record_id=record_id,
            from_trust=before.value if before else None,
            to_trust=after.value,
            actor=actor,
            note=note,
            problems_json=json.dumps(problems),
        )
    )
