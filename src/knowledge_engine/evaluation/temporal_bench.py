"""Temporal and current-state benchmark: does "later" ever wrongly become "instead"? (EVAL-005).

Two parts, both synthetic and pinned:

**Curated pairs.** Each case is an earlier and a later record with the
words the later one quotes, run through REC-005's ``evaluate`` exactly as
the reconciler does. The cases cover the ways a later statement can *look*
like a replacement without being one:

* ``true_supersession``: same subject, same scope, firm, says "instead";
* ``hypothetical``: "what if we switched...?", "maybe", a question;
* ``scope_change``: the same words about a different project;
* ``conflict_without_intent``: a contradicting later decision that never
  says it replaces anything (a conflict to review, not a replacement);
* ``weak_acceptance``: "instead", but only conditionally accepted;
* ``adjacent_subject``: same project, a shared word ("game") and a firm
  "instead", but about another part of the project (the modelling tool,
  not the engine);
* ``unknown_time`` and ``out_of_order``: when the order can't be trusted;
* ``different_subject``, ``different_actor``, ``rejected``: no relation.

The score that matters is **false supersessions**: any case recorded as
``supersedes`` that shouldn't be. The acceptance bar is zero, and zero for
hypotheticals in particular. Missed replacements are counted too (they go
to review, which is safe, but they are reported).

**Pipeline.** The ``engine_switch`` fixture is imported, decisions are
extracted by the rules, the reconciler runs, and the projection is read
three ways: now (the replaced decision is ``superseded``, with the event
that explains it), *as of* just before the switch was said (it is still
``current``: history is kept), and after the replacement is withdrawn (it
is ``current`` again).

The pair texts are invented and carry no shared marker word (a common
"Synthetic:" prefix would itself count as a shared subject and hide a
wrong verdict). The report holds case IDs, categories and outcomes only.

Talking points:
    - "Hand-made pairs try to trick the reconciler into calling
      a 'what if' a decision. The pass mark is zero tricks."
    - "Replaced decisions are never deleted: asking 'what was true then?'
      still shows them."
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from knowledge_engine.domain.enums import Role
from knowledge_engine.domain.models import EvidenceRef
from knowledge_engine.extraction.records import (
    Acceptance,
    KnowledgeRecord,
    Provenance,
    RecordType,
    Trust,
)
from knowledge_engine.reconciliation.relations import Placed
from knowledge_engine.reconciliation.supersession import Outcome, evaluate

TEMPORAL_VERSION = "eval-005-v1"

# The earlier decision every pair is measured against, unless a case says otherwise.
_BASE = "we are using Unity for the shed game."


@dataclass(frozen=True)
class Side:
    """One record of a pair."""

    assertion: str
    quote: str
    when: float | None
    project: str | None = "proj_shedgame"
    record_type: RecordType = RecordType.DECISION
    actor: Role = Role.USER
    acceptance: Acceptance = Acceptance.EXPLICIT
    trust: Trust = Trust.SUPPORTED


@dataclass(frozen=True)
class Case:
    """A curated pair and the outcome a careful person expects."""

    case_id: str
    category: str
    later: Side
    expected: Outcome
    earlier: Side = Side(_BASE, _BASE, 1000.0)


def _later(assertion: str, quote: str | None = None, **extra: Any) -> Side:
    return Side(assertion, quote if quote is not None else assertion, 2000.0, **extra)


CASES: tuple[Case, ...] = (
    # Real replacements.
    Case(
        "t01",
        "true_supersession",
        _later("we will use Godot instead of Unity."),
        Outcome.SUPERSEDES,
    ),
    Case(
        "t02",
        "true_supersession",
        _later("change of plan, switching to Godot for the shed game."),
        Outcome.SUPERSEDES,
    ),
    Case(
        "t03",
        "true_supersession",
        _later("we're no longer using Unity; Godot from now on."),
        Outcome.SUPERSEDES,
    ),
    Case(
        "t04",
        "true_supersession",
        _later("scrap that, the shed game moves over to Godot."),
        Outcome.SUPERSEDES,
    ),
    Case(
        "t05",
        "true_supersession",
        _later("I've changed my mind: Godot rather than Unity."),
        Outcome.SUPERSEDES,
    ),
    # Hypotheticals: never a replacement.
    Case(
        "h01",
        "hypothetical",
        _later("what if we switched to Godot instead of Unity?"),
        Outcome.REVIEW_REQUIRED,
    ),
    Case(
        "h02",
        "hypothetical",
        _later("maybe use Godot instead of Unity for the shed game."),
        Outcome.REVIEW_REQUIRED,
    ),
    Case(
        "h03",
        "hypothetical",
        _later("should we move the shed game over to Godot instead?"),
        Outcome.REVIEW_REQUIRED,
    ),
    Case(
        "h04",
        "hypothetical",
        _later("I'm thinking about switching to Godot instead of Unity."),
        Outcome.REVIEW_REQUIRED,
    ),
    Case(
        "h05",
        "hypothetical",
        _later("hypothetically, Godot could replace Unity for the shed game."),
        Outcome.REVIEW_REQUIRED,
    ),
    Case(
        "h06",
        "hypothetical",
        _later("perhaps we drop Unity for Godot later."),
        Outcome.REVIEW_REQUIRED,
    ),
    Case(
        "h07",
        "hypothetical",
        _later("if we switch to Godot instead, would the shed game load faster"),
        Outcome.REVIEW_REQUIRED,
    ),
    Case(
        "h08",
        "hypothetical",
        _later("I wonder whether Godot instead of Unity suits the shed game."),
        Outcome.REVIEW_REQUIRED,
    ),
    # A different project: the same words replace nothing here.
    Case(
        "s01",
        "scope_change",
        _later("we will use Godot instead of Unity.", project="proj_garden_app"),
        Outcome.UNRELATED,
    ),
    Case(
        "s02",
        "scope_change",
        _later("switching to Godot for the garden app.", project="proj_garden_app"),
        Outcome.UNRELATED,
    ),
    # A contradiction that never says "instead": a reviewer's call.
    Case(
        "c01",
        "conflict_without_intent",
        _later("we are using Godot for the shed game."),
        Outcome.REVIEW_REQUIRED,
    ),
    Case(
        "c02",
        "conflict_without_intent",
        _later("Godot is the engine for the shed game."),
        Outcome.REVIEW_REQUIRED,
    ),
    Case(
        "c03",
        "conflict_without_intent",
        _later("Unity is too heavy, but the shed game ships on it anyway."),
        Outcome.REVIEW_REQUIRED,
    ),
    # Says "instead", but the later acceptance isn't firm.
    Case(
        "w01",
        "weak_acceptance",
        _later("we will use Godot instead of Unity.", acceptance=Acceptance.CONDITIONAL),
        Outcome.REVIEW_REQUIRED,
    ),
    Case(
        "w02",
        "weak_acceptance",
        _later("we will use Godot instead of Unity.", trust=Trust.CANDIDATE),
        Outcome.REVIEW_REQUIRED,
    ),
    Case(
        "w03",
        "weak_acceptance",
        _later(
            "we will use Godot instead of Unity.",
            acceptance=Acceptance.INFERRED,
            trust=Trust.CANDIDATE,  # an inferred acceptance can't be trusted at all
        ),
        Outcome.REVIEW_REQUIRED,
    ),
    # When the order can't be trusted.
    Case(
        "o01",
        "unknown_time",
        Side(
            "we will use Godot instead of Unity.",
            "we will use Godot instead of Unity.",
            None,
        ),
        Outcome.REVIEW_REQUIRED,
    ),
    Case(
        "o02",
        "unknown_time",
        _later("we will use Godot instead of Unity."),
        Outcome.REVIEW_REQUIRED,
        earlier=Side(_BASE, _BASE, None),
    ),
    Case(
        "o03",
        "out_of_order",
        Side(
            "we will use Godot instead of Unity.",
            "we will use Godot instead of Unity.",
            1000.0,
        ),
        Outcome.REVIEW_REQUIRED,
    ),
    # Same project, shared words, firm "instead": but about something else.
    Case(
        "a01",
        "adjacent_subject",
        _later("we'll use Blender instead of Maya for the shed game models."),
        Outcome.UNRELATED,
    ),
    Case(
        "a02",
        "adjacent_subject",
        _later("switching to Blender for the shed game models."),
        Outcome.REVIEW_REQUIRED,  # can't tell what it replaces: a person decides
    ),
    Case(
        "a03",
        "adjacent_subject",
        _later("replace the shed game's pixel font with a serif one."),
        Outcome.UNRELATED,
    ),
    # Not about each other at all.
    Case(
        "u01",
        "different_subject",
        _later("switching to cedar boards instead of pine for the porch."),
        Outcome.UNRELATED,
    ),
    Case(
        "u02",
        "different_actor",
        _later("use Godot instead of Unity.", actor=Role.ASSISTANT),
        Outcome.UNRELATED,
    ),
    Case(
        "u03",
        "rejected",
        _later("we will use Godot instead of Unity.", trust=Trust.REJECTED),
        Outcome.UNRELATED,
    ),
    Case(
        "u04",
        "different_kind",
        _later("I prefer Godot instead of Unity.", record_type=RecordType.PREFERENCE),
        Outcome.UNRELATED,
    ),
)


def _record(n: int, side: Side) -> KnowledgeRecord:
    fields: dict[str, Any] = {
        "record_id": "krec_" + f"{n:032x}",
        "record_type": side.record_type,
        "assertion": side.assertion,
        "actor": side.actor,
        "acceptance": side.acceptance,
        "trust": side.trust,
        "scope_id": "seg_synthetic",
        "project_ids": (side.project,) if side.project else (),
        "evidence": (
            EvidenceRef(
                revision_id="rev_" + f"{n:032x}",
                start=0,
                end=max(1, len(side.quote)),
                quote_sha256=hashlib.sha256(side.quote.encode()).hexdigest(),
                actor=side.actor,
            ),
        ),
        "evidence_checked_by": "ext-002-test",
        "provenance": Provenance(
            stage_id="extract.bench.v1", stage_key="stg_" + "e" * 64, extractor_version="bench"
        ),
    }
    if side.trust is Trust.CONFIRMED:
        fields["reviewer"] = "bench"
    return KnowledgeRecord.model_validate(fields)


@dataclass(frozen=True)
class CaseResult:
    """One pair's verdict against the expected one."""

    case_id: str
    category: str
    expected: Outcome
    got: Outcome
    failed_tests: tuple[str, ...]

    @property
    def right(self) -> bool:
        """The verdict is the expected one."""
        return self.got is self.expected

    @property
    def false_supersession(self) -> bool:
        """Recorded as a replacement when it isn't one: the failure that matters."""
        return self.got is Outcome.SUPERSEDES and self.expected is not Outcome.SUPERSEDES


