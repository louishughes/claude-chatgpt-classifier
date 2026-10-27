"""Import: the one deep module behind ``import_source`` (M1_CONSOLIDATION §2.2).

Everything an import involves (choosing an adapter, snapshotting files,
logical identity, revisions, transactions, the report) is hidden behind one
function. Callers get a report; they can't call the steps in the wrong
order because they never see the steps.

Talking points:
    - "My whole importer is one function: give it a folder and an account
      label, get a report back."
    - "Importing the same export twice adds nothing: one test owns that
      promise, through this one function."
"""

from __future__ import annotations

from pathlib import Path

from knowledge_engine.importer.report import ImportReport
from knowledge_engine.settings import Settings, load_settings

__all__ = ["ImportReport", "import_source"]


def import_source(
    path: Path,
    account_ns: str,
    *,
    format: str | None = None,  # noqa: A002 - matches the CLI flag and the design note
    settings: Settings | None = None,
    full_export: bool = True,
) -> ImportReport:
    """Import one export (folder or ZIP) into the workspace and report what changed.

    Idempotent: importing identical material again adds no logical records
    and reports everything as ``unchanged``. The source is only read; the
    report proves it with tree fingerprints taken before and after.

    Args:
        path: The raw root: an export folder, a ZIP, or a split-export folder.
        account_ns: The account label for these conversations (OD-03).
        format: Force an adapter (``chatgpt-export-v1`` or
            ``chatgpt-split-v1``); None probes.
        settings: Settings to use; loaded from the environment if None.
        full_export: True when the source is a whole-history export, so a
            conversation it lacks is marked ``not_seen``. False for a partial
            source (one shared chat, a hand-picked folder): nothing is marked.

    Returns:
        The import report.

    Raises:
        UnsupportedFormatError: If no single adapter recognises the source.
        BlobCorruptError: If a previously archived copy is damaged.
        SourceTooLargeError: If an input file is over the size limit.
    """
    from knowledge_engine.importer.run import run_import

    return run_import(
        path,
        account_ns,
        format_id=format,
        settings=settings or load_settings(),
        full_export=full_export,
    )
