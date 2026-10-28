"""Watched folders: import new or changed exports when they land (INT-003).

You point ``ke watch`` at a folder (for example your downloads folder for
ChatGPT exports). Each export in it, a folder or a ``.zip`` at the top level,
is imported once it has stopped changing, and again only when its contents
change. Everything else is the importer's job, so its promises hold here:
the source is only read, and importing the same material twice adds nothing.

How one look at the folder (a *tick*) works:

1. **Debounce.** Each export's metadata fingerprint (names, sizes, modified
   times; no contents read) must be the same on two looks at least
   ``settle_s`` apart. A ZIP still being downloaded or a folder still being
   copied keeps changing, so it waits.
2. **Already seen?** The watch state (``<workspace>/watch/<key>.json``)
   remembers each export's fingerprints from last time. Same metadata: skip
   without reading anything. New metadata but contents already imported (a
   copy that was touched, re-downloaded or saved under a second name): note
   it and skip, so no import runs.
3. **Import.** Otherwise call the importer. A refused or broken export is
   recorded as ``failed`` with its error code and is not retried until it
   changes, so a bad file never loops.
4. **Affected stages.** If any import changed something and a vault is set,
   the vault is synced once (DOC-006): only notes whose content changed are
   rewritten; the rest stay byte-identical.

The report holds counts, error codes and import IDs only. Export names can
be private, so they never appear in it.

Talking points:
    - "Drop an export in the folder and it imports once it has finished
      copying. Dropping the same export again does nothing at all."
    - "A broken export is noted once and left alone until it changes."
"""

from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from knowledge_engine.importer.report import ImportReport
from knowledge_engine.ingestion.inventory import tree_signature
from knowledge_engine.settings import Settings

STATE_VERSION = 1
_CHUNK = 1 << 20

# Import one export: (path) -> report. The CLI passes the real importer.
Importer = Callable[[Path], ImportReport]
# Bring later stages up to date after a change; returns counts for the report.
Stage = Callable[[], dict[str, int]]


class WatchError(ValueError):
    """The folder can't be watched (missing, or inside the workspace)."""


def candidates(folder: Path) -> list[Path]:
    """The exports in a watched folder: top-level folders and ``.zip`` files.

    Hidden entries (``.name``) and anything else (partial downloads such as
    ``.crdownload`` or ``.part``, loose files) are ignored.
    """
    found = []
    for entry in sorted(folder.iterdir()):
        if entry.name.startswith((".", "~")) or entry.is_symlink():
            continue
        if entry.is_dir() or (entry.is_file() and entry.suffix.lower() == ".zip"):
            found.append(entry)
    return found


def content_fingerprint(source: Path) -> str:
    """SHA-256 over the exact bytes of every file (and its relative path)."""
    outer = hashlib.sha256()
    files = [source] if source.is_file() else sorted(p for p in source.rglob("*") if p.is_file())
    for path in files:
        inner = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(_CHUNK):
                inner.update(chunk)
        rel = path.name if path == source else path.relative_to(source).as_posix()
        outer.update(json.dumps([rel, inner.hexdigest()]).encode())
    return outer.hexdigest()


def state_path(settings: Settings, folder: Path) -> Path:
    """Where the watch state of one folder lives (one file per folder)."""
    key = hashlib.sha256(str(folder.resolve()).encode()).hexdigest()[:16]
    return settings.workspace_root / "watch" / f"{key}.json"


