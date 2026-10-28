"""What the pages show, read from the workspace database (UI-001).

Everything here only reads. The plain-words summary turns a stored import
report into sentences a non-programmer can act on.

Talking points:
    - "The report page doesn't recompute anything: it reads the receipt the
      import saved and explains it in plain English."
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from knowledge_engine.importer.ledger import ImportBatchRow
from knowledge_engine.importer.records import ConversationRow


@dataclass(frozen=True)
class ImportRow:
    """One past import, as the home page lists it."""

    import_id: str
    status: str
    started_at: datetime
    format_id: str
    conversations: dict[str, int]


def workspace_status(session: Session) -> dict[str, int]:
    """Return headline counts: conversations stored, present, not seen, imports."""
    present = session.scalar(
        select(func.count())
        .select_from(ConversationRow)
        .where(ConversationRow.presence == "present")
    )
    total = session.scalar(select(func.count()).select_from(ConversationRow))
    imports = session.scalar(select(func.count()).select_from(ImportBatchRow))
    return {
        "conversations": int(total or 0),
        "present": int(present or 0),
        "not_seen": int((total or 0) - (present or 0)),
        "imports": int(imports or 0),
    }


def list_imports(session: Session, limit: int = 50) -> list[ImportRow]:
    """Return the most recent imports, newest first."""
    rows = session.scalars(
        select(ImportBatchRow).order_by(ImportBatchRow.started_at.desc()).limit(limit)
    ).all()
    return [
        ImportRow(
            import_id=row.import_id,
            status=row.status,
            started_at=row.started_at,
            format_id=row.format_id,
            conversations=dict(_counts(row).get("conversations", {})),
        )
        for row in rows
    ]


def load_report(session: Session, import_id: str) -> dict[str, Any] | None:
    """Return one stored import report (counts, warnings, status), or None."""
    row = session.get(ImportBatchRow, import_id)
    if row is None:
        return None
    # The ledger's own columns win over the stored copy in the counts.
    return {
        **_counts(row),
        "import_id": row.import_id,
        "status": row.status,
        "started_at": row.started_at,
        "finished_at": row.finished_at,
        "format_id": row.format_id,
        "warnings": json.loads(row.warnings_json or "{}"),
    }


def plain_words(report: dict[str, Any]) -> list[tuple[str, str]]:
    """Explain a stored report as short sentences, each with a tone.

    Args:
        report: From ``load_report``.

    Returns:
        ``(tone, sentence)`` pairs; tone is ``good``, ``info`` or ``look``
        (something a person may want to check).
    """
    lines: list[tuple[str, str]] = []
    status = report.get("status")
    if status == "running":
        return [("info", "This import is still running, or it stopped before finishing.")]
    if status == "abandoned":
        return [("look", "This import stopped part-way. Running it again finishes the job.")]
    conversations: dict[str, int] = report.get("conversations", {})
    new, revised = conversations.get("new", 0), conversations.get("revised", 0)
    unchanged = conversations.get("unchanged", 0)
    lines.append(
        ("info", f"{_n(new, 'new chat')}, {_n(revised, 'changed chat')}, {unchanged} unchanged.")
    )
    if not new and not revised:
        lines.append(("good", "Nothing new: this export was already in the archive."))
    if branches := report.get("new_branches", 0):
        lines.append(
            (
                "info",
                f"{_n(branches, 'new branch', 'new branches')} (edited or regenerated messages).",
            )
        )
    if not_seen := conversations.get("not_seen", 0):
        lines.append(
            (
                "info",
                f"{_n(not_seen, 'chat')} weren't in this export. They are kept, marked "
                "'not seen', never deleted.",
            )
        )
    summary: dict[str, Any] = report.get("summary", {})
    if new_media := summary.get("new_media", 0):
        lines.append(("info", f"{_n(new_media, 'new image or file', 'new images or files')}."))
    occurrences: dict[str, int] = report.get("asset_occurrences", {})
    problems = {state: n for state, n in occurrences.items() if state != "available" and n}
    if problems:
        detail = ", ".join(f"{n} {state}" for state, n in sorted(problems.items()))
        lines.append(("look", f"Some images couldn't be found or matched: {detail}."))
    if candidates := summary.get("candidate_duplicates", 0):
        lines.append(
            ("look", f"{_n(candidates, 'chat')} set aside because its ID was missing or clashed.")
        )
    if failed := summary.get("failed", 0):
        lines.append(("look", f"{_n(failed, 'chat')} couldn't be imported."))
    integrity: dict[str, Any] = report.get("integrity", {})
    if integrity and not integrity.get("reconciled", True):
        mismatches = ", ".join(integrity.get("mismatches", []))
        lines.append(("look", f"The source and the archive disagree on: {mismatches}."))
    elif integrity:
        lines.append(("good", "Every message and image reference in the source is accounted for."))
    if report.get("raw_tree_unchanged") is True:
        lines.append(("good", "Your original files were not changed."))
    elif report.get("raw_tree_unchanged") is False:
        lines.append(("look", "The source folder changed while it was being read. Run it again."))
    rebuild = summary.get("rebuild", {})
    if rebuild.get("conversations"):
        lines.append(
            ("info", f"{_n(rebuild['conversations'], 'chat')} will be (re)analysed by later steps.")
        )
    return lines


def _counts(row: ImportBatchRow) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(row.counts_json or "{}")
    return data


def _n(count: int, singular: str, plural: str | None = None) -> str:
    return f"{count} {singular if count == 1 else (plural or singular + 's')}"
