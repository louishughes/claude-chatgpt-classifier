"""Saving classifications and reviewer corrections (CLS-004).

Three tables, all append-only:

* ``classifications``: one row per stage key, i.e. per exact piece of work
  (segment text + taxonomy version + method + its versions). It keeps the
  state (``done``, ``pending``, ``review_required``), the validated answer,
  the problems, and the provider and served model when a model answered.
  Saving the same stage key again changes nothing, except that a
  ``pending`` row is completed once its answer arrives.
* ``classification_labels``: the answer's labels, one row each (field,
  ID, rank, confidence, evidence), so "which segments are about project X"
  is a query, not a scan of JSON.
* ``classification_reviews``: a reviewer's correction for one segment and
  one field (a dimension, or ``projects``): the primary, the secondaries,
  or "none fits". The newest review for a segment and field wins; older
  ones stay as history.

A review belongs to the **segment**, not to a run. Re-classifying the
segment (same answer from cache, or a new run after a code change) adds or
reuses a machine row and never touches the review, so ``effective_labels``
keeps showing the reviewer's choice. If a later taxonomy version no longer
has a reviewed ID (merged, retired), that field comes back as ``stale``
instead of silently dropping or keeping the choice.

``review_queue`` lists what still needs a person: ``review_required`` rows
for a version, newest machine row per segment, unless a reviewer has
already decided every field it flagged.

Talking points:
    - "A person's correction is stored apart from the machine's answer, so
      re-running the machine can't overwrite it."
    - "If the vocabulary changes under a correction, it is flagged stale,
      not quietly kept or lost."
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    select,
)
from sqlalchemy.orm import Mapped, Session, mapped_column

from knowledge_engine.classification.classifier import (
    DONE,
    PENDING,
    REVIEW_REQUIRED,
    SegmentClassification,
)
from knowledge_engine.classification.schema import PROJECTS_FIELD, Rank, assignments
from knowledge_engine.infrastructure.db import Base
from knowledge_engine.taxonomy.registry import Dimension, TaxonomySnapshot

FIELDS = tuple(d.value for d in Dimension) + (PROJECTS_FIELD,)
_STATES = (DONE, PENDING, REVIEW_REQUIRED)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class ClassificationRow(Base):
    """One classification run of one segment (one stage key)."""

    __tablename__ = "classifications"
    __table_args__ = (
        CheckConstraint(
            "state IN (" + ",".join(f"'{s}'" for s in _STATES) + ")", name="state_valid"
        ),
    )

    classification_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    stage_key: Mapped[str] = mapped_column(String(70), unique=True)
    segment_id: Mapped[str] = mapped_column(String(40), index=True)
    conversation_id: Mapped[str] = mapped_column(String(40), index=True)
    taxonomy_version: Mapped[str] = mapped_column(String(40), index=True)
    method: Mapped[str] = mapped_column(String(20))
    state: Mapped[str] = mapped_column(String(20))
    answer_json: Mapped[str | None] = mapped_column(Text, default=None)
    problems_json: Mapped[str] = mapped_column(Text, default="[]")
    provider_id: Mapped[str | None] = mapped_column(String(40), default=None)
    served_model: Mapped[str | None] = mapped_column(String(100), default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


class ClassificationLabelRow(Base):
    """One label of one classification, for querying."""

    __tablename__ = "classification_labels"

    label_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    classification_id: Mapped[str] = mapped_column(
        ForeignKey("classifications.classification_id"), index=True
    )
    field: Mapped[str] = mapped_column(String(20))
    target_id: Mapped[str] = mapped_column(String(40), index=True)
    rank: Mapped[str] = mapped_column(String(10))
    confidence: Mapped[float] = mapped_column(Float)
    evidence_json: Mapped[str] = mapped_column(Text)


class ClassificationReviewRow(Base):
    """A reviewer's choice for one segment and one field (append-only)."""

    __tablename__ = "classification_reviews"
    __table_args__ = (UniqueConstraint("segment_id", "field", "sequence"),)

    review_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    segment_id: Mapped[str] = mapped_column(String(40), index=True)
    field: Mapped[str] = mapped_column(String(20))
    sequence: Mapped[int] = mapped_column(Integer)
    taxonomy_version: Mapped[str] = mapped_column(String(40))
    primary_id: Mapped[str | None] = mapped_column(String(40), default=None)
    secondary_json: Mapped[str] = mapped_column(Text, default="[]")
    reviewer: Mapped[str] = mapped_column(String(100))
    note: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


