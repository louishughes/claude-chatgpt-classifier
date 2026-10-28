"""Score a workspace against a private answer key, numbers only (EVAL-004 on real data).

The real golden set lives only on the owner's PC, in the git-ignored
workspace. This scores the knowledge records of the golden set's chats
in *that* workspace against it, so the real extraction baseline can be
made where the data is, and only the numbers leave the machine.

By default the rule extractors run first on just the golden set's chats
(each piece of work is done once: re-running repeats nothing). Records
made earlier by any other stage are scored too, since they are part of
what the engine would show. ``run_rules=False`` scores only what is
already there.

The report prints the key's version, its SHA-256 and who reviewed it
(LEG-002, REV-012), so a number can never pass for an owner verdict.

Talking points:
    - "On my own PC, one command scores the engine against my private
      answer key and writes a report with numbers only."
    - "The report says which key it used and that an AI reviewed it, not me."
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.evaluation.extraction_eval import (
    ExtractionReport,
    evaluate_extraction,
    scored_records,
)
from knowledge_engine.evaluation.gold import load_gold
from knowledge_engine.evaluation.report_labels import ReviewerKind, key_from_file


@dataclass(frozen=True)
class WorkspaceScore:
    """The report, plus how much of the key was found in the workspace."""

    report: ExtractionReport
    key_conversations: int
    found_conversations: int
    rules_run: int


def score_extraction(
    session: Session,
    gold_path: Path,
    reviewer: ReviewerKind,
    *,
    review_file: Path | None = None,
    run_rules: bool = True,
) -> WorkspaceScore:
    """Score the golden set's chats in this workspace. The caller commits.

    Args:
        session: The workspace that imported the chats the key names.
        gold_path: The private key (only read).
        reviewer: Who reviewed the key.
        review_file: The review record, whose hash the report prints.
        run_rules: Run the rule extractors on the key's chats first.
    """
    from knowledge_engine.evaluation.semantic_smoke import _rule_extractors
    from knowledge_engine.extraction import actions, decisions, entities, preferences
    from knowledge_engine.extraction.evidence import VALIDATOR_VERSION
    from knowledge_engine.extraction.runner import run
    from knowledge_engine.extraction.store import KnowledgeRecordRow, load
    from knowledge_engine.extraction.text import segment_extraction_messages
    from knowledge_engine.importer.records import ConversationRow
    from knowledge_engine.rendering.transcript import load_conversation
    from knowledge_engine.segmentation.overrides import load_segments
    from knowledge_engine.segmentation.segmenter import truncation_count

    gold = load_gold(gold_path)
    wanted = {c.native_conversation_id for c in gold.conversations}
    ids = session.scalars(
        select(ConversationRow.conversation_id)
        .where(ConversationRow.native_conversation_id.in_(sorted(wanted)))
        .order_by(ConversationRow.native_conversation_id)
    ).all()
    conversations = [load_conversation(session, c) for c in ids]
    segments = {c.conversation_id: load_segments(session, c) for c in conversations}
    rules_run = 0
    if run_rules:
        work = [
            (seg.segment_id, segment_extraction_messages(conv, seg))
            for conv in conversations
            for seg in segments[conv.conversation_id]
        ]
        rules_run = len(run(session, work, _rule_extractors(session, conversations)).done)
        session.flush()
    revisions = {r for c in conversations for r in c.revisions.values()}
    records = [
        record
        for record in (
            load(session, record_id)
            for record_id in session.scalars(
                select(KnowledgeRecordRow.record_id).order_by(KnowledgeRecordRow.record_id)
            )
        )
        if any(ref.revision_id in revisions for ref in record.evidence)
    ]
    lengths = {
        c.native_conversation_id: sum(len(n.text) for n in c.messages.values())
        for c in conversations
    }
    versions = {
        "decisions": decisions.EXTRACTOR_VERSION,
        "preferences": preferences.EXTRACTOR_VERSION,
        "actions": actions.EXTRACTOR_VERSION,
        "entities": entities.EXTRACTOR_VERSION,
        "validator": VALIDATOR_VERSION,
    }
    report = evaluate_extraction(
        gold,
        scored_records(session, records),
        versions,
        key=key_from_file(gold_path, reviewer, review_file),
        lengths=lengths,
        truncation_count=truncation_count([s for v in segments.values() for s in v]),
    )
    return WorkspaceScore(report, len(wanted), len(conversations), rules_run)
