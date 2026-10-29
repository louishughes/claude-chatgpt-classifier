"""SOC-004: a person confirms or rejects an account and links an ambiguous @handle.

Acceptance: confirm, reject and link on a synthetic fixture; the registry
note reflects each one; re-importing keeps them; an unknown ID exits with
code 2. The review history is append-only.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session

from knowledge_engine.cli.main import ExitCode, main
from knowledge_engine.documents.registries import account_note, account_registry_note
from knowledge_engine.importer.run import run_import
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.rendering.markdown import render_note
from knowledge_engine.settings import Settings

# Synthetic: two accounts with their platform named, and one bare @handle.
MESSAGES = [
    "Synthetic: my code is at https://github.com/Synth-Octo",
    "Synthetic: GitHub: @synth-other, and say hi to @synth-octo",
]


def _export(root: Path) -> Path:
    nodes: list[tuple[str, str | None]] = [("root", None)]
    nodes += [(f"m{i}", text) for i, text in enumerate(MESSAGES)]
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
                "create_time": 1704067200.0 + 86_400 * i,
                "content": {"content_type": "text", "parts": [text]},
                "metadata": {},
            },
        }
    root.mkdir(parents=True)
    chat = {"id": "c-soc-4", "title": "Synthetic", "mapping": mapping, "current_node": "m1"}
    (root / "conversations.json").write_text(json.dumps([chat]), encoding="utf-8")
    return root


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Settings, Path]:
    settings = Settings(workspace_root=tmp_path / "ws")
    export = _export(tmp_path / "export")
    run_import(export, "acct", format_id=None, settings=settings)
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(settings.workspace_root))
    return settings, export


def _ke(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, dict[str, Any]]:
    code = main(["--json", *argv])
    out: dict[str, Any] = json.loads(capsys.readouterr().out)
    return code, out


def _accounts(capsys: pytest.CaptureFixture[str], *flags: str) -> dict[str, dict[str, Any]]:
    _, out = _ke(capsys, "accounts", *flags)
    return {row["handle"]: row for row in out["data"]["accounts"]}


def _registry(settings: Settings) -> str:
    engine = create_sqlite_engine(database_path(settings))
    try:
        with Session(engine) as session:
            return render_note(account_registry_note(session))
    finally:
        engine.dispose()


def _account_note(settings: Settings, account_id: str) -> str:
    engine = create_sqlite_engine(database_path(settings))
    try:
        with Session(engine) as session:
            return render_note(account_note(session, account_id))
    finally:
        engine.dispose()


def test_confirm_shows_in_registry_and_survives_reimport(
    capsys: pytest.CaptureFixture[str], workspace: tuple[Settings, Path]
) -> None:
    settings, export = workspace
    octo = _accounts(capsys)["synth-octo"]

    code, out = _ke(
        capsys, "accounts", "review", octo["account_id"], "confirm", "--reviewer", "owner"
    )

    assert code == ExitCode.OK
    assert (out["data"]["from_state"], out["data"]["to_state"]) == ("probable", "confirmed")
    assert "`synth-octo` (confirmed)" in _registry(settings)
    run_import(export, "acct", format_id=None, settings=settings)
    assert _accounts(capsys)["synth-octo"]["identity_status"] == "confirmed"


def test_reject_drops_out_of_registry_but_keeps_history(
    capsys: pytest.CaptureFixture[str], workspace: tuple[Settings, Path]
) -> None:
    settings, export = workspace
    other = _accounts(capsys)["synth-other"]

    code, _ = _ke(
        capsys,
        "accounts",
        "review",
        other["account_id"],
        "reject",
        "--reviewer",
        "owner",
        "--note",
        "not a real account",
    )

    assert code == ExitCode.OK
    assert "synth-other" not in _accounts(capsys)
    assert _accounts(capsys, "--all")["synth-other"]["identity_status"] == "rejected"
    registry = _registry(settings)
    assert "synth-other" not in registry
    assert "1 account(s) a person rejected are left out" in registry
    note = _account_note(settings, other["account_id"])
    assert "## Review history" in note and "probable to rejected" in note
    run_import(export, "acct", format_id=None, settings=settings)
    assert "synth-other" not in _accounts(capsys)


def test_link_counts_the_mention_toward_the_account(
    capsys: pytest.CaptureFixture[str], workspace: tuple[Settings, Path]
) -> None:
    settings, export = workspace
    octo = _accounts(capsys)["synth-octo"]
    assert octo["mentions"] == 1
    _, out = _ke(capsys, "accounts", "--ambiguous")
    [bare] = out["data"]["ambiguous"]
    [mention_id] = bare["mention_ids"]

    code, out = _ke(
        capsys, "accounts", "link", mention_id, octo["account_id"], "--reviewer", "owner"
    )

    assert code == ExitCode.OK
    assert (out["data"]["from_state"], out["data"]["to_state"]) == ("ambiguous", "resolved")
    assert _accounts(capsys)["synth-octo"]["mentions"] == 2
    _, out = _ke(capsys, "accounts", "--ambiguous")
    assert out["data"]["ambiguous"] == []
    review = _registry(settings).split("## Needs review", 1)[1]
    assert "nothing to review" in review
    run_import(export, "acct", format_id=None, settings=settings)
    assert _accounts(capsys)["synth-octo"]["mentions"] == 2
    # Linking it a second time is refused: it isn't ambiguous any more.
    again, out = _ke(
        capsys, "accounts", "link", mention_id, octo["account_id"], "--reviewer", "owner"
    )
    assert again == ExitCode.USAGE and out["error"] == {"code": "refused"}


def test_unknown_ids_exit_2(
    capsys: pytest.CaptureFixture[str], workspace: tuple[Settings, Path]
) -> None:
    octo = _accounts(capsys)["synth-octo"]
    code, out = _ke(capsys, "accounts", "review", "acct_nope", "confirm", "--reviewer", "o")
    assert code == 2 and out["error"] == {"code": "not_found"}
    code, out = _ke(capsys, "accounts", "link", "amen_nope", octo["account_id"], "--reviewer", "o")
    assert code == 2 and out["error"] == {"code": "not_found"}


def test_history_is_append_only(
    capsys: pytest.CaptureFixture[str], workspace: tuple[Settings, Path]
) -> None:
    settings, _ = workspace
    octo = _accounts(capsys)["synth-octo"]
    _ke(capsys, "accounts", "review", octo["account_id"], "reject", "--reviewer", "owner")
    _ke(capsys, "accounts", "review", octo["account_id"], "confirm", "--reviewer", "owner")

    db = sqlite3.connect(database_path(settings))
    try:
        rows = db.execute("SELECT action, from_state, to_state FROM account_reviews").fetchall()
        assert rows == [("reject", "probable", "rejected"), ("confirm", "rejected", "confirmed")]
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            db.execute("UPDATE account_reviews SET reviewer = 'someone else'")
        with pytest.raises(sqlite3.DatabaseError, match="append-only"):
            db.execute("DELETE FROM account_reviews")
    finally:
        db.close()
