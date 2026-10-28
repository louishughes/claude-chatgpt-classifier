"""API-002: import and job endpoints, and paged sources and nodes.

The acceptance check: ``POST /imports`` answers with a job ID while the
import is still running, never with a premature "done".
"""

from __future__ import annotations

import shutil
import threading
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from knowledge_engine.api.app import PREFIX, create_app
from knowledge_engine.importer.run import run_import
from knowledge_engine.settings import Settings
from knowledge_engine.ui import jobs as jobs_module

CHATGPT = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt"


def _case_root(case: str) -> Path:
    export = CHATGPT / case / "export"
    zips = list(export.glob("*.zip"))
    return zips[0] if zips else export


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(workspace_root=tmp_path / "ws")


@pytest.fixture
def client(settings: Settings) -> TestClient:
    return TestClient(
        create_app(settings), base_url="http://127.0.0.1:8766", raise_server_exceptions=False
    )


def _copy(case: str, tmp_path: Path) -> Path:
    root = _case_root(case)
    target = tmp_path / f"in-{case}" / root.name
    if root.is_dir():
        shutil.copytree(root, target)
    else:
        target.parent.mkdir(parents=True)
        shutil.copy2(root, target)
    return target


def _wait(client: TestClient, job_id: str) -> dict[str, Any]:
    jobs = client.app.state.jobs[1]  # type: ignore[attr-defined]
    assert jobs.get(job_id).done.wait(30)
    body: dict[str, Any] = client.get(f"{PREFIX}/jobs/{job_id}").json()
    return body


