"""DOC-007 and DOC-008: a project bundle is written, checked and counted.

Uses the synthetic engine_switch fixture: its decisions are filed under one
approved project, so the bundle has a master, records with quotes and the
chats' knowledge notes. Checking a bundle treats it as untrusted: each
kind of tampering fails with its own reason.
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.documents.bundle import (
    MANIFEST,
    RECORDS,
    BundleError,
    export_bundle,
    verify_bundle,
)
from knowledge_engine.extraction import decisions
from knowledge_engine.extraction.records import CandidateRecord, KnowledgeRecord, Provenance
from knowledge_engine.extraction.runner import RuleExtractor, run
from knowledge_engine.extraction.store import KnowledgeRecordRow, add_candidates, gate
from knowledge_engine.extraction.text import segment_extraction_messages
from knowledge_engine.importer import import_source
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.rendering.transcript import load_conversation
from knowledge_engine.segmentation.segmenter import segment_conversation
from knowledge_engine.settings import Limits, Settings
from knowledge_engine.taxonomy.registry import TaxonomyRegistry, TermStatus

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt"
PROJECT = "proj_engine"


@pytest.fixture
def project(tmp_path: Path) -> Iterator[tuple[Settings, Session]]:
    """The engine_switch chats, with every decision filed under one approved project."""
    settings = Settings(workspace_root=tmp_path / "ws")
    import_source(FIXTURES / "engine_switch" / "export", "fixture", settings=settings)
    session = Session(create_sqlite_engine(database_path(settings)))
    segments = []
    for conversation_id in session.scalars(select(ConversationRow.conversation_id)).all():
        conv = load_conversation(session, conversation_id)
        segments += [
            (seg.segment_id, segment_extraction_messages(conv, seg))
            for seg in segment_conversation(conv)
        ]
    rule = RuleExtractor("decisions", decisions.EXTRACTOR_VERSION, decisions.extract_decisions)
    run(session, segments, [rule])
    provenance = Provenance(
        stage_id="extract.test.v1", stage_key="stg_" + "b" * 64, extractor_version="t"
    )
    for row in session.scalars(
        select(KnowledgeRecordRow).where(KnowledgeRecordRow.record_type == "decision")
    ).all():
        original = KnowledgeRecord.model_validate_json(row.record_json)
        fields = original.model_dump(include=set(CandidateRecord.model_fields) - {"project_ids"})
        [copy] = add_candidates(
            session, [CandidateRecord(**fields, project_ids=(PROJECT,))], provenance
        )
        gate(session, copy.record_id)
    registry = TaxonomyRegistry(session)
    registry.add_project("Synthetic engine", status=TermStatus.APPROVED, project_id=PROJECT)
    registry.add_project("Synthetic idea", project_id="proj_idea")  # proposed only
    session.commit()
    yield settings, session
    session.close()


def _members(path: Path) -> dict[str, bytes]:
    with zipfile.ZipFile(path) as archive:
        return {i.filename: archive.read(i) for i in archive.infolist()}


def _rezip(path: Path, members: dict[str, bytes]) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    path.write_bytes(buffer.getvalue())


def test_a_bundle_holds_the_project_and_is_byte_identical_again(
    project: tuple[Settings, Session], tmp_path: Path
) -> None:
    _, session = project
    first, again = tmp_path / "a.zip", tmp_path / "b.zip"
    summary = export_bundle(session, PROJECT, first)
    export_bundle(session, PROJECT, again)
    assert first.read_bytes() == again.read_bytes()

    members = _members(first)
    assert next(iter(members)) == MANIFEST
    manifest = json.loads(members[MANIFEST])
    assert manifest["project_id"] == PROJECT and manifest["format"] == "bundle-v1"
    assert manifest["counts"]["records"] == summary.records > 0
    assert set(manifest["members"]) == set(members) - {MANIFEST}
    assert any(n.startswith("Projects/") for n in members)
    assert sum(n.startswith("Knowledge/") for n in members) == summary.chats > 0
    assert not any(n.startswith("Sources/") for n in members)  # no transcripts by default
    lines = [json.loads(x) for x in members[RECORDS].decode().splitlines()]
    assert all(q["text"] for line in lines for q in line["quotes"])  # the words behind each

    check = verify_bundle(first)
    assert check.ok, check.problems
    assert check.records == summary.records and check.by_type["decision"] == summary.records

    with_text = export_bundle(session, PROJECT, tmp_path / "c.zip", with_transcripts=True)
    assert with_text.transcripts == summary.chats
    assert any(n.startswith("Sources/") for n in _members(tmp_path / "c.zip"))


def test_an_unknown_or_unapproved_project_or_a_bad_target_is_refused(
    project: tuple[Settings, Session], tmp_path: Path
) -> None:
    _, session = project
    for project_id in ("proj_missing", "proj_idea"):
        with pytest.raises(BundleError, match="approved"):
            export_bundle(session, project_id, tmp_path / "x.zip")
    with pytest.raises(BundleError, match=r"\.zip"):
        export_bundle(session, PROJECT, tmp_path / "x.txt")
    with pytest.raises(BundleError, match="folder"):
        export_bundle(session, PROJECT, tmp_path / "missing" / "x.zip")
    assert list(tmp_path.glob("*.zip*")) == []


def test_each_kind_of_tampering_fails_with_its_own_reason(
    project: tuple[Settings, Session], tmp_path: Path
) -> None:
    _, session = project
    good = tmp_path / "good.zip"
    export_bundle(session, PROJECT, good)
    members = _members(good)
    note = next(n for n in members if n.startswith("Projects/"))

    changed = tmp_path / "changed.zip"
    _rezip(changed, {**members, note: members[note] + b"\nSynthetic edit.\n"})
    assert verify_bundle(changed).problems == [f"member changed: {note}"]

    escaping = tmp_path / "escaping.zip"
    _rezip(escaping, {**members, "../outside.md": b"Synthetic"})
    assert verify_bundle(escaping).problems == ["unsafe member name: '../outside.md'"]

    small = Limits(max_source_file_bytes=len(members[RECORDS]) - 1)
    assert f"member too large: {RECORDS}" in verify_bundle(good, small).problems

    lines = [json.loads(x) for x in members[RECORDS].decode().splitlines()]
    lines[0]["quotes"][0]["text"] = "Synthetic words nobody said"
    forged = "".join(json.dumps(x) + "\n" for x in lines).encode()
    manifest = json.loads(members[MANIFEST])
    manifest["members"][RECORDS] = hashlib.sha256(forged).hexdigest()
    quoted = tmp_path / "quoted.zip"
    _rezip(quoted, {**members, MANIFEST: json.dumps(manifest).encode(), RECORDS: forged})
    assert verify_bundle(quoted).problems == [
        f"quote does not match its hash: {lines[0]['record_id']}"
    ]


def test_cli_exports_verifies_and_shows(
    project: tuple[Settings, Session],
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from knowledge_engine.cli.main import main

    settings, _ = project
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(settings.workspace_root))
    target = tmp_path / "p.zip"
    assert main(["--json", "bundle", "export", PROJECT, "--to", str(target)]) == 0
    records = json.loads(capsys.readouterr().out)["data"]["records"]
    assert main(["--json", "bundle", "verify", str(target)]) == 0
    assert json.loads(capsys.readouterr().out)["data"]["ok"]
    assert main(["--json", "bundle", "show", str(target)]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["data"]["by_type"] == {"decision": records}
    assert "Synthetic" not in shown["message"]  # counts, never text
    target.write_bytes(b"not a zip")
    assert main(["--json", "bundle", "verify", str(target)]) == 1
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "bad_bundle"
