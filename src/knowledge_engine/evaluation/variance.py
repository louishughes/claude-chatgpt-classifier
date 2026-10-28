"""Shuffled-order and repeated-run variance (EVAL-008).

The same chats must give the same answers whatever order they arrive in,
and a pinned model must give the same answers when asked again. This
evaluation checks both on a synthetic export:

1. **Shuffled orders.** The export's conversations are shuffled with three
   fixed seeds. Each order is imported into its own scratch workspace and
   run through classification (the model path, with a pinned fake model
   that answers like the keyword classifier), rule extraction and
   reconciliation; the segments are also fed to each stage in the shuffled
   order.
2. **Pinned repeats.** In the first workspace, classification is asked
   twice more. The answers must be identical and come from the ledger,
   with zero new model requests.

Each run is reduced to a **canonical view** keyed only by things the
export itself names (native conversation and message IDs, record type and
the quoted words), never by workspace-random IDs:

* each segment's labels per field;
* each knowledge record's trust and standing (current, superseded...),
  and which records replaced it.

Any key whose value differs between runs becomes a **review item**, with
every run's value side by side. Nothing is averaged or quietly picked: a
difference is never silent.

Talking points:
    - "I import the same chats in three different orders and ask the same
      pinned model twice; the labels and the 'what is current' answers
      must not change."
    - "Any difference is listed for a person to look at, with each run's
      answer next to the others."
"""

from __future__ import annotations

import json
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

VARIANCE_VERSION = "eval-008-v1"
SEEDS = (11, 22, 33)
# The synthetic exports the evaluation shuffles: between them they hold
# decisions, a replacement, preferences, several projects and topics.
SOURCES = (
    Path("e2e/export.zip"),
    Path("chatgpt/engine_switch/export"),
    Path("chatgpt/extraction_rules/export"),
    Path("chatgpt/mixed_projects/export"),
    Path("chatgpt/topic_segments/export"),
)

View = dict[str, str]  # canonical key -> canonical value
ProviderFactory = Callable[[Any, Sequence[Any]], Any]  # (snapshot, items) -> provider


@dataclass(frozen=True)
class ReviewItem:
    """One key whose answer changed between runs."""

    kind: str  # "classification" or "record"
    key: str
    values: tuple[str, ...]  # one per run, "(absent)" when a run lacks the key


@dataclass(frozen=True)
class RunView:
    """One run's canonical answers."""

    seed: int
    order: tuple[str, ...]  # native conversation IDs, in the order imported
    classification: View
    records: View


@dataclass
class VarianceReport:
    """Every run's view, the repeats check and the review items."""

    runs: list[RunView] = field(default_factory=list)
    repeat_identical: bool = False
    repeat_new_requests: int = 0
    items: list[ReviewItem] = field(default_factory=list)

    @property
    def silent_drift(self) -> bool:
        """A difference that isn't listed as a review item (must never happen)."""
        return bool(differences(self.runs)) and not self.items

    @property
    def stable(self) -> bool:
        """Same answers in every order and every repeat."""
        return not self.items and self.repeat_identical and self.repeat_new_requests == 0


def shuffled_export(source: Path, seed: int, out: Path) -> tuple[Path, tuple[str, ...]]:
    """Copy an official export (ZIP or folder) with its conversations in a seeded order."""
    import zipfile

    out.mkdir(parents=True, exist_ok=True)
    if source.is_file():
        with zipfile.ZipFile(source) as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
    else:
        files = {
            p.relative_to(source).as_posix(): p.read_bytes()
            for p in sorted(source.rglob("*"))
            if p.is_file()
        }
    chats = json.loads(files.pop("conversations.json"))
    for name, data in files.items():
        (out / name).parent.mkdir(parents=True, exist_ok=True)
        (out / name).write_bytes(data)
    random.Random(seed).shuffle(chats)
    (out / "conversations.json").write_text(json.dumps(chats), encoding="utf-8")
    return out, tuple(str(c.get("id") or c.get("conversation_id")) for c in chats)


def pinned_fake(snapshot: Any, items: Sequence[Any]) -> Any:
    """The pinned fake model: answers like the keyword classifier, no faults."""
    from knowledge_engine.evaluation.semantic_smoke import Faults, keyword_backed_fake

    return keyword_backed_fake(snapshot, items, Faults())


def _classify(session: Any, items: list[Any], snapshot: Any, provider: Any) -> list[Any]:
    """Classify through the model path until nothing waits (at most three passes)."""
    from knowledge_engine.classification.classifier import PENDING, SegmentClassifier
    from knowledge_engine.classification.store import save
    from knowledge_engine.providers.ledger import ModelStageRunner
    from knowledge_engine.settings import EgressPolicy

    classifier = SegmentClassifier(
        snapshot, runner=ModelStageRunner(session, provider, EgressPolicy())
    )
    results = classifier.classify(items)
    for _ in range(2):  # bounded: a fake that never answers stays pending, it isn't retried forever
        if all(r.state != PENDING for r in results):
            break
        results = classifier.classify(items)
    save(session, results)
    session.commit()
    return results


def _classification_view(items: list[Any], results: list[Any]) -> View:
    from knowledge_engine.evaluation.classification_eval import predicted_from

    view: View = {}
    for item in predicted_from(items, results):
        key = f"{item.native_conversation_id}|{item.messages[0] if item.messages else '-'}"
        labels = {
            name: [primary, sorted(rest)] for name, (primary, rest) in sorted(item.labels.items())
        }
        view[key] = json.dumps({"labels": labels, "review": item.review}, sort_keys=True)
    return view


