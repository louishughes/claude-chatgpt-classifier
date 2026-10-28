"""PROD-003: separate workspaces can't see each other through any door.

The acceptance check: an adversarial multi-user corpus has zero
cross-workspace exposure. Alice owns workspace ``a`` (chats about a shed,
with words like "skylight" and "cladding"); Mallory owns workspace ``b``
(other synthetic chats) and tries every way in: her token on ``a``, ``a``'s
IDs on ``b``, ``a``'s words in search, answers and documents, ``a``'s job
and proposal IDs, imports from ``a``'s folders, exports and a purge in
``b``. None of it may show or change anything of ``a``'s.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from knowledge_engine.access.tenants import (
    TenantError,
    create_tenant,
    list_tenants,
    tenant_settings,
)
from knowledge_engine.api.app import PREFIX, create_app
from knowledge_engine.cli.main import main
from knowledge_engine.evaluation.synthetic import write_generated
from knowledge_engine.extraction.decisions import extract_decisions
from knowledge_engine.extraction.preferences import extract_preferences
from knowledge_engine.extraction.records import Provenance
from knowledge_engine.extraction.store import add_candidates
from knowledge_engine.extraction.text import segment_extraction_messages
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.infrastructure.db import SessionFactory
from knowledge_engine.rendering.transcript import load_conversation
from knowledge_engine.retention.purge import plan_purge, run_purge
from knowledge_engine.segmentation.segmenter import segment_conversation
from knowledge_engine.settings import Settings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt"
CANARIES = ("skylight", "cladding", "gravel")  # words only workspace a's chats hold
PROVENANCE = Provenance(
    stage_id="extract.test.v1", stage_key="stg_" + "c" * 64, extractor_version="test-v1"
)


def _client(settings: Settings) -> TestClient:
    return TestClient(
        create_app(settings), base_url="http://127.0.0.1:8766", raise_server_exceptions=False
    )


def _as(token: str, workspace: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-KE-Workspace": workspace}


def _fingerprint(folder: Path) -> dict[str, str]:
    return {
        str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(folder.rglob("*"))
        if p.is_file()
    }


def _import(client: TestClient, headers: dict[str, str], source: str) -> str:
    started = client.post(f"{PREFIX}/imports", json={"source": source}, headers=headers)
    assert started.status_code == 202, started.text
    job_id: str = started.json()["job_id"]
    jobs = client.app.state.tenant_jobs  # type: ignore[attr-defined]
    [job_list] = [j for j in jobs.values() if job_id in j._jobs]
    assert job_list.get(job_id).done.wait(60)
    assert client.get(f"{PREFIX}/jobs/{job_id}", headers=headers).json()["state"] == "done"
    return job_id


def _add_records(settings: Settings) -> list[str]:
    sessions = SessionFactory.from_settings(settings)
    with sessions.transaction() as session:
        found = []
        for (conversation_id,) in session.query(ConversationRow.conversation_id).all():
            conv = load_conversation(session, conversation_id)
            for seg in segment_conversation(conv):
                messages = segment_extraction_messages(conv, seg)
                found += extract_decisions(messages, segment_id=seg.segment_id)
                found += extract_preferences(messages, segment_id=seg.segment_id)
        records = add_candidates(session, found, PROVENANCE)
        ids = [r.record_id for r in records]
    sessions.dispose()
    return ids


@pytest.fixture
def hosted(tmp_path: Path) -> dict[str, Any]:
    settings = Settings(workspace_root=tmp_path / "single", tenants_root=tmp_path / "tenants")
    tokens = {
        "alice": create_tenant(settings, "a", "alice"),
        "mallory": create_tenant(settings, "b", "mallory"),
    }
    shutil.copytree(FIXTURES / "extraction_rules" / "export", tmp_path / "tenants/inbox/a/export")
    generated = write_generated(tmp_path / "gen", 5, seed=21) / "export"
    shutil.copytree(generated, tmp_path / "tenants/inbox/b/export")
    b_text = "".join(p.read_text("utf-8") for p in generated.rglob("*.json")).lower()
    assert not any(word in b_text for word in CANARIES)  # the canaries really are a's alone
    return {"settings": settings, "tokens": tokens, "root": tmp_path / "tenants"}


def test_no_way_from_one_workspace_into_another(hosted: dict[str, Any]) -> None:
    settings, tokens, root = hosted["settings"], hosted["tokens"], hosted["root"]
    client = _client(settings)
    alice, mallory = _as(tokens["alice"], "a"), _as(tokens["mallory"], "b")

    # Alice fills workspace a through the API; Mallory fills b.
    a_job = _import(client, alice, "export")
    _import(client, mallory, "export")
    a_records = _add_records(tenant_settings(settings, "a"))
    assert a_records
    a_sources = client.get(f"{PREFIX}/sources", headers=alice).json()["items"]
    a_conversations = [s["conversation_id"] for s in a_sources]
    [a_import] = [
        i["import_id"] for i in client.get(f"{PREFIX}/imports", headers=alice).json()["items"]
    ]
    proposal = client.post(
        f"{PREFIX}/taxonomy/proposals",
        json={
            "operation": "add",
            "payload": {"label": "Sheds", "dimension": "topic"},
            "proposer": "alice",
        },
        headers=alice,
    ).json()["proposal_id"]
    a_documents = {
        d["path"] for d in client.get(f"{PREFIX}/documents", headers=alice).json()["items"]
    }
    hits = client.get(f"{PREFIX}/search", params={"q": "skylight"}, headers=alice).json()
    assert hits["hits"]  # a can find its own words
    before = _fingerprint(root / "workspaces" / "a")

    # ---- Mallory, in her own workspace, probing for a's things.
    b_sources = client.get(f"{PREFIX}/sources", headers=mallory).json()["items"]
    assert b_sources and not {s["conversation_id"] for s in b_sources} & set(a_conversations)
    for conversation_id in a_conversations:
        for suffix in ("", "/nodes"):
            got = client.get(f"{PREFIX}/sources/{conversation_id}{suffix}", headers=mallory)
            assert got.status_code == 404
    for word in CANARIES:
        assert (
            client.get(f"{PREFIX}/search", params={"q": word}, headers=mallory).json()["hits"] == []
        )
        for mode in ("phrase", "exact"):
            found = client.get(
                f"{PREFIX}/search", params={"q": word, "mode": mode}, headers=mallory
            )
            assert found.json()["hits"] == []
        found = client.get(f"{PREFIX}/find", params={"q": word}, headers=mallory).json()
        assert word not in json.dumps(found).lower()
        answer = client.post(
            f"{PREFIX}/answers", json={"question": f"what about the {word}?"}, headers=mallory
        )
        assert answer.status_code == 200
        cited = json.dumps(answer.json()).lower()
        assert word not in cited.replace(f"what about the {word}?", "")
        assert not any(c in cited for c in a_conversations)
    for record_id in a_records[:3]:
        assert client.get(f"{PREFIX}/knowledge/{record_id}", headers=mallory).status_code == 404
        assert (
            client.get(f"{PREFIX}/decisions/{record_id}/history", headers=mallory).status_code
            == 404
        )
        review = client.post(
            f"{PREFIX}/knowledge/{record_id}/review",
            json={"decision": "reject", "reviewer": "mallory", "note": "x"},
            headers=mallory,
        )
        assert review.status_code == 404
    listed = json.dumps(client.get(f"{PREFIX}/knowledge", headers=mallory).json())
    assert not any(r in listed for r in a_records)
    assert client.get(f"{PREFIX}/imports/{a_import}", headers=mallory).status_code == 404
    assert client.get(f"{PREFIX}/jobs/{a_job}", headers=mallory).status_code == 404
    proposals = json.dumps(
        client.get(f"{PREFIX}/taxonomy/proposals", params={"status": "all"}, headers=mallory).json()
    )
    assert proposal not in proposals
    hijack = client.post(
        f"{PREFIX}/taxonomy/proposals/{proposal}/review",
        json={"decision": "approve", "reviewer": "mallory"},
        headers=mallory,
    )
    assert hijack.status_code == 404
    b_documents = client.get(f"{PREFIX}/documents", headers=mallory).json()["items"]
    assert not any(word in json.dumps(b_documents).lower() for word in CANARIES)
    for path in sorted(a_documents - {d["path"] for d in b_documents})[:5]:
        preview = client.get(f"{PREFIX}/documents/preview", params={"path": path}, headers=mallory)
        assert preview.status_code == 404
    # Imports only from her own inbox: a's inbox, a's workspace and absolute paths are refused.
    for source in (
        "../a/export",
        str(root / "inbox" / "a" / "export"),
        str(root / "workspaces" / "a"),
        "../../workspaces/a",
    ):
        refused = client.post(f"{PREFIX}/imports", json={"source": source}, headers=mallory)
        assert (refused.status_code, refused.json()["error"]["code"]) == (
            403,
            "source_outside_inbox",
        )
    # An export lands in b's own folder.
    exported = client.post(f"{PREFIX}/exports", json={"destination": "main"}, headers=mallory)
    assert exported.status_code == 202
    jobs = client.app.state.tenant_export_jobs  # type: ignore[attr-defined]
    [export_jobs] = [j for j in jobs.values() if exported.json()["job_id"] in j._jobs]
    assert export_jobs.get(exported.json()["job_id"]).done.wait(60)
    assert (root / "workspaces" / "b" / "exports" / "main").is_dir()
    assert not (root / "workspaces" / "a" / "exports").exists()
    exported_text = " ".join(
        p.read_text("utf-8").lower() for p in (root / "workspaces/b/exports/main").rglob("*.md")
    )
    assert not any(word in exported_text for word in CANARIES)
    # Deleting in b deletes nothing of a's.
    b_settings = tenant_settings(settings, "b")
    target = [b_sources[0]["conversation_id"]]
    run_purge(b_settings, target, confirm=plan_purge(b_settings, target).token, reason="test")

    # Nothing Mallory did in b touched a single byte of a's folder.
    assert _fingerprint(root / "workspaces" / "a") == before
    again = client.get(f"{PREFIX}/search", params={"q": "skylight"}, headers=alice).json()
    assert again == hits

    # ---- Mallory knocking on a's door directly.
    for headers in (_as(tokens["mallory"], "a"), _as("ke_forged", "a"), {"X-KE-Workspace": "a"}):
        refused = client.get(f"{PREFIX}/sources", headers=headers)
        assert (refused.status_code, refused.json()["error"]["code"]) == (401, "unauthenticated")


def test_workspace_selection_rules(hosted: dict[str, Any]) -> None:
    settings, tokens = hosted["settings"], hosted["tokens"]
    client = _client(settings)
    assert client.get(f"{PREFIX}/health").status_code == 200  # open, no workspace needed
    missing = client.get(
        f"{PREFIX}/sources", headers={"Authorization": f"Bearer {tokens['alice']}"}
    )
    assert (missing.status_code, missing.json()["error"]["code"]) == (400, "workspace_required")
    for name in ("nope", "../a", "a/../b", ""):
        unknown = client.get(f"{PREFIX}/sources", headers=_as(tokens["alice"], name or " "))
        assert unknown.status_code in (400, 401)
        assert unknown.json()["error"]["code"] in ("unauthenticated", "workspace_required")
    me = client.get(f"{PREFIX}/access/me", headers=_as(tokens["alice"], "a")).json()
    assert (me["checking"], me["account"], me["role"]) == (True, "alice", "owner")


def test_a_hosted_workspace_without_accounts_lets_nobody_in(hosted: dict[str, Any]) -> None:
    settings, root = hosted["settings"], hosted["root"]
    # A workspace folder made by hand, with a database but no accounts.
    bare = tenant_settings(settings, "bare")
    sessions = SessionFactory.from_settings(bare)
    from knowledge_engine.infrastructure.migrations import upgrade_to_head

    upgrade_to_head(sessions.engine)
    sessions.dispose()
    assert (root / "workspaces" / "bare" / "knowledge.db").exists()
    refused = _client(settings).get(f"{PREFIX}/sources", headers={"X-KE-Workspace": "bare"})
    assert (refused.status_code, refused.json()["error"]["code"]) == (401, "unauthenticated")


def test_tenant_names_and_cli(
    hosted: dict[str, Any], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = hosted["settings"]
    for bad in ("../x", "a/b", "", "x" * 65, "a"):
        with pytest.raises(TenantError):
            create_tenant(settings, bad, "someone")
    with pytest.raises(TenantError, match="tenants_root"):
        create_tenant(Settings(workspace_root=settings.workspace_root), "c", "carol")
    assert list_tenants(settings) == ["a", "b"]

    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(settings.workspace_root))
    monkeypatch.setenv("KE_TENANTS_ROOT", str(settings.tenants_root))
    assert main(["--json", "tenant", "add", "c", "--owner", "carol"]) == 0
    made = json.loads(capsys.readouterr().out)["data"]
    assert made["workspace"] == "c" and made["token"].startswith("ke_")
    assert main(["--json", "tenant", "list"]) == 0
    assert json.loads(capsys.readouterr().out)["data"]["workspaces"] == ["a", "b", "c"]
    me = _client(settings).get(f"{PREFIX}/access/me", headers=_as(made["token"], "c")).json()
    assert me["account"] == "carol"