class ReviewInputError(ValueError):
    """A correction that names an unknown field or an ID not approved in its version."""


def classification_id(stage_key: str) -> str:
    """``cls_`` + a short hash of the stage key: one ID per exact piece of work."""
    return "cls_" + hashlib.sha256(stage_key.encode()).hexdigest()[:32]


def save(
    session: Session,
    results: Iterable[SegmentClassification],
    *,
    provider_id: str | None = None,
    served_model: str | None = None,
) -> list[ClassificationRow]:
    """Store results; an existing stage key is reused, a pending one completed.

    Args:
        session: The caller commits.
        results: From ``SegmentClassifier.classify``.
        provider_id: For model answers, which provider.
        served_model: For model answers, which model answered (as reported).

    Returns:
        The rows, one per result, in order.
    """
    rows = []
    for result in results:
        row = session.scalar(
            select(ClassificationRow).where(ClassificationRow.stage_key == result.stage_key)
        )
        if row is None:
            row = ClassificationRow(
                classification_id=classification_id(result.stage_key),
                stage_key=result.stage_key,
                segment_id=result.segment_id,
                conversation_id=result.conversation_id,
                taxonomy_version=result.taxonomy_version,
                method=result.method,
                state=PENDING,
            )
            session.add(row)
            session.flush()
        if row.state == PENDING and result.state != PENDING:
            # The only change a stored row ever gets: its answer arriving.
            row.state = result.state
            row.answer_json = result.answer.model_dump_json() if result.answer else None
            row.problems_json = json.dumps(list(result.problems))
            if result.method == "model":
                row.provider_id, row.served_model = provider_id, served_model
            row.updated_at = _utc_now()
            if result.answer is not None:
                for name, item in assignments(result.answer):
                    session.add(
                        ClassificationLabelRow(
                            classification_id=row.classification_id,
                            field=name,
                            target_id=item.get("term_id") or item["project_id"],
                            rank=item["rank"],
                            confidence=item["confidence"],
                            evidence_json=json.dumps(item["evidence"]),
                        )
                    )
        rows.append(row)
    session.flush()
    return rows


def record_review(
    session: Session,
    snapshot: TaxonomySnapshot,
    segment_id: str,
    field: str,
    *,
    primary: str | None,
    secondary: Sequence[str] = (),
    reviewer: str,
    note: str | None = None,
    conversation_id: str | None = None,
) -> ClassificationReviewRow:
    """Record a reviewer's choice for one field of one segment.

    ``primary=None`` with no secondaries means "nothing in the vocabulary
    fits". Every ID must be approved in ``snapshot`` for that field.

    The review is anchored to the segment's messages at their current
    revisions (IMP-006), so a later re-import that changes them flags it.
    ``conversation_id`` helps find a segment that was never classified.

    Raises:
        ReviewInputError: Unknown field, unapproved ID, or secondaries
            without a primary.
    """
    if field not in FIELDS:
        raise ReviewInputError(f"unknown field {field!r}")
    if secondary and primary is None:
        raise ReviewInputError("secondary labels need a primary")
    allowed = set(_allowed(snapshot, field))
    chosen = [primary, *secondary] if primary else list(secondary)
    unknown = sorted(set(chosen) - allowed)
    if unknown:
        raise ReviewInputError(f"not approved in {snapshot.version} for {field}: {unknown}")
    if len(set(chosen)) != len(chosen):
        raise ReviewInputError("an ID is listed twice")
    latest = _latest_review(session, segment_id, field)
    row = ClassificationReviewRow(
        segment_id=segment_id,
        field=field,
        sequence=(latest.sequence + 1) if latest else 1,
        taxonomy_version=snapshot.version,
        primary_id=primary,
        secondary_json=json.dumps(list(secondary)),
        reviewer=reviewer,
        note=note,
    )
    session.add(row)
    session.flush()
    from knowledge_engine.importer.corrections import OverrideKind, anchor, segment_messages

    found = segment_messages(session, segment_id, conversation_id)
    if found is not None:
        anchor(session, OverrideKind.CLASSIFICATION, str(row.review_id), found[0], found[1])
    return row


