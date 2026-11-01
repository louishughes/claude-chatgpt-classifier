"""RCL-001: `recall history find` returns ke's hits, with chat title and date added."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from knowledge_engine.cli.main import main as ke_main
from knowledge_engine.importer import import_source
from knowledge_engine.recall.cli import main as recall_main
from knowledge_engine.settings import Settings

CASE = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt" / "search_terms"


@pytest.fixture(scope="module")
def workspace(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    settings = Settings(workspace_root=tmp_path_factory.mktemp("ws"))
    import_source(CASE / "export", "fixture", settings=settings)
    yield settings.workspace_root


@pytest.fixture
def env(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(workspace))
    return workspace


def _json(capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    out: dict[str, object] = json.loads(capsys.readouterr().out)
    return out


def test_same_hits_as_ke_search(env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert ke_main(["--json", "search", "synthetic", "--limit", "5"]) == 0
    ke_hits = _json(capsys)["data"]["hits"]  # type: ignore[index]
    assert recall_main(["history", "find", "synthetic", "--limit", "5", "--json"]) == 0
    recall = _json(capsys)
    assert recall["command"] == "history find"
    recall_hits = recall["data"]["hits"]  # type: ignore[index]
    assert [h["revision_id"] for h in recall_hits] == [h["revision_id"] for h in ke_hits]
    assert len(recall_hits) == 5


def test_hits_carry_title_date_and_ids(env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert (
        recall_main(["--json", "history", "find", "synthetic blue widget", "--mode", "phrase"]) == 0
    )
    hits = _json(capsys)["data"]["hits"]  # type: ignore[index]
    assert [h["native_node_id"] for h in hits] == ["c0000009-0000-4000-8000-000000000001-a1"]
    hit = hits[0]
    assert hit["conversation_id"].startswith("conv_")
    assert hit["title"]  # the fixture chat has a title
    assert hit["date"] is None or len(hit["date"]) == 10  # YYYY-MM-DD when dated
    assert "[" in hit["snippet"]  # the match is marked, as in ke search


def test_meaning_search_adds_a_snippet(env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert (
        recall_main(["--json", "history", "find", "blue widget", "--meaning", "--limit", "3"]) == 0
    )
    data = _json(capsys)["data"]
    assert data["how"] == "meaning"  # type: ignore[index]
    hits = data["hits"]  # type: ignore[index]
    assert hits
    assert all(isinstance(h["snippet"], str) for h in hits)
    assert all(len(h["snippet"]) <= 160 for h in hits)


def test_meaning_search_refuses_filters_it_cannot_apply(
    env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    code = recall_main(["--json", "history", "find", "x", "--meaning", "--since", "2024-01-01"])
    assert code == 2
    assert _json(capsys)["error"] == {"code": "usage"}


def test_text_output_for_a_person(env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert recall_main(["history", "find", "synthetic blue widget", "--mode", "phrase"]) == 0
    out = capsys.readouterr().out
    assert "c0000009-0000-4000-8000-000000000001-a1" in out
    assert "conv_" in out
    assert "{" not in out.splitlines()[0]  # plain text, not JSON


def test_no_workspace_yet(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(tmp_path / "empty"))
    assert recall_main(["--json", "history", "find", "anything"]) == 1
    assert _json(capsys)["error"] == {"code": "no_imports"}


def test_help_and_missing_command(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as done:
        recall_main(["--help"])
    assert done.value.code == 0
    assert "history" in capsys.readouterr().out
    assert recall_main(["--json"]) == 2
    assert _json(capsys)["error"] == {"code": "usage"}
    assert recall_main(["--json", "history", "find"]) == 2  # query is required
    assert _json(capsys)["error"] == {"code": "usage"}
