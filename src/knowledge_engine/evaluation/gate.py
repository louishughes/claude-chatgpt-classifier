"""Release gate: every evaluation once, each labelled PASS, FAIL, REVIEW or BLOCKED (EVAL-007).

The gate runs each check in ``CHECKS`` **exactly once**, in order, and then
stops. It never re-runs a check to get a different answer, and one check
crashing does not stop the others: the crash is that check's FAIL. This is
the "finite stop" rule from TEST_STRATEGY §7.

The four labels:

* ``PASS``: measured, and at or above the proposed release threshold
  (TEST_STRATEGY §6);
* ``FAIL``: measured, and below it (or the check crashed). Each FAIL needs
  a ticket; the report lists them under "Tickets to file";
* ``REVIEW``: the hard rule held, but some cases were sent to a person
  instead of being decided (for example, replacements that didn't say
  what they replace);
* ``BLOCKED``: can't be measured here, with the reason and the ticket that
  unblocks it (the private golden set, a paid provider run).

Every check says what data it measured (``synthetic`` fixtures or ``real``
data), because a perfect score on synthetic fixtures proves the plumbing,
not the quality. The overall result is the worst label, in the order
FAIL, BLOCKED, REVIEW, PASS; the gate itself fails only on a FAIL.

Talking points:
    - "One command runs every evaluation once and labels each one pass,
      fail, needs review or blocked, with the threshold next to the number."
    - "It never retries to get a better answer, and a crash in one check
      can't hide the others."
    - "Anything measured only on fake data says so."
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Any

GATE_VERSION = "eval-007-v1"
THRESHOLD = 0.9  # TEST_STRATEGY §6: every proposed rate floor is 90%


class Status(StrEnum):
    """A check's label. Ordered worst first for the overall result."""

    FAIL = "FAIL"
    BLOCKED = "BLOCKED"
    REVIEW = "REVIEW"
    PASS = "PASS"


_WORST_FIRST = list(Status)


@dataclass(frozen=True)
class Outcome:
    """What one check found."""

    status: Status
    measured: str
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class Check:
    """One gate line: what it measures, against what, and how to run it alone.

    Attributes:
        check_id: Stable name, e.g. ``extraction.unsupported_decisions``.
        ticket: The ticket that owns the measurement.
        threshold: The release threshold, in words.
        data: ``synthetic`` or ``real``: what the number was measured on.
        command: The command that runs this measurement on its own.
        run: Given the gate's inputs, measure. Must not raise on purpose.
    """

    check_id: str
    ticket: str
    threshold: str
    data: str
    command: str
    run: Callable[[GateInputs], Outcome]


@dataclass(frozen=True)
class GateInputs:
    """Where the gate reads fixtures and writes scratch workspaces."""

    fixtures: Path  # tests/fixtures
    scratch: Path


@dataclass(frozen=True)
class Result:
    """A check and what it found."""

    check: Check
    outcome: Outcome
    seconds: float


@dataclass
class GateReport:
    """The whole pass."""

    results: list[Result] = field(default_factory=list)

    @property
    def overall(self) -> Status:
        """The worst label (PASS when there are no checks)."""
        found = {r.outcome.status for r in self.results}
        return next((s for s in _WORST_FIRST if s in found), Status.PASS)

    @property
    def passed(self) -> bool:
        """No check failed (REVIEW and BLOCKED are filed, not failures)."""
        return all(r.outcome.status is not Status.FAIL for r in self.results)

    def counts(self) -> dict[str, int]:
        """How many checks got each label."""
        return {s.value: sum(r.outcome.status is s for r in self.results) for s in Status}


def _rate(value: float) -> str:
    return f"{value:.3f}"


def _floor(value: float, measured: str, *notes: str) -> Outcome:
    status = Status.PASS if value >= THRESHOLD else Status.FAIL
    return Outcome(status, measured, tuple(notes))


# --- The checks ---------------------------------------------------------------