def _quotes(said: dict[str, str]) -> Callable[[KnowledgeRecord], str]:
    return lambda record: said[record.record_id]


def run_pairs(cases: tuple[Case, ...] = CASES) -> list[CaseResult]:
    """Judge every curated pair with the reconciler's own tests."""
    results = []
    for index, case in enumerate(cases):
        earlier = _record(2 * index + 1, case.earlier)
        later = _record(2 * index + 2, case.later)
        quotes = {earlier.record_id: case.earlier.quote, later.record_id: case.later.quote}
        verdict = evaluate(
            Placed(
                earlier, "conv_synthetic", (earlier.evidence[0].revision_id,), case.earlier.when
            ),
            Placed(later, "conv_synthetic", (later.evidence[0].revision_id,), case.later.when),
            _quotes(quotes),
        )
        results.append(
            CaseResult(case.case_id, case.category, case.expected, verdict.outcome, verdict.failed)
        )
    return results


@dataclass(frozen=True)
class PipelineResult:
    """The end-to-end retention checks on the ``engine_switch`` fixture."""

    superseded_now: bool
    explained_by_event: bool
    current_before_switch: bool
    current_after_withdrawal: bool

    @property
    def passed(self) -> bool:
        """All four held."""
        return all(
            (
                self.superseded_now,
                self.explained_by_event,
                self.current_before_switch,
                self.current_after_withdrawal,
            )
        )


