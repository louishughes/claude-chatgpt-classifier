"""RET-004 / RET-005: fused search keeps exact codes and one hit per message; questions route."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.extraction import decisions
from knowledge_engine.extraction.runner import RuleExtractor, run
from knowledge_engine.extraction.text import segment_extraction_messages
from knowledge_engine.importer import import_source
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.importer.run import run_import
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.infrastructure.workspace import WorkspaceRow
from knowledge_engine.reconciliation.projection import Status
from knowledge_engine.reconciliation.supersession import reconcile
from knowledge_engine.rendering.transcript import load_conversation
from knowledge_engine.retrieval.embeddings import LocalHashEmbedder
from knowledge_engine.retrieval.hybrid import Channel, HybridRetriever
from knowledge_engine.retrieval.lexical import LexicalIndex, search_index_path, sync_index
from knowledge_engine.retrieval.planner import Route, plan, run_plan
from knowledge_engine.retrieval.semantic import SemanticIndex, semantic_index_path, sync_semantic
from knowledge_engine.segmentation.segmenter import segment_conversation
from knowledge_engine.settings import EgressPolicy, Settings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt"
SWITCH: dict[str, Any] = json.loads(
    (FIXTURES / "engine_switch" / "manifest.json").read_text(encoding="utf-8")
)["expected"]
EGRESS_OFF = EgressPolicy()
# Many messages about deploy errors, and one that only gives the code.
NOISE = [f"Synthetic: the deploy error came back again on server {n}" for n in range(12)]
CODE = "Synthetic: ERR-4012"
EDITED = "Synthetic: the deploy error is fixed by pinning the cache"


def _export(root: Path, *, edited: bool) -> Path:
    texts = [*NOISE, CODE, EDITED if edited else "Synthetic: the deploy error is a cache issue"]
    nodes: list[tuple[str, str | None]] = [("hy-root", None)]
    nodes += [(f"hy-m{i}", text) for i, text in enumerate(texts)]
    mapping: dict[str, Any] = {}
    for i, (node, text) in enumerate(nodes):
        mapping[node] = {
            "id": node,
            "parent": nodes[i - 1][0] if i else None,
            "children": [nodes[i + 1][0]] if i + 1 < len(nodes) else [],
            "message": None
            if text is None
            else {
                "id": node,
                "author": {"role": "user"},
                "create_time": 1704067200.0 + 60 * i,
                "content": {"content_type": "text", "parts": [text]},
                "metadata": {},
            },
        }
    conversation = {
        "id": "hy-chat",
        "title": "Synthetic hybrid",
        "mapping": mapping,
        "current_node": nodes[-1][0],
    }
    root.mkdir(parents=True)
    (root / "conversations.json").write_text(json.dumps([conversation]), encoding="utf-8")
    return root


class Open:
    """An archive session with both indexes synced."""

    def __init__(self, settings: Settings) -> None:
        self.engine = create_sqlite_engine(database_path(settings))
        self.session = Session(self.engine)
        self.lexical = LexicalIndex(search_index_path(settings))
        self.semantic = SemanticIndex(semantic_index_path(settings), LocalHashEmbedder())
        sync_index(self.session, self.lexical)
        sync_semantic(self.session, self.semantic, EGRESS_OFF)
        self.retriever = HybridRetriever(self.session, self.lexical, self.semantic, EGRESS_OFF)
        self.workspace = self.session.scalars(select(WorkspaceRow.workspace_id)).one()

    def close(self) -> None:
        self.lexical.close()
        self.semantic.close()
        self.session.close()
        self.engine.dispose()


@pytest.fixture
def noisy(tmp_path: Path) -> Iterator[Open]:
    settings = Settings(workspace_root=tmp_path / "ws")
    run_import(_export(tmp_path / "e1", edited=False), "acct", format_id=None, settings=settings)
    # A second export edits the last message: the same message, a second version.
    run_import(_export(tmp_path / "e2", edited=True), "acct", format_id=None, settings=settings)
    world = Open(settings)
    yield world
    world.close()


def test_exact_code_is_pinned_first(noisy: Open) -> None:
    question = plan("why does the deploy error ERR-4012 keep coming back")
    assert question.route is Route.HYBRID and question.exact_terms == ("ERR-4012",)
    hits = noisy.retriever.search(
        question.query, workspace_id=noisy.workspace, limit=3, exact_terms=question.exact_terms
    ).hits
    assert len(hits) == 3
    assert hits[0].native_node_id == "hy-m12" and hits[0].pinned
    assert not any(h.pinned for h in hits[1:])
    # Without pinning, twelve near-identical deploy messages bury the code.
    unpinned = noisy.retriever.search(
        question.query, workspace_id=noisy.workspace, limit=3, exact_terms=[]
    ).hits
    assert "hy-m12" not in {h.native_node_id for h in unpinned}


def test_one_hit_per_message_and_a_stable_order(noisy: Open) -> None:
    result = noisy.retriever.search("deploy error cache", workspace_id=noisy.workspace, limit=50)
    assert result.out_of_scope == 0
    assert result.channels == ("lexical", "semantic", "structured")
    keys = [h.key for h in result.hits]
    assert len(keys) == len(set(keys))  # every message once
    [edited] = [h for h in result.hits if h.native_node_id == "hy-m13"]
    assert len(edited.revisions) == 2  # both versions matched; one hit lists them
    assert set(edited.ranks) == {"lexical", "semantic"}  # found by both channels
    again = noisy.retriever.search("deploy error cache", workspace_id=noisy.workspace, limit=50)
    assert again == result
    scores = [h.score for h in result.hits if not h.pinned]
    assert scores == sorted(scores, reverse=True)
    # Scope: another workspace or another channel set.
    assert noisy.retriever.search("deploy", workspace_id="ws_other").hits == ()
    words_only = noisy.retriever.search(
        "deploy", workspace_id=noisy.workspace, channels=[Channel.LEXICAL]
    )
    assert words_only.channels == ("lexical",)
    assert all(set(h.ranks) <= {"lexical"} for h in words_only.hits)
    assert noisy.retriever.search("  ", workspace_id=noisy.workspace).hits == ()


def test_exact_route_finds_the_code_only(noisy: Open) -> None:
    question = plan("ERR-4012")
    assert question.route is Route.EXACT
    result = run_plan(
        noisy.session, question, noisy.retriever, noisy.lexical, workspace_id=noisy.workspace
    )
    assert [h.native_node_id for h in result.hits] == ["hy-m12"]
    empty = run_plan(
        noisy.session, plan("  "), noisy.retriever, noisy.lexical, workspace_id=noisy.workspace
    )
    assert empty.route is Route.EMPTY and empty.hits == () and empty.records == ()


@pytest.fixture
def switch(tmp_path: Path) -> Iterator[tuple[Settings, Open]]:
    settings = Settings(workspace_root=tmp_path / "switch")
    import_source(FIXTURES / "engine_switch" / "export", "fixture", settings=settings)
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
        session.commit()
    engine.dispose()
    world = Open(settings)
    yield settings, world
    world.close()


def test_decision_question_reads_the_current_records(switch: tuple[Settings, Open]) -> None:
    _, world = switch
    question = plan("What game engine did I decide on?")
    assert question.route is Route.STRUCTURED

    def ask() -> list[tuple[str, Status]]:
        result = run_plan(
            world.session, question, world.retriever, world.lexical, workspace_id=world.workspace
        )
        assert result.route is Route.STRUCTURED and not result.fallback
        return [(r.assertion, r.status) for r in result.records]

    before = ask()
    assert [s for _, s in before] == [Status.CURRENT] * 3
    reconcile(world.session)
    world.session.commit()
    after = ask()
    # Current answers first; the replaced Unity decision is still shown, last, as replaced.
    assert [s for _, s in after] == [Status.CURRENT, Status.CURRENT, Status.SUPERSEDED]
    assert any("Godot" in text for text, s in after if s is Status.CURRENT)
    # Nothing about the subject: fall back to the combined search, and say so.
    other = run_plan(
        world.session,
        plan("What did I decide about the marketing budget?"),
        world.retriever,
        world.lexical,
        workspace_id=world.workspace,
    )
    assert other.fallback and other.route is Route.HYBRID and other.records == ()


def test_structured_channel_joins_the_fusion(switch: tuple[Settings, Open]) -> None:
    _, world = switch
    hits = world.retriever.search("Godot game engine", workspace_id=world.workspace).hits
    records = [h for h in hits if h.kind == "record"]
    assert records and all(h.revisions and h.record_type == "decision" for h in records)
    assert all(set(h.ranks) == {"structured"} for h in records)
    exact = run_plan(
        world.session,
        plan('"Godot instead of Unity"'),
        world.retriever,
        world.lexical,
        workspace_id=world.workspace,
    )
    assert [h.native_node_id for h in exact.hits] == [SWITCH["replaced"]["switch"]]


def test_cli_find(
    switch: tuple[Settings, Open],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from knowledge_engine.cli.main import main

    settings, world = switch
    world.close()
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(settings.workspace_root))
    assert main(["--json", "find", "What game engine did I decide on?"]) == 0
    data = json.loads(capsys.readouterr().out)["data"]
    assert data["route"] == "structured" and not data["fallback"]
    assert {r["status"] for r in data["records"]} == {"current"}
    assert main(["--json", "find", '"change of plan"']) == 0
    data = json.loads(capsys.readouterr().out)["data"]
    assert data["route"] == "exact" and len(data["hits"]) == 1
