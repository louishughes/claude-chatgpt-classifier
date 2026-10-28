"""API-001: the app factory, swappable dependencies, the error shape, health and status.

Every request goes through FastAPI's test client: in-process, no network,
no server. The acceptance check is that overrides make an endpoint use a
temporary database and a fake provider.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from knowledge_engine import __version__
from knowledge_engine.api.app import (
    PREFIX,
    create_app,
    get_provider,
    get_settings,
    host_is_local,
)
from knowledge_engine.importer.run import run_import
from knowledge_engine.infrastructure.db import SessionFactory
from knowledge_engine.infrastructure.migrations import downgrade_to
from knowledge_engine.providers.base import FakeProvider
from knowledge_engine.settings import Settings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _client(app: FastAPI) -> TestClient:
    return TestClient(app, base_url="http://127.0.0.1:8766", raise_server_exceptions=False)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(workspace_root=tmp_path / "ws")


@pytest.fixture
def imported(tmp_path: Path) -> tuple[Settings, int]:
    """A separate temporary workspace with one fixture export imported."""
    source = next(p for p in sorted(FIXTURES.rglob("conversations.json")))
    export = tmp_path / "export"
    shutil.copytree(source.parent, export)
    other = Settings(workspace_root=tmp_path / "test-db")
    report = run_import(export, "acct", format_id=None, settings=other)
    return other, report.conversations["new"]


def test_health_needs_nothing(settings: Settings) -> None:
    response = _client(create_app(settings)).get(f"{PREFIX}/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__, "api_version": "v1"}
    assert not settings.workspace_root.exists()  # health touched no workspace


def test_status_on_an_empty_workspace(settings: Settings) -> None:
    body = _client(create_app(settings)).get(f"{PREFIX}/status").json()
    assert body["database"]["exists"] is False
    assert body["database"]["revision"] == "none"
    assert body["egress_enabled"] == []
    # The default provider is the file-batch one, and egress doesn't allow it.
    assert body["provider"]["name"] == "file_batch"
    assert body["provider"]["allowed"] is False
    assert "workspace" not in body  # no folder paths


def test_overrides_swap_in_a_temporary_database_and_a_fake_provider(
    settings: Settings, imported: tuple[Settings, int]
) -> None:
    other, conversations = imported
    fake = FakeProvider(lambda _request: None)
    app = create_app(settings)
    app.dependency_overrides[get_settings] = lambda: other
    app.dependency_overrides[get_provider] = lambda: fake
    client = _client(app)

    status = client.get(f"{PREFIX}/status").json()
    assert status["provider"]["name"] == "fake"
    assert status["database"]["exists"] is True
    counts = client.get(f"{PREFIX}/counts").json()
    assert counts["conversations"] == conversations > 0
    assert not settings.workspace_root.exists()  # the app's own workspace was never opened
    assert fake.submitted == []  # status asks the provider who it is, never sends it anything


def test_counts_before_any_import_is_a_clear_error(settings: Settings) -> None:
    response = _client(create_app(settings)).get(f"{PREFIX}/counts")
    assert response.status_code == 503
    assert response.json() == {
        "error": {
            "code": "no_database",
            "message": "nothing has been imported into this workspace yet",
        }
    }


def test_an_older_database_is_refused_until_upgraded(imported: tuple[Settings, int]) -> None:
    other, _ = imported
    sessions = SessionFactory.from_settings(other)
    downgrade_to(sessions.engine, "0027_override_anchors")
    sessions.dispose()
    client = _client(create_app(other))
    response = client.get(f"{PREFIX}/counts")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "schema_mismatch"
    assert "ke db upgrade" in response.json()["error"]["message"]
    # Status still works, so a program can see why.
    assert client.get(f"{PREFIX}/status").json()["database"]["revision"] == "0027_override_anchors"


def test_requests_to_another_host_are_refused(settings: Settings) -> None:
    client = _client(create_app(settings))
    refused = client.get(f"{PREFIX}/health", headers={"host": "evil.example:8766"})
    assert refused.status_code == 400
    assert refused.json()["error"]["code"] == "host_not_local"
    assert client.get(f"{PREFIX}/health", headers={"host": "localhost:8766"}).status_code == 200
    assert host_is_local("[::1]:8766")
    assert not host_is_local("127.0.0.1.evil.example")
    assert not host_is_local("")


def test_errors_share_one_shape_and_never_echo_input(settings: Settings) -> None:
    app = create_app(settings)

    @app.get(f"{PREFIX}/test-number")
    def number(n: int) -> dict[str, int]:
        return {"n": n}

    @app.get(f"{PREFIX}/test-crash")
    def crash() -> None:
        raise RuntimeError("private words from a chat")

    client = _client(app)
    invalid = client.get(f"{PREFIX}/test-number", params={"n": "my secret plan"})
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "invalid_request"
    assert "query.n" in invalid.json()["error"]["message"]
    assert "secret" not in invalid.text

    crashed = client.get(f"{PREFIX}/test-crash")
    assert crashed.status_code == 500
    assert crashed.json()["error"]["code"] == "internal_error"
    assert "private" not in crashed.text

    missing = client.get(f"{PREFIX}/nowhere")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"
    wrong = client.post(f"{PREFIX}/health")
    assert wrong.json()["error"]["code"] == "method_not_allowed"


def test_openapi_is_versioned_and_under_the_prefix(settings: Settings) -> None:
    document = _client(create_app(settings)).get(f"{PREFIX}/openapi.json").json()
    assert document["info"]["version"] == __version__
    assert set(document["paths"]) == {f"{PREFIX}/health", f"{PREFIX}/status", f"{PREFIX}/counts"}
    assert "ErrorBody" in document["components"]["schemas"]
