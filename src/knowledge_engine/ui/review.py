"""Data for the suggestions and reviews pages (UI-005). Read only.

Two views, so nothing an AI proposed can be mistaken for something decided:

* **Suggestions** (``/suggestions``): every knowledge record the extractors
  proposed, grouped by trust (candidate, review_required, supported,
  confirmed, rejected), each quote one click from its message.
* **Reviews** (``/reviews``): every decision a named reviewer made, and
  why: on knowledge records, taxonomy proposals, classification labels and
  conversation links. The owner delegated review to independent reviewer
  sessions, so these names are usually AI sessions; nothing here is shown
  as owner-approved. What the automatic evidence validator did is counted
  separately, never mixed in with people's decisions.

These functions only read. The pages have no forms and accept GET only.

Talking points:
    - "One page shows what the AI suggested and how far each suggestion
      got; another shows every reviewer decision and the reason given."
    - "Automatic checks and reviewer decisions are kept apart, and nothing
      claims to be my approval."
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from knowledge_engine.classification.store import ClassificationReviewRow
from knowledge_engine.extraction.records import KnowledgeRecord, RecordType, Trust
from knowledge_engine.extraction.store import VALIDATOR, KnowledgeRecordEventRow, KnowledgeRecordRow
from knowledge_engine.relationships.store import RelationshipReviewRow
from knowledge_engine.taxonomy.registry import TaxonomyProposalRow
from knowledge_engine.ui.registries import places

TRUST_ORDER = [
    t.value
    for t in (
        Trust.REVIEW_REQUIRED,
        Trust.CANDIDATE,
        Trust.SUPPORTED,
        Trust.CONFIRMED,
        Trust.REJECTED,
    )
]
TRUST_WORDS = {
    Trust.CANDIDATE.value: "proposed, not checked yet",
    Trust.REVIEW_REQUIRED.value: "waiting for a reviewer",
    Trust.SUPPORTED.value: "evidence checked",
    Trust.CONFIRMED.value: "confirmed by a reviewer",
    Trust.REJECTED.value: "rejected",
}


def suggestions(
    session: Session, trust: str = "", record_type: str = "", limit: int = 200
) -> dict[str, Any]:
    """Knowledge records by trust, newest first, with links to their quotes.

    Args:
        session: A read session.
        trust: Only this trust state ("" for all).
        record_type: Only this record type ("" for all).
        limit: Most records listed.
    """
    # Built from pairs on purpose: dict() on a Result would read it as a mapping.
    counts = {
        trust_value: int(n)
        for trust_value, n in session.execute(
            select(KnowledgeRecordRow.trust, func.count()).group_by(KnowledgeRecordRow.trust)
        )
    }
    query = select(KnowledgeRecordRow)
    if trust in TRUST_WORDS:
        query = query.where(KnowledgeRecordRow.trust == trust)
    if record_type in {t.value for t in RecordType}:
        query = query.where(KnowledgeRecordRow.record_type == record_type)
    rows = session.scalars(
        query.order_by(KnowledgeRecordRow.updated_at.desc(), KnowledgeRecordRow.record_id).limit(
            limit
        )
    ).all()
    records = [KnowledgeRecord.model_validate_json(row.record_json) for row in rows]
    where = places(session, [ref.revision_id for r in records for ref in r.evidence])
    listed = []
    for record in records:
        quotes = [
            {"place": where[ref.revision_id], "speaker": ref.actor.value}
            for ref in record.evidence
            if ref.revision_id in where
        ]
        listed.append(
            {
                "record_id": record.record_id,
                "type": record.record_type.value,
                "assertion": record.assertion,
                "actor": record.actor.value,
                "attributed_to": record.attributed_to,
                "acceptance": record.acceptance.value,
                "trust": record.trust.value,
                "trust_words": TRUST_WORDS[record.trust.value],
                "why": record.review_reason,
                "reviewer": record.reviewer,
                "extractor": record.provenance.stage_id if record.provenance else None,
                "quotes": quotes,
            }
        )
    return {
        "counts": [(t, counts.get(t, 0), TRUST_WORDS[t]) for t in TRUST_ORDER],
        "total": sum(counts.values()),
        "records": listed,
        "types": sorted(t.value for t in RecordType),
        "trust": trust if trust in TRUST_WORDS else "",
        "record_type": record_type if record_type in {t.value for t in RecordType} else "",
    }


def reviews(session: Session, limit: int = 200) -> dict[str, Any]:
    """Every named reviewer's decision and its reason, plus what the validator did."""
    people = session.execute(
        select(
            KnowledgeRecordEventRow, KnowledgeRecordRow.record_type, KnowledgeRecordRow.record_json
        )
        .join(KnowledgeRecordRow, KnowledgeRecordRow.record_id == KnowledgeRecordEventRow.record_id)
        .where(KnowledgeRecordEventRow.actor != VALIDATOR)
        .where(KnowledgeRecordEventRow.from_trust.is_not(None))  # not the extractor's "proposed"
        .order_by(KnowledgeRecordEventRow.at.desc(), KnowledgeRecordEventRow.event_id.desc())
        .limit(limit)
    ).all()
    record_decisions = [
        {
            "record_id": event.record_id,
            "type": record_type,
            "assertion": json.loads(record_json).get("assertion"),
            "change": f"{event.from_trust} → {event.to_trust}",
            "reviewer": event.actor,
            "note": event.note,
            "at": event.at,
        }
        for event, record_type, record_json in people
    ]
    validator = Counter[str]()
    problems = Counter[str]()
    for to_trust, problems_json in session.execute(
        select(KnowledgeRecordEventRow.to_trust, KnowledgeRecordEventRow.problems_json).where(
            KnowledgeRecordEventRow.actor == VALIDATOR
        )
    ):
        validator[to_trust] += 1
        problems.update(json.loads(problems_json))
    taxonomy = [
        {
            "operation": row.operation,
            "status": row.status,
            "proposer": row.proposer,
            "reviewer": row.reviewer,
            "note": row.decision_note,
            "at": row.decided_at,
        }
        for row in session.scalars(
            select(TaxonomyProposalRow)
            .where(TaxonomyProposalRow.status != "open")
            .order_by(TaxonomyProposalRow.decided_at.desc())
            .limit(limit)
        )
    ]
    open_proposals = session.scalar(
        select(func.count())
        .select_from(TaxonomyProposalRow)
        .where(TaxonomyProposalRow.status == "open")
    )
    labels = [
        {
            "segment_id": row.segment_id,
            "field": row.field,
            "primary": row.primary_id,
            "secondary": json.loads(row.secondary_json),
            "version": row.taxonomy_version,
            "reviewer": row.reviewer,
            "note": row.note,
            "at": row.created_at,
        }
        for row in session.scalars(
            select(ClassificationReviewRow)
            .order_by(ClassificationReviewRow.created_at.desc())
            .limit(limit)
        )
    ]
    links = [
        {
            "relationship_id": row.relationship_id,
            "change": f"{row.from_state} → {row.to_state}",
            "action": row.action,
            "reviewer": row.reviewer,
            "note": row.note,
            "at": row.at,
        }
        for row in session.scalars(
            select(RelationshipReviewRow).order_by(RelationshipReviewRow.at.desc()).limit(limit)
        )
    ]
    return {
        "record_decisions": record_decisions,
        "validator": sorted(validator.items()),
        "problems": problems.most_common(),
        "taxonomy": taxonomy,
        "open_proposals": int(open_proposals or 0),
        "labels": labels,
        "links": links,
    }
