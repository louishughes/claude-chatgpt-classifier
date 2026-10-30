"""ING-015: erasing a chat keeps an imported note that quotes it, and says so.

Louis's decision (2026-10-30): a note is the person's own separate file,
so a purge doesn't change it. Before this, a note quoting the chat made
the purge's check fail for good ("residual"), with no way to fix it.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from knowledge_engine.cli.main import ExitCode, main
from knowledge_engine.evaluation.end_to_end import E2E_FIXTURE, E2E_QUERY, run_end_to_end
from knowledge_engine.retention import purge
from knowledge_engine.retention.purge import plan_purge, run_purge
from knowledge_engine.settings import Settings

ROOT = Path(__file__).resolve().parents[2]
CHAT = "Synthetic garden shed plan"


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Settings, str]:
    """The EVAL-006 synthetic workspace, with the chat to purge picked out."""
    run_end_to_end(ROOT / E2E_FIXTURE, tmp_path, query=E2E_QUERY)
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(tmp_path / "ws"))
    with sqlite3.connect(tmp_path / "ws" / "knowledge.db") as db:
        titles = dict(db.execute("SELECT title, conversation_id FROM conversations"))
    return Settings(workspace_root=tmp_path / "ws"), titles[CHAT]


def _chat_text(settings: Settings, conversation: str) -> list[str]:
    with sqlite3.connect(settings.workspace_root / "knowledge.db") as db:
        rows = db.execute(
            "SELECT r.content_json FROM message_revisions r "
            "JOIN message_nodes n ON n.node_key = r.node_key WHERE n.conversation_id = ?",
            (conversation,),
        ).fetchall()
    return [p for (c,) in rows for p in json.loads(c).get("parts") or () if isinstance(p, str)]


def _purge(settings: Settings, conversation: str, vault: Path | None = None) -> dict[str, Any]:
    plan = plan_purge(settings, [conversation])
    result = run_purge(
        settings, [conversation], confirm=plan.token, reason="synthetic test", vault=vault
    )
    return result.verification.to_dict()


def _quote_note(settings: Settings, conversation: str, path: Path) -> None:
    path.write_bytes(
        ("# Quote\n\n" + "\n\n".join(_chat_text(settings, conversation)) + "\n").encode()
    )
    assert main(["--json", "import-doc", str(path)]) == ExitCode.OK


def test_a_note_quoting_the_chat_is_kept_and_named(
    workspace: tuple[Settings, str], tmp_path: Path
) -> None:
    settings, conversation = workspace
    note = tmp_path / "quote.md"
    note.write_bytes(
        ("# Quote\n\n" + "\n\n".join(_chat_text(settings, conversation)) + "\n").encode()
    )
    assert main(["--json", "import-doc", str(note)]) == ExitCode.OK
    before = note.read_bytes()

    check = _purge(settings, conversation)

    assert check["ok"] is True  # the purge finishes verified
    kept = check["kept_in_notes"]
    assert isinstance(kept, list) and kept
    assert {n["name"] for n in kept} == {"quote.md"}
    assert all(set(n) == {"document_id", "name", "locator", "revision_id", "current"} for n in kept)
    assert all(n["current"] is True for n in kept)
    assert check["probes_in_notes"] == check["probes"] > 0  # still searched for
    assert note.read_bytes() == before  # the file is never touched
    with sqlite3.connect(settings.workspace_root / "knowledge.db") as db:
        assert db.execute("SELECT count(*) FROM document_blocks").fetchone()[0] > 0
        [(status,)] = db.execute("SELECT status FROM purge_events").fetchall()
    assert status == "verified"


def test_a_purge_with_no_notes_names_none(workspace: tuple[Settings, str]) -> None:
    settings, conversation = workspace
    check = _purge(settings, conversation)
    assert check["ok"] is True
    assert check["kept_in_notes"] == []
    assert check["probes_in_notes"] == 0


# From the clean review of this fix: a note must not hide real leftovers.


def test_a_note_does_not_hide_a_leftover_vault_file(
    workspace: tuple[Settings, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, conversation = workspace
    _quote_note(settings, conversation, tmp_path / "quote.md")
    # Simulate a vault re-sync that failed to remove the chat's own vault note.
    monkeypatch.setattr(purge, "_sync_vault", lambda *args, **kwargs: {})

    check = _purge(settings, conversation, vault=tmp_path / "vault")

    assert check["vault_hits"] > 0
    assert check["ok"] is False


def test_an_old_version_of_a_note_is_named_as_old(
    workspace: tuple[Settings, str], tmp_path: Path
) -> None:
    settings, conversation = workspace
    note = tmp_path / "quote.md"
    _quote_note(settings, conversation, note)
    note.write_bytes(b"# Quote\n\nNothing quoted any more.\n")
    assert main(["--json", "import-doc", str(note)]) == ExitCode.OK

    check = _purge(settings, conversation)

    assert check["ok"] is True
    assert check["kept_in_notes"] and all(n["current"] is False for n in check["kept_in_notes"])


def test_a_note_heading_naming_the_chat_is_not_a_leftover(
    workspace: tuple[Settings, str], tmp_path: Path
) -> None:
    settings, conversation = workspace
    note = tmp_path / "about.md"
    note.write_bytes(f"# Notes on {conversation}\n\nUnrelated synthetic text.\n".encode())
    assert main(["--json", "import-doc", str(note)]) == ExitCode.OK

    check = _purge(settings, conversation)

    assert check["residual_ids"] == {}
    assert check["ok"] is True
