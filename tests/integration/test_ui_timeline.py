"""UI-008: the Timeline page shows what holds now above what was replaced."""

from __future__ import annotations

import io
import re
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.extraction import decisions
from knowledge_engine.extraction.runner import RuleExtractor, run
from knowledge_engine.extraction.store import KnowledgeRecordRow, gate
from knowledge_engine.extraction.text import segment_extraction_messages
from knowledge_engine.importer import import_source
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.reconciliation.supersession import reconcile
from knowledge_engine.reconciliation.timeline import build_events
from knowledge_engine.rendering.transcript import load_conversation
from knowledge_engine.segmentation.segmenter import segment_conversation
from knowledge_engine.settings import Settings
from knowledge_engine.ui.app import make_app

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt"


def _world(case: str, root: Path) -> tuple[Settings, Session]:
    # Import a fixture and run the decision rule extractor, as REC-004's tests do.
    settings = Settings(workspace_root=root / case)
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
    return settings, session


def _get(settings: Settings, target: str) -> tuple[str, str]:
    captured: dict[str, Any] = {}

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        captured["status"] = status

    path, _, query = target.partition("?")
    environ: dict[str, Any] = {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": path,
        "QUERY_STRING": query,
        "HTTP_HOST": "127.0.0.1:8765",
        "CONTENT_LENGTH": "0",
        "wsgi.input": io.BytesIO(b""),
    }
    body: Iterable[bytes] = make_app(settings)(environ, start_response)
    return captured["status"], b"".join(body).decode("utf-8")


@pytest.fixture
def switch(tmp_path: Path) -> Iterator[tuple[Settings, tuple[tuple[str, str], ...]]]:
    # engine_switch: one chat decides Unity, then explicitly switches to Godot.
    settings, session = _world("engine_switch", tmp_path)
    for record_id in session.scalars(select(KnowledgeRecordRow.record_id)).all():
        gate(session, record_id)
    replaced = reconcile(session).superseded
    build_events(session)
    session.commit()
    session.close()
    yield settings, replaced


def test_replaced_decision_sits_below_its_replacement(
    switch: tuple[Settings, tuple[tuple[str, str], ...]],
) -> None:
    settings, replaced = switch
    [(later, earlier)] = replaced
    status, page = _get(settings, "/timeline")
    assert status == "200 OK"
    assert 'href="/timeline" aria-current="page"' in page
    now, history = page.index("Holds now"), page.index("Replaced later")
    assert now < page.index(f'id="{later}"') < history < page.index(f'id="{earlier}"')
    # The old decision links to the one that replaced it, on the same page.
    old = page[page.index(f'id="{earlier}"') :]
    assert f'Replaced by <a href="#{later}">' in old
    assert f'this replaces <a href="#{earlier}">' in page[page.index(f'id="{later}"') :]


def test_every_message_link_resolves(switch: tuple[Settings, tuple[tuple[str, str], ...]]) -> None:
    settings, _ = switch
    _, page = _get(settings, "/timeline")
    links = re.findall(r'href="(/chats/[^"#]+)#([^"]+)"', page)
    assert links
    for chat, anchor in links:
        status, chat_page = _get(settings, chat)
        assert status == "200 OK" and f'id="{anchor}"' in chat_page


def test_unknown_project_and_empty_workspace(
    switch: tuple[Settings, tuple[tuple[str, str], ...]], tmp_path: Path
) -> None:
    settings, _ = switch
    status, page = _get(settings, "/timeline?project=proj_nope%3Cb%3E")
    assert status == "200 OK" and "No such project." in page and "<b>" not in page
    _, empty = _get(settings.model_copy(update={"workspace_root": tmp_path / "none"}), "/timeline")
    assert "Nothing imported yet." in empty


def test_nothing_built_yet_says_what_to_run(tmp_path: Path) -> None:
    settings = Settings(workspace_root=tmp_path / "ws")
    import_source(FIXTURES / "engine_switch" / "export", "fixture", settings=settings)
    _, page = _get(settings, "/timeline")  # imported, but nothing extracted
    assert "ke timeline --build" in page


def test_project_filter_keeps_only_its_records(
    switch: tuple[Settings, tuple[tuple[str, str], ...]],
) -> None:
    settings, _ = switch
    from knowledge_engine.taxonomy.registry import TaxonomyRegistry, TermStatus

    engine = create_sqlite_engine(database_path(settings))
    with Session(engine) as session:
        unused = TaxonomyRegistry(session).add_project(
            "Synthetic unused", status=TermStatus.APPROVED
        )
        session.commit()
        project_id = unused.project_id
    engine.dispose()
    _, page = _get(settings, f"/timeline?project={project_id}")
    assert "Timeline: Synthetic unused" in page
    assert "names this project" in page and "ke timeline --build" not in page
