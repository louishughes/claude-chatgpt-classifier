"""RCL-004: `recall decisions history` and `recall decisions conflicts`.

The same synthetic world as RCL-003's test: the engine_switch and
extraction_rules chats, every record filed under one approved project,
plus a test-made decision that accepts what the user rejected (a
conflict). All text is synthetic.
"""

from __future__ import annotations

import json
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
from knowledge_engine.extraction.store import (
    Decision,
    KnowledgeRecordRow,
    add_candidates,
    decide,
    gate,
)
from knowledge_engine.extraction.text import segment_extraction_messages
from knowledge_engine.importer import import_source
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.recall.cli import main as recall_main
from knowledge_engine.recall.decisions import status_word
from knowledge_engine.reconciliation.conflicts import detect_conflicts
from knowledge_engine.reconciliation.relations import place
from knowledge_engine.reconciliation.supersession import reconcile
from knowledge_engine.reconciliation.timeline import (
    DecisionEventRow,
    Transition,
    build_events,
    record_event,
    revoke,
)
from knowledge_engine.rendering.transcript import load_conversation
from knowledge_engine.segmentation.segmenter import segment_conversation
from knowledge_engine.settings import Settings
from knowledge_engine.taxonomy.registry import TaxonomyRegistry, TermStatus

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt"
PROJECT = "proj_shed"
SWITCH: dict[str, Any] = json.loads(
    (FIXTURES / "engine_switch" / "manifest.json").read_text("utf-8")
)["expected"]
SHED = "c0000030-0000-4000-8000-000000000002"  # extraction_rules' shed chat
GRAVEL_YES, PAINT_NO, CEDAR = f"{SHED}-u1", f"{SHED}-u2", f"{SHED}-u4"


def _world(root: Path) -> Path:
    """Build the project world; returns its workspace root."""
    settings = Settings(workspace_root=root)
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
        stage_id="extract.test.v1", stage_key="stg_" + "d" * 64, extractor_version="t"
    )
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
        # Withdraw the unfiled original so only the project's copy takes
        # part in events (otherwise each step would show twice).
        decide(session, original.record_id, Decision.REJECT, reviewer="test", note="refiled")
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
    TaxonomyRegistry(session).add_project(
        "Garden shed", status=TermStatus.APPROVED, project_id=PROJECT
    )
    session.commit()
    session.close()
    return root