def test_post_import_answers_with_a_running_job_not_a_result(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    release = threading.Event()
    real = jobs_module.import_source

    def held(*args: Any, **kwargs: Any) -> Any:
        assert release.wait(30)  # the import can't finish until the test says so
        return real(*args, **kwargs)

    monkeypatch.setattr(jobs_module, "import_source", held)
    export = _copy("export_single", tmp_path)
    started = client.post(f"{PREFIX}/imports", json={"source": str(export), "account": "acct"})
    assert started.status_code == 202
    job = started.json()
    assert job["state"] == "running"
    assert job["import_id"] is None and job["status"] is None
    assert client.get(f"{PREFIX}/jobs/{job['job_id']}").json()["state"] == "running"

    release.set()
    done = _wait(client, job["job_id"])
    assert done["state"] == "done"
    assert done["status"] == "succeeded"
    report = client.get(f"{PREFIX}/imports/{done['import_id']}").json()
    assert report["import_id"] == done["import_id"]
    assert report["status"] == "succeeded"
    assert "warnings" in report
    listed = client.get(f"{PREFIX}/imports").json()
    assert [row["import_id"] for row in listed["items"]] == [done["import_id"]]
    assert listed["next_offset"] is None


def test_a_failed_import_job_says_why_without_paths(client: TestClient, tmp_path: Path) -> None:
    broken = tmp_path / "private-name" / "export"
    broken.mkdir(parents=True)
    (broken / "conversations.json").write_text("{ not json", encoding="utf-8")
    job = client.post(f"{PREFIX}/imports", json={"source": str(broken)}).json()
    done = _wait(client, job["job_id"])
    assert done["state"] == "failed"
    assert done["error"]
    assert "private-name" not in done["error"]


def test_bad_import_requests_are_refused_without_echoing_the_path(
    client: TestClient, settings: Settings, tmp_path: Path
) -> None:
    missing = client.post(f"{PREFIX}/imports", json={"source": str(tmp_path / "secret-folder")})
    assert missing.status_code == 400
    assert missing.json()["error"]["code"] == "source_not_found"
    assert "secret-folder" not in missing.text

    settings.workspace_root.mkdir(parents=True)
    inside = client.post(f"{PREFIX}/imports", json={"source": str(settings.workspace_root)})
    assert inside.json()["error"]["code"] == "source_in_workspace"

    export = _copy("export_single", tmp_path)
    bad = client.post(f"{PREFIX}/imports", json={"source": str(export), "account": "a b"})
    assert bad.json()["error"]["code"] == "invalid_account"
    assert client.post(f"{PREFIX}/imports", json={}).json()["error"]["code"] == "invalid_request"


def test_cross_site_posts_are_refused(client: TestClient, tmp_path: Path) -> None:
    export = _copy("export_single", tmp_path)
    # What an HTML form on another site can send: not JSON.
    form = client.post(f"{PREFIX}/imports", data={"source": str(export)})
    assert form.status_code == 415
    assert form.json()["error"]["code"] == "json_required"
    foreign = client.post(
        f"{PREFIX}/imports",
        json={"source": str(export)},
        headers={"origin": "https://evil.example"},
    )
    assert foreign.status_code == 403
    assert foreign.json()["error"]["code"] == "origin_not_local"
    assert getattr(client.app.state, "jobs", None) is None  # nothing was started


def test_sources_are_paged_and_filtered(client: TestClient, settings: Settings) -> None:
    run_import(_case_root("similar_unrelated"), "fixture", format_id=None, settings=settings)
    everything = client.get(f"{PREFIX}/sources").json()
    total = everything["total"]
    assert total >= 2 and everything["next_offset"] is None
    first = client.get(f"{PREFIX}/sources", params={"limit": 1}).json()
    assert len(first["items"]) == 1 and first["next_offset"] == 1
    second = client.get(f"{PREFIX}/sources", params={"limit": 1, "offset": 1}).json()
    assert first["items"][0] != second["items"][0]
    word = everything["items"][0]["title"].split()[0]
    filtered = client.get(f"{PREFIX}/sources", params={"q": word}).json()
    assert 1 <= filtered["total"] <= total
    too_big = client.get(f"{PREFIX}/sources", params={"limit": 501})
    assert too_big.json()["error"]["code"] == "invalid_request"


@pytest.mark.parametrize("case", ["branches_edit", "branches_regen"])
def test_nodes_keep_the_tree_and_its_branches(
    case: str, client: TestClient, settings: Settings
) -> None:
    run_import(_case_root(case), "fixture", format_id=None, settings=settings)
    sources = client.get(f"{PREFIX}/sources").json()["items"]
    branched = 0
    for source in sources:
        cid = source["conversation_id"]
        facts = client.get(f"{PREFIX}/sources/{cid}").json()
        whole = client.get(f"{PREFIX}/sources/{cid}/nodes", params={"limit": 500}).json()
        nodes = whole["items"]
        assert whole["total"] == len(nodes) == facts["messages"]
        ids = [n["node_id"] for n in nodes]
        assert len(set(ids)) == len(ids)  # each message once
        # Active path first, then the alternates: never interleaved.
        sections = [n["section"] for n in nodes]
        assert sections == sorted(sections, key=lambda s: s != "active")
        # Paging gives the same list.
        paged: list[dict[str, Any]] = []
        offset: int | None = 0
        while offset is not None:
            page = client.get(
                f"{PREFIX}/sources/{cid}/nodes", params={"limit": 2, "offset": offset}
            ).json()
            paged += page["items"]
            offset = page["next_offset"]
        assert paged == nodes
        if facts["branch_points"]:
            branched += 1
            assert any(n["section"] == "alternate" for n in nodes)
            for point in facts["branch_points"]:
                assert len(point["children"]) > 1
                for child in point["children"]:
                    if child in ids:
                        assert nodes[ids.index(child)]["parent_id"] == point["parent_id"]
    assert branched


def test_nodes_carry_their_images(client: TestClient, settings: Settings, tmp_path: Path) -> None:
    run_import(_copy("repeated_image", tmp_path), "fixture", format_id=None, settings=settings)
    shas = set()
    for source in client.get(f"{PREFIX}/sources").json()["items"]:
        nodes = client.get(f"{PREFIX}/sources/{source['conversation_id']}/nodes").json()["items"]
        for node in nodes:
            shas.update(m["blob_sha256"] for m in node["media"] if m["availability"] == "available")
    assert shas


def test_unknown_things_are_404(client: TestClient, settings: Settings) -> None:
    run_import(_case_root("export_single"), "fixture", format_id=None, settings=settings)
    for path in ("/jobs/nope", "/imports/nope", "/sources/conv_nope", "/sources/conv_nope/nodes"):
        response = client.get(PREFIX + path)
        assert response.status_code == 404, path
        assert response.json()["error"]["code"] == "not_found"
