"""DOC-006: the managed vault keeps people's edits and rewrites nothing needlessly."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.documents.vault import (
    MANIFEST,
    MARKER,
    SyncReport,
    plan_vault,
    split_manual,
    sync_vault,
)
from knowledge_engine.domain.enums import Role
from knowledge_engine.domain.models import EvidenceRef
from knowledge_engine.extraction.records import CandidateRecord, Provenance, RecordType, Scope
from knowledge_engine.extraction.store import add_candidates
from knowledge_engine.graph.offsets import quote_hash
from knowledge_engine.importer import import_source
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.relationships.store import EvidenceClass, RelationKind, propose
from knowledge_engine.rendering.transcript import load_conversation
from knowledge_engine.settings import Settings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt"


@pytest.fixture
def workspace(tmp_path: Path) -> Iterator[tuple[Settings, Session]]:
    settings = Settings(workspace_root=tmp_path / "ws")
    import_source(FIXTURES / "repeated_image" / "export", "images", settings=settings)
    import_source(FIXTURES / "asset_problems" / "export", "problems", settings=settings)
    session = Session(create_sqlite_engine(database_path(settings)))
    first = load_conversation(
        session, session.scalars(select(ConversationRow.conversation_id)).first() or ""
    )
    native, message = next(
        (n, m) for n, m in first.messages.items() if m.role == "user" and (m.text or "").strip()
    )
    text = message.text or ""
    evidence = EvidenceRef(
        revision_id=first.revisions[native],
        start=0,
        end=len(text),
        quote_sha256=quote_hash(text),
        actor=Role.USER,
    )
    add_candidates(
        session,
        [
            CandidateRecord(
                record_type=RecordType.FACT,
                assertion="Synthetic project fact.",
                actor=Role.USER,
                scope=Scope.GLOBAL,
                project_ids=("proj_synthetic",),
                evidence=(evidence,),
            )
        ],
        Provenance(stage_id="extract.test.v1", stage_key="stg_" + "a" * 64, extractor_version="t"),
    )
    session.commit()
    yield settings, session
    session.close()


def _sync(settings: Settings, session: Session, vault: Path) -> SyncReport:
    return sync_vault(session, vault, settings.workspace_root / "archive")


def _files(vault: Path) -> dict[str, int]:
    """Every file in the vault -> its modification time (ns)."""
    return {
        p.relative_to(vault).as_posix(): p.stat().st_mtime_ns
        for p in vault.rglob("*")
        if p.is_file()
    }


def test_first_build_then_an_unchanged_build_writes_nothing(
    workspace: tuple[Settings, Session], tmp_path: Path
) -> None:
    settings, session = workspace
    vault = tmp_path / "vault"
    first = _sync(settings, session, vault)
    kinds = {n.kind for n in plan_vault(session)}
    assert kinds == {"transcript", "knowledge", "project"}
    assert first.created and not (first.written or first.conflicts or first.occupied)
    assert first.broken_embeds == {}  # every available image was copied in
    assert first.attachments["copied"] > 0
    for key in first.created:
        text = (vault / key).read_text(encoding="utf-8")
        assert text.endswith(f"\n{MARKER}\n")
    # Missing images are marked, never linked.
    knowledge = [k for k in first.created if k.startswith("Knowledge/")]
    assert any("[!warning] Image" in (vault / k).read_text(encoding="utf-8") for k in knowledge)
    before = _files(vault)
    second = _sync(settings, session, vault)
    assert second.counts()["created"] == second.counts()["written"] == 0
    assert sorted(second.unchanged) == sorted(first.created)
    assert second.attachments.get("copied", 0) == 0
    assert _files(vault) == before  # not one file rewritten, the manifest included


def test_edits_and_own_notes_are_safe_through_a_rebuild(
    workspace: tuple[Settings, Session], tmp_path: Path
) -> None:
    settings, session = workspace
    vault = tmp_path / "vault"
    first = _sync(settings, session, vault)
    chats = session.scalars(
        select(ConversationRow.conversation_id).order_by(ConversationRow.conversation_id)
    ).all()
    one, two = chats[0], chats[1]
    note_one = next(k for k in first.created if k.startswith("Knowledge/") and one[5:13] in k)
    note_two = next(k for k in first.created if k.startswith("Knowledge/") and two[5:13] in k)
    # Below the marker: an addition. Above it in the other note: a hand edit.
    (vault / note_one).write_text(
        (vault / note_one).read_text(encoding="utf-8") + "My own thoughts.\n", encoding="utf-8"
    )
    edited = (vault / note_two).read_text(encoding="utf-8").replace("## Summary", "## My summary")
    (vault / note_two).write_text(edited, encoding="utf-8")
    (vault / "My notes.md").write_text("Mine.\n", encoding="utf-8")
    # Something changes that both chats' notes show.
    propose(
        session,
        from_conversation_id=two,
        kind=RelationKind.RELATED_TO,
        to_conversation_id=one,
        evidence_class=EvidenceClass.HUMAN,
        confidence=1.0,
        detector="test-v1",
        evidence={},
        import_id=None,
    )
    session.commit()
    report = _sync(settings, session, vault)
    assert note_one in report.written
    parts = split_manual((vault / note_one).read_text(encoding="utf-8"))
    assert parts is not None and parts[1] == "My own thoughts.\n"
    assert "related_to" in parts[0]  # the new content arrived above the marker
    assert report.conflicts == [note_two]
    assert (vault / note_two).read_text(encoding="utf-8") == edited  # kept exactly
    assert (vault / "My notes.md").read_text(encoding="utf-8") == "Mine.\n"
    manifest = json.loads((vault / MANIFEST.as_posix()).read_text(encoding="utf-8"))
    assert "My notes.md" not in manifest["notes"]
    # Deleting the edited note hands it back to the engine.
    (vault / note_two).unlink()
    again = _sync(settings, session, vault)
    assert note_two in again.created and not again.conflicts


def test_files_the_engine_does_not_own_are_never_touched(
    workspace: tuple[Settings, Session], tmp_path: Path
) -> None:
    settings, session = workspace
    vault = tmp_path / "vault"
    taken = next(n.path for n in plan_vault(session) if n.kind == "transcript")
    (vault / taken.parent.as_posix()).mkdir(parents=True)
    (vault / taken.as_posix()).write_text("Someone else's file.\n", encoding="utf-8")
    report = _sync(settings, session, vault)
    assert report.occupied == [taken.as_posix()]
    assert (vault / taken.as_posix()).read_text(encoding="utf-8") == "Someone else's file.\n"
    assert _sync(settings, session, vault).occupied == [taken.as_posix()]  # still never claimed


def test_notes_no_longer_made_are_removed_only_if_unedited(
    workspace: tuple[Settings, Session], tmp_path: Path
) -> None:
    settings, session = workspace
    vault = tmp_path / "vault"
    _sync(settings, session, vault)
    manifest_path = vault / MANIFEST.as_posix()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    body = "# Old note\n"
    for name, tail in (
        ("Sources/Old (conv-00000000).md", ""),
        ("Sources/Kept (conv-11111111).md", "Mine.\n"),
    ):
        (vault / name).write_text(body + MARKER + "\n" + tail, encoding="utf-8")
        manifest["notes"][name] = {
            "kind": "transcript",
            "sha256": hashlib.sha256(body.encode()).hexdigest(),
        }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    report = _sync(settings, session, vault)
    assert report.removed == ["Sources/Old (conv-00000000).md"]
    assert not (vault / "Sources/Old (conv-00000000).md").exists()
    assert report.kept_stale == ["Sources/Kept (conv-11111111).md"]
    assert (vault / "Sources/Kept (conv-11111111).md").is_file()


def test_cli_docs_vault_prints_counts_only(
    workspace: tuple[Settings, Session],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    from knowledge_engine.cli.main import main

    settings, session = workspace
    titles = [t for t in session.scalars(select(ConversationRow.title)) if t]
    session.close()
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(settings.workspace_root))
    vault = tmp_path / "vault"
    assert main(["--json", "docs", "vault", "--vault", str(vault)]) == 0
    out = capsys.readouterr().out
    assert not any(title in out for title in titles)
    data = json.loads(out)["data"]
    assert data["created"] > 0 and data["conflicts"] == 0
    assert main(["--json", "docs", "vault", "--vault", str(vault)]) == 0
    assert json.loads(capsys.readouterr().out)["data"]["written"] == 0
