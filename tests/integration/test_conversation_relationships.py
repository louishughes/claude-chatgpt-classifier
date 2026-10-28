"""REL-002: links between conversations, from exact evidence only.

Fixtures: ``copied_prefix`` (a copied opening, copied node IDs, a
chatgpt.com link, a pasted paragraph and a share link) and
``similar_unrelated`` (same title, topic and greeting; nothing shared).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import Session

from knowledge_engine.cli.main import main
from knowledge_engine.importer import import_source
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.relationships.detect import detect_relationships
from knowledge_engine.relationships.store import (
    ConversationRelationshipRow,
    RelationshipReviewRow,
    ReviewAction,
    history,
    review,
)
from knowledge_engine.settings import Settings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt"


def _expected(case: str) -> dict[str, Any]:
    manifest = json.loads((FIXTURES / case / "manifest.json").read_text(encoding="utf-8"))
    expected: dict[str, Any] = manifest["expected"]
    return expected


def _links(settings: Settings) -> list[list[str]]:
    engine = create_sqlite_engine(database_path(settings))
    try:
        with Session(engine) as session:
            native = {
                row.conversation_id: row.native_conversation_id
                for row in session.scalars(select(ConversationRow))
            }
            return sorted(
                [
                    native[r.from_conversation_id],
                    r.kind,
                    native[r.to_conversation_id],
                    r.evidence_class,
                    r.detector,
                ]
                for r in session.scalars(select(ConversationRelationshipRow))
            )
    finally:
        engine.dispose()


def test_copied_prefix_and_friends_become_candidates(tmp_path: Path) -> None:
    expected = _expected("copied_prefix")
    settings = Settings(workspace_root=tmp_path / "ws")
    report = import_source(FIXTURES / "copied_prefix" / "export", "fixture", settings=settings)

    assert _links(settings) == sorted(expected["relationships"])
    assert report.relationships["unresolved_share_links"] == expected["unresolved_share_links"]
    engine = create_sqlite_engine(database_path(settings))
    try:
        with Session(engine) as session:
            states = {r.review_state for r in session.scalars(select(ConversationRelationshipRow))}
            # Nothing is accepted by a machine.
            assert states == {expected["review_state"]}
            evidence = [
                json.loads(r.evidence_json)
                for r in session.scalars(select(ConversationRelationshipRow))
            ]
            # Evidence is IDs and counts, never copied text.
            assert "Synthetic" not in json.dumps(evidence)
    finally:
        engine.dispose()


def test_similar_but_unrelated_chats_get_no_link(tmp_path: Path) -> None:
    settings = Settings(workspace_root=tmp_path / "ws")
    import_source(FIXTURES / "similar_unrelated" / "export", "fixture", settings=settings)
    assert _links(settings) == _expected("similar_unrelated")["relationships"] == []


def test_reviews_are_append_only_and_keep_direction(tmp_path: Path) -> None:
    settings = Settings(workspace_root=tmp_path / "ws")
    export = FIXTURES / "copied_prefix" / "export"
    import_source(export, "fixture", settings=settings)
    engine = create_sqlite_engine(database_path(settings))
    try:
        with Session(engine) as session, session.begin():
            fork = session.scalars(
                select(ConversationRelationshipRow).where(
                    ConversationRelationshipRow.detector == "prefix-v1"
                )
            ).one()
            before = (fork.from_conversation_id, fork.kind, fork.to_conversation_id)
            review(session, fork.relationship_id, ReviewAction.ACCEPT, reviewer="owner")
            review(session, fork.relationship_id, ReviewAction.REJECT, reviewer="owner", note="no")
            rel_id = fork.relationship_id
        with Session(engine) as session:
            row = session.get(ConversationRelationshipRow, rel_id)
            assert row is not None
            assert (row.from_conversation_id, row.kind, row.to_conversation_id) == before
            assert row.review_state == "rejected"
            assert [(h.action, h.from_state, h.to_state) for h in history(session, rel_id)] == [
                ("accept", "candidate", "accepted"),
                ("reject", "accepted", "rejected"),
            ]
        # The database itself refuses to rewrite or erase history.
        for statement in (
            "UPDATE relationship_reviews SET action = 'accept'",
            "DELETE FROM relationship_reviews",
        ):
            with pytest.raises(DatabaseError, match="append-only"), engine.begin() as conn:
                conn.execute(text(statement))
    finally:
        engine.dispose()

    # A re-run (new import of changed data, or `ke related detect`) never
    # re-proposes or re-opens the rejected link.
    engine = create_sqlite_engine(database_path(settings))
    try:
        with Session(engine) as session, session.begin():
            workspace = session.scalars(select(ConversationRow.workspace_id)).first()
            assert workspace is not None
            assert detect_relationships(session, workspace_id=workspace, import_id=None) == {
                "unresolved_share_links": 1
            }
        with Session(engine) as session:
            row = session.get(ConversationRelationshipRow, rel_id)
            assert row is not None and row.review_state == "rejected"
            assert len(session.scalars(select(RelationshipReviewRow)).all()) == 2
    finally:
        engine.dispose()


def test_identical_reimport_runs_no_detection(tmp_path: Path) -> None:
    settings = Settings(workspace_root=tmp_path / "ws")
    export = FIXTURES / "copied_prefix" / "export"
    import_source(export, "fixture", settings=settings)
    again = import_source(export, "fixture", settings=settings)
    assert again.relationships == {}
    assert len(_links(settings)) == 4


def test_cli_lists_and_reviews(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = Settings(workspace_root=tmp_path / "ws")
    import_source(FIXTURES / "copied_prefix" / "export", "fixture", settings=settings)
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(settings.workspace_root))

    assert main(["--json", "related", "list", "--state", "candidate"]) == 0
    items = json.loads(capsys.readouterr().out)["data"]["relationships"]
    assert len(items) == 4
    quote = next(i for i in items if i["kind"] == "quotes")

    assert main(["--json", "related", "review", quote["relationship_id"], "accept"]) == 0
    assert json.loads(capsys.readouterr().out)["data"]["to_state"] == "accepted"
    assert main(["--json", "related", "list", "--state", "accepted"]) == 0
    [accepted] = json.loads(capsys.readouterr().out)["data"]["relationships"]
    assert accepted["history"][0]["reviewer"] == "owner"

    assert main(["--json", "related", "review", "rel_missing", "reject"]) != 0
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "unknown_relationship"