def run_pipeline(fixture: Path, scratch: Path) -> PipelineResult:
    """Import ``engine_switch``, extract, reconcile, and read the projection three ways."""
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from knowledge_engine.extraction import decisions
    from knowledge_engine.extraction.runner import RuleExtractor, run
    from knowledge_engine.extraction.store import KnowledgeRecordRow
    from knowledge_engine.extraction.text import segment_extraction_messages
    from knowledge_engine.importer import import_source
    from knowledge_engine.importer.records import ConversationRow
    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
    from knowledge_engine.reconciliation.projection import Status, project
    from knowledge_engine.reconciliation.relations import place
    from knowledge_engine.reconciliation.supersession import reconcile
    from knowledge_engine.reconciliation.timeline import DecisionEventRow, revoke
    from knowledge_engine.rendering.transcript import load_conversation
    from knowledge_engine.segmentation.segmenter import segment_conversation
    from knowledge_engine.settings import Settings

    settings = Settings(workspace_root=scratch / "ws")
    import_source(fixture, "bench", settings=settings)
    engine = create_sqlite_engine(database_path(settings))
    try:
        with Session(engine) as session:
            segments = []
            for conversation_id in session.scalars(select(ConversationRow.conversation_id)).all():
                chat = load_conversation(session, conversation_id)
                segments += [
                    (s.segment_id, segment_extraction_messages(chat, s))
                    for s in segment_conversation(chat)
                ]
            rule = RuleExtractor(
                "decisions", decisions.EXTRACTOR_VERSION, decisions.extract_decisions
            )
            run(session, segments, [rule])
            session.commit()
            report = reconcile(session)
            session.commit()
            if not report.superseded:
                return PipelineResult(False, False, False, False)
            later, earlier = report.superseded[0]
            now = {e.record_id: e for e in project(session).entries}
            [event] = session.scalars(select(DecisionEventRow)).all()
            rows = session.scalars(
                select(KnowledgeRecordRow).where(KnowledgeRecordRow.record_id == later)
            )
            [placed] = place(
                session, [KnowledgeRecord.model_validate_json(r.record_json) for r in rows]
            )
            said_at = placed.first_time or 0.0
            before = project(session, as_of=said_at - 1)
            revoke(session, event.event_id, reviewer="bench", note="benchmark undo")
            session.commit()
            after = project(session)
            return PipelineResult(
                superseded_now=now[earlier].status is Status.SUPERSEDED
                and now[earlier].superseded_by == (later,),
                explained_by_event=now[earlier].because == (event.event_id,),
                current_before_switch=earlier in before.by_status(Status.CURRENT),
                current_after_withdrawal=earlier in after.by_status(Status.CURRENT),
            )
    finally:
        engine.dispose()


