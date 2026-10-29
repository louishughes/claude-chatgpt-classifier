"""REC-008: a person can work through conflicts and record links from the command line."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.cli.main import main
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
from knowledge_engine.reconciliation.graph import Direction, walk
from knowledge_engine.reconciliation.relations import (
    LinkCandidate,
    LinkState,
    Predicate,
    allowed,
    links_of,
    store_link,
)
from knowledge_engine.rendering.transcript import load_conversation
from knowledge_engine.segmentation.segmenter import segment_conversation
from knowledge_engine.settings import Settings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt"


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Settings, str]]:
    """The rules fixture, plus a decision that contradicts one of its rejections.

    Yields the settings and the text of that rejection, so tests can check it
    never appears in command output.
    """
    settings = Settings(workspace_root=tmp_path / "ws")
    import_source(FIXTURES / "extraction_rules" / "export", "fixture", settings=settings)
    engine = create_sqlite_engine(database_path(settings))
    with Session(engine) as session:
        segments = []
        for conversation_id in session.scalars(select(ConversationRow.conversation_id)).all():
            conv = load_conversation(session, conversation_id)
            segments += [
                (seg.segment_id, segment_extraction_messages(conv, seg))
                for seg in segment_conversation(conv)
            ]
        rule = RuleExtractor("decisions", decisions.EXTRACTOR_VERSION, decisions.extract_decisions)
        run(session, segments, [rule])
        rejection = next(
            KnowledgeRecord.model_validate_json(r.record_json)
            for r in session.scalars(
                select(KnowledgeRecordRow).where(KnowledgeRecordRow.record_type == "rejection")
            )
        )
        # The same statement as a decision: "accepted and rejected" in one chat.
        fields = rejection.model_dump(
            include=set(CandidateRecord.model_fields) - {"record_type", "acceptance"}
        )
        accepted = CandidateRecord(
            **fields, record_type=RecordType.DECISION, acceptance=Acceptance.EXPLICIT
        )
        provenance = Provenance(
            stage_id="extract.test.v1", stage_key="stg_" + "f" * 64, extractor_version="t"
        )
        [decision] = add_candidates(session, [accepted], provenance)
        gate(session, decision.record_id)
        # The fixture's detectors may propose no record link, so store one by
        # hand between the first pair of records the link rules allow.
        records = [
            KnowledgeRecord.model_validate_json(r.record_json)
            for r in session.scalars(
                select(KnowledgeRecordRow).order_by(KnowledgeRecordRow.record_id)
            )
        ]
        source, predicate, target = next(
            (a, p, b)
            for p in Predicate
            for a in records
            for b in records
            if a.evidence and b.evidence and allowed(p, a, b)
        )
        cited = {
            "from_revisions": [source.evidence[0].revision_id],
            "to_revisions": [target.evidence[0].revision_id],
        }
        store_link(
            session,
            LinkCandidate(source.record_id, predicate, target.record_id, cited, "test-v1"),
        )
        session.commit()
    engine.dispose()
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(settings.workspace_root))
    yield settings, rejection.assertion


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, dict[str, Any], str]:
    code = main(["--json", *argv])
    out = capsys.readouterr().out
    return code, json.loads(out), out


def _conflicted(capsys: pytest.CaptureFixture[str]) -> set[str]:
    code, body, _ = _run(capsys, "state")
    assert code == 0
    return {e["record_id"] for e in body["data"]["entries"] if e["status"] == "conflicted"}


def test_dismiss_and_reopen_a_conflict(
    world: tuple[Settings, str], capsys: pytest.CaptureFixture[str]
) -> None:
    _, private = world
    assert _run(capsys, "reconcile")[0] == 0
    code, body, out = _run(capsys, "conflicts", "list")
    assert code == 0 and private not in out  # IDs only, never the chat's words
    [conflict] = body["data"]["conflicts"]
    assert conflict["state"] == "unresolved" and conflict["history"] == []
    assert _conflicted(capsys) == set(conflict["records"])

    code, body, _ = _run(
        capsys,
        "conflicts",
        "review",
        conflict["conflict_id"],
        "dismiss",
        "--reviewer",
        "owner",
        "--note",
        "same sentence read twice",
    )
    assert code == 0 and body["data"]["to_state"] == "dismissed"
    assert _conflicted(capsys) == set()
    _, body, _ = _run(capsys, "conflicts", "list", "--state", "unresolved")
    assert body["data"]["conflicts"] == []

    # Reopening brings the flag back, and both reviews stay in the history.
    assert (
        _run(
            capsys,
            "conflicts",
            "review",
            conflict["conflict_id"],
            "reopen",
            "--reviewer",
            "owner",
            "--note",
            "looked again",
        )[0]
        == 0
    )
    assert _conflicted(capsys) == set(conflict["records"])
    _, body, _ = _run(capsys, "conflicts", "list")
    history = body["data"]["conflicts"][0]["history"]
    assert [(h["from_state"], h["to_state"]) for h in history] == [
        ("unresolved", "dismissed"),
        ("dismissed", "unresolved"),
    ]


def test_conflict_reviews_are_refused_not_ignored(
    world: tuple[Settings, str], capsys: pytest.CaptureFixture[str]
) -> None:
    _run(capsys, "reconcile")
    _, body, _ = _run(capsys, "conflicts", "list")
    conflict_id = body["data"]["conflicts"][0]["conflict_id"]
    code, body, out = _run(
        capsys,
        "conflicts",
        "review",
        "kcf_secret-words",
        "resolve",
        "--reviewer",
        "o",
        "--note",
        "x",
    )
    assert (code, body["error"]["code"]) == (2, "unknown_conflict")
    assert "secret-words" not in out  # the ID asked for is never echoed
    # Already unresolved: reopening it again is a refusal, not a silent no-op.
    code, body, _ = _run(
        capsys, "conflicts", "review", conflict_id, "reopen", "--reviewer", "o", "--note", "x"
    )
    assert (code, body["error"]["code"]) == (2, "refused")
    code, body, _ = _run(
        capsys, "conflicts", "review", conflict_id, "resolve", "--reviewer", " ", "--note", "x"
    )
    assert (code, body["error"]["code"]) == (2, "refused")


def test_reject_and_accept_a_record_link(
    world: tuple[Settings, str], capsys: pytest.CaptureFixture[str]
) -> None:
    settings, private = world
    _run(capsys, "reconcile")
    code, body, out = _run(capsys, "links", "list", "--state", "candidate")
    assert code == 0 and private not in out
    links = body["data"]["links"]
    link = next(item for item in links if item["detector"] == "test-v1")
    _, body, _ = _run(capsys, "links", "list", "--record", link["from"])
    assert link["link_id"] in {item["link_id"] for item in body["data"]["links"]}

    code, body, _ = _run(
        capsys, "links", "review", link["link_id"], "reject", "--reviewer", "owner"
    )
    assert code == 0 and body["data"]["to_state"] == "rejected"
    engine = create_sqlite_engine(database_path(settings))
    with Session(engine) as session:
        shown = links_of(session, link["from"], (LinkState.CANDIDATE, LinkState.ACCEPTED))
        assert link["link_id"] not in {row.link_id for row in shown}  # gone from notes
        # A walk skips the rejected edge unless asked to include closed ones.
        along = {"kinds": [link["predicate"]], "depth": 1, "direction": Direction.OUT}
        reached = {step.record_id for step in walk(session, link["from"], **along)}
        closed = {s.record_id for s in walk(session, link["from"], include_closed=True, **along)}
    engine.dispose()
    assert link["to"] in closed and link["to"] not in reached

    assert _run(capsys, "links", "review", link["link_id"], "accept", "--reviewer", "owner")[0] == 0
    _, body, _ = _run(capsys, "links", "list", "--state", "accepted")
    [accepted] = [item for item in body["data"]["links"] if item["link_id"] == link["link_id"]]
    assert [h["to_state"] for h in accepted["history"]] == ["rejected", "accepted"]
    code, body, out = _run(capsys, "links", "review", "krl_nope", "accept", "--reviewer", "o")
    assert (code, body["error"]["code"]) == (2, "unknown_link")
    assert "nope" not in out  # the ID asked for is never echoed
    # A review that changes nothing, or names nobody, is refused.
    for reviewer in ("owner", " "):
        code, body, _ = _run(
            capsys, "links", "review", link["link_id"], "accept", "--reviewer", reviewer
        )
        assert (code, body["error"]["code"]) == (2, "refused")
