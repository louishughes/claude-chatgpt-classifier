"""UI-005: read-only pages for AI suggestions and reviewer decisions."""

from __future__ import annotations

import io
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.extraction import decisions, preferences
from knowledge_engine.extraction.runner import RuleExtractor, run
from knowledge_engine.extraction.store import Decision, KnowledgeRecordRow, decide
from knowledge_engine.extraction.text import segment_extraction_messages
from knowledge_engine.importer import import_source
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.rendering.transcript import load_conversation
from knowledge_engine.segmentation.segmenter import segment_conversation
from knowledge_engine.settings import Settings
from knowledge_engine.taxonomy.review import Operation, propose, reject
from knowledge_engine.ui.app import make_app

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt"
NOTE = "Synthetic <i>reason</i> & check"


def _call(settings: Settings, target: str, method: str = "GET") -> tuple[str, str]:
    captured: dict[str, Any] = {}

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        captured["status"] = status

    path, _, query = target.partition("?")
    environ: dict[str, Any] = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": query,
        "HTTP_HOST": "127.0.0.1:8765",
        "CONTENT_LENGTH": "0",
        "wsgi.input": io.BytesIO(b""),
    }
    body: Iterable[bytes] = make_app(settings)(environ, start_response)
    return captured["status"], b"".join(body).decode("utf-8")


@pytest.fixture(scope="module")
def settings(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    settings = Settings(workspace_root=tmp_path_factory.mktemp("ui5") / "ws")
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
        run(
            session,
            segments,
            [
                RuleExtractor(
                    "decisions", decisions.EXTRACTOR_VERSION, decisions.extract_decisions
                ),
                RuleExtractor(
                    "preferences", preferences.EXTRACTOR_VERSION, preferences.extract_preferences
                ),
            ],
        )
        waiting = session.scalars(
            select(KnowledgeRecordRow.record_id).where(KnowledgeRecordRow.trust != "rejected")
        ).first()
        assert waiting is not None
        decide(session, waiting, Decision.REJECT, reviewer="review-session-7", note=NOTE)
        proposal = propose(
            session, Operation.ADD, {"dimension": "topic", "label": "Synthetic"}, proposer="run-1"
        )
        reject(session, proposal.proposal_id, reviewer="review-session-8", note="Synthetic dup")
        session.commit()
    engine.dispose()
    return settings


def test_suggestions_page_shows_trust_and_links_to_quotes(settings: Settings) -> None:
    status, body = _call(settings, "/suggestions")
    assert status == "200 OK"
    assert "AI suggestions" in body and "A suggestion is not a decision" in body
    assert "review-session-7" in body  # the rejecting reviewer is named on the record
    assert 'href="/chats/' in body and "#" in body
    for trust in ("candidate", "review_required", "supported", "confirmed", "rejected"):
        assert f"/suggestions?trust={trust}" in body


def test_suggestions_filter(settings: Settings) -> None:
    _, rejected = _call(settings, "/suggestions?trust=rejected")
    assert "review-session-7" in rejected
    _, confirmed = _call(settings, "/suggestions?trust=confirmed")
    assert "review-session-7" not in confirmed
    assert "No suggestions match this filter" in confirmed
    _, by_type = _call(settings, "/suggestions?type=preference")
    assert "<td>decision</td>" not in by_type
    _, junk = _call(settings, "/suggestions?trust=%3Cscript%3E&type=nope")
    assert "<script>" not in junk


def test_reviews_page_names_reviewers_and_reasons_escaped(settings: Settings) -> None:
    status, body = _call(settings, "/reviews")
    assert status == "200 OK"
    assert "review-session-7" in body and "review-session-8" in body
    assert "Synthetic &lt;i&gt;reason&lt;/i&gt; &amp; check" in body
    assert "<i>reason</i>" not in body
    assert "Synthetic dup" in body and "rejected" in body
    # The validator is counted on its own, never listed as a reviewer.
    assert "Automatic evidence check" in body
    reviewers = body.split("<h2>Vocabulary proposals</h2>")[0]
    assert "<td>validator</td>" not in reviewers
    assert "Owner verdict" not in body


def test_pages_are_read_only(settings: Settings) -> None:
    for path in ("/suggestions", "/reviews"):
        status, _ = _call(settings, path, method="POST")
        assert status.startswith("405")


def test_pages_work_before_any_import(tmp_path: Path) -> None:
    empty = Settings(workspace_root=tmp_path / "ws")
    for path in ("/suggestions", "/reviews"):
        status, body = _call(empty, path)
        assert status == "200 OK", body
    assert "No reviewer decisions" in _call(empty, "/reviews")[1]
    nav = _call(empty, "/")[1]
    assert 'href="/suggestions"' in nav and 'href="/reviews"' in nav
