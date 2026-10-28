"""PROD-002: accounts, workspace roles and the authorisation log.

The acceptance check: an account from another workspace is refused on
every source and knowledge endpoint (in fact on every endpoint), and a
refused request changes nothing.
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from knowledge_engine.access import accounts as acc
from knowledge_engine.access.policy import AccountKind, Role
from knowledge_engine.api.access import ROUTE_PERMISSIONS
from knowledge_engine.api.app import PREFIX, create_app
from knowledge_engine.cli.main import main
from knowledge_engine.importer import import_source
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.settings import Settings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    settings = Settings(workspace_root=tmp_path / "ws")
    import_source(FIXTURES / "extraction_rules" / "export", "fixture", settings=settings)
    return settings


def _client(settings: Settings) -> TestClient:
    return TestClient(
        create_app(settings), base_url="http://127.0.0.1:8766", raise_server_exceptions=False
    )


def _setup(settings: Settings, people: dict[str, tuple[AccountKind, str, Role]]) -> dict[str, str]:
    """Create accounts with one role each; return their tokens."""
    engine = create_sqlite_engine(database_path(settings))
    tokens = {}
    with Session(engine) as session:
        for name, (kind, workspace, role) in people.items():
            acc.add_account(session, name, kind)
            acc.grant(session, name, workspace, role, by="test")
            tokens[name] = acc.issue_token(session, name)
        session.commit()
    engine.dispose()
    return tokens


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _call(client: TestClient, method: str, path: str, headers: dict[str, str]) -> Any:
    url = re.sub(r"\{[a-z_]+\}", "x", path)
    if method == "POST":
        return client.post(url, json={}, headers=headers)
    return client.get(url, headers=headers)


def _counts(client: TestClient, token: str) -> dict[str, int]:
    response = client.get(f"{PREFIX}/counts", headers=_auth(token))
    assert response.status_code == 200
    counts: dict[str, int] = response.json()
    return counts


def test_without_accounts_the_api_works_as_before(settings: Settings) -> None:
    client = _client(settings)
    assert client.get(f"{PREFIX}/sources").status_code == 200
    me = client.get(f"{PREFIX}/access/me").json()
    assert me["checking"] is False and me["account"] is None


def test_every_route_has_exactly_one_access_rule(settings: Settings) -> None:
    documented = create_app(settings).openapi()["paths"]
    routes = {(method.upper(), path) for path, methods in documented.items() for method in methods}
    assert routes == set(ROUTE_PERMISSIONS)


def test_another_workspaces_account_is_refused_everywhere(settings: Settings) -> None:
    tokens = _setup(
        settings,
        {
            "alice": (AccountKind.PERSON, "default", Role.OWNER),
            "mallory": (AccountKind.PERSON, "other", Role.OWNER),
        },
    )
    client = _client(settings)
    before = _counts(client, tokens["alice"])

    checked = 0
    for (method, path), permission in ROUTE_PERMISSIONS.items():
        if permission is None:
            continue
        for headers, status, code in (
            (_auth(tokens["mallory"]), 403, "not_a_member"),
            ({}, 401, "unauthenticated"),
            (_auth("ke_not-a-real-token"), 401, "unauthenticated"),
            ({"Authorization": tokens["alice"]}, 401, "unauthenticated"),  # no "Bearer"
        ):
            response = _call(client, method, path, headers)
            assert (response.status_code, response.json()["error"]["code"]) == (status, code), (
                method,
                path,
            )
        checked += 1
    assert checked == len(ROUTE_PERMISSIONS) - 1
    assert _counts(client, tokens["alice"]) == before  # nothing changed

    # The workspace's own owner gets in: refusals were about mallory, not the route.
    assert client.get(f"{PREFIX}/sources", headers=_auth(tokens["alice"])).status_code == 200
    me = client.get(f"{PREFIX}/access/me", headers=_auth(tokens["alice"])).json()
    assert (me["checking"], me["account"], me["role"]) == (True, "alice", "owner")


def test_roles_decide_what_an_account_can_do(settings: Settings) -> None:
    tokens = _setup(
        settings,
        {
            "vic": (AccountKind.PERSON, "default", Role.VIEWER),
            "eddie": (AccountKind.PERSON, "default", Role.EDITOR),
            "rita": (AccountKind.PERSON, "default", Role.REVIEWER),
        },
    )
    client = _client(settings)
    proposal = {
        "operation": "add",
        "payload": {"label": "Gardening", "dimension": "topic"},
        "proposer": "eddie",
    }
    viewer = client.post(
        f"{PREFIX}/taxonomy/proposals", json=proposal, headers=_auth(tokens["vic"])
    )
    assert (viewer.status_code, viewer.json()["error"]["code"]) == (403, "forbidden")
    assert client.get(f"{PREFIX}/knowledge", headers=_auth(tokens["vic"])).status_code == 200

    made = client.post(
        f"{PREFIX}/taxonomy/proposals", json=proposal, headers=_auth(tokens["eddie"])
    )
    assert made.status_code == 201
    proposal_id = made.json()["proposal_id"]
    review = f"{PREFIX}/taxonomy/proposals/{proposal_id}/review"
    editor = client.post(
        review, json={"decision": "reject", "reviewer": "eddie"}, headers=_auth(tokens["eddie"])
    )
    assert (editor.status_code, editor.json()["error"]["code"]) == (403, "forbidden")

    # Rita can review, but only under her own name.
    forged = client.post(
        review, json={"decision": "reject", "reviewer": "vic"}, headers=_auth(tokens["rita"])
    )
    assert (forged.status_code, forged.json()["error"]["code"]) == (403, "identity_mismatch")
    done = client.post(
        review,
        json={"decision": "reject", "reviewer": "rita", "note": "not now"},
        headers=_auth(tokens["rita"]),
    )
    assert done.status_code == 200 and done.json()["reviewer"] == "rita"

    # An editor can't propose under someone else's name either.
    other = {**proposal, "proposer": "rita"}
    posed = client.post(f"{PREFIX}/taxonomy/proposals", json=other, headers=_auth(tokens["eddie"]))
    assert (posed.status_code, posed.json()["error"]["code"]) == (403, "identity_mismatch")


def test_service_accounts_cannot_review_or_own(settings: Settings) -> None:
    engine = create_sqlite_engine(database_path(settings))
    with Session(engine) as session:
        acc.add_account(session, "nightly-bot", AccountKind.SERVICE)
        for role in (Role.REVIEWER, Role.OWNER):
            with pytest.raises(acc.AccessError, match="service account"):
                acc.grant(session, "nightly-bot", "default", role, by="test")
        acc.grant(session, "nightly-bot", "default", Role.EDITOR, by="test")
        with pytest.raises(acc.AccessError, match="already exists"):
            acc.add_account(session, "nightly-bot", AccountKind.PERSON)
        with pytest.raises(acc.AccessError, match="letters"):
            acc.add_account(session, "../bad name", AccountKind.PERSON)
        session.commit()
    engine.dispose()


def test_revoked_and_disabled_accounts_are_locked_out(settings: Settings) -> None:
    tokens = _setup(settings, {"alice": (AccountKind.PERSON, "default", Role.OWNER)})
    client = _client(settings)
    url = f"{PREFIX}/sources"
    assert client.get(url, headers=_auth(tokens["alice"])).status_code == 200

    engine = create_sqlite_engine(database_path(settings))
    with Session(engine) as session:
        assert acc.revoke_tokens(session, "alice") == 1
        fresh = acc.issue_token(session, "alice")
        session.commit()
    assert client.get(url, headers=_auth(tokens["alice"])).status_code == 401
    assert client.get(url, headers=_auth(fresh)).status_code == 200
    with Session(engine) as session:
        acc.disable_account(session, "alice")
        session.commit()
        with pytest.raises(acc.AccessError, match="disabled"):
            acc.issue_token(session, "alice")
    engine.dispose()
    assert client.get(url, headers=_auth(fresh)).status_code == 401

    # Only a fingerprint of a token is stored, never the token.
    stored = database_path(settings).read_bytes()
    assert fresh.encode() not in stored and tokens["alice"].encode() not in stored


def test_the_authorisation_log_keeps_refusals_and_cannot_be_edited(settings: Settings) -> None:
    tokens = _setup(
        settings,
        {
            "alice": (AccountKind.PERSON, "default", Role.OWNER),
            "mallory": (AccountKind.PERSON, "other", Role.OWNER),
        },
    )
    client = _client(settings)
    client.get(f"{PREFIX}/search", params={"q": "secretword"}, headers=_auth(tokens["mallory"]))
    client.get(f"{PREFIX}/sources", headers=_auth(tokens["alice"]))  # a plain read: not logged

    engine = create_sqlite_engine(database_path(settings))
    with Session(engine) as session:
        log = acc.authz_log(session)
    engine.dispose()
    refusal = log[0]
    assert (refusal["account"], refusal["allowed"], refusal["reason"]) == (
        "mallory",
        False,
        "not_a_member",
    )
    assert refusal["resource"] == f"GET {PREFIX}/search"
    assert "secretword" not in json.dumps(log)
    assert not any(e["resource"] == f"GET {PREFIX}/sources" for e in log)
    assert sum(e["resource"].startswith("grant ") for e in log) == 2

    with sqlite3.connect(database_path(settings)) as db:
        for statement in ("UPDATE authz_events SET allowed = 1", "DELETE FROM authz_events"):
            with pytest.raises(sqlite3.DatabaseError, match="audit log"):
                db.execute(statement)


def test_ke_access_commands(
    settings: Settings, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(settings.workspace_root))

    def ke(*args: str) -> dict[str, Any]:
        code = main(["--json", "access", *args])
        result: dict[str, Any] = json.loads(capsys.readouterr().out)
        assert code == result["exit_code"]
        return result

    assert ke("add", "louis")["ok"]
    assert ke("grant", "louis", "owner")["ok"]
    token = ke("token", "louis")["data"]["token"]
    assert token.startswith("ke_")
    assert ke("add", "bot", "--service")["ok"]
    refused = ke("grant", "bot", "reviewer")
    assert (refused["ok"], refused["error"]["code"]) == (False, "refused")
    listed = ke("list")["data"]["accounts"]
    assert [(a["name"], a["kind"]) for a in listed] == [("bot", "service"), ("louis", "person")]
    assert token not in json.dumps(listed)
    assert ke("remove", "louis")["data"]["removed"] is True
    assert ke("log", "--limit", "5")["data"]["events"][0]["resource"] == "remove louis"

    client = _client(settings)
    refused_api = client.get(f"{PREFIX}/sources", headers=_auth(token))
    assert refused_api.json()["error"]["code"] == "not_a_member"