@dataclass
class TickReport:
    """What one look at the folder did. Counts and IDs only."""

    waiting: int = 0  # still changing (debounce)
    unchanged: int = 0  # same as last time, nothing read or imported
    same_contents: int = 0  # touched or re-copied, contents identical: not imported
    imported: list[str] = field(default_factory=list)  # import IDs
    failed: dict[str, int] = field(default_factory=dict)  # error code -> count
    changed_revisions: int = 0
    stages: dict[str, dict[str, int]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """A JSON-ready summary."""
        return {
            "waiting": self.waiting,
            "unchanged": self.unchanged,
            "same_contents": self.same_contents,
            "imported": len(self.imported),
            "import_ids": list(self.imported),
            "failed": dict(sorted(self.failed.items())),
            "changed_revisions": self.changed_revisions,
            "stages": self.stages,
        }

    @property
    def busy(self) -> bool:
        """Did anything happen worth printing?"""
        return bool(self.imported or self.failed or self.same_contents)


class FolderWatcher:
    """Watches one folder; call ``tick`` repeatedly (see the module docstring)."""

    def __init__(
        self,
        settings: Settings,
        folder: Path,
        importer: Importer,
        *,
        settle_s: float = 3.0,
        stages: dict[str, Stage] | None = None,
        clock: Callable[[], float] = time.monotonic,
        describe: Callable[[BaseException], str | None] | None = None,
    ) -> None:
        """Set up a watcher; raises WatchError if the folder can't be watched."""
        if not folder.is_dir():
            raise WatchError("that folder doesn't exist")
        workspace = settings.workspace_root.resolve()
        resolved = folder.resolve()
        if resolved == workspace or workspace in resolved.parents or resolved in workspace.parents:
            # The engine writes into its workspace; watching it would loop.
            raise WatchError("the watched folder can't contain or be inside the workspace")
        self._folder = folder
        self._importer = importer
        self._settle = settle_s
        self._stages = stages or {}
        self._clock = clock
        self._describe = describe
        self._path = state_path(settings, folder)
        self._state: dict[str, dict[str, Any]] = self._load()
        self._pending: dict[str, tuple[str, float]] = {}

    def _load(self) -> dict[str, dict[str, Any]]:
        if not self._path.is_file():
            return {}
        data = json.loads(self._path.read_text("utf-8"))
        entries: dict[str, dict[str, Any]] = data.get("entries", {})
        return entries

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        body = {"version": STATE_VERSION, "entries": self._state}
        temporary = self._path.with_suffix(".tmp")
        temporary.write_text(json.dumps(body, indent=2, sort_keys=True), encoding="utf-8")
        temporary.replace(self._path)  # never a half-written state file

    def _settled(self, name: str, signature: str, now: float) -> bool:
        seen = self._pending.get(name)
        if seen is None or seen[0] != signature:
            self._pending[name] = (signature, now)
            return False
        return now - seen[1] >= self._settle

    def tick(self) -> TickReport:
        """Look at the folder once and act on what has settled."""
        report = TickReport()
        now = self._clock()
        changed = False
        present = set()
        for source in candidates(self._folder):
            name = source.name
            present.add(name)
            try:
                signature = tree_signature(source)
            except OSError:
                report.waiting += 1  # vanished or locked mid-copy: look again later
                continue
            known = self._state.get(name, {})
            if known.get("stat") == signature:
                report.unchanged += 1
                self._pending.pop(name, None)
                continue
            if not self._settled(name, signature, now):
                report.waiting += 1
                continue
            self._pending.pop(name, None)
            contents = content_fingerprint(source)
            if any(e.get("contents") == contents for e in self._state.values()):
                # Already imported, under this name or another (a second copy).
                self._state[name] = known | {"stat": signature, "contents": contents}
                report.same_contents += 1
                changed = True
                continue
            entry: dict[str, Any] = {"stat": signature, "contents": contents}
            try:
                result = self._importer(source)
            except Exception as error:  # noqa: BLE001 - recorded, never retried until it changes
                code = (self._describe(error) if self._describe else None) or type(error).__name__
                entry |= {"status": "failed", "error": code}
                report.failed[code] = report.failed.get(code, 0) + 1
            else:
                entry |= {"status": result.status.value, "import_id": result.import_id}
                report.imported.append(result.import_id)
                report.changed_revisions += len(result.changed_revisions)
            self._state[name] = entry
            changed = True
        # A removed export is forgotten in the debounce only: its record stays,
        # because a chat missing from the folder is never a deletion.
        for name in list(self._pending):
            if name not in present:
                del self._pending[name]
        if changed:
            self._save()
        if report.changed_revisions:
            for stage, run in self._stages.items():
                report.stages[stage] = run()
        return report
