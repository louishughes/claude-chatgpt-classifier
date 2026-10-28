"""Semantic batch smoke test: segment, classify and extract N conversations (EVAL-011).

EVAL-010 proved import and rendering at 50 and 100 conversations. This
does the same for the semantic stages, on an already-imported workspace:

1. **segment** every conversation (NRM-004);
2. **classify** every segment through the model path (``ModelStageRunner``
   with a ``RunBudget``), so the cache, the one repair, the call cap, the
   batch size and the timeout are all exercised;
3. **extract** with the rule extractors (EXT-008 runner), first
   **interrupted** part-way by a stage deadline, then **resumed**;
4. classify again and compare: **run-to-run stability**.

The provider is ``keyword_backed_fake``: a fake model that answers with
the free keyword classifier's answer, with faults injected on purpose.
Every ``invalid_every``-th request first answers with broken JSON (so it
needs its repair) and every ``silent_every``-th request never answers (so
it times out). No data leaves the machine and nothing costs money. A run
with a pinned real provider under a cost cap is a separate, opt-in step
for the owner; it is not part of this module.

The report holds counts, rates and pass/fail checks only. It **passes**
when:

* every segment ends ``done`` or with a *recorded* bounded outcome
  (``review_required`` with an error code, or ``capped`` and logged);
* every stored model output still validates (zero unvalidated outputs);
* the resumed extraction repeats none of the stage keys done before the
  interruption, and finishes everything;
* a stability figure is produced.

Talking points:
    - "The smoke test pushes 50 and 100 chats through classification and
      extraction with a fake model that misbehaves on purpose, and checks
      every failure ends somewhere recorded."
    - "It interrupts extraction half-way and proves the restart doesn't
      redo anything."
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.classification.classifier import (
    DONE,
    PENDING,
    SegmentClassifier,
    segment_messages,
)
from knowledge_engine.classification.schema import STAGE_ID, output_model, segment_input
from knowledge_engine.evaluation.classification_eval import predicted_from, stability
from knowledge_engine.extraction import actions, decisions, entities, preferences
from knowledge_engine.extraction.runner import RuleExtractor, run
from knowledge_engine.extraction.text import ExtractionMessage, segment_extraction_messages
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.infrastructure.logs import EventLog, null_log
from knowledge_engine.orchestration.limits import Deadline, RunBudget
from knowledge_engine.providers.base import (
    FakeProvider,
    ModelRequest,
    ProviderIdentity,
    StructuredModelProvider,
)
from knowledge_engine.providers.ledger import (
    ModelOutputRow,
    ModelStageRunner,
    not_answered,
    schema_failures,
)
from knowledge_engine.rendering.transcript import StoredConversation, load_conversation
from knowledge_engine.segmentation.overrides import load_segments
from knowledge_engine.segmentation.segmenter import Segment
from knowledge_engine.settings import Capability, EgressPolicy, Limits
from knowledge_engine.taxonomy.registry import SnapshotTerm, TaxonomySnapshot

SMOKE_VERSION = "eval-011-v1"


def smoke_taxonomy() -> TaxonomySnapshot:
    """A tiny fixed vocabulary for plumbing runs (not a real taxonomy)."""
    terms = (
        SnapshotTerm("term_smoke_code", "topic", "Code", None, None, ("python", "code")),
        SnapshotTerm("term_smoke_image", "topic", "Images", None, None, ("image", "picture")),
        SnapshotTerm("term_smoke_question", "topic", "Questions", None, None, ("question",)),
    )
    content = json.dumps([[t.term_id, t.label, t.aliases] for t in terms])
    return TaxonomySnapshot("smoke-tax-1", hashlib.sha256(content.encode()).hexdigest(), terms, ())


@dataclass(frozen=True)
class Faults:
    """Which requests misbehave (0 turns a fault off)."""

    invalid_every: int = 7
    silent_every: int = 0


class LocalFakeProvider(FakeProvider):
    """The test fake, declared as never sending anything off the machine.

    ``FakeProvider`` counts as sending, so tests can prove the egress
    switch works. The smoke test must run with egress off, so this one says
    truthfully that it computes its answers locally.
    """

    @property
    def identity(self) -> ProviderIdentity:
        """A local fake text model."""
        return ProviderIdentity(
            "smoke-fake", Capability.TEXT_LLM, "smoke-fake-v1", sends_data=False
        )


def keyword_backed_fake(
    snapshot: TaxonomySnapshot,
    items: Sequence[tuple[StoredConversation, Segment]],
    faults: Faults,
) -> LocalFakeProvider:
    """A fake model answering with the keyword classifier's answer, plus faults."""
    keyword = SegmentClassifier(snapshot)
    answers: dict[str, str] = {}
    for (conv, seg), result in zip(items, keyword.classify(items), strict=True):
        if result.answer is not None:
            text = segment_input(segment_messages(conv, seg))
            answers[text] = result.answer.model_dump_json()
    order: dict[str, int] = {}

    def answer(request: ModelRequest) -> str | None:
        index = order.setdefault(request.input_text, len(order) + 1)
        if faults.silent_every and index % faults.silent_every == 0:
            return None
        if faults.invalid_every and index % faults.invalid_every == 0 and request.attempt == 1:
            return "Synthetic broken answer {"
        return answers.get(request.input_text, '{"needs_review": true}')

    return LocalFakeProvider(answer)


