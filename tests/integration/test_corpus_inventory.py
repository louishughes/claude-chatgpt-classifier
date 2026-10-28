"""NRM-006: the inventory covers every stored segment and changes nothing."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from knowledge_engine.importer import import_source
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.segmentation.inventory import corpus_inventory, summarise
from knowledge_engine.settings import Settings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt"


def test_inventory_covers_the_fixture_and_writes_nothing(tmp_path: Path) -> None:
    settings = Settings(workspace_root=tmp_path / "ws")
    import_source(FIXTURES / "topic_segments" / "export", "fixture", settings=settings)
    db = database_path(settings)
    before = db.read_bytes()
    engine = create_sqlite_engine(db)
    with Session(engine) as session:
        items = list(corpus_inventory(session))
        assert not session.new and not session.dirty
    engine.dispose()
    assert db.read_bytes() == before
    summary = summarise(items)
    # Three topics in one chat, one topic in the other.
    assert (summary.conversations, summary.segments) == (2, 4)
    assert all("Synthetic" in item.text for item in items)


def test_cli_corpus_shows_counts_and_ids_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from knowledge_engine.cli.main import main

    settings = Settings(workspace_root=tmp_path / "ws")
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(settings.workspace_root))
    assert main(["--json", "corpus"]) != 0  # nothing imported yet
    capsys.readouterr()
    import_source(FIXTURES / "topic_segments" / "export", "fixture", settings=settings)
    assert main(["--json", "corpus", "--sample", "3", "--seed", "s"]) == 0
    data = json.loads(capsys.readouterr().out)["data"]
    assert data["segments"] == 4
    assert len(data["sample"]["segment_ids"]) == 3
    assert "Synthetic" not in json.dumps(data)
