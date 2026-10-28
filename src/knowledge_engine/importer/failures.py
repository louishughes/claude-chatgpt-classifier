"""Why an import couldn't start, in words a person can act on (UI-002).

The command line and the web interface both run ``import_source`` and need
to say the same thing when it stops early. Messages never include paths or
file names: they can be private, and these messages may be shared.

Talking points:
    - "If an import can't run, both the CLI and the browser give the same
      short reason, and never print my private file names."
"""

from __future__ import annotations

from dataclasses import dataclass

from knowledge_engine.importer.archive import BlobStoreError
from knowledge_engine.importer.lock import ImportLockTimeoutError
from knowledge_engine.ingestion.source import (
    SourceTooLargeError,
    UnsafeArchiveError,
    UnsupportedFormatError,
)


@dataclass(frozen=True)
class ImportFailure:
    """A known reason an import stopped: a stable code and a plain message."""

    code: str
    message: str


def describe_failure(error: BaseException) -> ImportFailure | None:
    """Return the plain reason for a known import error, or None if unknown.

    Args:
        error: What ``import_source`` raised.

    Returns:
        The reason, or None (an unexpected bug: let it surface).
    """
    known: list[tuple[type[BaseException], str, str]] = [
        (FileNotFoundError, "not_found", "That file or folder doesn't exist."),
        (
            UnsupportedFormatError,
            "unsupported_format",
            "That isn't a ChatGPT export this version understands (a ZIP or folder "
            "with conversations.json, or a split export).",
        ),
        (
            UnsafeArchiveError,
            "unsafe_archive",
            "The ZIP contains unsafe paths, so it wasn't opened.",
        ),
        (SourceTooLargeError, "too_large", "A file in the export is over the size limit."),
        (
            ImportLockTimeoutError,
            "busy",
            "Another import is running in this workspace. Try again when it finishes.",
        ),
        (
            BlobStoreError,
            "archive_damaged",
            "A previously archived copy is damaged; nothing was changed. Run `ke status`.",
        ),
    ]
    for kind, code, message in known:
        if isinstance(error, kind):
            return ImportFailure(code, message)
    return None