def _fidelity(inputs: GateInputs) -> Outcome:
    from knowledge_engine.evaluation.import_fidelity import evaluate_fixtures

    report = evaluate_fixtures(inputs.fixtures / "chatgpt", inputs.scratch / "fidelity")
    drops = [e.name for e in report.exports if e.verdict == "silent_drop"]
    measured = f"{len(report.exports)} exports, {len(drops)} silent drop(s)"
    return Outcome(Status.FAIL if drops else Status.PASS, measured, tuple(drops))


def _gold(inputs: GateInputs) -> Any:
    from knowledge_engine.evaluation.gold import load_gold

    return load_gold(inputs.fixtures / "gold" / "synthetic-v1" / "gold.json")


def _stored(inputs: GateInputs, cases: set[str], name: str) -> tuple[Any, Any]:
    """Import fixture cases into a scratch workspace; (engine, settings)."""
    from knowledge_engine.importer import import_source
    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
    from knowledge_engine.settings import Settings

    settings = Settings(workspace_root=inputs.scratch / name)
    for case in sorted(cases):
        import_source(inputs.fixtures / "chatgpt" / case / "export", "gate", settings=settings)
    return create_sqlite_engine(database_path(settings)), settings


def _conversations(session: Any) -> list[Any]:
    from sqlalchemy import select

    from knowledge_engine.importer.records import ConversationRow
    from knowledge_engine.rendering.transcript import load_conversation

    return [
        load_conversation(session, conversation_id)
        for conversation_id in session.scalars(
            select(ConversationRow.conversation_id).order_by(ConversationRow.native_conversation_id)
        ).all()
    ]


@lru_cache(maxsize=2)  # three checks read one report; it is measured once per gate run
def classification_report(inputs: GateInputs) -> Any:
    """EVAL-003 on the synthetic golden set with the keyword classifier."""
    from sqlalchemy.orm import Session

    from knowledge_engine.classification.classifier import SegmentClassifier
    from knowledge_engine.evaluation.classification_eval import (
        evaluate_classification,
        predicted_from,
    )
    from knowledge_engine.segmentation.segmenter import segment_conversation

    gold = _gold(inputs)
    cases = {c.fixture_case for c in gold.conversations if c.segments and c.fixture_case}
    engine, _ = _stored(inputs, cases, "classification")
    try:
        with Session(engine) as session:
            pairs = [(c, s) for c in _conversations(session) for s in segment_conversation(c)]
    finally:
        engine.dispose()
    classifier = SegmentClassifier(gold.snapshot())
    predicted = predicted_from(pairs, classifier.classify(pairs))
    return evaluate_classification(gold, predicted, {"classifier": classifier.method})


def _primary(inputs: GateInputs) -> Outcome:
    report = classification_report(inputs)
    # OD-17: "primary category" is the primary domain; the synthetic set has
    # no domain field, so its primary topic stands in and the note says so.
    name = "domain" if "domain" in report.fields else "topic"
    value = report.fields[name].primary_accuracy
    notes = () if name == "domain" else ("no domain labels in this set; primary topic used",)
    return _floor(value, f"primary {name} accuracy {_rate(value)}", *notes)


def _ambiguous(inputs: GateInputs) -> Outcome:
    report = classification_report(inputs)
    measured = (
        f"{report.ambiguous_flagged} ambiguous segment(s) sent to review, "
        f"{report.ambiguous_missed} forced"
    )
    if report.ambiguous_flagged + report.ambiguous_missed == 0:
        return Outcome(Status.REVIEW, measured, ("the set has no ambiguous segments to test",))
    return Outcome(Status.FAIL if report.ambiguous_missed else Status.PASS, measured)


