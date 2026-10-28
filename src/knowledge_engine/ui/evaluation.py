"""Data for the evaluation dashboard (UI-006). Read only.

Louis wants to judge the engine's output without labelling anything
himself. So this module shows, side by side:

* **every output** the engine stored (knowledge records, classifications,
  conversation links, vocabulary proposals, model requests), counted by
  state;
* **scores** against a private answer key, using the exact pairing that
  ``evaluate_extraction`` (EVAL-004) counts, so the page and the report
  can never disagree;
* **one output at a time**: its quotes, what the automatic evidence check
  says today, who changed its trust and why, and how it compares with the
  answer key, attribute by attribute;
* **segment labels**: each answer-key segment beside the labels stored for
  the segment holding it, paired exactly as EVAL-003 pairs them;
* **model requests**: the ledger by stage, provider and state (counts only).

Every score carries the answer key's name, fingerprint and the label from
``report_labels`` saying who checked the key, e.g. "AI check (not
owner-verified)". The key file is only read, never copied, and nothing
here runs an extractor or calls a model.

Talking points:
    - "The dashboard reuses the evaluator's own matching, so a number on
      the page is the same number in the report."
    - "Every score says who checked the answer key, and it's never
      dressed up as my approval."
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from knowledge_engine.classification.classifier import PENDING, REVIEW_REQUIRED
from knowledge_engine.classification.schema import Rank
from knowledge_engine.classification.store import (
    ClassificationLabelRow,
    ClassificationReviewRow,
    ClassificationRow,
)
from knowledge_engine.evaluation.classification_eval import (
    Predicted,
    evaluate_classification,
    match_classification,
)
from knowledge_engine.evaluation.extraction_eval import (
    ExtractionReport,
    Matching,
    ScoredRecord,
    evaluate_extraction,
    match_extraction,
    scored_records,
)
from knowledge_engine.evaluation.gold import FIELDS, GoldRecord, GoldSet, load_gold
from knowledge_engine.evaluation.report_labels import AnswerKey, ReviewerKind, key_from_file
from knowledge_engine.extraction.evidence import check_record, revision_text
from knowledge_engine.extraction.records import KnowledgeRecord, RecordType, Trust
from knowledge_engine.extraction.store import VALIDATOR, KnowledgeRecordEventRow, KnowledgeRecordRow
from knowledge_engine.importer.records import ConversationRow, MessageNodeRow
from knowledge_engine.providers.ledger import ModelRequestRow
from knowledge_engine.relationships.store import ConversationRelationshipRow
from knowledge_engine.rendering.transcript import message_anchor
from knowledge_engine.taxonomy.registry import TaxonomyProposalRow
from knowledge_engine.ui.registries import places
from knowledge_engine.ui.review import TRUST_ORDER, TRUST_WORDS

# What each verdict means, in the words the pages print.
VERDICTS = {
    "matched": "matches the answer key",
    "extra": "not in the answer key (counts against precision)",
    "forbidden": "the answer key says this must never be claimed",
    "unscored": "not scored: this chat isn't annotated for records",
    "rejected": "rejected, so not scored",
    "missed": "expected by the answer key, but nothing produced it",
    "no_key": "no answer key loaded",
}
_VALIDATOR_WORDS = "automatic evidence check (code, not a person)"


@dataclass(frozen=True)
class KeySource:
    """Where the private answer key is and who checked it (from ``ke ui --gold``).

    Attributes:
        gold_path: The key file. Only read; it stays in the git-ignored workspace.
        reviewer: Who reviewed the key (``owner`` only if Louis did).
        review_file: The review record, whose hash the page prints.
    """

    gold_path: Path
    reviewer: ReviewerKind
    review_file: Path | None = None


@dataclass(frozen=True)
class _Scoring:
    gold: GoldSet
    key: AnswerKey
    scored: list[ScoredRecord]
    matching: Matching


def _load_key(source: KeySource | None) -> tuple[GoldSet, AnswerKey] | str | None:
    # Returns the key, an error sentence, or None when no key was given.
    if source is None:
        return None
    try:
        gold = load_gold(source.gold_path)
        key = key_from_file(source.gold_path, source.reviewer, source.review_file)
        key.lines()  # refuses a key without version, hash or a backed review claim
    except FileNotFoundError:
        return "The answer key file (or its review file) wasn't found."
    except (ValidationError, ValueError):
        return "The answer key couldn't be read: it isn't a valid gold-v1 file or review claim."
    return gold, key


def _score(session: Session, gold: GoldSet, key: AnswerKey) -> _Scoring:
    # Load every stored record, then keep those quoting the key's chats.
    # Reading all records is fine at personal-archive scale (hundreds to a
    # few thousand); it keeps this the same set the scorer sees.
    records = [
        KnowledgeRecord.model_validate_json(row.record_json)
        for row in session.scalars(
            select(KnowledgeRecordRow).order_by(KnowledgeRecordRow.record_id)
        )
    ]
    wanted = {c.native_conversation_id for c in gold.conversations}
    scored = [s for s in scored_records(session, records) if s.native_conversation_id in wanted]
    return _Scoring(gold, key, scored, match_extraction(gold, scored))


def _key_view(key: AnswerKey) -> dict[str, Any]:
    return {
        "heading": key.heading,
        "label": key.label,
        "kind": key.reviewer_kind.value,
        "version": key.version,
        "sha256": key.sha256,
        "review_sha256": key.review_sha256,
    }


def _versions(scored: list[ScoredRecord]) -> dict[str, str]:
    # Which extractor versions made the scored records, read from their own
    # provenance (the dashboard never runs an extractor to find out).
    found: dict[str, set[str]] = defaultdict(set)
    for item in scored:
        p = item.record.provenance
        if p is not None:
            found[p.stage_id].add(p.extractor_version)
    return {stage: ", ".join(sorted(v)) for stage, v in sorted(found.items())}


def _counts(session: Session, column: Any) -> list[tuple[str, int]]:
    return [
        (str(value), int(n))
        for value, n in session.execute(
            select(column, func.count()).group_by(column).order_by(column)
        )
    ]


def overview(session: Session, source: KeySource | None) -> dict[str, Any]:
    """Counts of every output, review outcomes, and scores against the key."""
    by_type_trust: dict[str, Counter[str]] = defaultdict(Counter)
    for record_type, trust, n in session.execute(
        select(KnowledgeRecordRow.record_type, KnowledgeRecordRow.trust, func.count()).group_by(
            KnowledgeRecordRow.record_type, KnowledgeRecordRow.trust
        )
    ):
        by_type_trust[record_type][trust] = int(n)
    records = [
        (t, [by_type_trust[t][trust] for trust in TRUST_ORDER], sum(by_type_trust[t].values()))
        for t in sorted(by_type_trust)
    ]
    reviewer_outcomes = _counts_where_reviewer(session)
    values: dict[str, Any] = {
        "trust_order": [(t, TRUST_WORDS[t]) for t in TRUST_ORDER],
        "records": records,
        "record_total": sum(total for _, _, total in records),
        "classifications": _counts(session, ClassificationRow.state),
        "label_reviews": int(
            session.scalar(select(func.count()).select_from(ClassificationReviewRow)) or 0
        ),
        "relationships": _counts(session, ConversationRelationshipRow.review_state),
        "proposals": _counts(session, TaxonomyProposalRow.status),
        "model_requests": _counts(session, ModelRequestRow.state),
        "reviewer_outcomes": reviewer_outcomes,
        "validator_outcomes": _counts_validator(session),
        "model_runs": model_runs(session),
        "key": None,
        "key_error": None,
        "report": None,
    }
    loaded = _load_key(source)
    if isinstance(loaded, str):
        values["key_error"] = loaded
    elif loaded is not None:
        gold, key = loaded
        scoring = _score(session, gold, key)
        report = evaluate_extraction(gold, scoring.scored, _versions(scoring.scored), key=key)
        values["key"] = _key_view(key)
        values["report"] = _report_view(report, gold)
    return values


def _counts_where_reviewer(session: Session) -> list[tuple[str, int]]:
    # Named reviewers' decisions only: not the extractor's "proposed" event
    # and not the automatic validator, which is counted separately.
    return [
        (str(to), int(n))
        for to, n in session.execute(
            select(KnowledgeRecordEventRow.to_trust, func.count())
            .where(KnowledgeRecordEventRow.actor != VALIDATOR)
            .where(KnowledgeRecordEventRow.from_trust.is_not(None))
            .group_by(KnowledgeRecordEventRow.to_trust)
            .order_by(KnowledgeRecordEventRow.to_trust)
        )
    ]


def _counts_validator(session: Session) -> list[tuple[str, int]]:
    return [
        (str(to), int(n))
        for to, n in session.execute(
            select(KnowledgeRecordEventRow.to_trust, func.count())
            .where(KnowledgeRecordEventRow.actor == VALIDATOR)
            .group_by(KnowledgeRecordEventRow.to_trust)
            .order_by(KnowledgeRecordEventRow.to_trust)
        )
    ]


def _report_view(report: ExtractionReport, gold: GoldSet) -> dict[str, Any]:
    total = report.total
    rows = [
        {
            "name": name,
            "tp": s.true_pos,
            "fp": s.false_pos,
            "fn": s.false_neg,
            "precision": s.precision,
            "recall": s.recall,
            "f1": s.f1,
        }
        for name, s in [*sorted(report.by_type.items()), ("all types", total)]
    ]
    return {
        "gold": report.gold,
        "eval_version": report.eval_version,
        "versions": report.versions,
        "conversations": len(gold.conversations),
        "annotated": sum(1 for c in gold.conversations if c.records_annotated),
        "rows": rows,
        "agreement": [(n, a.checked, a.right, a.rate) for n, a in report.agreement.items()],
        "produced": report.produced,
        "unscored": report.unscored,
        "anchor_validity": report.anchor_validity,
        "forbidden_produced": len(report.forbidden_produced),
        "forbidden_in_truth": len(report.forbidden_in_truth),
        "unsupported": len(report.unsupported_truth_decisions),
        "passed": report.passed,
    }


def _verdicts(scoring: _Scoring | None) -> dict[str, str]:
    # record_id -> verdict key. Forbidden wins over the others: it's the
    # most serious thing the key can say about a record.
    if scoring is None:
        return {}
    verdict = {item.record.record_id: "unscored" for item in scoring.scored}
    verdict |= {item.record.record_id: "extra" for item in scoring.matching.extra}
    verdict |= {item.record.record_id: "matched" for _, _, item in scoring.matching.matched}
    verdict |= {item.record.record_id: "forbidden" for item, _ in scoring.matching.forbidden}
    verdict |= {
        item.record.record_id: "rejected"
        for item in scoring.scored
        if item.record.trust is Trust.REJECTED
    }
    return verdict


def _message_places(
    session: Session, wanted: set[tuple[str, str]]
) -> dict[tuple[str, str], tuple[str, str, str]]:
    # (native conversation, native message) -> (conversation_id, title, anchor),
    # so a missed record can link to the message the key names.
    if not wanted:
        return {}
    natives = sorted({c for c, _ in wanted})
    rows = session.execute(
        select(
            ConversationRow.native_conversation_id,
            MessageNodeRow.native_node_id,
            ConversationRow.conversation_id,
            ConversationRow.title,
            MessageNodeRow.node_key,
        )
        .join(MessageNodeRow, MessageNodeRow.conversation_id == ConversationRow.conversation_id)
        .where(ConversationRow.native_conversation_id.in_(natives))
    )
    return {
        (conv, node): (conversation_id, title or "Untitled conversation", message_anchor(key))
        for conv, node, conversation_id, title, key in rows
        if (conv, node) in wanted
    }


def _expected_view(expected: GoldRecord, place: tuple[str, str, str] | None) -> dict[str, Any]:
    return {
        "type": expected.record_type.value,
        "actor": expected.actor.value,
        "acceptance": expected.acceptance.value if expected.acceptance else None,
        "attributed_to": expected.attributed_to,
        "strength": expected.strength.value if expected.strength else None,
        "message_id": expected.message_id,
        "place": place,
    }


def outputs(
    session: Session, source: KeySource | None, verdict: str = "", record_type: str = ""
) -> dict[str, Any]:
    """Every knowledge record with its verdict, plus the expected records nobody found."""
    loaded = _load_key(source)
    scoring = None
    if isinstance(loaded, tuple):
        scoring = _score(session, *loaded)
    verdicts = _verdicts(scoring)
    query = select(KnowledgeRecordRow).order_by(
        KnowledgeRecordRow.record_type, KnowledgeRecordRow.record_id
    )
    if record_type in {t.value for t in RecordType}:
        query = query.where(KnowledgeRecordRow.record_type == record_type)
    listed = []
    for row in session.scalars(query):
        record = KnowledgeRecord.model_validate_json(row.record_json)
        mark = verdicts.get(record.record_id, "unscored" if scoring else "no_key")
        if scoring is not None and record.trust is Trust.REJECTED:
            mark = "rejected"
        if verdict and verdict != mark:
            continue
        listed.append(
            {
                "record_id": record.record_id,
                "type": record.record_type.value,
                "assertion": record.assertion,
                "actor": record.actor.value,
                "trust": record.trust.value,
                "verdict": mark,
                "verdict_words": VERDICTS[mark],
            }
        )
    missed = []
    if scoring is not None and verdict in ("", "missed"):
        wanted = {(conv, exp.message_id) for conv, exp in scoring.matching.missed}
        where = _message_places(session, wanted)
        missed = [
            _expected_view(exp, where.get((conv, exp.message_id)))
            for conv, exp in scoring.matching.missed
            if not record_type or exp.record_type.value == record_type
        ]
    tally = Counter(item["verdict"] for item in listed)
    tally["missed"] = len(missed)
    return {
        "records": listed,
        "missed": missed,
        "tally": [(v, tally.get(v, 0), VERDICTS[v]) for v in VERDICTS if tally.get(v)],
        "verdicts": [v for v in VERDICTS if v != "no_key"],
        "types": sorted(t.value for t in RecordType),
        "verdict": verdict if verdict in VERDICTS else "",
        "record_type": record_type if record_type in {t.value for t in RecordType} else "",
        "key": _key_view(scoring.key) if scoring else None,
        "key_error": loaded if isinstance(loaded, str) else None,
    }


def output(session: Session, source: KeySource | None, record_id: str) -> dict[str, Any] | None:
    """One knowledge record: quotes, evidence check, history and the key's view of it."""
    row = session.get(KnowledgeRecordRow, record_id)
    if row is None:
        return None
    record = KnowledgeRecord.model_validate_json(row.record_json)
    where = places(session, [ref.revision_id for ref in record.evidence])
    quotes = []
    for ref in record.evidence:
        found = revision_text(session, ref.revision_id)
        quotes.append(
            {
                "text": found[0][ref.start : ref.end] if found else None,
                "speaker": ref.actor.value,
                "place": where.get(ref.revision_id),
                "span": f"{ref.start}–{ref.end}",
            }
        )
    check = check_record(session, record)
    history = [
        {
            "at": event.at,
            "change": f"{event.from_trust or 'new'} → {event.to_trust}",
            "who": _VALIDATOR_WORDS if event.actor == VALIDATOR else event.actor,
            "is_validator": event.actor == VALIDATOR,
            "note": event.note,
        }
        for event in session.scalars(
            select(KnowledgeRecordEventRow)
            .where(KnowledgeRecordEventRow.record_id == record_id)
            .order_by(KnowledgeRecordEventRow.at, KnowledgeRecordEventRow.event_id)
        )
    ]
    loaded = _load_key(source)
    comparison = None
    if isinstance(loaded, tuple):
        scoring = _score(session, *loaded)
        comparison = _compare_view(session, scoring, record)
    p = record.provenance
    return {
        "record": {
            "record_id": record.record_id,
            "type": record.record_type.value,
            "assertion": record.assertion,
            "actor": record.actor.value,
            "acceptance": record.acceptance.value,
            "attributed_to": record.attributed_to,
            "strength": record.strength.value if record.strength else None,
            "trust": record.trust.value,
            "trust_words": TRUST_WORDS[record.trust.value],
            "why": record.review_reason,
            "reviewer": record.reviewer,
        },
        "made_by": (
            {
                "stage": p.stage_id,
                "version": p.extractor_version,
                "provider": p.provider_id,
                "model": p.served_model,
            }
            if p
            else None
        ),
        "quotes": quotes,
        "check": {
            "verdict": check.verdict.value,
            "problems": [pr.code for pr in check.problems],
            "version": check.validator_version,
        },
        "history": history,
        "comparison": comparison,
        "key": _key_view(loaded[1]) if isinstance(loaded, tuple) else None,
        "key_error": loaded if isinstance(loaded, str) else None,
    }