def _records_view(session: Any) -> View:
    from sqlalchemy import select

    from knowledge_engine.evaluation.extraction_eval import scored_records
    from knowledge_engine.extraction.store import KnowledgeRecordRow, load
    from knowledge_engine.reconciliation.projection import project

    records = [
        load(session, record_id)
        for record_id in session.scalars(
            select(KnowledgeRecordRow.record_id).order_by(KnowledgeRecordRow.record_id)
        )
    ]
    keys = {
        s.record.record_id: (
            f"{s.native_conversation_id}|{','.join(sorted(s.messages))}|"
            f"{s.record.record_type.value}|{s.record.assertion}"
        )
        for s in scored_records(session, records)
    }
    standing = {e.record_id: e for e in project(session).entries}
    view: View = {}
    for record in records:
        entry = standing.get(record.record_id)
        value = {
            "trust": record.trust.value,
            "status": entry.status.value if entry else "-",
            "superseded_by": sorted(keys[r] for r in entry.superseded_by) if entry else [],
        }
        view[keys[record.record_id]] = json.dumps(value, sort_keys=True)
    return view


def run_order(
    sources: Sequence[Path],
    scratch: Path,
    seed: int,
    *,
    provider_factory: ProviderFactory = pinned_fake,
    repeats: int = 0,
) -> tuple[RunView, bool, int]:
    """Import the exports in one shuffled order and reduce them to a canonical view.

    Both the order of the exports and the order of the chats inside each
    are shuffled with ``seed``; so is the order segments reach each stage.

    Returns:
        The view, whether ``repeats`` extra classifications matched the
        first, and how many model requests those repeats made.
    """
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from knowledge_engine.evaluation.classification_eval import predicted_from, stability
    from knowledge_engine.evaluation.semantic_smoke import (
        _extraction_segments,
        _rule_extractors,
        smoke_taxonomy,
    )
    from knowledge_engine.extraction.runner import run
    from knowledge_engine.importer import import_source
    from knowledge_engine.importer.records import ConversationRow
    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
    from knowledge_engine.reconciliation.supersession import reconcile
    from knowledge_engine.rendering.transcript import load_conversation
    from knowledge_engine.segmentation.overrides import load_segments
    from knowledge_engine.settings import Settings

    shuffle = random.Random(seed).shuffle
    settings = Settings(workspace_root=scratch / "ws")
    indexed = list(enumerate(sources))
    shuffle(indexed)
    order: tuple[str, ...] = ()
    for index, source in indexed:
        export, chats = shuffled_export(source, seed, scratch / f"export-{index}")
        import_source(export, "variance", settings=settings)
        order += chats
    engine = create_sqlite_engine(database_path(settings))
    try:
        with Session(engine) as session:
            conversations = [
                load_conversation(session, c)
                for c in session.scalars(select(ConversationRow.conversation_id)).all()
            ]
            shuffle(conversations)
            items = [(c, s) for c in conversations for s in load_segments(session, c)]
            shuffle(items)
            snapshot = smoke_taxonomy()
            provider = provider_factory(snapshot, items)
            results = _classify(session, items, snapshot, provider)
            identical, requests = True, 0
            if repeats:
                before = len(provider.submitted)  # every request the fake was ever sent
                again = [_classify(session, items, snapshot, provider) for _ in range(repeats)]
                runs = [predicted_from(items, r) for r in (results, *again)]
                identical, requests = stability(runs) == 1.0, len(provider.submitted) - before
            segments = _extraction_segments(session, conversations)
            shuffle(segments)
            run(session, segments, _rule_extractors(session, conversations))
            session.commit()
            reconcile(session)
            session.commit()
            view = RunView(
                seed, order, _classification_view(items, results), _records_view(session)
            )
    finally:
        engine.dispose()
    return view, identical, requests


def differences(runs: Sequence[RunView]) -> list[ReviewItem]:
    """Every key whose value is not the same in all runs."""
    items = []
    for kind in ("classification", "records"):
        views = [getattr(r, kind) for r in runs]
        for key in sorted(set().union(*views)):
            values = tuple(v.get(key, "(absent)") for v in views)
            if len(set(values)) > 1:
                items.append(ReviewItem(kind.removesuffix("s"), key, values))
    return items


def run_variance(
    sources: Sequence[Path],
    scratch: Path,
    *,
    seeds: Sequence[int] = SEEDS,
    provider_factory: ProviderFactory = pinned_fake,
) -> VarianceReport:
    """Run every seed once (the first with two pinned repeats) and list the differences."""
    report = VarianceReport()
    for index, seed in enumerate(seeds):
        view, identical, requests = run_order(
            sources,
            scratch / f"seed-{seed}",
            seed,
            provider_factory=provider_factory,
            repeats=2 if index == 0 else 0,
        )
        report.runs.append(view)
        if index == 0:
            report.repeat_identical, report.repeat_new_requests = identical, requests
    report.items = differences(report.runs)
    return report


def to_dict(report: VarianceReport) -> dict[str, Any]:
    """JSON-ready summary (synthetic fixture IDs and quotes only)."""
    return {
        "version": VARIANCE_VERSION,
        "stable": report.stable,
        "silent_drift": report.silent_drift,
        "seeds": [r.seed for r in report.runs],
        "orders_differ": len({r.order for r in report.runs}) == len(report.runs),
        "segments": len(report.runs[0].classification) if report.runs else 0,
        "records": len(report.runs[0].records) if report.runs else 0,
        "repeat_identical": report.repeat_identical,
        "repeat_new_requests": report.repeat_new_requests,
        "review_items": [
            {"kind": i.kind, "key": i.key, "values": list(i.values)} for i in report.items
        ],
    }