@pytest.fixture(scope="module")
def workspace(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return _world(tmp_path_factory.mktemp("ws"))


def _run(capsys: pytest.CaptureFixture[str], *args: str) -> dict[str, Any]:
    assert recall_main(["--json", "decisions", *args]) == 0
    data: dict[str, Any] = json.loads(capsys.readouterr().out)["data"]
    return data


def _said_in(record: dict[str, Any]) -> set[str]:
    """The user messages a record quotes."""
    return {q["native_node_id"] for q in record["quotes"] if q["actor"] == "user"}


def _subject_with(data: dict[str, Any], message: str, record_type: str) -> dict[str, Any]:
    return next(
        s
        for s in data["subjects"]
        if any(r["record_type"] == record_type and message in _said_in(r) for r in s["records"])
    )


def _record(subject: dict[str, Any], message: str, record_type: str) -> dict[str, Any]:
    return next(
        r for r in subject["records"] if r["record_type"] == record_type and message in _said_in(r)
    )


def test_status_words_follow_the_approved_mapping() -> None:
    assert status_word("proposal", "open") == "explored"
    assert status_word("proposal", "accepted") == "proposed"
    assert status_word("recommendation", "rejected") == "proposed"
    assert status_word("decision", "current") == "confirmed"
    assert status_word("requirement", "current") == "confirmed"
    assert status_word("preference", "current") == "preferred"
    assert status_word("rejection", "current") == "rejected"
    assert status_word("decision", "superseded") == "superseded"
    assert status_word("decision", "conflicted") == "conflicted"


def test_a_suggestion_and_its_acceptance_print_in_order(
    workspace: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(workspace))
    data = _run(capsys, "history", "Garden shed")
    gravel = _subject_with(data, GRAVEL_YES, "decision")
    decision = _record(gravel, GRAVEL_YES, "decision")
    [proposal] = [r for r in gravel["records"] if r["record_type"] == "proposal"]
    assert (decision["status"], proposal["status"]) == ("confirmed", "proposed")
    labels = [(s["label"], s["from_record"]) for s in gravel["steps"]]
    assert labels == [
        ("suggested", proposal["record_id"]),
        ("accepted", decision["record_id"]),
    ]
    # Every record in a subject quotes the message it comes from.
    assert all(q["text"] for r in gravel["records"] for q in r["quotes"])
    # A suggestion nobody answered is "explored", alone in its own subject.
    unanswered = [r for s in data["subjects"] for r in s["records"] if r["status"] == "explored"]
    assert len(unanswered) == 1 and unanswered[0]["record_type"] == "proposal"


def test_an_explicit_switch_is_a_replacement_in_order(
    workspace: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(workspace))
    data = _run(capsys, "history", "Garden shed")
    engine = _subject_with(data, SWITCH["replaced"]["decision"], "decision")
    old = _record(engine, SWITCH["replaced"]["decision"], "decision")
    new = _record(engine, SWITCH["replaced"]["switch"], "decision")
    assert (old["status"], new["status"]) == ("superseded", "confirmed")
    replaced = [s for s in engine["steps"] if s["label"] == "replaced"]
    assert {(s["from_record"], s["to_record"]) for s in replaced} >= {
        (new["record_id"], old["record_id"])
    }
    dates = [s["date"] for s in engine["steps"]]
    assert dates == sorted(dates)  # oldest first


def test_a_later_date_alone_replaces_nothing(
    workspace: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # Cedar cladding was decided after the gravel base, in the same chat and
    # project, but about something else: both hold, and neither replaces.
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(workspace))
    data = _run(capsys, "history", "Garden shed")
    cedar = _subject_with(data, CEDAR, "decision")
    gravel = _subject_with(data, GRAVEL_YES, "decision")
    assert cedar is not gravel
    assert _record(cedar, CEDAR, "decision")["status"] == "confirmed"
    assert _record(gravel, GRAVEL_YES, "decision")["status"] == "confirmed"
    replaced = [s for subject in data["subjects"] for s in subject["steps"]]
    replaced = [s for s in replaced if s["label"] == "replaced"]
    # The only replacements are the engine switch's explicit "instead of".
    engine = _subject_with(data, SWITCH["replaced"]["switch"], "decision")
    switch = _record(engine, SWITCH["replaced"]["switch"], "decision")
    assert replaced and all(s["from_record"] == switch["record_id"] for s in replaced)


def test_a_contradiction_stays_unresolved_and_is_not_a_replacement(
    workspace: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(workspace))
    history = _run(capsys, "history", "Garden shed")
    paint = _subject_with(history, PAINT_NO, "rejection")
    sides = [r for r in paint["records"] if r["record_type"] in ("decision", "rejection")]
    assert {r["status"] for r in sides} == {"conflicted"}
    assert "contradicted" in [s["label"] for s in paint["steps"]]
    assert "replaced" not in [s["label"] for s in paint["steps"]]

    data = _run(capsys, "conflicts", "Garden shed")
    [conflict] = data["conflicts"]
    assert conflict["state"] == "unresolved"
    assert {r["record_type"] for r in conflict["records"]} == {"decision", "rejection"}
    assert all(r["status"] == "conflicted" and r["quotes"] for r in conflict["records"])
    assert recall_main(["decisions", "conflicts", "Garden shed"]) == 0
    assert "unresolved: nothing says which holds" in capsys.readouterr().out


def test_suggest_accept_replace_and_a_revoked_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # A reviewer records that the later cedar decision replaced the gravel
    # one (synthetic, only to make a three-step chain), and withdraws the
    # skylight acceptance. Both show; the withdrawn step stays, marked.
    root = _world(tmp_path / "ws")
    session = Session(create_sqlite_engine(database_path(Settings(workspace_root=root))))
    placed = {
        p.record.record_id: p
        for p in place(
            session,
            [
                KnowledgeRecord.model_validate_json(r.record_json)
                for r in session.scalars(select(KnowledgeRecordRow))
                if PROJECT in r.record_json
            ],
        )
    }
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(root))
    before = _run(capsys, "history", "Garden shed")
    cedar_id = _record(_subject_with(before, CEDAR, "decision"), CEDAR, "decision")["record_id"]
    gravel_subject = _subject_with(before, GRAVEL_YES, "decision")
    gravel_id = _record(gravel_subject, GRAVEL_YES, "decision")["record_id"]
    record_event(
        session,
        Transition.SUPERSEDES,
        placed[cedar_id],
        placed[gravel_id],
        actor="review-test",
        note="Synthetic: to build a three-step chain",
    )
    accept = session.scalars(
        select(DecisionEventRow).where(
            DecisionEventRow.predicate == "accepts", DecisionEventRow.from_record == gravel_id
        )
    ).one()
    revoke(session, accept.event_id, reviewer="review-test", note="Synthetic: misread")
    session.commit()
    session.close()

    data = _run(capsys, "history", "Garden shed")
    chain = _subject_with(data, GRAVEL_YES, "decision")
    assert [s["label"] for s in chain["steps"]] == ["suggested", "accepted", "replaced"]
    accepted = chain["steps"][1]
    assert accepted["revoked"] and accepted["revoked_by"] == "review-test"
    assert accepted["revoked_note"] == "Synthetic: misread"
    assert _record(chain, GRAVEL_YES, "decision")["status"] == "superseded"
    assert recall_main(["decisions", "history", "Garden shed"]) == 0
    out = capsys.readouterr().out
    assert "[revoked by review-test: Synthetic: misread]" in out
    assert " replaced " in out


def test_unknown_project_and_text_output(
    workspace: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(workspace))
    for action in ("history", "conflicts"):
        assert recall_main(["--json", "decisions", action, "Moon base"]) == 2
        assert json.loads(capsys.readouterr().out)["error"] == {"code": "no_project"}
    assert recall_main(["decisions", "history", "garden shed"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("Garden shed: ")
    assert "A. " in out and " suggested" in out and " accepted " in out