@lru_cache(maxsize=2)
def extraction_report(inputs: GateInputs) -> Any:
    """EVAL-004 on the synthetic golden set with the rule extractors."""
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from knowledge_engine.evaluation.extraction_eval import evaluate_extraction, scored_records
    from knowledge_engine.evaluation.semantic_smoke import _rule_extractors
    from knowledge_engine.extraction import actions, decisions, entities, preferences
    from knowledge_engine.extraction.evidence import VALIDATOR_VERSION
    from knowledge_engine.extraction.runner import run
    from knowledge_engine.extraction.store import KnowledgeRecordRow, load
    from knowledge_engine.extraction.text import segment_extraction_messages
    from knowledge_engine.segmentation.segmenter import segment_conversation

    gold = _gold(inputs)
    cases = {c.fixture_case for c in gold.conversations if c.records_annotated and c.fixture_case}
    engine, _ = _stored(inputs, cases, "extraction")
    try:
        with Session(engine) as session:
            conversations = _conversations(session)
            segments = [
                (seg.segment_id, segment_extraction_messages(conv, seg))
                for conv in conversations
                for seg in segment_conversation(conv)
            ]
            run(session, segments, _rule_extractors(session, conversations))
            session.commit()
            records = [
                load(session, record_id)
                for record_id in session.scalars(
                    select(KnowledgeRecordRow.record_id).order_by(KnowledgeRecordRow.record_id)
                )
            ]
            versions = {
                "decisions": decisions.EXTRACTOR_VERSION,
                "preferences": preferences.EXTRACTOR_VERSION,
                "actions": actions.EXTRACTOR_VERSION,
                "entities": entities.EXTRACTOR_VERSION,
                "validator": VALIDATOR_VERSION,
            }
            return evaluate_extraction(gold, scored_records(session, records), versions)
    finally:
        engine.dispose()


def _unsupported(inputs: GateInputs) -> Outcome:
    report = extraction_report(inputs)
    bad = report.unsupported_truth_decisions + report.forbidden_in_truth
    measured = (
        f"{len(report.unsupported_truth_decisions)} unsupported decision(s) and "
        f"{len(report.forbidden_in_truth)} forbidden record(s) in current truth"
    )
    return Outcome(Status.FAIL if bad else Status.PASS, measured, tuple(bad))


def _anchors(inputs: GateInputs) -> Outcome:
    report = extraction_report(inputs)
    value = report.anchor_validity
    status = Status.PASS if value == 1.0 else Status.FAIL
    return Outcome(status, f"{report.anchors_valid} of {report.produced} records anchored")


def _decision_recall(inputs: GateInputs) -> Outcome:
    report = extraction_report(inputs)
    score = report.by_type.get("decision")
    if score is None or score.true_pos + score.false_neg == 0:
        return Outcome(Status.BLOCKED, "no decisions in the answer key")
    return _floor(score.recall, f"decision recall {_rate(score.recall)}")


def _temporal(inputs: GateInputs) -> Outcome:
    from knowledge_engine.evaluation.temporal_bench import run_benchmark

    fixture = inputs.fixtures / "chatgpt" / "engine_switch" / "export"
    report = run_benchmark(fixture, inputs.scratch / "temporal")
    right = sum(r.right for r in report.pairs)
    measured = (
        f"{right} of {len(report.pairs)} pairs as expected, "
        f"{len(report.false_supersessions)} false supersession(s)"
    )
    if not report.passed:
        notes = tuple(report.false_supersessions) or ("history pipeline failed",)
        return Outcome(Status.FAIL, measured, notes)
    waiting = tuple(f"{r.case_id} sent to review" for r in report.pairs if not r.right)
    return Outcome(Status.REVIEW if waiting else Status.PASS, measured, waiting)


