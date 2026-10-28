"""Where an import spends its time, phase by phase (PERF-001).

Builds a synthetic export shaped like a real one (many per-chat JSON files
plus hundreds of images the chats don't all use), then imports it twice into
a fresh workspace and times each phase of both runs. Nothing private is
read, and the numbers are comparable between machines.

Run it with ``python -m knowledge_engine.evaluation.import_timing``.

Talking points:
    - "I measured before I optimised: every phase of an import and a
      re-import, on generated data the same shape as mine."
"""

from __future__ import annotations

import argparse
import cProfile
import json
import os
import pstats
import random
import tempfile
import time
from pathlib import Path
from typing import Any

from knowledge_engine.evaluation.synthetic import write_generated
from knowledge_engine.importer.run import run_import
from knowledge_engine.settings import Settings

# Phase -> (file suffix, function name) whose cumulative time is that phase.
PHASES: dict[str, tuple[tuple[str, ...], str]] = {
    "raw tree fingerprint": (("ingestion/inventory.py",), "tree_signature"),
    "list the export": (("ingestion/chatgpt_export.py", "ingestion/chatgpt_split.py"), "open"),
    "archive source files": (("importer/ledger.py",), "record_file"),
    "  of which fsync": (("~",), "<built-in method posix.fsync>"),
    "conversations and messages": (("importer/delta.py",), "apply_conversation"),
    "images and attachments": (("importer/media.py",), "record_occurrences"),
    "links and accounts": (("links/store.py",), "record_links"),
    "related conversations": (("relationships/detect.py",), "detect_relationships"),
    "search index": (("retrieval/lexical.py",), "sync_index"),
}


def build_tree(root: Path, conversations: int, padding_images: int, seed: int = 7) -> Path:
    """Write a synthetic split-layout export with extra unused images."""
    write_generated(root, conversations, seed, layout="split")
    export = root / "export"
    rng = random.Random(seed)
    for index in range(padding_images):
        size = rng.randrange(40_000, 400_000)
        (export / f"file-PAD{index:05d}-synthetic.png").write_bytes(
            rng.randbytes(size)  # noise: real photos don't compress either
        )
    return export


def _phase_times(profile: cProfile.Profile) -> dict[str, float]:
    stats = pstats.Stats(profile).stats  # type: ignore[attr-defined]
    times: dict[str, float] = {}
    for phase, (suffixes, name) in PHASES.items():
        total = 0.0
        for (filename, _line, function), (_cc, _nc, _tt, cumulative, _callers) in stats.items():
            path = filename.replace(os.sep, "/")
            matches_file = suffixes == ("~",) or path.endswith(suffixes)
            if matches_file and function in (name, name.replace("posix", "nt")):
                total += cumulative
        times[phase] = round(total, 2)
    return times


def run(conversations: int, padding_images: int, limit: int | None) -> dict[str, Any]:
    """Import the same synthetic export twice and time each phase."""
    with tempfile.TemporaryDirectory(prefix="ke-timing-") as work:
        export = build_tree(Path(work) / "tree", conversations, padding_images)
        files = sum(1 for p in export.rglob("*") if p.is_file())
        settings = Settings(workspace_root=Path(work) / "ws")
        result: dict[str, Any] = {
            "conversations": conversations,
            "files": files,
            "limit": limit,
            "runs": {},
        }
        for label in ("import", "re-import"):
            profile = cProfile.Profile()
            started = time.perf_counter()
            profile.enable()
            report = run_import(export, "timing", format_id=None, settings=settings, limit=limit)
            profile.disable()
            elapsed = time.perf_counter() - started
            result["runs"][label] = {
                "seconds": round(elapsed, 2),
                "status": report.status.value,
                "phases": _phase_times(profile),
            }
        return result


def main() -> int:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--conversations", type=int, default=1100)
    parser.add_argument("--padding-images", type=int, default=900)
    parser.add_argument("--limit", type=int, default=50)
    args = parser.parse_args()
    print(json.dumps(run(args.conversations, args.padding_images, args.limit), indent=2))  # noqa: T201
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
