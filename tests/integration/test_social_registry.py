"""SOC-002: one account across URL and handle; ambiguous handles never link."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.cli.main import main
from knowledge_engine.importer.run import run_import
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.links.social_store import (
    AccountAliasRow,
    AccountMentionRow,
    SocialAccountRow,
)
from knowledge_engine.settings import Settings

MESSAGES = [
    "Synthetic: my code is at https://github.com/Synth-Octo",
    "Synthetic: also GitHub: @synth-octo, and say hi to @synth-octo",
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
    conversation = {
        "id": "c-soc-1",
        "title": "Synthetic",
        "mapping": mapping,
        "current_node": nodes[-1][0],
    }
    (root / "conversations.json").write_text(json.dumps([conversation]), encoding="utf-8")
    return root


def test_url_and_qualified_handle_are_one_account(tmp_path: Path) -> None:
    settings = Settings(workspace_root=tmp_path / "ws")
    export = _export(tmp_path / "export")
    report = run_import(export, "acct", format_id=None, settings=settings)
    assert report.accounts == {"ambiguous_mentions": 1, "new_accounts": 1, "new_mentions": 3}

    engine = create_sqlite_engine(database_path(settings))
    try:
        with Session(engine) as session:
            [account] = session.scalars(select(SocialAccountRow)).all()
            assert (account.platform, account.canonical_handle) == ("github", "synth-octo")
            assert account.identity_status == "probable"
            mentions = session.scalars(select(AccountMentionRow)).all()
            linked = [m for m in mentions if m.account_id == account.account_id]
            assert len(linked) == 2
            [bare] = [m for m in mentions if m.account_id is None]
            # Same handle text as the account, still never linked.
            assert (bare.resolution, bare.handle, bare.platform) == (
                "ambiguous",
                "synth-octo",
                None,
            )
            aliases = {(a.kind, a.alias) for a in session.scalars(select(AccountAliasRow)).all()}
            assert aliases == {
                ("url", "https://github.com/Synth-Octo"),
                ("handle", "@synth-octo"),
            }
    finally:
        engine.dispose()

    again = run_import(export, "acct", format_id=None, settings=settings)
    assert again.accounts.get("new_mentions", 0) == 0
    assert again.accounts.get("new_accounts", 0) == 0


def test_cli_lists_accounts_and_ambiguous_handles(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(workspace_root=tmp_path / "ws")
    run_import(_export(tmp_path / "export"), "acct", format_id=None, settings=settings)
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(settings.workspace_root))

    assert main(["--json", "accounts"]) == 0
    [row] = json.loads(capsys.readouterr().out)["data"]["accounts"]
    assert (row["platform"], row["handle"], row["mentions"], row["conversations"]) == (
        "github",
        "synth-octo",
        2,
        1,
    )
    assert (row["first_seen"], row["last_seen"]) == ("2024-01-02", "2024-01-03")

    assert main(["--json", "accounts", "--ambiguous"]) == 0
    [bare] = json.loads(capsys.readouterr().out)["data"]["ambiguous"]
    assert (bare["handle"], bare["mentions"]) == ("@synth-octo", 1)