def _end_to_end(inputs: GateInputs) -> Outcome:
    import json

    from knowledge_engine.evaluation.end_to_end import (
        E2E_QUERY,
        golden_diff,
        run_end_to_end,
        vault_golden,
    )

    e2e = inputs.fixtures / "e2e"
    report = run_end_to_end(e2e / "export.zip", inputs.scratch / "e2e", query=E2E_QUERY)
    golden = json.loads((e2e / "vault_golden.json").read_text(encoding="utf-8"))
    diffs = golden_diff(vault_golden(report.check), golden)
    broken = len(report.check.broken_links) + len(report.check.broken_embeds)
    measured = (
        f"{report.check.notes} notes, {report.check.links} links, {broken} broken; "
        f"{len(diffs)} golden difference(s)"
    )
    ok = report.passed and not diffs
    return Outcome(Status.PASS if ok else Status.FAIL, measured, tuple(diffs[:5]))


def _retrieval(inputs: GateInputs) -> Outcome:
    from knowledge_engine.evaluation.retrieval_bench import check, run_benchmark

    report = run_benchmark(inputs.scratch / "retrieval")
    value = report.scores["hybrid"].recall[10]
    failures = check(report)
    status = Status.PASS if value >= THRESHOLD and not failures else Status.FAIL
    return Outcome(status, f"hybrid Recall@10 {_rate(value)}", tuple(failures))


def _variance(inputs: GateInputs) -> Outcome:
    from knowledge_engine.evaluation.variance import SOURCES, run_variance

    report = run_variance([inputs.fixtures / s for s in SOURCES], inputs.scratch / "variance")
    measured = (
        f"{len(report.runs)} orders, {len(report.items)} difference(s), "
        f"{report.repeat_new_requests} new request(s) on repeat"
    )
    if report.silent_drift or report.repeat_new_requests or not report.repeat_identical:
        return Outcome(Status.FAIL, measured)
    notes = tuple(f"{i.kind} {i.key}" for i in report.items[:5])
    return Outcome(Status.REVIEW if report.items else Status.PASS, measured, notes)


def _blocked(reason: str) -> Callable[[GateInputs], Outcome]:
    return lambda inputs: Outcome(Status.BLOCKED, "not run", (reason,))


CHECKS: tuple[Check, ...] = (
    Check(
        "import.fidelity",
        "EVAL-002",
        "100% of supported fixtures accounted for (0 silent drops)",
        "synthetic",
        "ke eval fidelity",
        _fidelity,
    ),
    Check(
        "classification.primary",
        "EVAL-003",
        "primary category agreement >= 0.90",
        "synthetic",
        "pytest tests/integration/test_gold_and_classification_eval.py",
        _primary,
    ),
    Check(
        "classification.ambiguous",
        "EVAL-003",
        "ambiguous cases flagged, not forced",
        "synthetic",
        "pytest tests/integration/test_gold_and_classification_eval.py",
        _ambiguous,
    ),
    Check(
        "extraction.unsupported_decisions",
        "EVAL-004",
        "0 unsupported accepted decisions in current truth",
        "synthetic",
        "pytest tests/integration/test_extraction_eval.py",
        _unsupported,
    ),
    Check(
        "extraction.anchors",
        "EVAL-004",
        "every record has a valid exact evidence anchor",
        "synthetic",
        "pytest tests/integration/test_extraction_eval.py",
        _anchors,
    ),
    Check(
        "extraction.decision_recall",
        "EVAL-004",
        "explicit decision recall >= 0.90",
        "synthetic",
        "pytest tests/integration/test_extraction_eval.py",
        _decision_recall,
    ),
    Check(
        "temporal.supersession",
        "EVAL-005",
        "0 false supersessions; history kept",
        "synthetic",
        "ke eval temporal",
        _temporal,
    ),
    Check(
        "end_to_end.vault",
        "EVAL-006",
        "ZIP to vault: every link resolves; shape matches the golden",
        "synthetic",
        "ke eval e2e",
        _end_to_end,
    ),
    Check(
        "variance.order_and_repeats",
        "EVAL-008",
        "same answers in 3 shuffled orders and on pinned repeats; differences go to review",
        "synthetic",
        "ke eval variance",
        _variance,
    ),
    Check(
        "retrieval.recall_at_10",
        "RET-008",
        "Recall@10 >= 0.90",
        "synthetic",
        "ke eval retrieval",
        _retrieval,
    ),
    Check(
        "relationships.precision",
        "REL-002",
        "directional relationship precision >= 0.90",
        "real",
        "ke eval relationships --key <key> (on the owner's PC)",
        _blocked(
            "the private key relkey-v1 (30 chats, 49 links, independent session) is on the "
            "owner's PC; scored there, numbers only (docs/evaluation/EVAL-012_REAL.md)"
        ),
    ),
    Check(
        "quality.real_golden_set",
        "EVAL-013",
        "the extraction thresholds above, on the private golden set",
        "real",
        "ke gold score --gold <key> --reviewer ai_session (on the owner's PC)",
        _blocked(
            "the private key golden-v1 (extraction only, AI-reviewed) is on the owner's PC; "
            "scored there, numbers only"
        ),
    ),
    Check(
        "provider.real_smoke",
        "EVAL-011",
        "pinned real-provider batch smoke under a cost cap",
        "real",
        "ke eval semantic --provider ... (parked)",
        _blocked("parked by the owner: no paid model calls"),
    ),
)