def _compare_view(session: Session, scoring: _Scoring, record: KnowledgeRecord) -> dict[str, Any]:
    mark = _verdicts(scoring).get(record.record_id, "unscored")
    expected = next(
        (
            (conv, exp)
            for conv, exp, item in scoring.matching.matched
            if item.record.record_id == record.record_id
        ),
        None,
    )
    view: dict[str, Any] = {"verdict": mark, "verdict_words": VERDICTS[mark], "rows": []}
    if expected is not None:
        conv, exp = expected
        where = _message_places(session, {(conv, exp.message_id)})
        view["expected"] = _expected_view(exp, where.get((conv, exp.message_id)))
        # Attribute by attribute, as the evaluator compares them. "not stated"
        # means the key doesn't say, so any answer is fine.
        pairs = [
            ("type", exp.record_type.value, record.record_type.value),
            ("actor", exp.actor.value, record.actor.value),
            (
                "acceptance",
                exp.acceptance.value if exp.acceptance else None,
                record.acceptance.value,
            ),
            ("attributed_to", exp.attributed_to, record.attributed_to),
            (
                "strength",
                exp.strength.value if exp.strength else None,
                record.strength.value if record.strength else None,
            ),
        ]
        for name, want, got in pairs:
            optional = name in ("acceptance", "strength") and want is None
            view["rows"].append(
                {
                    "name": name,
                    "expected": "not stated" if optional else (want or "none"),
                    "produced": got or "none",
                    "agrees": optional or want == got,
                }
            )
    view["forbidden"] = [
        {"reason": rule.reason, "type": rule.record_type.value, "actor": rule.actor.value}
        for item, rule in scoring.matching.forbidden
        if item.record.record_id == record.record_id
    ]
    return view


