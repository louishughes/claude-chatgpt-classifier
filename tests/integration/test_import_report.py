"""Slice I6: the stored import report, and source-vs-stored reconciliation.

Acceptance (IMP-005): report counts reconcile exactly with fixture
expectations for a first import, an identical re-import (all unchanged,
zero model calls) and an incremental export. (ING-007): fixture
inventories reconcile and omissions are never silent. The report is read
back with ``ke imports report latest`` as JSON and text, without private
content.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from knowledge_engine.cli.main import main
from knowledge_engine.importer import import_source
from knowledge_engine.settings import Settings, load_settings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt"
CASES = sorted(p.name for p in FIXTURES.iterdir() if (p / "manifest.json").is_file())


def _root(case: str) -> Path:
    export = FIXTURES / case / "export"
    zips = list(export.glob("*.zip"))
    return zips[0] if zips else export


def _expected(case: str) -> dict[str, Any]:
    manifest = json.loads((FIXTURES / case / "manifest.json").read_text(encoding="utf-8"))
    expected: dict[str, Any] = manifest["expected"]
    return expected


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(tmp_path / "ws"))
    return load_settings(workspace_root=tmp_path / "ws")


def _report(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, dict[str, Any]]:
    capsys.readouterr()
    code = main(["--json", "imports", "report", *args])
    payload: dict[str, Any] = json.loads(capsys.readouterr().out)
    return code, payload


@pytest.mark.parametrize("case", CASES)
def test_first_import_report_matches_the_fixture_manifest(
    case: str, settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    import_source(_root(case), "fixture", settings=settings)
    expected = _expected(case)

    code, payload = _report(capsys, "latest")

    assert code == 0
    data = payload["data"]
    integrity = data["integrity"]
    assert integrity["reconciled"] is True
    assert data["model_calls_triggered"] == 0
    checks = {
        "conversations_in_file": integrity["conversations"]["read"],
        "mapping_nodes": integrity["source"]["mapping_nodes"],
        "messages": integrity["source"]["messages"],
        "image_files": integrity["media_files"]["listed"],
        "asset_occurrences": data["asset_occurrences"],
        "candidate_matches": data["candidate_matches"],
        "assets": data["media"]["new_assets"],
        "blobs": data["media"]["new_blobs"],
    }
    if case != "id_collision":
        checks["conversations"] = data["conversations"].get("new", 0)
    for key, actual in checks.items():
        if key in expected:
            assert actual == expected[key], key
    if expected.get("warnings") == []:
        assert data["warnings"] == {}


def test_identical_reimport_report_is_all_unchanged(
    settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    root = _root("reexport_v1")
    import_source(root, "fixture", settings=settings)
    import_source(root, "fixture", settings=settings)

    _, payload = _report(capsys)

    data = payload["data"]
    assert data["conversations"] == {"unchanged": 4}
    assert data["messages"] == {"unchanged": 12}
    assert data["changed_revisions"] == 0
    assert data["model_calls_triggered"] == 0
    assert data["summary"]["rebuild"] == {"conversations": 0, "revisions": 0}


def test_incremental_export_report_matches_the_answer_key(
    settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    import_source(_root("reexport_v1"), "fixture", settings=settings)
    import_source(_root("reexport_v2"), "fixture", settings=settings)
    expected = _expected("reexport_v2")

    _, payload = _report(capsys)

    data = payload["data"]
    assert data["conversations"] == expected["conversation_delta"]
    assert data["messages"] == expected["message_delta"]
    assert data["new_branches"] == expected["new_branches"]
    assert data["summary"]["new_media"] == expected["new_media"]
    assert data["model_calls_triggered"] == expected["model_calls_triggered"]
    # Later stages redo the new and revised conversations, nothing else.
    assert data["summary"]["rebuild"]["conversations"] == 3


def test_report_names_problems_in_its_summary(
    settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    import_source(_root("repeated_image"), "fixture", settings=settings)
    _, images = _report(capsys)
    import_source(_root("id_collision"), "fixture", settings=settings, full_export=False)
    _, identity = _report(capsys)

    assert images["data"]["summary"]["duplicate_assets"] == 1
    assert identity["data"]["summary"]["candidate_duplicates"] == 2
    assert identity["data"]["summary"]["failed"] == 1


def _strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def test_report_contains_no_private_content(
    settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    import_source(_root("export_single"), "fixture", settings=settings)
    conversations = json.loads(
        (_root("export_single") / "conversations.json").read_text(encoding="utf-8")
    )
    # Every title and message string in the source, long enough to be text.
    private = {s for s in _strings(conversations) if len(s) > 12 and " " in s}
    assert private

    _, payload = _report(capsys)
    capsys.readouterr()
    main(["imports", "report"])
    text = capsys.readouterr().out

    output = json.dumps(payload) + text
    assert not [s for s in private if s in output]
    assert "file-SYN0001-synthetic.png" not in output


def test_omissions_are_never_silent(
    tmp_path: Path, settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "source"
    shutil.copytree(_root("export_single"), source)
    path = source / "conversations.json"
    conversations = json.loads(path.read_text(encoding="utf-8"))
    # A mapping entry that isn't a node object: the graph can't keep it.
    conversations[0]["mapping"]["synthetic-broken-node"] = "not a node"
    path.write_text(json.dumps(conversations), encoding="utf-8")

    report = import_source(source, "fixture", settings=settings)

    assert report.integrity["reconciled"] is False
    assert report.integrity["mismatches"] == ["mapping_nodes"]
    assert report.warnings["integrity_mismatch"] == 1


def test_report_errors(settings: Settings, capsys: pytest.CaptureFixture[str]) -> None:
    code, payload = _report(capsys)
    assert (code, payload["error"]) == (1, {"code": "no_imports"})

    import_source(_root("export_single"), "fixture", settings=settings)
    code, payload = _report(capsys, "no-such-import")
    assert (code, payload["error"]) == (1, {"code": "not_found"})

    import_id = _report(capsys)[1]["data"]["import_id"]
    code, payload = _report(capsys, import_id)
    assert (code, payload["data"]["import_id"]) == (0, import_id)
