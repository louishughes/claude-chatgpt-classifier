"""EVAL-012: score real detector output on a fixture against a synthetic key.

The ``copied_prefix`` fixture makes the detectors propose four links. The
key below is written by hand for the test (synthetic data, never the real
answer key): chat 3 says "carry on from <link to chat 1>", which a person
would call ``continues``, while the URL detector says ``references``. So
one proposal in four is the wrong kind and precision is 0.75.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from knowledge_engine.cli.main import main
from knowledge_engine.importer import import_source
from knowledge_engine.settings import Settings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt"
PREFIX = "c0000008-0000-4000-8000-00000000000"


def _chat(n: int) -> str:
    return f"{PREFIX}{n}"


def _evidence(n: int, number: int, speaker: str, quote: str) -> dict[str, Any]:
    return {"conversation": _chat(n), "message_number": number, "speaker": speaker, "quote": quote}


def _key(chat3_kind: str, *, quote: str = "help me plan a garden shed") -> dict[str, Any]:
    return {
        "produced_by": {"session": "test", "model": "none", "saw_engine_output": False},
        "synthetic": True,
        "conversations": [_chat(n) for n in range(1, 6)],
        "links": [
            {
                "from_conversation": _chat(2),
                "kind": "forked_from",
                "to_conversation": _chat(1),
                "evidence": [_evidence(2, 2, "user", quote)],
            },
            {
                "from_conversation": _chat(3),
                "kind": chat3_kind,
                "to_conversation": _chat(1),
                "evidence": [_evidence(3, 2, "user", "carry on from")],
            },
            {
                "from_conversation": _chat(4),
                "kind": "quotes",
                "to_conversation": _chat(1),
                "evidence": [_evidence(4, 2, "user", "a level gravel pad")],
            },
            {
                "from_conversation": _chat(5),
                "kind": "forked_from",
                "to_conversation": _chat(1),
                "evidence": [_evidence(5, 6, "user", "and the walls?")],
            },
        ],
    }


def _run(
    tmp_path: Path, key: dict[str, Any], monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> tuple[int, dict[str, Any]]:
    root = tmp_path / "ws"
    import_source(
        FIXTURES / "copied_prefix" / "export", "fixture", settings=Settings(workspace_root=root)
    )
    path = tmp_path / "key.json"
    path.write_text(json.dumps(key), encoding="utf-8")
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(root))
    code = main(["--json", "eval", "relationships", "--key", str(path)])
    return code, json.loads(capsys.readouterr().out)


def test_a_wrong_kind_lowers_precision_below_the_floor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    code, out = _run(tmp_path, _key("continues"), monkeypatch, capsys)
    assert code != 0
    data = out["data"]
    assert data["precision"] == 0.75
    assert data["verdicts"] == {
        "correct": 3,
        "wrong_direction": 0,
        "wrong_kind": 1,
        "false_link": 0,
    }
    assert data["data"] == "synthetic"


def test_a_key_that_agrees_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    code, out = _run(tmp_path, _key("references"), monkeypatch, capsys)
    assert code == 0
    assert out["data"]["precision"] == 1.0


def test_a_quote_the_archive_does_not_hold_stops_scoring(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    code, out = _run(
        tmp_path, _key("references", quote="a quote nobody wrote"), monkeypatch, capsys
    )
    assert code != 0
    assert out["error"]["code"] == "key_evidence_invalid"
    problems = out["data"]["problems"]
    assert problems == [f"link 1, {_chat(2)} message 2: quote not found in the message"]
    assert "nobody" not in json.dumps(out)  # problems never repeat the key's text
