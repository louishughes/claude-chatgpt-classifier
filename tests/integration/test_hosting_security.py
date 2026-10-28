"""PROD-004: deletion and access control behave as the security review says.

The review (docs/operations/HOSTING_AND_SECURITY.md) promises that a
rotated token stops working at once, that an erased account leaves no name
behind, that deleting a workspace removes everything it stored and nothing
else, and that no secret is written where a backup or log would keep it.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from knowledge_engine.access import accounts as acc
from knowledge_engine.access.tenants import (
    TenantError,
    create_tenant,
    delete_tenant,
    list_tenants,
    tenant_settings,
)
from knowledge_engine.api.app import PREFIX, create_app
from knowledge_engine.cli.main import main
from knowledge_engine.importer import import_source
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.settings import Settings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt"


@pytest.fixture
def hosted(tmp_path: Path) -> dict[str, Any]:
    settings = Settings(workspace_root=tmp_path / "single", tenants_root=tmp_path / "tenants")
    tokens = {
        owner: create_tenant(settings, name, owner)
        for name, owner in (("a", "alice"), ("b", "bob"))
    }
    for name in ("a", "b"):
        import_source(
            FIXTURES / "extraction_rules" / "export", "x", settings=tenant_settings(settings, name)
        )
    client = TestClient(
        create_app(settings), base_url="http://127.0.0.1:8766", raise_server_exceptions=False
    )
    return {"settings": settings, "tokens": tokens, "client": client, "root": tmp_path / "tenants"}


def _get(client: TestClient, token: str, workspace: str) -> int:
    headers = {"Authorization": f"Bearer {token}", "X-KE-Workspace": workspace}
    return client.get(f"{PREFIX}/sources", headers=headers).status_code


def test_rotating_a_token_locks_the_old_one_out_at_once(hosted: dict[str, Any]) -> None:
    settings, client, old = hosted["settings"], hosted["client"], hosted["tokens"]["alice"]
    assert _get(client, old, "a") == 200
    engine = create_sqlite_engine(database_path(tenant_settings(settings, "a")))
    with Session(engine) as session:
        new = acc.rotate_token(session, "alice")
        session.commit()
    engine.dispose()
    assert (_get(client, old, "a"), _get(client, new, "a")) == (401, 200)


def test_an_erased_account_leaves_no_name_behind(hosted: dict[str, Any]) -> None:
    settings, client, token = hosted["settings"], hosted["client"], hosted["tokens"]["alice"]
    a = tenant_settings(settings, "a")
    engine = create_sqlite_engine(database_path(a))
    with Session(engine) as session:
        acc.add_account(session, "zelda-erasable", acc.AccountKind.PERSON)
        acc.grant(session, "zelda-erasable", "default", acc.Role.VIEWER, by="cli")
        zelda = acc.issue_token(session, "zelda-erasable")
        session.commit()
    assert _get(client, zelda, "a") == 200
    client.post(  # a refused write, so the log has a row about her
        f"{PREFIX}/exports",
        json={"destination": "x"},
        headers={"Authorization": f"Bearer {zelda}", "X-KE-Workspace": "a"},
    )
    with Session(engine) as session:
        assert any(e["account"] == "zelda-erasable" for e in acc.authz_log(session))
        short = acc.delete_account(session, "zelda-erasable", by="cli")
        session.commit()
        log = acc.authz_log(session)
    engine.dispose()

    assert _get(client, zelda, "a") == 401
    assert _get(client, token, "a") == 200  # nobody else is affected
    assert f"deleted-{short}" in json.dumps(log) and "zelda-erasable" not in json.dumps(log)
    with sqlite3.connect(database_path(a)) as db:
        db.execute("VACUUM")
    assert b"zelda-erasable" not in database_path(a).read_bytes()


def test_deleting_a_workspace_removes_it_and_nothing_else(
    hosted: dict[str, Any], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    settings, client, tokens, root = (
        hosted["settings"],
        hosted["client"],
        hosted["tokens"],
        hosted["root"],
    )
    b_files = (root / "workspaces" / "b").rglob("*")
    b_before = sorted(str(p.relative_to(root)) for p in b_files)
    with pytest.raises(TenantError, match="repeat"):
        delete_tenant(settings, "a", confirm="b")
    with pytest.raises(TenantError, match="no workspace"):
        delete_tenant(settings, "nope", confirm="nope")

    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(settings.workspace_root))
    monkeypatch.setenv("KE_TENANTS_ROOT", str(settings.tenants_root))
    assert main(["--json", "tenant", "delete", "a", "--confirm", "a"]) == 0
    removed = json.loads(capsys.readouterr().out)["data"]["removed"]
    assert sorted(removed) == [str(Path("inbox/a")), str(Path("workspaces/a"))]
    assert not (root / "workspaces" / "a").exists() and not (root / "inbox" / "a").exists()
    assert list_tenants(settings) == ["b"]
    assert _get(client, tokens["alice"], "a") == 401
    assert _get(client, tokens["bob"], "b") == 200
    assert (
        sorted(str(p.relative_to(root)) for p in (root / "workspaces" / "b").rglob("*")) == b_before
    )


def test_a_workspace_folder_that_is_a_link_out_is_not_followed(
    hosted: dict[str, Any], tmp_path: Path
) -> None:
    settings, root = hosted["settings"], hosted["root"]
    outside = tmp_path / "precious"
    shutil.copytree(root / "workspaces" / "b", outside)
    shutil.rmtree(root / "workspaces" / "b")
    try:
        (root / "workspaces" / "b").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("this system doesn't allow symlinks")
    with pytest.raises(TenantError, match="outside"):
        delete_tenant(settings, "b", confirm="b")
    assert (outside / "knowledge.db").exists()


def test_the_cli_erases_and_rotates(
    hosted: dict[str, Any], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    settings, client = hosted["settings"], hosted["client"]
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(tenant_settings(settings, "b").workspace_root))

    def ke(*args: str) -> dict[str, Any]:
        main(["--json", "access", *args])
        result: dict[str, Any] = json.loads(capsys.readouterr().out)
        return result

    rotated = ke("rotate", "bob")["data"]["token"]
    assert _get(client, hosted["tokens"]["bob"], "b") == 401 and _get(client, rotated, "b") == 200
    refused = ke("delete", "bob", "--confirm", "bobby")
    assert (refused["ok"], refused["error"]["code"]) == (False, "refused")
    assert ke("delete", "bob", "--confirm", "bob")["ok"]
    assert _get(client, rotated, "b") == 401
    assert ke("list")["data"]["accounts"] == []


def test_no_secret_is_written_where_it_would_be_kept(hosted: dict[str, Any]) -> None:
    settings, root, tokens = hosted["settings"], hosted["root"], hosted["tokens"]
    for token in tokens.values():
        for workspace in ("a", "b"):
            _get(hosted["client"], token, workspace)  # one allowed, one refused each
    stored = b"".join(p.read_bytes() for p in root.rglob("*") if p.is_file())
    assert not any(token.encode() in stored for token in tokens.values())
    assert settings.anthropic_api_key is None or (
        settings.anthropic_api_key.get_secret_value().encode() not in stored
    )