@dataclass(frozen=True)
class TemporalReport:
    """Both parts' results."""

    pairs: tuple[CaseResult, ...]
    pipeline: PipelineResult

    @property
    def false_supersessions(self) -> list[str]:
        """Case IDs wrongly recorded as replacements (must be empty)."""
        return [r.case_id for r in self.pairs if r.false_supersession]

    @property
    def passed(self) -> bool:
        """No false supersession, and history kept end to end."""
        return not self.false_supersessions and self.pipeline.passed


def run_benchmark(fixture: Path, scratch: Path) -> TemporalReport:
    """Run both parts (the pipeline in ``scratch``, never your workspace)."""
    return TemporalReport(tuple(run_pairs()), run_pipeline(fixture, scratch))


def to_dict(report: TemporalReport) -> dict[str, Any]:
    """JSON-ready: IDs, categories and outcomes only."""
    right = Counter(r.category for r in report.pairs if r.right)
    total = Counter(r.category for r in report.pairs)
    return {
        "version": TEMPORAL_VERSION,
        "passed": report.passed,
        "pairs": len(report.pairs),
        "right": sum(right.values()),
        "false_supersessions": report.false_supersessions,
        "missed_supersessions": [
            r.case_id
            for r in report.pairs
            if r.expected is Outcome.SUPERSEDES and r.got is not Outcome.SUPERSEDES
        ],
        "by_category": {c: {"right": right[c], "total": total[c]} for c in sorted(total)},
        "wrong": [
            {"case": r.case_id, "expected": r.expected.value, "got": r.got.value}
            for r in report.pairs
            if not r.right
        ],
        "pipeline": {
            "superseded_now": report.pipeline.superseded_now,
            "explained_by_event": report.pipeline.explained_by_event,
            "current_before_switch": report.pipeline.current_before_switch,
            "current_after_withdrawal": report.pipeline.current_after_withdrawal,
        },
    }


def to_markdown(report: TemporalReport) -> str:
    """The committed report."""
    data = to_dict(report)
    lines = [
        "<!-- Generated by `ke eval temporal` from pinned synthetic cases. Outcomes only; "
        "regenerate, never edit by hand. -->",
        "",
        f"# Temporal and current-state benchmark ({TEMPORAL_VERSION})",
        "",
        f"**{'PASS' if report.passed else 'FAIL'}**: {data['right']} of {data['pairs']} pairs "
        f"judged as expected; false supersessions: {len(data['false_supersessions'])} "
        "(must be 0).",
        "",
        "## Curated pairs by category",
        "",
        "| Category | Right | Cases |",
        "|---|---|---|",
    ]
    for category, counts in data["by_category"].items():
        lines.append(f"| {category} | {counts['right']} | {counts['total']} |")
    lines += ["", "## Every pair", "", "| Case | Category | Expected | Got | Failed tests |"]
    lines.append("|---|---|---|---|---|")
    for r in report.pairs:
        lines.append(
            f"| {r.case_id} | {r.category} | {r.expected.value} | {r.got.value} "
            f"| {', '.join(r.failed_tests) or '-'} |"
        )
    pipeline = data["pipeline"]
    lines += [
        "",
        "## Pipeline (`engine_switch` fixture)",
        "",
        f"- Replaced decision shown as superseded now: {pipeline['superseded_now']}",
        f"- Explained by its supersession event: {pipeline['explained_by_event']}",
        f"- Still current as of just before the switch was said: "
        f"{pipeline['current_before_switch']}",
        f"- Current again after the replacement is withdrawn: "
        f"{pipeline['current_after_withdrawal']}",
        "",
    ]
    return "\n".join(lines)
