"""Parser and import fidelity: every node of every export accounted for (EVAL-002).

For each export (by default every synthetic fixture case), the evaluation:

1. takes a **census** of the source files itself: every JSON file, inside
   folders and ZIPs, is searched for conversation objects (anything with a
   ``mapping``), and their node IDs are listed. This is a third opinion,
   independent of both the importer's adapters and ING-007's tally;
2. imports the export into a **scratch workspace** (never yours);
3. compares, per conversation, the source node IDs with the stored ones.

Each export then gets a verdict:

* ``ok``: every source node is stored, nothing to warn about;
* ``warned``: every source node is stored but the import warned about
  something (missing images, duplicate conversations in the source, an
  unknown payload...), or some nodes are missing **and** the import said so
  (a failed conversation, an ``integrity_mismatch`` warning);
* ``silent_drop``: nodes are missing and nothing in the report admits it.
  That is the failure this evaluation exists to catch: the acceptance bar
  is zero.

It also measures **branch retention** (nodes off the selected path that
were kept), **missing assets** (image occurrences whose bytes aren't
there) and the **unknown payload audit** (parts kept only as raw JSON,
content types seen).

The report is numbers and fixture case names only, never message text or
private file names (a non-fixture export is named ``export-N``).

Talking points:
    - "It counts every node in the files on its own, imports them, and
      checks each one landed. A node can go missing only if the report
      says so."
    - "Alternative branches count too: an edit or a regeneration that's
      no longer selected must still be in the archive."
"""

from __future__ import annotations

import json
import zipfile
from collections import Counter, defaultdict
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

FIDELITY_VERSION = "eval-002-v1"
_MAX_DEPTH = 4  # how deep to look inside a JSON file for conversation objects


@dataclass
class Census:
    """What the source files hold, counted without the importer.

    Attributes:
        conversations: Conversation objects found (a duplicate ID counts twice).
        nodes: Native conversation ID -> every node ID in its mapping(s).
        messages: Nodes carrying a message.
        inactive: Native conversation ID -> message nodes off the selected path.
    """

    conversations: int = 0
    nodes: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    messages: int = 0
    inactive: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))


def _json_documents(export: Path) -> Iterator[Any]:
    """Every parseable JSON document in a folder or ZIP (unparseable ones are skipped)."""
    paths = [export] if export.is_file() else sorted(p for p in export.rglob("*") if p.is_file())
    for path in paths:
        if path.suffix.lower() == ".json":
            try:
                yield json.loads(path.read_bytes())
            except (ValueError, UnicodeDecodeError):
                continue
        elif path.suffix.lower() == ".zip":
            with zipfile.ZipFile(path) as archive:
                for name in sorted(archive.namelist()):
                    if name.lower().endswith(".json"):
                        try:
                            yield json.loads(archive.read(name))
                        except (ValueError, UnicodeDecodeError):
                            continue


