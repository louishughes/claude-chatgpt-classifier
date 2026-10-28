"""SQLite versus PostgreSQL on the same generated export (PROD-001 benchmark).

``python -m knowledge_engine.evaluation.backend_bench --conversations 500``
generates synthetic conversations, imports them into a SQLite workspace and
into a private temporary PostgreSQL server, imports them a second time
(which must change nothing), and runs the same word searches against each.
It prints seconds per step and the stored row counts, which must be equal.

It needs PostgreSQL's programs on this computer and a non-root user (see
``devtools.postgres``). No model is called and nothing leaves the machine.

Talking points:
    - "Before anyone hosts this, there's a measured answer to 'how does
      the same import behave on PostgreSQL?', from the same code."
"""

from __future__ import annotations

import argparse
import json
import tempfile
import time
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, func, select
from sqlalchemy.orm import Session

from knowledge_engine.devtools.postgres import new_database, temporary_server
from knowledge_engine.evaluation.synthetic import write_generated
from knowledge_engine.importer.run import run_import
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.infrastructure.dialects import create_postgres_engine
from knowledge_engine.infrastructure.migrations.tables import all_tables
from knowledge_engine.infrastructure.workspace import WorkspaceRow
from knowledge_engine.retrieval.lexical import LexicalIndex, sync_index
from knowledge_engine.settings import Settings

WORDS = ("synthetic", "question", "answer", "regenerated", "edited", "python", "print", "image")


def _rows(engine: Engine) -> dict[str, int]:
    with Session(engine) as session:
        return {
            table.name: int(session.scalar(select(func.count()).select_from(table)) or 0)
            for table in all_tables().sorted_tables
        }


def _backend(export: Path, work: Path, url: str | None) -> dict[str, Any]:
    settings = Settings(workspace_root=work)
    timings: dict[str, float] = {}
    for step in ("first_import", "repeat_import"):
        started = time.perf_counter()
        report = run_import(export, "bench", format_id=None, settings=settings, database_url=url)
        timings[step] = round(time.perf_counter() - started, 3)
        if step == "repeat_import" and set(report.conversations) != {"unchanged"}:
            raise RuntimeError("the repeat import changed something")
    engine = create_postgres_engine(url) if url else create_sqlite_engine(database_path(settings))
    try:
        with Session(engine) as session:
            started = time.perf_counter()
            with LexicalIndex(work / "rebuilt-search.db") as index:
                sync_index(session, index)
                timings["search_index_rebuild"] = round(time.perf_counter() - started, 3)
                workspace = session.scalars(select(WorkspaceRow.workspace_id)).one()
                started = time.perf_counter()
                hits = sum(len(index.search(w, workspace_id=workspace)) for w in WORDS)
                timings["searches"] = round(time.perf_counter() - started, 4)
        return {"seconds": timings, "search_hits": hits, "rows": _rows(engine)}
    finally:
        engine.dispose()


def run(conversations: int, seed: int = 1) -> dict[str, Any]:
    """Benchmark both backends on one generated export."""
    with tempfile.TemporaryDirectory(prefix="ke-bench-") as folder:
        work = Path(folder)
        export = write_generated(work / "source", conversations, seed) / "export"
        sqlite = _backend(export, work / "sqlite", None)
        with temporary_server() as server:
            postgres = _backend(export, work / "postgres", new_database(server))
    return {
        "conversations": conversations,
        "sqlite": sqlite["seconds"],
        "postgres": postgres["seconds"],
        "search_hits": {"sqlite": sqlite["search_hits"], "postgres": postgres["search_hits"]},
        "rows_equal": sqlite["rows"] == postgres["rows"],
        "rows": sum(sqlite["rows"].values()),
    }


def main() -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--conversations", type=int, default=200)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()
    print(json.dumps(run(args.conversations, args.seed), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
