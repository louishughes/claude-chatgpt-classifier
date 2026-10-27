"""Slice I5: imports into one workspace run one at a time (IMP-004).

Acceptance (IMP-004): N repeated or concurrent imports of the same fixture
produce identical logical record counts. The crash-and-rerun half is owned
by ``test_import_source.py``.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import func, select

from knowledge_engine.importer import import_source
from knowledge_engine.importer.lock import ImportLockTimeoutError, import_lock
from knowledge_engine.infrastructure.db import Base, create_sqlite_engine, database_path
from knowledge_engine.settings import Settings, load_settings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt"
LEDGER_TABLES = {"import_batches", "import_batch_files"}

# Run in a separate Python process, so the two imports really are concurrent
# processes, as two `ke import` commands would be.
_CHILD = """
import json, sys
from pathlib import Path
from knowledge_engine.importer import import_source
from knowledge_engine.settings import load_settings
settings = load_settings(workspace_root=Path(sys.argv[2]))
report = import_source(Path(sys.argv[1]), "fixture", settings=settings)
print(json.dumps(report.to_dict()))
"""


def _counts(settings: Settings) -> dict[str, int]:
    engine = create_sqlite_engine(database_path(settings))
    try:
        with engine.connect() as conn:
            return {
                table.name: int(conn.scalar(select(func.count()).select_from(table)) or 0)
                for table in Base.metadata.sorted_tables
                if table.name not in LEDGER_TABLES
            }
    finally:
        engine.dispose()


def test_two_concurrent_imports_equal_one(tmp_path: Path) -> None:
    root = FIXTURES / "reexport_v1" / "export"
    serial = load_settings(workspace_root=tmp_path / "serial")
    import_source(root, "fixture", settings=serial)
    concurrent = tmp_path / "concurrent"

    children = [
        subprocess.Popen(
            [sys.executable, "-c", _CHILD, str(root), str(concurrent)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(2)
    ]
    outputs = [child.communicate(timeout=120) for child in children]

    assert [child.returncode for child in children] == [0, 0], [err for _, err in outputs]
    reports = [json.loads(out) for out, _ in outputs]
    assert all(report["status"] == "succeeded" for report in reports)
    # One import did the work; the other waited, then found it all done.
    categories = sorted(tuple(report["conversations"]) for report in reports)
    assert categories == [("new",), ("unchanged",)]
    assert sorted(report["changed_revisions"] for report in reports)[0] == 0
    assert _counts(load_settings(workspace_root=concurrent)) == _counts(serial)


def test_second_import_waits_for_the_lock_then_gives_up(tmp_path: Path) -> None:
    with (
        import_lock(tmp_path, timeout_s=1.0),
        pytest.raises(ImportLockTimeoutError),
        import_lock(tmp_path, timeout_s=0.1),
    ):
        pass  # pragma: no cover - the inner lock must not be acquired


def test_lock_is_free_again_after_an_error(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError), import_lock(tmp_path, timeout_s=1.0):
        raise RuntimeError("import failed")

    with import_lock(tmp_path, timeout_s=0.1):
        pass