def _conversations(value: Any, depth: int = 0) -> Iterator[Mapping[str, Any]]:
    if depth > _MAX_DEPTH:
        return
    if isinstance(value, Mapping):
        if isinstance(value.get("mapping"), Mapping):
            yield value
            return
        for item in value.values():
            yield from _conversations(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            yield from _conversations(item, depth + 1)


def _active_path(mapping: Mapping[str, Any], current: Any) -> set[str]:
    path: set[str] = set()
    node = current if isinstance(current, str) else None
    while node is not None and node in mapping and node not in path:
        path.add(node)
        parent = mapping[node].get("parent") if isinstance(mapping[node], Mapping) else None
        node = parent if isinstance(parent, str) else None
    return path


def census(export: Path) -> Census:
    """Count conversations and nodes straight from the files."""
    found = Census()
    for document in _json_documents(export):
        for conversation in _conversations(document):
            native = conversation.get("id") or conversation.get("conversation_id")
            if not isinstance(native, str):
                continue
            found.conversations += 1
            mapping: Mapping[str, Any] = conversation["mapping"]
            active = _active_path(mapping, conversation.get("current_node"))
            for node_id, node in mapping.items():
                found.nodes[native].add(str(node_id))
                if isinstance(node, Mapping) and isinstance(node.get("message"), Mapping):
                    found.messages += 1
                    if node_id not in active:
                        found.inactive[native].add(str(node_id))
    return found


@dataclass(frozen=True)
class ExportFidelity:
    """One export's result. Counts only.

    Attributes:
        name: The fixture case name, or ``export-N``.
        layout: The fixture's layout, or ``export``.
        source_conversations: Conversation objects in the files.
        stored_conversations: Conversation rows the import holds.
        source_nodes: Node IDs in the files (per conversation, deduplicated).
        stored_nodes: Of those, how many are stored.
        dropped_nodes: Source nodes not stored.
        inactive_nodes: Message nodes off the selected path, in the files.
        inactive_kept: Of those, how many are stored.
        missing_assets: Image occurrences without their bytes.
        unparsed_parts: Content parts kept only as raw JSON.
        content_types: Message content types seen.
        warnings: Import warning code -> count.
        reconciled: ING-007's own verdict.
        verdict: ``ok``, ``warned`` or ``silent_drop``.
    """

    name: str
    layout: str
    source_conversations: int
    stored_conversations: int
    source_nodes: int
    stored_nodes: int
    dropped_nodes: int
    inactive_nodes: int
    inactive_kept: int
    missing_assets: int
    unparsed_parts: int
    content_types: tuple[str, ...]
    warnings: Mapping[str, int]
    reconciled: bool
    verdict: str


@dataclass(frozen=True)
class FidelityReport:
    """Every export's result, and whether the evaluation passed."""

    exports: tuple[ExportFidelity, ...]

    @property
    def passed(self) -> bool:
        """True when no export lost a node without saying so."""
        return all(e.verdict != "silent_drop" for e in self.exports)


def evaluate_export(export: Path, scratch: Path, *, name: str, layout: str) -> ExportFidelity:
    """Census, import into ``scratch`` and compare one export.

    Args:
        export: The export folder or ZIP (only read).
        scratch: An empty folder for the throwaway workspace.
        name: How the report names it.
        layout: The layout label for the report.
    """
    from knowledge_engine.importer.records import ConversationRow, MessageNodeRow
    from knowledge_engine.importer.run import run_import
    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
    from knowledge_engine.settings import Settings

    source = census(export)
    settings = Settings(workspace_root=scratch / "ws")
    report = run_import(export, "fidelity", format_id=None, settings=settings)
    engine = create_sqlite_engine(database_path(settings))
    stored: dict[str, set[str]] = defaultdict(set)
    try:
        with Session(engine) as session:
            rows = session.execute(
                select(ConversationRow.native_conversation_id, MessageNodeRow.native_node_id).join(
                    MessageNodeRow,
                    MessageNodeRow.conversation_id == ConversationRow.conversation_id,
                )
            )
            for native, node in rows.tuples():
                stored[native].add(node)
            stored_conversations = len(
                session.scalars(select(ConversationRow.conversation_id)).all()
            )
    finally:
        engine.dispose()
    source_nodes = sum(len(ids) for ids in source.nodes.values())
    kept = sum(len(ids & stored.get(native, set())) for native, ids in source.nodes.items())
    inactive = sum(len(ids) for ids in source.inactive.values())
    inactive_kept = sum(
        len(ids & stored.get(native, set())) for native, ids in source.inactive.items()
    )
    integrity: Mapping[str, Any] = report.integrity
    warnings = dict(sorted(report.warnings.items()))
    missing = sum(n for state, n in report.asset_occurrences.items() if state != "available")
    dropped = source_nodes - kept
    reconciled = bool(integrity.get("reconciled", True))
    return ExportFidelity(
        name=name,
        layout=layout,
        source_conversations=source.conversations,
        stored_conversations=stored_conversations,
        source_nodes=source_nodes,
        stored_nodes=kept,
        dropped_nodes=dropped,
        inactive_nodes=inactive,
        inactive_kept=inactive_kept,
        missing_assets=missing,
        unparsed_parts=int(integrity.get("unparsed_parts", 0)),
        content_types=tuple(sorted(integrity.get("content_types", {}))),
        warnings=warnings,
        reconciled=reconciled,
        verdict=verdict(dropped, warnings, reconciled, missing),
    )


def verdict(dropped: int, warnings: Mapping[str, int], reconciled: bool, missing: int) -> str:
    """``ok``, ``warned`` or ``silent_drop`` (see the module text)."""
    if dropped:
        # A loss is acceptable only if the import report itself admits something is off.
        return "warned" if (warnings or not reconciled) else "silent_drop"
    return "warned" if (warnings or missing) else "ok"


def evaluate_fixtures(fixtures: Path, scratch: Path) -> FidelityReport:
    """Run ``evaluate_export`` on every fixture case under ``fixtures`` (``<case>/export``)."""
    results = []
    for case in sorted(p for p in fixtures.iterdir() if (p / "export").exists()):
        manifest = case / "manifest.json"
        layout = "unknown"
        if manifest.is_file():
            layout = str(json.loads(manifest.read_text(encoding="utf-8")).get("layout", layout))
        export = case / "export"
        zips = sorted(export.glob("*.zip"))
        if zips and len(list(export.iterdir())) == 1:
            export = zips[0]  # a ZIP export is imported as the ZIP itself
        results.append(evaluate_export(export, scratch / case.name, name=case.name, layout=layout))
    return FidelityReport(tuple(results))


def to_dict(report: FidelityReport) -> dict[str, Any]:
    """JSON-ready, counts and names only."""
    return {
        "version": FIDELITY_VERSION,
        "passed": report.passed,
        "verdicts": dict(Counter(e.verdict for e in report.exports)),
        "exports": [
            {
                "name": e.name,
                "layout": e.layout,
                "conversations": {
                    "source": e.source_conversations,
                    "stored": e.stored_conversations,
                },
                "nodes": {
                    "source": e.source_nodes,
                    "stored": e.stored_nodes,
                    "dropped": e.dropped_nodes,
                },
                "inactive_nodes": {"source": e.inactive_nodes, "kept": e.inactive_kept},
                "missing_assets": e.missing_assets,
                "unparsed_parts": e.unparsed_parts,
                "content_types": list(e.content_types),
                "warnings": dict(e.warnings),
                "reconciled": e.reconciled,
                "verdict": e.verdict,
            }
            for e in report.exports
        ],
    }


def to_markdown(report: FidelityReport) -> str:
    """The committed report: one row per export, then the totals."""
    lines = [
        "<!-- Generated by `ke eval fidelity` from the synthetic fixtures. Numbers only; "
        "regenerate, never edit by hand. -->",
        "",
        f"# Import fidelity ({FIDELITY_VERSION})",
        "",
        f"**{'PASS' if report.passed else 'FAIL'}**: "
        + ", ".join(
            f"{n} {v}" for v, n in sorted(Counter(e.verdict for e in report.exports).items())
        )
        + ". A `silent_drop` (a node missing with nothing in the report saying so) fails the run.",
        "",
        "| Export | Layout | Chats (files / stored) | Nodes (files / stored) | Dropped "
        "| Off-path nodes kept | Missing images | Raw-only parts | Warnings | Verdict |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for e in report.exports:
        warned = ", ".join(f"{k} {v}" for k, v in e.warnings.items()) or "none"
        lines.append(
            f"| {e.name} | {e.layout} | {e.source_conversations} / {e.stored_conversations} "
            f"| {e.source_nodes} / {e.stored_nodes} | {e.dropped_nodes} "
            f"| {e.inactive_kept} of {e.inactive_nodes} | {e.missing_assets} "
            f"| {e.unparsed_parts} | {warned} | {e.verdict} |"
        )
    total = sum(e.source_nodes for e in report.exports)
    kept = sum(e.stored_nodes for e in report.exports)
    inactive = sum(e.inactive_nodes for e in report.exports)
    inactive_kept = sum(e.inactive_kept for e in report.exports)
    types = sorted({t for e in report.exports for t in e.content_types})
    lines += [
        "",
        "## Totals",
        "",
        f"- Nodes: {kept} of {total} stored ({total - kept} dropped).",
        f"- Branch retention: {inactive_kept} of {inactive} off-path message nodes kept.",
        f"- Missing images: {sum(e.missing_assets for e in report.exports)} occurrence(s), "
        "each recorded with its state.",
        f"- Unknown payload: {sum(e.unparsed_parts for e in report.exports)} part(s) kept only "
        f"as raw JSON; content types seen: {', '.join(types) or 'none'}.",
        "",
    ]
    return "\n".join(lines)
