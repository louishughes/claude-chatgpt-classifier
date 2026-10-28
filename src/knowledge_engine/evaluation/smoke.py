"""Batch smoke test: import, re-import and render N conversations (EVAL-010).

One run does the whole M1 path on a batch and records what happened:

1. fingerprint the source (read-only proof);
2. import it, timed;
3. import it again, timed, and count every logical table before and after
   (the second import must add nothing);
4. render every imported conversation as a source transcript note into a
   scratch vault, timed, and run the link checker on each;
5. fingerprint the source again.

The result is counts, timings and warning codes only: no titles, text or
file names, so a run on real data can be shared.

Talking points:
    - "The smoke test runs the whole pipeline on 50 and 100 conversations
      and proves the second import adds nothing and the raw files didn't
      change."
    - "Its report is numbers only, so it's safe to run on my real archive."
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.importer.run import run_import
from knowledge_engine.infrastructure.db import Base, create_sqlite_engine, database_path
from knowledge_engine.ingestion.inventory import tree_signature
from knowledge_engine.rendering.transcript import load_conversation, write_transcript
from knowledge_engine.settings import Settings

# Tables that record attempts, which are allowed to grow on every run.
_LEDGER_TABLES = {"import_batches", "import_batch_files"}


def run_smoke(
    root: Path,
    settings: Settings,
    *,
    limit: int | None = None,
    account_ns: str = "smoke",
    vault: Path | None = None,
) -> dict[str, Any]:
    """Run the import / re-import / render path on one source.

    Args:
        root: The export (folder or ZIP). Only read.
        settings: Settings for a *scratch* workspace.
        limit: Import only the first N conversations (None for all).
        account_ns: Account label for the batch.
        vault: Where to render notes; defaults to ``<workspace>/smoke-vault``.

    Returns:
        A JSON-ready report: counts, timings, warning codes, and pass/fail
        checks. No private content.
    """
    vault = vault or settings.workspace_root / "smoke-vault"
    before = tree_signature(root)

    started = time.perf_counter()
    first = run_import(root, account_ns, format_id=None, settings=settings, limit=limit)
    import_s = time.perf_counter() - started
    counts_after_first = _logical_counts(settings)

    started = time.perf_counter()
    second = run_import(root, account_ns, format_id=None, settings=settings, limit=limit)
    reimport_s = time.perf_counter() - started
    counts_after_second = _logical_counts(settings)

    started = time.perf_counter()
    notes, broken = _render_all(settings, vault)
    render_s = time.perf_counter() - started
    after = tree_signature(root)

    added = {
        table: counts_after_second[table] - counts_after_first[table]
        for table in counts_after_first
        if counts_after_second[table] != counts_after_first[table]
    }
    checks = {
        "reimport_adds_nothing": not added,
        "reimport_all_unchanged": set(second.conversations) <= {"unchanged"},
        "zero_model_calls": first.model_calls_triggered == second.model_calls_triggered == 0,
        "all_rendered": notes == counts_after_second.get("conversations", 0),
        "no_broken_embeds": broken == 0,
        "raw_unchanged": before == after,
        "reconciled": bool(first.integrity.get("reconciled")),
    }
    return {
        "conversations": counts_after_second.get("conversations", 0),
        "limit": limit,
        "timings_s": {
            "import": round(import_s, 3),
            "reimport": round(reimport_s, 3),
            "render": round(render_s, 3),
        },
        "peak_memory_mb": _peak_memory_mb(),
        "first_import": first.to_dict(),
        "reimport": {
            "conversations": dict(second.conversations),
            "messages": dict(second.messages),
            "changed_revisions": len(second.changed_revisions),
            "added_records": added,
        },
        "render": {"notes": notes, "broken_embeds": broken},
        "logical_records": counts_after_second,
        "checks": checks,
        "passed": all(checks.values()),
    }


def _logical_counts(settings: Settings) -> dict[str, int]:
    engine = create_sqlite_engine(database_path(settings))
    try:
        with engine.connect() as conn:
            return {
                table.name: int(conn.scalar(select(func.count()).select_from(table)) or 0)
                for table in Base.metadata.sorted_tables
                if table.name not in _LEDGER_TABLES
            }
    finally:
        engine.dispose()


def _render_all(settings: Settings, vault: Path) -> tuple[int, int]:
    engine = create_sqlite_engine(database_path(settings))
    notes = broken = 0
    try:
        with Session(engine) as session:
            for conversation_id in session.scalars(
                select(ConversationRow.conversation_id).order_by(ConversationRow.conversation_id)
            ):
                conversation = load_conversation(session, conversation_id)
                _, missing = write_transcript(
                    session, conversation, vault, settings.workspace_root / "archive"
                )
                notes += 1
                broken += len(missing)
    finally:
        engine.dispose()
    return notes, broken


UNAVAILABLE = "unavailable_on_platform"


def _peak_memory_mb() -> float | str:
    # Peak resident memory of this process, in MiB. POSIX has the resource
    # module; Windows has GetProcessMemoryInfo, reached through ctypes so no
    # new dependency is needed (OPS-009). Anything else says so plainly.
    if sys.platform == "win32":
        return _windows_peak_mb()
    try:
        import resource
    except ImportError:
        return UNAVAILABLE
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # Linux reports KiB, macOS bytes.
    divisor = 1024 * 1024 if sys.platform == "darwin" else 1024
    return round(peak / divisor, 1)


def _windows_peak_mb() -> float | str:
    import ctypes
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        # PROCESS_MEMORY_COUNTERS, from psapi.h.
        _fields_ = [  # noqa: RUF012 - ctypes needs a class attribute
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    try:
        windll = ctypes.WinDLL  # type: ignore[attr-defined,unused-ignore]
        psapi, kernel32 = windll("psapi"), windll("kernel32")
        kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        # Without argtypes ctypes passes the process pseudo-handle (-1 as an
        # unsigned 64-bit value) as a C int, which overflows on 64-bit Windows.
        psapi.GetProcessMemoryInfo.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(Counters),
            wintypes.DWORD,
        ]
        psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
        counters = Counters()
        counters.cb = ctypes.sizeof(Counters)
        ok = psapi.GetProcessMemoryInfo(
            kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb
        )
    except (AttributeError, OSError, ctypes.ArgumentError):
        return UNAVAILABLE
    if not ok:
        return UNAVAILABLE
    return round(int(counters.PeakWorkingSetSize) / (1024 * 1024), 1)