# ---------------------------------------------------------------------------
# Classifications (segment labels) against the answer key's segment labels.


def _label_names(session: Session, gold: GoldSet) -> dict[str, str]:
    # ID -> readable name, so the page says "Godot" rather than a random ID.
    # A synthetic key brings its own vocabulary; a real one uses the
    # published version it names. No names is fine: the page shows IDs.
    snapshot = None
    if gold.terms or gold.projects:
        snapshot = gold.snapshot()
    else:
        from knowledge_engine.taxonomy.registry import TaxonomyRegistry

        try:
            snapshot = TaxonomyRegistry(session).snapshot(gold.taxonomy_version)
        except KeyError:
            return {}
    names = {t.term_id: t.label for t in snapshot.terms}
    names |= {p.project_id: p.name for p in snapshot.projects}
    return names


def _stored_predictions(
    session: Session, gold: GoldSet
) -> tuple[list[Predicted], dict[str, ClassificationRow]]:
    # The newest finished classification of every segment of the key's
    # chats, under the key's own taxonomy version (labels from another
    # version can't be compared). Nothing is classified here.
    from knowledge_engine.rendering.transcript import load_conversation
    from knowledge_engine.segmentation.overrides import load_segments

    natives = sorted({c.native_conversation_id for c in gold.conversations if c.segments})
    predicted: list[Predicted] = []
    rows: dict[str, ClassificationRow] = {}
    for conversation_id in session.scalars(
        select(ConversationRow.conversation_id).where(
            ConversationRow.native_conversation_id.in_(natives)
        )
    ):
        conversation = load_conversation(session, conversation_id)
        chars = sum(len(node.text) for node in conversation.messages.values())
        for segment in load_segments(session, conversation):
            row = session.scalar(
                select(ClassificationRow)
                .where(
                    ClassificationRow.segment_id == segment.segment_id,
                    ClassificationRow.taxonomy_version == gold.taxonomy_version,
                    ClassificationRow.state != PENDING,
                )
                .order_by(ClassificationRow.updated_at.desc(), ClassificationRow.classification_id)
            )
            if row is None:
                continue
            grouped: dict[str, tuple[str | None, list[str]]] = {}
            for label in session.scalars(
                select(ClassificationLabelRow)
                .where(ClassificationLabelRow.classification_id == row.classification_id)
                .order_by(ClassificationLabelRow.label_id)
            ):
                primary, rest = grouped.get(label.field, (None, []))
                if label.rank == Rank.PRIMARY.value:
                    primary = label.target_id
                else:
                    rest.append(label.target_id)
                grouped[label.field] = (primary, rest)
            rows[segment.segment_id] = row
            predicted.append(
                Predicted(
                    segment_id=segment.segment_id,
                    native_conversation_id=conversation.native_conversation_id,
                    messages=segment.messages,
                    labels={k: (p, tuple(r)) for k, (p, r) in grouped.items()},
                    review=row.state == REVIEW_REQUIRED,
                    chat_chars=chars,
                )
            )
    return predicted, rows


