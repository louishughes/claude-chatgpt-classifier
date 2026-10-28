"""RET-002 / RET-003: a versioned local vector index; reworded queries find their message."""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.importer.run import run_import
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.infrastructure.workspace import WorkspaceRow
from knowledge_engine.retrieval.embeddings import (
    EmbeddingShapeError,
    FakeEmbedder,
    LocalHashEmbedder,
    stem,
)
from knowledge_engine.retrieval.semantic import (
    SemanticIndex,
    StaleIndexError,
    semantic_index_path,
    sync_semantic,
)
from knowledge_engine.settings import EgressDisabledError, EgressPolicy, Settings

CHATS = {
    "c-sem-1": [
        "Synthetic: we painted the garden shed bright red last weekend",
        "Synthetic: the kubernetes cluster keeps restarting its pods",
    ],
    "c-sem-2": [
        "Synthetic: I am baking sourdough bread with a new starter",
        "Synthetic: booking flights to Lisbon for the conference",
    ],
}
# Reworded, re-ordered, inflected or misspelt: query -> the message it means.
GOLDEN = [
    ("painting sheds red", "c-sem-1-m0"),
    ("pod restarts in my kubernetes clusters", "c-sem-1-m1"),
    ("baked sourdough", "c-sem-2-m0"),
    ("conference flight bookings", "c-sem-2-m1"),
    ("kubernetis clustr", "c-sem-1-m1"),
]
EGRESS_OFF = EgressPolicy()


def _export(root: Path) -> Path:
    conversations = []
    for conv_id, texts in CHATS.items():
        nodes: list[tuple[str, str | None]] = [(f"{conv_id}-root", None)]
        nodes += [(f"{conv_id}-m{i}", text) for i, text in enumerate(texts)]
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
        conversations.append(
            {
                "id": conv_id,
                "title": f"Synthetic {conv_id}",
                "mapping": mapping,
                "current_node": nodes[-1][0],
            }
        )
    root.mkdir(parents=True)
    (root / "conversations.json").write_text(json.dumps(conversations), encoding="utf-8")
    return root


@pytest.fixture
def world(tmp_path: Path) -> Iterator[tuple[Settings, Session, str]]:
    settings = Settings(workspace_root=tmp_path / "ws")
    run_import(_export(tmp_path / "export"), "acct", format_id=None, settings=settings)
    engine = create_sqlite_engine(database_path(settings))
    with Session(engine) as session:
        workspace = session.scalars(select(WorkspaceRow.workspace_id)).one()
        yield settings, session, workspace
    engine.dispose()


class Counting(LocalHashEmbedder):
    """The local embedder, counting how many texts it was asked to embed."""

    def __init__(self, dimension: int = 512) -> None:
        super().__init__(dimension)
        self.texts = 0

    def vectors(self, texts: Sequence[str]) -> list[list[float]]:
        self.texts += len(texts)
        return super().vectors(texts)


def test_stem_is_rough_but_safe() -> None:
    assert stem("painting") == stem("painted") == stem("paints") == "paint"
    assert stem("bus") == "bus"  # never below three letters


def test_reworded_queries_find_their_message(world: tuple[Settings, Session, str]) -> None:
    settings, session, workspace = world
    with SemanticIndex(semantic_index_path(settings), LocalHashEmbedder()) as index:
        sync_semantic(session, index, EGRESS_OFF)
        for query, target in GOLDEN:
            [best, *_] = index.search(query, workspace_id=workspace, egress=EGRESS_OFF, limit=3)
            assert best.native_node_id == target, query
        # The same query twice gives the same order (ties by revision ID).
        first = index.search("synthetic", workspace_id=workspace, egress=EGRESS_OFF)
        assert first == index.search("synthetic", workspace_id=workspace, egress=EGRESS_OFF)


def test_scope_is_enforced(world: tuple[Settings, Session, str]) -> None:
    settings, session, workspace = world
    conv_2 = session.scalars(
        select(ConversationRow.conversation_id).where(
            ConversationRow.native_conversation_id == "c-sem-2"
        )
    ).one()
    with SemanticIndex(semantic_index_path(settings), LocalHashEmbedder()) as index:
        sync_semantic(session, index, EGRESS_OFF)
        hits = index.search(
            "kubernetes cluster",
            workspace_id=workspace,
            egress=EGRESS_OFF,
            conversation_ids=[conv_2],
        )
        assert hits and {h.conversation_id for h in hits} == {conv_2}
        assert index.search("kubernetes", workspace_id="ws_other", egress=EGRESS_OFF) == []
        assert (
            index.search(
                "kubernetes", workspace_id=workspace, egress=EGRESS_OFF, roles=["assistant"]
            )
            == []
        )


def test_replay_embeds_nothing_new_and_a_new_model_is_refused(
    world: tuple[Settings, Session, str],
) -> None:
    settings, session, _ = world
    path = semantic_index_path(settings)
    counting = Counting()
    with SemanticIndex(path, counting) as index:
        first = sync_semantic(session, index, EGRESS_OFF)
        second = sync_semantic(session, index, EGRESS_OFF)
    assert first.embedded == 4 and first.empty == 0
    assert second.embedded == 0 and second.unchanged == 4
    assert counting.texts == 4  # the replay cost nothing
    with pytest.raises(StaleIndexError, match="rebuild"):
        SemanticIndex(path, LocalHashEmbedder(dimension=256))
    smaller = Counting(dimension=256)
    with SemanticIndex(path, smaller, rebuild=True) as index:
        assert sync_semantic(session, index, EGRESS_OFF).embedded == 4
    with pytest.raises(StaleIndexError):
        SemanticIndex(path, LocalHashEmbedder())  # the old size is now the stale one


def test_sending_embedders_need_the_egress_switch(world: tuple[Settings, Session, str]) -> None:
    settings, session, _ = world
    remote = FakeEmbedder({}, dimension=4, model="remote", sends_data=True)
    with SemanticIndex(semantic_index_path(settings), remote) as index:
        with pytest.raises(EgressDisabledError):
            sync_semantic(session, index, EGRESS_OFF)
        assert remote.calls == []  # nothing was sent
        assert sync_semantic(session, index, EgressPolicy(embedding=True)).embedded == 4
    wrong = FakeEmbedder({CHATS["c-sem-1"][0]: [1.0, 0.0]}, dimension=4, model="wrong")
    with SemanticIndex(tmp := settings.workspace_root / "other.db", wrong) as index:
        with pytest.raises(EmbeddingShapeError):
            sync_semantic(session, index, EGRESS_OFF)
    assert tmp.exists()


def test_cli_similar(
    world: tuple[Settings, Session, str],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from knowledge_engine.cli.main import main

    settings, session, _ = world
    session.close()
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(settings.workspace_root))
    assert main(["--json", "similar", "painting sheds red", "--limit", "1"]) == 0
    data = json.loads(capsys.readouterr().out)["data"]
    assert [h["native_node_id"] for h in data["hits"]] == ["c-sem-1-m0"]
    assert data["newly_embedded"] == 4
    with SemanticIndex(
        semantic_index_path(settings), LocalHashEmbedder(dimension=64), rebuild=True
    ):
        pass  # someone rebuilt it with another size
    assert main(["--json", "similar", "shed"]) != 0
    assert "stale" in capsys.readouterr().out
    assert main(["--json", "similar", "shed", "--rebuild"]) == 0
