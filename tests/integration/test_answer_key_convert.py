"""EVAL-014: a per-chat answer key (the spike's shape) becomes a golden set `ke gold score` reads.

The fixtures are synthetic: one chat with a hidden system message first
(so engine numbers start at 2 for the user's first message, the trap v1
fell into), and a key with one item of each case: mapped types, a decision
accepted in a later user message, unmapped types, an unverified item, a
v1-style item placed by a wrong number, and a v2 item whose number
disagrees with its message ID.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from knowledge_engine.cli.main import main
from knowledge_engine.evaluation.gold import load_gold
from knowledge_engine.extraction.records import RecordType
from knowledge_engine.importer.run import run_import
from knowledge_engine.settings import load_settings

CASE = Path(__file__).resolve().parents[1] / "fixtures" / "answer_key"


def _cli(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, dict[str, Any]]:
    capsys.readouterr()
    code = main(["--json", *args])
    return code, json.loads(capsys.readouterr().out)


def _hash(folder: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(folder.iterdir()):
        digest.update(path.name.encode() + path.read_bytes())
    return digest.hexdigest()


@pytest.fixture
def key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The chat imported into a fresh workspace, and a copy of the key folder."""
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(tmp_path / "ws"))
    run_import(CASE / "export", "acct", format_id=None, settings=load_settings())
    folder = tmp_path / "answer-key" / "v2"
    shutil.copytree(CASE / "key", folder)
    return folder


def test_key_converts_to_a_golden_set_the_scorer_accepts(
    key: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = _hash(key)
    out = tmp_path / "scratch" / "answer-key-v2.json"
    code, payload = _cli(capsys, "gold", "convert", "--key", str(key), "--out", str(out))

    assert code == 0, payload
    data = payload["data"]
    assert (data["files"], data["found"], data["records"]) == (1, 1, 5)
    assert data["unmapped"] == {"decision:unclear": 1, "fact": 1, "task": 1}
    assert data["unverified"] == 1
    assert data["skipped"] == {"quote not in the numbered message": 1}  # the v1-style item
    assert data["number_mismatch"] == 1 and data["segments_not_converted"] == 1
    assert _hash(key) == before  # the key folder is only read

    gold = load_gold(out)
    [chat] = gold.conversations
    placed = {(r.record_type, r.actor.value, r.message_id) for r in chat.records}
    assert placed == {
        (RecordType.REQUIREMENT, "user", "u1"),
        (RecordType.DECISION, "user", "u2"),  # held by the user, at the accepting message
        (RecordType.PREFERENCE, "user", "u2"),
        (RecordType.IDEA, "assistant", "a2"),
        (RecordType.QUESTION, "user", "u3"),  # placed by its ID, not its wrong number
    }

    code, scored = _cli(
        capsys, "gold", "score", "--gold", str(out), "--reviewer", "ai_session", "--no-rules"
    )
    assert code == 0 and scored["data"]["key_conversations"] == 1


def test_output_inside_the_key_folder_is_refused(
    key: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = _hash(key)
    code, payload = _cli(
        capsys, "gold", "convert", "--key", str(key), "--out", str(key / "gold.json")
    )

    assert (code, payload["error"]["code"]) == (2, "inside_key")
    assert _hash(key) == before
