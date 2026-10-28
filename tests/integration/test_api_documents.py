"""API-005: document list, preview and background export.

The acceptance check: an export never overwrites a file the user made or
edited, and a destination that is a path (or a link out) is refused.
"""

from __future__ import annotations

import os
import shutil
import threading
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from knowledge_engine.api import documents as documents_module
from knowledge_engine.api.app import PREFIX, create_app
from knowledge_engine.importer import import_source
from knowledge_engine.settings import Settings

CHATGPT = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    settings = Settings(workspace_root=tmp_path / "ws")
    export = tmp_path / "in"
    shutil.copytree(CHATGPT / "repeated_image" / "export", export)
    import_source(export, "fixture", settings=settings)
    return settings


@pytest.fixture
def client(settings: Settings) -> TestClient:
    return TestClient(
        create_app(settings), base_url="http://127.0.0.1:8766", raise_server_exceptions=False
    )


def _export(client: TestClient, destination: str) -> dict[str, Any]:
    started = client.post(f"{PREFIX}/exports", json={"destination": destination})
    assert started.status_code == 202, started.text
    job = started.json()
    jobs = client.app.state.export_jobs[1]  # type: ignore[attr-defined]
    assert jobs.get(job["job_id"]).done.wait(60)
    done: dict[str, Any] = client.get(f"{PREFIX}/exports/jobs/{job['job_id']}").json()
    assert done["state"] == "done", done
    return done


def test_list_and_preview_write_nothing(client: TestClient, settings: Settings) -> None:
    listed = client.get(f"{PREFIX}/documents").json()
    kinds = {item["kind"] for item in listed["items"]}
    assert {"transcript", "knowledge"} <= kinds
    transcripts = client.get(f"{PREFIX}/documents", params={"kind": "transcript"}).json()
    assert transcripts["total"] and all(i["kind"] == "transcript" for i in transcripts["items"])
    path = transcripts["items"][0]["path"]
    shown = client.get(f"{PREFIX}/documents/preview", params={"path": path}).json()
    assert shown["kind"] == "transcript" and shown["markdown"].startswith("---")
    for probe in ("../../etc/passwd", "/etc/passwd", "Sources/../../x.md"):
        missing = client.get(f"{PREFIX}/documents/preview", params={"path": probe})
        assert missing.status_code == 404
    assert client.get(f"{PREFIX}/documents", params={"kind": "secrets"}).status_code == 422
    assert not (settings.workspace_root / "exports").exists()


@pytest.mark.parametrize(
    "destination", ["../outside", "/tmp/x", "C:\\Users\\x", "a/b", "..", ".", "x" * 65, "a b"]
)
def test_paths_are_not_destinations(
    destination: str, client: TestClient, settings: Settings
) -> None:
    refused = client.post(f"{PREFIX}/exports", json={"destination": destination})
    assert refused.status_code == 400
    assert refused.json()["error"]["code"] == "invalid_destination"
    assert not (settings.workspace_root / "exports").exists()
    assert getattr(client.app.state, "export_jobs", None) is None or not (
        client.app.state.export_jobs[1]._jobs  # type: ignore[attr-defined]
    )


def test_a_link_out_of_exports_is_refused(
    client: TestClient, settings: Settings, tmp_path: Path
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    root = settings.workspace_root / "exports"
    root.mkdir(parents=True)
    try:
        os.symlink(outside, root / "planted", target_is_directory=True)
    except OSError:
        pytest.skip("this system doesn't allow creating links")
    refused = client.post(f"{PREFIX}/exports", json={"destination": "planted"})
    assert refused.json()["error"]["code"] == "invalid_destination"
    assert list(outside.iterdir()) == []


def test_export_runs_in_the_background_and_lists(client: TestClient, settings: Settings) -> None:
    done = _export(client, "main")
    assert done["counts"]["created"] > 0
    folder = settings.workspace_root / "exports" / "main"
    assert (folder / ".ke" / "manifest.json").is_file()
    assert client.get(f"{PREFIX}/exports").json() == {"destinations": ["main"]}
    again = _export(client, "main")
    assert again["counts"]["created"] == again["counts"]["written"] == 0  # nothing changed


def test_user_files_and_edits_are_never_overwritten(client: TestClient, settings: Settings) -> None:
    path = client.get(f"{PREFIX}/documents", params={"kind": "knowledge"}).json()["items"][0][
        "path"
    ]
    # A note edited by hand above the marker is kept as it is.
    _export(client, "main")
    note = settings.workspace_root / "exports" / "main" / path
    edited = "My own words.\n" + note.read_text(encoding="utf-8")
    note.write_text(edited, encoding="utf-8")
    after = _export(client, "main")
    assert after["counts"]["conflicts"] == 1
    assert note.read_text(encoding="utf-8") == edited
    # A file of mine where the engine wants to write is left alone.
    mine = settings.workspace_root / "exports" / "other" / path
    mine.parent.mkdir(parents=True)
    mine.write_text("mine\n", encoding="utf-8")
    other = _export(client, "other")
    assert other["counts"]["occupied"] == 1
    assert mine.read_text(encoding="utf-8") == "mine\n"


def test_one_export_per_destination_at_a_time(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = threading.Event()
    real = documents_module.sync_vault

    def held(*args: Any, **kwargs: Any) -> Any:
        assert release.wait(30)
        return real(*args, **kwargs)

    monkeypatch.setattr(documents_module, "sync_vault", held)
    first = client.post(f"{PREFIX}/exports", json={"destination": "main"}).json()
    assert first["state"] == "running" and first["counts"] is None
    busy = client.post(f"{PREFIX}/exports", json={"destination": "main"})
    assert busy.status_code == 409 and busy.json()["error"]["code"] == "export_running"
    other = client.post(f"{PREFIX}/exports", json={"destination": "second"})
    assert other.status_code == 202
    release.set()
    jobs = client.app.state.export_jobs[1]  # type: ignore[attr-defined]
    assert jobs.get(first["job_id"]).done.wait(60)
    assert jobs.get(other.json()["job_id"]).done.wait(60)
    assert client.get(f"{PREFIX}/exports/jobs/nope").status_code == 404
    unknown = client.post(f"{PREFIX}/exports", json={"destination": "x", "taxonomy": "tax-9"})
    assert unknown.status_code == 404