def _labels_text(primary: str | None, secondary: tuple[str, ...], names: dict[str, str]) -> str:
    if primary is None and not secondary:
        return "none"
    shown = [names.get(primary, primary)] if primary else []
    shown += [f"{names.get(s, s)} (secondary)" for s in secondary]
    return ", ".join(shown)


def classifications(session: Session, source: KeySource | None) -> dict[str, Any]:
    """Each answer-key segment beside the stored labels of the segment holding it."""
    loaded = _load_key(source)
    values: dict[str, Any] = {
        "key": None,
        "key_error": loaded if isinstance(loaded, str) else None,
        "report": None,
        "segments": [],
        "stored": _counts(session, ClassificationRow.state),
    }
    if not isinstance(loaded, tuple):
        return values
    gold, key = loaded
    values["key"] = _key_view(key)
    if not any(c.segments for c in gold.conversations):
        values["no_labels"] = True  # e.g. the real key before a taxonomy is published
        return values
    predicted, rows = _stored_predictions(session, gold)
    methods = sorted({row.method for row in rows.values()})
    report = evaluate_classification(
        gold, predicted, {"classifier": ", ".join(methods) or "none stored"}, key=key
    )
    names = _label_names(session, gold)
    pairs = match_classification(gold, predicted)
    where = _message_places(session, {(conv, seg.first_message) for conv, seg, _ in pairs})
    for conv, segment, match in pairs:
        fields = []
        for name in FIELDS:
            want = segment.labels.get(name)
            want_primary = want.primary if want else None
            want_secondary = want.secondary if want else ()
            got_primary, got_secondary = match.labels.get(name, (None, ())) if match else (None, ())
            if not (want_primary or want_secondary or got_primary or got_secondary):
                continue
            fields.append(
                {
                    "name": name,
                    "expected": _labels_text(want_primary, want_secondary, names),
                    "produced": _labels_text(got_primary, got_secondary, names),
                    "primary_right": want_primary == got_primary,
                    "same_set": {want_primary, *want_secondary} - {None}
                    == {got_primary, *got_secondary} - {None},
                }
            )
        row = rows.get(match.segment_id) if match else None
        if match is None:
            verdict = "not classified (or not under this taxonomy version)"
        elif segment.ambiguous:
            verdict = (
                "sent to review, as it should be" if match.review else "should have gone to review"
            )
        elif all(f["same_set"] for f in fields):
            verdict = "matches the answer key"
        else:
            verdict = "differs from the answer key"
        values["segments"].append(
            {
                "place": where.get((conv, segment.first_message)),
                "ambiguous": segment.ambiguous,
                "fields": fields,
                "verdict": verdict,
                "good": verdict in ("matches the answer key", "sent to review, as it should be"),
                "state": row.state if row else None,
                "method": row.method if row else None,
                "provider": row.provider_id if row else None,
                "model": row.served_model if row else None,
                "problems": json.loads(row.problems_json) if row else [],
            }
        )
    values["report"] = {
        "taxonomy_version": report.taxonomy_version,
        "eval_version": report.eval_version,
        "versions": report.versions,
        "gold_segments": report.gold_segments,
        "unmatched": report.unmatched_segments,
        "flagged": report.ambiguous_flagged,
        "missed": report.ambiguous_missed,
        "fields": [
            (n, s.segments, s.precision, s.recall, s.micro_f1, s.macro_f1, s.primary_accuracy)
            for n, s in report.fields.items()
        ],
    }
    return values


def model_runs(session: Session) -> list[dict[str, Any]]:
    """The model-request ledger by stage and provider: no prompts, no answers."""
    found = session.execute(
        select(
            ModelRequestRow.stage_id,
            ModelRequestRow.provider_id,
            ModelRequestRow.state,
            func.count(),
            func.sum(ModelRequestRow.attempts),
            func.sum(ModelRequestRow.transient_failures),
            func.sum(ModelRequestRow.characters),
        )
        .group_by(ModelRequestRow.stage_id, ModelRequestRow.provider_id, ModelRequestRow.state)
        .order_by(ModelRequestRow.stage_id, ModelRequestRow.provider_id, ModelRequestRow.state)
    )
    return [
        {
            "stage": stage,
            "provider": provider,
            "state": state,
            "requests": int(n),
            "attempts": int(attempts or 0),
            "transient": int(transient or 0),
            "characters": int(chars or 0),
        }
        for stage, provider, state, n, attempts, transient, chars in found
    ]