def run_semantic_smoke(
    session: Session,
    *,
    limit: int | None,
    limits: Limits,
    faults: Faults | None = None,
    interrupt_after: int | None = None,
    log: EventLog | None = None,
    snapshot: TaxonomySnapshot | None = None,
    provider: StructuredModelProvider | None = None,
    egress: EgressPolicy | None = None,
) -> dict[str, Any]:
    """Run the semantic stages on the first ``limit`` imported conversations.

    Args:
        session: An imported workspace (scratch copy recommended). The
            caller commits.
        limit: How many conversations, by native ID order (None for all).
        limits: Budgets: ``max_model_calls_per_run`` must allow the run.
        faults: Injected provider faults.
        interrupt_after: Interrupt the first extraction pass after this
            many runs (a step-counting deadline); None picks half.
        log: Structured event log (OPS-001).
        snapshot: The frozen vocabulary; ``smoke_taxonomy()`` by default.
        provider: A real provider instead of the faulty fake (the owner's
            one approved paid run). Its ``usage()`` goes in the report.
        egress: The egress switches; all off by default, which only a
            local provider passes.

    Returns:
        A JSON-ready report of counts, rates and checks. No text.
    """
    log = log or null_log()
    faults = faults or Faults()
    snapshot = snapshot or smoke_taxonomy()
    query = select(ConversationRow.conversation_id).order_by(ConversationRow.native_conversation_id)
    if limit is not None:
        query = query.limit(limit)
    conversations = [load_conversation(session, c) for c in session.scalars(query).all()]
    items = [(conv, seg) for conv in conversations for seg in load_segments(session, conv)]

    # Classification through the model path, under the run budget.
    budget = RunBudget(limits, log=log)
    if provider is None:
        provider = keyword_backed_fake(snapshot, items, faults)
    runner = ModelStageRunner(session, provider, egress or EgressPolicy(), log=log, budget=budget)
    classifier = SegmentClassifier(snapshot, runner=runner)
    first = classifier.classify(items)
    second = classifier.classify(items)  # collects the repairs
    late = datetime.now(UTC) + timedelta(seconds=limits.provider_timeout_s + 1)
    runner.clock = lambda: late  # anything still waiting has now timed out
    final = classifier.classify(items)
    states = Counter(r.state for r in final)
    capped = sorted({r.stage_key for r in final if r.state == PENDING})
    again = classifier.classify(items)  # everything answered comes from the cache
    stable = stability([predicted_from(items, final), predicted_from(items, again)])
    unanswered = not_answered(session, STAGE_ID)

    # Extraction, interrupted part-way and resumed.
    segments = _extraction_segments(session, conversations)
    extractors = _rule_extractors(session, conversations)
    total_runs = len(segments) * len(extractors)
    steps = interrupt_after if interrupt_after is not None else total_runs // 2
    counter = iter(range(10**9))
    deadline = Deadline(float(steps), clock=lambda: float(next(counter)))
    interrupted = run(session, segments, extractors, log=log, deadline=deadline)
    resumed = run(session, segments, extractors, log=log)
    repeated = sorted(set(interrupted.done) & set(resumed.done))

    unvalidated = _unvalidated_outputs(session, snapshot)
    recorded = states[DONE] + states["review_required"] + len(capped) == len(final)
    checks = {
        "every_segment_recorded": recorded
        and (not capped or "max_model_calls_per_run" in budget.reached),
        "zero_unvalidated_outputs": unvalidated == 0,
        "resume_repeats_nothing": not repeated
        and sorted(resumed.skipped) == sorted(interrupted.done)
        and not resumed.deferred,
        "extraction_bounded": not resumed.failed and not resumed.pending,
        "stability_reported": stable is not None,
    }
    return {
        "smoke_version": SMOKE_VERSION,
        "taxonomy_version": snapshot.version,
        "conversations": len(conversations),
        "segments": len(items),
        "classification": {
            "done": states[DONE],
            "review_required": states["review_required"],
            "capped": len(capped),
            "model_calls": budget.calls,
            "timeouts": unanswered["timeout"],
            "too_big": unanswered["too_big"],
            "limits_reached": sorted(set(budget.reached)),
            "first_pass_pending": sum(1 for r in first if r.state == PENDING),
            "second_pass_pending": sum(1 for r in second if r.state == PENDING),
            "schema": dict(schema_failures(session, STAGE_ID)),
        },
        "stability": stable,
        "extraction": {
            "runs": total_runs,
            "interrupted": {
                "done": len(interrupted.done),
                "deferred": len(interrupted.deferred),
                "records": interrupted.records,
            },
            "resumed": {
                "done": len(resumed.done),
                "skipped": len(resumed.skipped),
                "repeated": len(repeated),
                "failed": len(resumed.failed),
                "records": resumed.records,
            },
        },
        "unvalidated_outputs": unvalidated,
        "checks": checks,
        "passed": all(checks.values()),
        "provider": _usage(provider),
    }


