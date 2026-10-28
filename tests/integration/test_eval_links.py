"""EVAL-010c: `ke eval links` counts links, videos and accounts for a batch, and shows none.

Two synthetic chats. The first (by native ID) has a web link, the same
YouTube video twice (once with a timestamp), a GitHub profile URL and a
bare @name. The second has one more web link. `--limit 1` counts only the
first chat.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from knowledge_engine.cli.main import main
from knowledge_engine.importer.run import run_import
from knowledge_engine.settings import load_settings

FIRST = [
    "Synthetic: notes at https://example.org/garden and https://youtu.be/dQw4w9WgXcQ",
    "Synthetic: again https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=42 by https://github.com/Synth-Octo",
    "Synthetic: say hi to @synth-friend",
]
SECOND = ["Synthetic: see https://example.net/other"]


def _chat(cid: str, texts: list[str]) -> dict[str, Any]:
    nodes: list[tuple[str, str | None]] = [("root", None)]
    nodes += [(f"{cid}-m{i}", text) for i, text in enumerate(texts)]
    mapping: dict[str, Any] = {}
    for i, (node, text) in enumerate(nodes):
        mapping[node] = {
            "id": node,
            "parent": nodes[i - 1][0] if i else None,
            "children": [nodes[i + 1][0]] if i + 1 < len(nodes) else [],
            "message": None
            if text is None
            else {
                "id": node,
                "author": {"role": "user"},
                "create_time": 1704067200.0 + 60 * i,
                "content": {"content_type": "text", "parts": [text]},
                "metadata": {},
            },
        }
    return {"id": cid, "title": "Synthetic", "mapping": mapping, "current_node": nodes[-1][0]}


def _cli(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, dict[str, Any]]:
    capsys.readouterr()
    code = main(["--json", *args])
    return code, json.loads(capsys.readouterr().out)


def test_counts_for_the_first_chat_only_and_no_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(tmp_path / "ws"))
    code, missing = _cli(capsys, "eval", "links")
    assert (code, missing["error"]["code"]) == (1, "no_imports")

    export = tmp_path / "export"
    export.mkdir()
    chats = [_chat("c-a", FIRST), _chat("c-b", SECOND)]
    (export / "conversations.json").write_text(json.dumps(chats), encoding="utf-8")
    run_import(export, "acct", format_id=None, settings=load_settings())

    code, payload = _cli(capsys, "eval", "links", "--limit", "1")
    assert code == 0, payload
    data = payload["data"]
    assert data["conversations"] == 1
    assert data["links"]["occurrences"] == 4
    assert data["links"]["conversations_with_links"] == 1
    # Two URL forms of one video are two link targets but one video below.
    assert data["links"]["distinct_targets"] == 4
    youtube = data["youtube"]
    assert (youtube["mentions"], youtube["distinct_videos"], youtube["with_timestamp"]) == (2, 1, 1)
    social = data["social"]
    assert social["distinct_accounts"] == 1
    assert social["accounts_by_platform"] == {"github": 1}
    assert social["ambiguous_handles"] == 1
    out = json.dumps(payload)
    for secret in ("example.org", "dQw4w9WgXcQ", "synth", "Synthetic"):
        assert secret.casefold() not in out.casefold()  # counts only

    code, everything = _cli(capsys, "eval", "links")
    assert everything["data"]["conversations"] == 2
    assert everything["data"]["links"]["occurrences"] == 5