@dataclass(frozen=True)
class FieldLabels:
    """The labels in force for one field of one segment.

    Attributes:
        field: A dimension name or ``projects``.
        primary: The primary ID, or None.
        secondary: Secondary IDs.
        source: ``review``, ``machine``, ``stale_review`` (a reviewed ID is
            no longer approved in this version) or ``none``.
    """

    field: str
    primary: str | None
    secondary: tuple[str, ...]
    source: str


def effective_labels(
    session: Session, segment_id: str, snapshot: TaxonomySnapshot
) -> dict[str, FieldLabels]:
    """The labels in force for a segment under one version: reviews over machine.

    The machine answer used is the newest ``done`` classification of the
    segment under the same version.
    """
    machine: dict[str, tuple[str | None, list[str]]] = {}
    row = session.scalar(
        select(ClassificationRow)
        .where(
            ClassificationRow.segment_id == segment_id,
            ClassificationRow.taxonomy_version == snapshot.version,
            ClassificationRow.state == DONE,
        )
        .order_by(ClassificationRow.updated_at.desc(), ClassificationRow.classification_id)
    )
    if row is not None:
        for label in session.scalars(
            select(ClassificationLabelRow)
            .where(ClassificationLabelRow.classification_id == row.classification_id)
            .order_by(ClassificationLabelRow.label_id)
        ):
            primary, rest = machine.get(label.field, (None, []))
            if label.rank == Rank.PRIMARY.value:
                primary = label.target_id
            else:
                rest.append(label.target_id)
            machine[label.field] = (primary, rest)
    found = {}
    for field in FIELDS:
        review = _latest_review(session, segment_id, field)
        if review is not None:
            secondary = tuple(json.loads(review.secondary_json))
            chosen = {review.primary_id, *secondary} - {None}
            stale = bool(chosen - set(_allowed(snapshot, field)))
            source = "stale_review" if stale else "review"
            found[field] = FieldLabels(field, review.primary_id, secondary, source)
        elif field in machine:
            primary, rest = machine[field]
            found[field] = FieldLabels(field, primary, tuple(rest), "machine")
        else:
            found[field] = FieldLabels(field, None, (), "none")
    return found


def review_queue(session: Session, taxonomy_version: str) -> list[ClassificationRow]:
    """Newest ``review_required`` row per segment, unless every field has a review since."""
    rows = session.scalars(
        select(ClassificationRow)
        .where(
            ClassificationRow.taxonomy_version == taxonomy_version,
            ClassificationRow.state == REVIEW_REQUIRED,
        )
        .order_by(ClassificationRow.segment_id, ClassificationRow.updated_at.desc())
    ).all()
    queue = []
    seen: set[str] = set()
    for row in rows:
        if row.segment_id in seen:
            continue
        seen.add(row.segment_id)
        flagged = _flagged_fields(row)
        decided = {
            f
            for f in flagged
            if (r := _latest_review(session, row.segment_id, f)) is not None
            and _aware(r.created_at) >= _aware(row.updated_at)
        }
        if not flagged or decided != flagged:
            queue.append(row)
    return queue


def _flagged_fields(row: ClassificationRow) -> set[str]:
    # The problem strings start with the field name ("topic: 2 primaries",
    # "projects.proj_x: ..."); a general flag ("flagged: ...") means all.
    fields = set()
    for problem in json.loads(row.problems_json):
        head = problem.split(":", 1)[0].split(".", 1)[0]
        if head in FIELDS:
            fields.add(head)
        else:
            return set(FIELDS)
    return fields


def _aware(value: datetime) -> datetime:
    # SQLite returns naive datetimes; they were written in UTC.
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _allowed(snapshot: TaxonomySnapshot, field: str) -> tuple[str, ...]:
    if field == PROJECTS_FIELD:
        return snapshot.project_ids()
    return snapshot.allowed_ids(Dimension(field))


def _latest_review(session: Session, segment_id: str, field: str) -> ClassificationReviewRow | None:
    return session.scalar(
        select(ClassificationReviewRow)
        .where(
            ClassificationReviewRow.segment_id == segment_id,
            ClassificationReviewRow.field == field,
        )
        .order_by(ClassificationReviewRow.sequence.desc())
    )