def _usage(provider: StructuredModelProvider) -> dict[str, Any]:
    usage = getattr(provider, "usage", None)
    if callable(usage):
        report: dict[str, Any] = usage()
        return report
    return {"provider": provider.identity.provider_id}


def _extraction_segments(
    session: Session, conversations: Sequence[StoredConversation]
) -> list[tuple[str, list[ExtractionMessage]]]:
    return [
        (seg.segment_id, segment_extraction_messages(conv, seg))
        for conv in conversations
        for seg in load_segments(session, conv)
    ]


def _rule_extractors(
    session: Session, conversations: Sequence[StoredConversation]
) -> list[RuleExtractor]:
    revisions = [r for conv in conversations for r in conv.revisions.values()]
    occurrences = actions.load_occurrences(session, revisions)
    return [
        RuleExtractor("decisions", decisions.EXTRACTOR_VERSION, decisions.extract_decisions),
        RuleExtractor(
            "preferences", preferences.EXTRACTOR_VERSION, preferences.extract_preferences
        ),
        RuleExtractor(
            "actions",
            actions.EXTRACTOR_VERSION,
            partial(actions.extract_actions, occurrences=occurrences),
        ),
        RuleExtractor("entities", entities.EXTRACTOR_VERSION, entities.extract_entities),
    ]


def _unvalidated_outputs(session: Session, snapshot: TaxonomySnapshot) -> int:
    # Re-validate every stored classification answer: the ledger must never
    # have kept one that doesn't fit the schema.
    model = output_model(snapshot)
    bad = 0
    for row in session.scalars(select(ModelOutputRow).where(ModelOutputRow.stage_id == STAGE_ID)):
        try:
            model.model_validate_json(row.output_json)
        except ValidationError:
            bad += 1
    return bad
