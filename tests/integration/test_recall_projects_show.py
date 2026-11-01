"""RCL-003: `recall projects show NAME` puts each kind of knowledge in its own section.

The world: two synthetic fixtures, every extracted record filed under one
approved project. engine_switch gives a decision later replaced (Unity,
then "change of plan" to Godot); extraction_rules gives a suggestion the
user accepted, one nobody answered, and a rejection. A test-made decision
that says yes to what was rejected gives a conflict. All text is synthetic.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.extraction import decisions
from knowledge_engine.extraction.records import (
    Acceptance,
    CandidateRecord,
    KnowledgeRecord,
    Provenance,
    RecordType,
)
from knowledge_engine.extraction.runner import RuleExtractor, run
from knowledge_engine.extraction.store import KnowledgeRecordRow, add_candidates, gate
from knowledge_engine.extraction.text import segment_extraction_messages
from knowledge_engine.importer import import_source
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.recall.cli import main as recall_main
from knowledge_engine.reconciliation.conflicts import detect_conflicts
from knowledge_engine.reconciliation.supersession import reconcile
from knowledge_engine.reconciliation.timeline import build_events
from knowledge_engine.rendering.transcript import load_conversation
from knowledge_engine.segmentation.segmenter import segment_conversation
from knowledge_engine.settings import Settings
from knowledge_engine.taxonomy.projects import propose_project
from knowledge_engine.taxonomy.registry import TaxonomyRegistry, TermStatus

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt"
PROJECT = "proj_shed"


def _expected(case: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / case / "manifest.json").read_text("utf-8"))
    return data["expected"]


SWITCH = _expected("engine_switch")
RULES = _expected("extraction_rules")


@pytest.fixture(scope="module")
def workspace(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Path]:
    settings = Settings(workspace_root=tmp_path_factory.mktemp("ws"))
    for case in ("engine_switch", "extraction_rules"):
        import_source(FIXTURES / case / "export", "fixture", settings=settings)
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
        stage_id="extract.test.v1", stage_key="stg_" + "c" * 64, extractor_version="t"
    )
    # File a copy of every record under the project (as test_project_bundle does).
    rejection = None
    for row in session.scalars(select(KnowledgeRecordRow)).all():
        original = KnowledgeRecord.model_validate_json(row.record_json)
        fields = original.model_dump(include=set(CandidateRecord.model_fields) - {"project_ids"})
        [copy] = add_candidates(
            session, [CandidateRecord(**fields, project_ids=(PROJECT,))], provenance
        )
        gate(session, copy.record_id)
        if original.record_type is RecordType.REJECTION:
            rejection = copy
    # A decision that accepts what the user rejected: a conflict (REC-003).
    assert rejection is not None
    fields = rejection.model_dump(
        include=set(CandidateRecord.model_fields) - {"record_type", "acceptance"}
    )
    [accepted] = add_candidates(
        session,
        [
            CandidateRecord(
                **fields, record_type=RecordType.DECISION, acceptance=Acceptance.EXPLICIT
            )
        ],
        provenance,
    )
    gate(session, accepted.record_id)
    reconcile(session)
    detect_conflicts(session)
    build_events(session)
    registry = TaxonomyRegistry(session)
    registry.add_project(
        "Garden shed", aliases=["Shed build"], status=TermStatus.APPROVED, project_id=PROJECT
    )
    registry.add_project("Garden path", status=TermStatus.APPROVED, project_id="proj_path_a")
    registry.add_project("Old path", status=TermStatus.APPROVED, project_id="proj_path_b")
    registry.add_project("Pond", project_id="proj_pond")  # proposed, not approved
    propose_project(session, "Greenhouse", proposer="test", evidence={})
    session.commit()
    session.close()
    yield settings.workspace_root


@pytest.fixture
def env(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(workspace))
    return workspace


def _show(capsys: pytest.CaptureFixture[str], name: str) -> dict[str, Any]:
    assert recall_main(["--json", "projects", "show", name]) == 0
    data: dict[str, Any] = json.loads(capsys.readouterr().out)["data"]
    return data


def _user_messages(entries: list[dict[str, Any]]) -> set[str]:
    return {q["native_node_id"] for e in entries for q in e["quotes"] if q["actor"] == "user"}


def test_each_kind_lands_in_its_own_section(env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    data = _show(capsys, "Garden shed")
    sections = data["sections"]
    accepted_yes = next(
        n
        for kind, how, n in RULES["decisions"]["c0000030-0000-4000-8000-000000000002"]
        if kind == "decision" and how == "explicit"
    )
    # The accepted decision holds now.
    assert accepted_yes in _user_messages(sections["current"])
    # The replaced one is under Replaced, pointing at what replaced it, and not current.
    replaced = SWITCH["replaced"]["decision"]
    assert replaced in _user_messages(sections["superseded"])
    assert replaced not in _user_messages(sections["current"])
    current_ids = {e["record_id"] for e in sections["current"]}
    switch = next(
        e for e in sections["current"] if SWITCH["replaced"]["switch"] in _user_messages([e])
    )
    old = next(e for e in sections["superseded"] if replaced in _user_messages([e]))
    assert switch["record_id"] in old["superseded_by"] and switch["record_id"] in current_ids
    # The conflict: both sides are listed, each naming the other.
    conflicted = sections["conflicted"]
    assert {e["record_type"] for e in conflicted} == {"decision", "rejection"}
    a, b = conflicted
    assert b["record_id"] in a["conflicts_with"] or a["record_id"] in b["conflicts_with"]
    # Suggestions are counted, and nobody's unanswered suggestion is a decision.
    assert data["suggestions"]["open"] >= 1 and data["suggestions"]["accepted"] >= 1
    listed = [e for key in sections for e in sections[key]]
    assert all(e["record_type"] != "proposal" for e in listed)


def test_every_quote_is_rechecked_and_cites_its_message(
    env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    data = _show(capsys, "Garden shed")
    entries = [e for items in data["sections"].values() for e in items]
    assert entries
    for entry in entries:
        assert entry["quotes"], entry["record_id"]
        for q in entry["quotes"]:
            assert q["text"] and q["problem"] is None  # the stored words, re-checked
            assert q["conversation_id"].startswith("conv_") and q["native_node_id"]
            assert q["date"] is None or len(q["date"]) == 10
    chats = {c["conversation_id"] for c in data["chats"]}
    # The chats list is exactly the chats the project's records cite.
    assert {q["conversation_id"] for e in entries for q in e["quotes"]} <= chats
    assert len(chats) >= 3  # both engine_switch chats and the extraction_rules ones
    dates = [c["date"] for c in data["chats"] if c["date"]]
    assert dates == sorted(dates)  # oldest first


def test_names_aliases_and_ids_find_the_same_project(
    env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for name in ("Garden shed", "garden-SHED", "Shed build", PROJECT):
        assert _show(capsys, name)["project_id"] == PROJECT, name


def test_names_that_are_not_one_approved_project_are_refused(
    env: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for name, code in (
        ("Pond", "not_yet_a_project"),  # a proposed project
        ("greenhouse", "not_yet_a_project"),  # an open proposal
        ("Moon base", "no_project"),
        ("!!!", "no_project"),
    ):
        assert recall_main(["--json", "projects", "show", name]) == 2, name
        assert json.loads(capsys.readouterr().out)["error"] == {"code": code}, name


def test_a_name_matching_two_projects_lists_both(
    env: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Two approved projects can share a display name (aliases can't), so the
    # name alone doesn't say which one is meant.
    session = Session(create_sqlite_engine(database_path(Settings(workspace_root=env))))
    from knowledge_engine.taxonomy.registry import ProjectRow

    row = session.get_one(ProjectRow, "proj_path_b")
    row.name = "Garden path"
    session.commit()
    session.close()
    try:
        assert recall_main(["--json", "projects", "show", "Garden path"]) == 2
        out = json.loads(capsys.readouterr().out)
        assert out["error"] == {"code": "ambiguous"}
        assert [m["project_id"] for m in out["data"]["matches"]] == ["proj_path_a", "proj_path_b"]
        assert recall_main(["projects", "show", "Garden path"]) == 2
        assert "proj_path_b" in capsys.readouterr().err
    finally:
        session = Session(create_sqlite_engine(database_path(Settings(workspace_root=env))))
        session.get_one(ProjectRow, "proj_path_b").name = "Old path"
        session.commit()
        session.close()


def test_text_output(env: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert recall_main(["projects", "show", "Garden shed"]) == 0
    out = capsys.readouterr().out
    assert out.startswith(f"Garden shed  ({PROJECT})")
    for heading in ("What holds now", "In conflict", "Replaced", "Assistant suggestions", "Chats"):
        assert heading in out
    assert "replaced by #" in out and "conflicts with #" in out
    assert "{" not in out.splitlines()[0]
