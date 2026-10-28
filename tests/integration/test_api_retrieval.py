"""API-004: search, grounded answers and decision history.

The acceptance check: every citation in an answer resolves to stored text
through the API itself, and ``as_of`` answers as things stood then.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from knowledge_engine.api.app import PREFIX, create_app
from knowledge_engine.extraction import decisions
from knowledge_engine.extraction.runner import RuleExtractor, run
from knowledge_engine.extraction.text import segment_extraction_messages
from knowledge_engine.importer import import_source
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.infrastructure.db import SessionFactory
from knowledge_engine.reconciliation.supersession import reconcile
from knowledge_engine.rendering.transcript import load_conversation
from knowledge_engine.segmentation.segmenter import segment_conversation
from knowledge_engine.settings import Settings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt"
SWITCH: dict[str, Any] = json.loads(
    (FIXTURES / "engine_switch" / "manifest.json").read_text(encoding="utf-8")
)["expected"]
TEXTS = [
    "Synthetic: we painted the garden shed bright red last weekend",
    "Synthetic: red is a bold choice for a shed",
    "Synthetic: the kubernetes cluster keeps restarting its pods",
    "Synthetic: check the liveness probe settings",
]


def _client(settings: Settings) -> TestClient:
    return TestClient(
        create_app(settings), base_url="http://127.0.0.1:8766", raise_server_exceptions=False
    )


def _export(root: Path) -> Path:
    nodes: list[tuple[str, str | None]] = [("api-root", None)]
    nodes += [(f"api-m{i}", text) for i, text in enumerate(TEXTS)]
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
                "author": {"role": "user" if i % 2 else "assistant"},
                "create_time": 1704067200.0 + 60 * i,
                "content": {"content_type": "text", "parts": [text]},
                "metadata": {},
            },
        }
    chat = {
        "id": "api-chat",
        "title": "Synthetic",
        "mapping": mapping,
        "current_node": nodes[-1][0],
    }
    root.mkdir(parents=True)
    (root / "conversations.json").write_text(json.dumps([chat]), encoding="utf-8")
    return root


@pytest.fixture
def shed(tmp_path: Path) -> TestClient:
    settings = Settings(workspace_root=tmp_path / "ws")
    import_source(_export(tmp_path / "export"), "acct", settings=settings)
    return _client(settings)


def _resolve(client: TestClient, citation: dict[str, Any]) -> str:
    """The cited characters, fetched through the API's own message listing."""
    nodes = client.get(
        f"{PREFIX}/sources/{citation['conversation_id']}/nodes", params={"limit": 500}
    ).json()["items"]
    [node] = [n for n in nodes if n["node_id"] == citation["native_node_id"]]
    assert node["revision_id"] == citation["revision_id"]
    assert 0 <= citation["start"] < citation["end"] <= len(node["text"])
    cited: str = node["text"][citation["start"] : citation["end"]]
    return cited


def test_answers_cite_text_that_resolves(shed: TestClient) -> None:
    body = shed.post(
        f"{PREFIX}/answers", json={"question": "what colour did we paint the shed"}
    ).json()
    found = body["answer"]
    assert found["status"] == "answered" and found["citations"]
    used = {c for s in found["sentences"] for c in s["citations"]}
    assert used and used <= {c["citation_id"] for c in found["citations"]}
    cited = [_resolve(shed, c) for c in found["citations"]]
    assert any("shed" in text for text in cited)


def test_an_unanswerable_question_abstains(shed: TestClient) -> None:
    found = shed.post(f"{PREFIX}/answers", json={"question": "what is the capital of peru"})
    assert found.json()["answer"]["status"] == "unknown"
    assert found.json()["answer"]["citations"] == []


def test_search_and_find(shed: TestClient) -> None:
    hits = shed.get(f"{PREFIX}/search", params={"q": "shed"}).json()["hits"]
    assert {h["native_node_id"] for h in hits} == {"api-m0", "api-m1"}
    exact = shed.get(f"{PREFIX}/search", params={"q": "garden shed", "mode": "phrase"}).json()
    assert [h["native_node_id"] for h in exact["hits"]] == ["api-m0"]
    one = shed.get(f"{PREFIX}/search", params={"q": "shed", "limit": 1}).json()["hits"]
    assert len(one) == 1
    assert shed.get(f"{PREFIX}/search", params={"q": "shed", "mode": "fuzzy"}).status_code == 422
    found = shed.get(f"{PREFIX}/find", params={"q": "kubernetes pods restarting"}).json()
    assert found["hits"] and found["hits"][0]["conversation_id"].startswith("conv_")


@pytest.fixture
def switch(tmp_path: Path) -> tuple[TestClient, Settings]:
    settings = Settings(workspace_root=tmp_path / "ws")
    import_source(FIXTURES / "engine_switch" / "export", "fixture", settings=settings)
    sessions = SessionFactory.from_settings(settings)
    with sessions.transaction() as session:
        segments = []
        for conversation_id in session.scalars(select(ConversationRow.conversation_id)).all():
            conv = load_conversation(session, conversation_id)
            segments += [
                (seg.segment_id, segment_extraction_messages(conv, seg))
                for seg in segment_conversation(conv)
            ]
        rule = RuleExtractor("decisions", decisions.EXTRACTOR_VERSION, decisions.extract_decisions)
        run(session, segments, [rule])
        reconcile(session)
    sessions.dispose()
    return _client(settings), settings


def _switch_time(client: TestClient) -> float:
    for source in client.get(f"{PREFIX}/sources").json()["items"]:
        nodes = client.get(f"{PREFIX}/sources/{source['conversation_id']}/nodes").json()["items"]
        for node in nodes:
            if node["node_id"] == SWITCH["replaced"]["switch"]:
                when: float = datetime.fromisoformat(node["created"]).timestamp()
                return when
    raise AssertionError("switch message not found")


def test_as_of_answers_as_things_stood_then(switch: tuple[TestClient, Settings]) -> None:
    client, _ = switch
    question = "What game engine did I decide on?"
    now = client.post(f"{PREFIX}/answers", json={"question": question}).json()["answer"]
    assert now["status"] == "answered"
    assert any(s["text"].startswith("Replaced decision") for s in now["sentences"])
    for citation in now["citations"]:
        assert _resolve(client, citation)

    before = client.post(
        f"{PREFIX}/answers", json={"question": question, "as_of": _switch_time(client) - 1}
    ).json()["answer"]
    texts = [s["text"] for s in before["sentences"]]
    assert texts and not any("Godot" in t for t in texts)
    assert not any(t.startswith("Replaced decision") for t in texts)

    found_before = client.get(
        f"{PREFIX}/find", params={"q": question, "as_of": _switch_time(client) - 1}
    ).json()
    assert found_before["route"] == "structured"
    assert all(r["status"] == "current" for r in found_before["records"])


def test_decision_history_with_evidence(switch: tuple[TestClient, Settings]) -> None:
    client, _ = switch
    found = client.get(f"{PREFIX}/find", params={"q": "What game engine did I decide on?"}).json()
    replaced = [r for r in found["records"] if r["superseded_by"]]
    assert replaced
    history = client.get(f"{PREFIX}/decisions/{replaced[0]['record_id']}/history").json()
    assert history["evidence"]  # the record's own quotes
    [event] = [e for e in history["events"] if e["predicate"] == "supersedes"]
    assert (
        event["to_record"] == replaced[0]["record_id"]
        or event["from_record"] == (replaced[0]["record_id"])
    )
    assert event["evidence"]
    assert client.get(f"{PREFIX}/decisions/krec_nope/history").status_code == 404