def run_gate(inputs: GateInputs, checks: Sequence[Check] = CHECKS) -> GateReport:
    """Run every check once, in order, and stop. A crash is that check's FAIL."""
    report = GateReport()
    for check in checks:
        started = time.monotonic()
        try:
            outcome = check.run(inputs)
        except Exception as error:  # noqa: BLE001 - one crash must not hide the other checks
            outcome = Outcome(Status.FAIL, "crashed", (f"{type(error).__name__}: {error}",))
        report.results.append(Result(check, outcome, round(time.monotonic() - started, 2)))
    return report


def to_dict(report: GateReport) -> dict[str, Any]:
    """JSON-ready report."""
    return {
        "version": GATE_VERSION,
        "overall": report.overall.value,
        "passed": report.passed,
        "counts": report.counts(),
        "checks": [
            {
                "check": r.check.check_id,
                "ticket": r.check.ticket,
                "status": r.outcome.status.value,
                "threshold": r.check.threshold,
                "measured": r.outcome.measured,
                "data": r.check.data,
                "command": r.check.command,
                "notes": list(r.outcome.notes),
            }
            for r in report.results
        ],
    }


def to_markdown(report: GateReport, *, commit: str | None = None) -> str:
    """The gate report: a table, then what needs a ticket or a person."""
    counts = report.counts()
    lines = [
        "# Release gate (EVAL-007)",
        "",
        f"- Gate: `{GATE_VERSION}`; commit `{commit or 'working tree'}`",
        f"- Overall: **{report.overall.value}** "
        + ", ".join(f"{n} {s}" for s, n in counts.items() if n),
        "- Every check ran once; nothing was re-run. `synthetic` numbers prove the "
        "plumbing, not quality on real chats.",
        "",
        "| Check | Ticket | Status | Measured | Threshold | Data | Run alone |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in report.results:
        lines.append(
            f"| {r.check.check_id} | {r.check.ticket} | **{r.outcome.status.value}** | "
            f"{r.outcome.measured} | {r.check.threshold} | {r.check.data} | "
            f"`{r.check.command}` |"
        )
    for title, status in (
        ("Tickets to file (FAIL)", Status.FAIL),
        ("Waiting on a person (REVIEW)", Status.REVIEW),
        ("Blocked", Status.BLOCKED),
    ):
        found = [r for r in report.results if r.outcome.status is status]
        lines += ["", f"## {title}", ""]
        if not found:
            lines.append("- none")
        for r in found:
            notes = "; ".join(r.outcome.notes) or r.outcome.measured
            lines.append(f"- `{r.check.check_id}` ({r.check.ticket}): {notes}")
    return "\n".join(lines) + "\n"
