"""RCL-002: `recall history repeats` against the repeat_requests answer key."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from knowledge_engine.importer import import_source
from knowledge_engine.recall.cli import main as recall_main
from knowledge_engine.settings import Settings

CASE = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt" / "repeat_requests"
EXPECTED: dict[str, Any] = json.loads((CASE / "manifest.json").read_text("utf-8"))["expected"]


@pytest.fixture(scope="module")
def workspace(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    settings = Settings(workspace_root=tmp_path_factory.mktemp("ws"))
    import_source(CASE / "export", "fixture", settings=settings)
    yield settings.workspace_root


@pytest.fixture
def env(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(workspace))
    return workspace


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> dict[str, Any]:
    assert recall_main(["--json", "history", "repeats", *args]) == 0
    data: dict[str, Any] = json.loads(capsys.readouterr().out)["data"]
    return data


def _groups(data: dict[str, Any]) -> list[list[str]]:
    return sorted(sorted(m["native_node_id"] for m in g["members"]) for g in data["groups"])


def test_finds_exactly_the_planted_repeats(env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    data = _run(capsys)
    assert _groups(data) == sorted(EXPECTED["groups"])


def test_look_alikes_short_messages_and_edits_stay_out(
    env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = _run(capsys)
    grouped = {node for group in _groups(data) for node in group}
    for key in ("never_grouped", "too_short", "same_chat_edit"):
        assert grouped.isdisjoint(EXPECTED[key]), key
    assert data["too_short"] == len(EXPECTED["too_short"])


def test_groups_are_ranked_and_carry_their_evidence(
    env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = _run(capsys)
    first = data["groups"][0]
    assert first["chats"] == 3  # the request asked in three chats comes first
    assert first["weakest_match"] >= data["threshold"]
    dates = [m["date"] for m in first["members"]]
    assert dates == sorted(dates)  # oldest first
    assert (first["first_date"], first["last_date"]) == (dates[0], dates[-1])
    for member in first["members"]:
        assert member["conversation_id"].startswith("conv_")
        assert member["title"]
        assert member["revision_id"]
        assert member["snippet"]


def test_a_reexport_adds_no_repeats(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The same export imported twice is one set of logical chats (IMP-002),
    # so a re-export can't make a chat repeat itself.
    settings = Settings(workspace_root=tmp_path / "ws")
    import_source(CASE / "export", "fixture", settings=settings)
    import_source(CASE / "export", "fixture", settings=settings)
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(settings.workspace_root))
    assert _groups(_run(capsys)) == sorted(EXPECTED["groups"])


def test_options_narrow_the_result(env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert len(_run(capsys, "--min-chats", "3")["groups"]) == 1
    limited = _run(capsys, "--limit", "2")
    assert len(limited["groups"]) == 2
    assert limited["groups_found"] == 5
    # The fixture's chats run from 2024-03-31 to 2024-04-14. From 2024-04-05
    # on, only the farming request is still asked in two chats (04-05, 04-10).
    assert [len(g) for g in _groups(_run(capsys, "--since", "2024-04-05"))] == [2]
    assert _groups(_run(capsys, "--since", "2024-04-15")) == []


def test_bad_options_are_refused(env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    for args, code in (
        (["--min-chats", "1"], "usage"),
        (["--limit", "0"], "usage"),
        (["--since", "yesterday"], "bad_filter"),
        (["--project", "proj_does_not_exist"], "unknown_term"),
    ):
        assert recall_main(["--json", "history", "repeats", *args]) == 2
        assert json.loads(capsys.readouterr().out)["error"] == {"code": code}, args


def test_text_output(env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert recall_main(["history", "repeats"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("5 repeated request(s)")
    assert "1. asked in 3 chats" in out
