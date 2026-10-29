"""IMP-009: a person lists identity candidates and accepts or rejects them.

Acceptance: a chat missing its ``id`` yields exactly one candidate; accepting
it creates exactly one conversation; importing again adds nothing; rejecting
it leaves zero. The listing shows hashes and positions, never chat text.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from sqlalchemy import text

from knowledge_engine.cli.main import ExitCode, main
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.settings import load_settings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt"


@pytest.fixture
def export(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    # Synthetic: the export_single fixture with its first chat's ID removed.
    root = tmp_path / "export"
    shutil.copytree(FIXTURES / "export_single" / "export", root)
    path = root / "conversations.json"
    chats = json.loads(path.read_text(encoding="utf-8"))
    for key in ("id", "conversation_id"):
        chats[0].pop(key, None)
    path.write_text(json.dumps(chats), encoding="utf-8")
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(tmp_path / "ws"))
    return root


def _ke(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, dict[str, object]]:
    code = main(["--json", *argv])
    return code, json.loads(capsys.readouterr().out)


def _candidates(capsys: pytest.CaptureFixture[str]) -> list[dict[str, object]]:
    code, out = _ke(capsys, "imports", "candidates")
    assert code == ExitCode.OK
    data = out["data"]
    assert isinstance(data, dict)
    listed: list[dict[str, object]] = data["candidates"]
    return listed


def _conversation_count(capsys: pytest.CaptureFixture[str]) -> int:
    code, out = _ke(capsys, "imports", "report", "latest")
    assert code == ExitCode.OK
    data = out["data"]
    assert isinstance(data, dict)
    integrity = data["integrity"]
    assert isinstance(integrity, dict)
    return int(integrity["conversations"].get("imported", 0))


def _new(out: dict[str, object]) -> int:
    data = out["data"]
    assert isinstance(data, dict)
    return int(data["conversations"].get("new", 0))


def test_missing_id_lists_one_candidate_without_text(
    capsys: pytest.CaptureFixture[str], export: Path
) -> None:
    _ke(capsys, "import", str(export))
    _ke(capsys, "import", str(export))

    listed = _candidates(capsys)

    assert len(listed) == 1
    candidate = listed[0]
    assert candidate["reason"] == "missing_native_id"
    assert candidate["status"] == "review_required"
    assert candidate["source_index"] == 0
    assert candidate["snapshot_id"]
    assert candidate["conversation_hash"]
    title = json.loads((export / "conversations.json").read_text(encoding="utf-8"))[0]["title"]
    assert title not in json.dumps(listed)


def test_accept_imports_it_once_under_a_content_id(
    capsys: pytest.CaptureFixture[str], export: Path
) -> None:
    _, first = _ke(capsys, "import", str(export))
    before = _new(first)
    candidate_id = str(_candidates(capsys)[0]["candidate_id"])

    code, out = _ke(
        capsys, "imports", "candidates", "review", candidate_id, "accept", "--reviewer", "owner"
    )
    assert code == ExitCode.OK
    decided = out["data"]
    assert isinstance(decided, dict)
    assert decided["status"] == "accepted"
    assert decided["decided_by"] == "owner"
    assert decided["decided_at"]
    assigned = decided["assigned_conversation_id"]

    _, second = _ke(capsys, "import", str(export))
    # Exactly one more conversation, under the ID the review assigned.
    assert _new(second) == 1
    engine = create_sqlite_engine(database_path(load_settings()))
    try:
        with engine.connect() as conn:
            natives = conn.execute(
                text("SELECT native_conversation_id FROM conversations WHERE conversation_id = :c"),
                {"c": assigned},
            ).all()
            total = conn.execute(text("SELECT count(*) FROM conversations")).scalar()
    finally:
        engine.dispose()
    assert len(natives) == 1 and str(natives[0][0]).startswith("content-sha256:")
    assert total == before + 1

    _, third = _ke(capsys, "import", str(export))
    third_data = third["data"]
    assert isinstance(third_data, dict)
    assert set(third_data["conversations"]) == {"unchanged"}
    assert third_data["candidate_matches"] == {}
    assert len(_candidates(capsys)) == 1


def test_reject_keeps_it_out(capsys: pytest.CaptureFixture[str], export: Path) -> None:
    _, first = _ke(capsys, "import", str(export))
    before = _new(first)
    candidate_id = str(_candidates(capsys)[0]["candidate_id"])

    code, _ = _ke(
        capsys, "imports", "candidates", "review", candidate_id, "reject", "--reviewer", "owner"
    )
    assert code == ExitCode.OK

    _, second = _ke(capsys, "import", str(export))
    data = second["data"]
    assert isinstance(data, dict)
    assert data["conversations"] == {"unchanged": before, "rejected_candidate": 1}
    assert data["candidate_matches"] == {}
    assert _conversation_count(capsys) == before
    rejected = _candidates(capsys)[0]
    assert rejected["status"] == "rejected" and rejected["assigned_conversation_id"] is None


def test_a_decision_is_final_and_unknown_ids_are_refused(
    capsys: pytest.CaptureFixture[str], export: Path
) -> None:
    _ke(capsys, "import", str(export))
    candidate_id = str(_candidates(capsys)[0]["candidate_id"])
    _ke(capsys, "imports", "candidates", "review", candidate_id, "reject", "--reviewer", "owner")

    again, out = _ke(
        capsys, "imports", "candidates", "review", candidate_id, "accept", "--reviewer", "owner"
    )
    assert again != ExitCode.OK and out["error"] == {"code": "already_decided"}
    unknown, out = _ke(
        capsys, "imports", "candidates", "review", "nope", "accept", "--reviewer", "owner"
    )
    assert unknown == ExitCode.USAGE and out["error"] == {"code": "unknown_candidate"}


def test_accepted_collision_stays_a_separate_chat(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(tmp_path / "ws2"))
    root = FIXTURES / "id_collision" / "export"
    _ke(capsys, "import", str(root))
    collision = next(c for c in _candidates(capsys) if c["reason"] == "id_collision")

    _ke(
        capsys,
        "imports",
        "candidates",
        "review",
        str(collision["candidate_id"]),
        "accept",
        "--reviewer",
        "owner",
    )
    _, out = _ke(capsys, "import", str(root))

    data = out["data"]
    assert isinstance(data, dict)
    # The first chat is unchanged; the colliding one is new, not merged into it.
    assert data["conversations"].get("unchanged") == 1
    assert data["conversations"].get("new") == 1
    assert collision["existing_conversation_id"] != collision.get("assigned_conversation_id")


def test_accepted_collision_is_never_merged_when_the_export_is_reordered(
    capsys: pytest.CaptureFixture[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Review finding: the decision used to depend on which chat came first.
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(tmp_path / "ws3"))
    root = FIXTURES / "id_collision" / "export"
    _ke(capsys, "import", str(root))
    collision = next(c for c in _candidates(capsys) if c["reason"] == "id_collision")
    _ke(
        capsys,
        "imports",
        "candidates",
        "review",
        str(collision["candidate_id"]),
        "accept",
        "--reviewer",
        "owner",
    )
    _ke(capsys, "import", str(root))
    reordered = tmp_path / "reordered"
    reordered.mkdir()
    chats = json.loads((root / "conversations.json").read_text(encoding="utf-8"))
    (reordered / "conversations.json").write_text(json.dumps(chats[::-1]), encoding="utf-8")

    _, out = _ke(capsys, "import", str(reordered))

    data = out["data"]
    assert isinstance(data, dict)
    assert data["conversations"].get("unchanged") == 2
    assert "revised" not in data["conversations"]
    assert data["candidate_matches"] == {"missing_native_id": 1}


def test_a_purged_accepted_chat_does_not_come_back_as_a_candidate(
    capsys: pytest.CaptureFixture[str], export: Path
) -> None:
    _ke(capsys, "import", str(export))
    candidate_id = str(_candidates(capsys)[0]["candidate_id"])
    _, out = _ke(
        capsys, "imports", "candidates", "review", candidate_id, "accept", "--reviewer", "owner"
    )
    decided = out["data"]
    assert isinstance(decided, dict)
    conversation = str(decided["assigned_conversation_id"])
    _ke(capsys, "import", str(export))
    _, plan = _ke(capsys, "purge", "plan", conversation)
    token = plan["data"]["token"]
    code, _ = _ke(capsys, "purge", "run", conversation, "--confirm", token, "--reason", "test")
    assert code == ExitCode.OK

    _, again = _ke(capsys, "import", str(export))

    data = again["data"]
    assert isinstance(data, dict)
    assert data["conversations"].get("purged") == 1
    assert data["candidate_matches"] == {}
    assert _candidates(capsys) == []
