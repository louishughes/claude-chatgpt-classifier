"""RET-009: word search narrowed by day, speaker and vocabulary term (CLI and API)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.api.app import PREFIX, create_app
from knowledge_engine.classification.store import record_review
from knowledge_engine.cli.main import main
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.importer.run import run_import
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.rendering.transcript import load_conversation
from knowledge_engine.retrieval.filters import (
    BadFilterDate,
    BadFilterRole,
    UnknownFilterTerm,
    build_filters,
    day_bounds,
)
from knowledge_engine.retrieval.lexical import LexicalIndex, search_index_path, sync_index
from knowledge_engine.segmentation.overrides import load_segments
from knowledge_engine.settings import Settings
from knowledge_engine.taxonomy.registry import Dimension, TaxonomyRegistry, TermStatus

JAN_1 = 1704067200.0  # 2024-01-01 00:00 UTC
FEB_1 = 1706745600.0  # 2024-02-01 00:00 UTC


def _chat(cid: str, messages: list[tuple[str, str, float | None]]) -> dict[str, Any]:
    # messages: (role, text, create_time); a straight line, no branches.
    mapping: dict[str, Any] = {"root": {"id": "root", "parent": None, "children": []}}
    parent = "root"
    for i, (role, text, when) in enumerate(messages):
        node = f"{cid}-m{i}"
        mapping[node] = {
            "id": node,
            "parent": parent,
            "children": [],
            "message": {
                "id": node,
                "author": {"role": role},
                "create_time": when,
                "content": {"content_type": "text", "parts": [text]},
                "metadata": {},
            },
        }
        mapping[parent]["children"].append(node)
        parent = node
    return {"id": cid, "title": f"Synthetic {cid}", "mapping": mapping, "current_node": parent}


def _export(root: Path) -> Path:
    chats = [
        # January, labelled Gardening.
        _chat(
            "c-jan",
            [
                ("user", "My garden needs synthetic compost.", JAN_1 + 60),
                ("assistant", "Compost helps any garden.", JAN_1 + 120),
            ],
        ),
        # February 1st, last minute of the day; labelled Cooking.
        _chat(
            "c-feb",
            [
                ("user", "Herbs from the garden go in the soup.", FEB_1 + 86399),
                ("assistant", "A garden soup sounds good.", FEB_1 + 86399.5),
            ],
        ),
        # No times at all; never labelled.
        _chat("c-undated", [("user", "An undated garden note.", None)]),
    ]
    root.mkdir(parents=True)
    (root / "conversations.json").write_text(json.dumps(chats), encoding="utf-8")
    return root


@dataclass
class World:
    settings: Settings
    session: Session
    chats: dict[str, str]  # native ID -> conv_ ID
    terms: dict[str, str]  # label -> term ID
    workspace: str


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    settings = Settings(workspace_root=tmp_path / "ws")
    run_import(_export(tmp_path / "export"), "acct", format_id=None, settings=settings)
    engine = create_sqlite_engine(database_path(settings))
    session = Session(engine)
    chats = dict(
        session.execute(
            select(ConversationRow.native_conversation_id, ConversationRow.conversation_id)
        )
        .tuples()
        .all()
    )
    registry = TaxonomyRegistry(session)
    gardening = registry.add_term(Dimension.TOPIC, "Gardening", status=TermStatus.APPROVED)
    cooking = registry.add_term(Dimension.TOPIC, "Cooking", status=TermStatus.APPROVED)
    unused = registry.add_term(Dimension.TOPIC, "Proposed only", status=TermStatus.PROPOSED)
    taxonomy = registry.publish("tax-1", author="test")
    for native, term in (("c-jan", gardening.term_id), ("c-feb", cooking.term_id)):
        chat = load_conversation(session, chats[native])
        for segment in load_segments(session, chat):
            record_review(
                session, taxonomy, segment.segment_id, "topic", primary=term, reviewer="test"
            )
    session.commit()
    workspace = session.scalars(select(ConversationRow.workspace_id)).first()
    assert workspace is not None
    terms = {"Gardening": gardening.term_id, "Cooking": cooking.term_id, "unused": unused.term_id}
    yield World(settings, session, chats, terms, workspace)
    session.close()
    engine.dispose()


def _search(world: World, **asked: str) -> tuple[set[str], int]:
    filters = build_filters(world.session, **asked)
    with LexicalIndex(search_index_path(world.settings)) as index:
        sync_index(world.session, index)
        hits = index.search("garden", workspace_id=world.workspace, limit=50, filters=filters)
        undated = index.undated("garden", workspace_id=world.workspace, filters=filters)
    return {h.native_node_id for h in hits}, undated


def test_no_filter_searches_as_before(world: World) -> None:
    assert build_filters(world.session) is None
    found, undated = _search(world)
    assert found == {"c-jan-m0", "c-jan-m1", "c-feb-m0", "c-feb-m1", "c-undated-m0"}
    assert undated == 0


def test_days_are_inclusive_utc_and_undated_messages_are_counted(world: World) -> None:
    found, undated = _search(world, since="2024-01-01", until="2024-01-31")
    assert found == {"c-jan-m0", "c-jan-m1"}
    assert undated == 1
    # The last second of 1 February is still "on 2024-02-01".
    found, _ = _search(world, since="2024-02-01", until="2024-02-01")
    assert found == {"c-feb-m0", "c-feb-m1"}
    found, _ = _search(world, since="2024-02-02")
    assert found == set()


def test_speaker_filter(world: World) -> None:
    found, undated = _search(world, role="assistant")
    assert found == {"c-jan-m1", "c-feb-m1"}
    assert undated == 0  # no date filter, nothing left out for lacking one


def test_term_filter_follows_labels_in_force(world: World) -> None:
    found, _ = _search(world, term=world.terms["Gardening"])
    assert found == {"c-jan-m0", "c-jan-m1"}
    found, _ = _search(world, term=world.terms["Cooking"])
    assert found == {"c-feb-m0", "c-feb-m1"}


def test_filters_combine(world: World) -> None:
    found, _ = _search(world, term=world.terms["Cooking"], role="user", since="2024-02-01")
    assert found == {"c-feb-m0"}
    found, _ = _search(world, term=world.terms["Gardening"], since="2024-02-01")
    assert found == set()


def test_bad_filters_are_refused_never_ignored(world: World) -> None:
    for asked in (
        {"term": world.terms["unused"]},  # proposed, not approved
        {"term": "term_doesnotexist"},
        {"term": world.terms["Gardening"], "taxonomy": "tax-9"},
    ):
        with pytest.raises(UnknownFilterTerm):
            build_filters(world.session, **asked)
    for since in ("2024-1-1", "20240101", "yesterday"):
        with pytest.raises(BadFilterDate):
            build_filters(world.session, since=since)
    with pytest.raises(BadFilterDate):
        day_bounds("2024-02-01", "2024-01-01")
    with pytest.raises(BadFilterRole):
        build_filters(world.session, role="moderator")


def test_cli_search_filters(
    world: World, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(world.settings.workspace_root))
    assert main(["--json", "search", "garden", "--until", "2024-01-31"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert {h["native_node_id"] for h in out["data"]["hits"]} == {"c-jan-m0", "c-jan-m1"}
    assert out["data"]["undated_left_out"] == 1
    assert "have no date" in out["message"]
    assert main(["--json", "search", "garden", "--term", world.terms["Cooking"]]) == 0
    out = json.loads(capsys.readouterr().out)
    assert {h["native_node_id"] for h in out["data"]["hits"]} == {"c-feb-m0", "c-feb-m1"}
    assert "undated_left_out" not in out["data"]
    assert main(["--json", "search", "garden", "--term", world.terms["unused"]]) == 2
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "unknown_term"
    assert main(["--json", "search", "garden", "--since", "01/02/2024"]) == 2
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "bad_filter"


def test_api_search_filters(world: World) -> None:
    client = TestClient(
        create_app(world.settings), base_url="http://127.0.0.1:8766", raise_server_exceptions=False
    )
    url = f"{PREFIX}/search"
    body = client.get(url, params={"q": "garden", "role": "user", "since": "2024-01-01"}).json()
    assert {h["native_node_id"] for h in body["hits"]} == {"c-jan-m0", "c-feb-m0"}
    assert body["undated_left_out"] == 1
    body = client.get(url, params={"q": "garden", "term": world.terms["Gardening"]}).json()
    assert {h["native_node_id"] for h in body["hits"]} == {"c-jan-m0", "c-jan-m1"}
    refused = client.get(url, params={"q": "garden", "term": "term_secret-words"})
    assert refused.status_code == 400
    assert refused.json()["error"]["code"] == "unknown_term"
    assert "secret-words" not in refused.text  # input never echoed
    refused = client.get(url, params={"q": "garden", "since": "2024-13-45"})
    assert (refused.status_code, refused.json()["error"]["code"]) == (400, "bad_filter")
