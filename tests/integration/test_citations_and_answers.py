"""RET-006 / RET-007: citations resolve or are rejected; answers cite every sentence or abstain."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.domain.enums import Role
from knowledge_engine.extraction import decisions
from knowledge_engine.extraction.evidence import revision_text
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
from knowledge_engine.graph.offsets import quote_hash
from knowledge_engine.importer import import_source
from knowledge_engine.importer.records import ConversationRow, MessageNodeRow, MessageRevisionRow
from knowledge_engine.importer.run import run_import
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.infrastructure.workspace import WorkspaceRow
from knowledge_engine.providers.base import FakeProvider, ModelRequest
from knowledge_engine.reconciliation.conflicts import detect_conflicts
from knowledge_engine.reconciliation.supersession import reconcile
from knowledge_engine.rendering.transcript import load_conversation
from knowledge_engine.retrieval.answers import (
    ABSTAIN_TEXT,
    ExtractiveWriter,
    ModelWriter,
    answer,
)
from knowledge_engine.retrieval.citations import (
    Citation,
    Problem,
    Rejected,
    audit,
    cite_message,
    hydrate,
    resolve,
)
from knowledge_engine.retrieval.embeddings import LocalHashEmbedder
from knowledge_engine.retrieval.hybrid import HybridHit, HybridRetriever
from knowledge_engine.retrieval.lexical import LexicalIndex, search_index_path, sync_index
from knowledge_engine.retrieval.semantic import SemanticIndex, semantic_index_path, sync_semantic
from knowledge_engine.segmentation.segmenter import segment_conversation
from knowledge_engine.settings import EgressDisabledError, EgressPolicy, Settings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt"
EGRESS_OFF = EgressPolicy()
TEXTS = [
    "Synthetic: we painted the garden shed bright red last weekend",
    "Synthetic: red is a bold choice for a shed",
    "Synthetic: the kubernetes cluster keeps restarting its pods",
    "Synthetic: check the liveness probe settings",
    "Synthetic: I am baking sourdough bread with a new starter",
]
EDITED = "Synthetic: I am baking rye sourdough bread with a new starter"


def _export(root: Path, *, edited: bool) -> Path:
    texts = [*TEXTS[:-1], EDITED if edited else TEXTS[-1]]
    nodes: list[tuple[str, str | None]] = [("ci-root", None)]
    nodes += [(f"ci-m{i}", text) for i, text in enumerate(texts)]
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
    conversation = {
        "id": "ci-chat",
        "title": "Synthetic citations",
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

    def ask(self, question: str, **options: Any) -> Any:
        return answer(
            self.session,
            question,
            self.retriever,
            self.lexical,
            workspace_id=self.workspace,
            **options,
        )

    def revisions(self, native: str) -> list[str]:
        return list(
            self.session.scalars(
                select(MessageRevisionRow.revision_id)
                .join(MessageNodeRow, MessageNodeRow.node_key == MessageRevisionRow.node_key)
                .where(MessageNodeRow.native_node_id == native)
                .order_by(MessageRevisionRow.created_at)
            )
        )

    def close(self) -> None:
        self.lexical.close()
        self.semantic.close()
        self.session.close()
        self.engine.dispose()


@pytest.fixture
def chat(tmp_path: Path) -> Iterator[Open]:
    settings = Settings(workspace_root=tmp_path / "ws")
    run_import(_export(tmp_path / "e1", edited=False), "acct", format_id=None, settings=settings)
    run_import(_export(tmp_path / "e2", edited=True), "acct", format_id=None, settings=settings)
    world = Open(settings)
    yield world
    world.close()


def test_citations_resolve_only_against_the_stored_text(chat: Open) -> None:
    [revision] = chat.revisions("ci-m0")
    text, _ = revision_text(chat.session, revision) or ("", Role.UNKNOWN)
    start = text.index("garden shed")
    end = start + len("garden shed")
    cited = resolve(chat.session, revision, start, end, quote_hash("garden shed"))
    assert isinstance(cited, Citation)
    assert cited.native_node_id == "ci-m0" and cited.actor == "user" and cited.newest_version
    again = resolve(chat.session, revision, start, end, quote_hash("garden shed"))
    assert again == cited  # the same evidence always has the same ID
    wrong = [
        resolve(chat.session, revision, start, end, quote_hash("garden shod")),
        resolve(chat.session, revision, start, len(text) + 5, quote_hash("garden shed")),
        resolve(chat.session, "rev_" + "0" * 32, 0, 3, quote_hash("Syn")),
        resolve(
            chat.session, revision, start, end, quote_hash("garden shed"), actor=Role.ASSISTANT
        ),
    ]
    assert [w.problem for w in wrong if isinstance(w, Rejected)] == [
        Problem.QUOTE_MISMATCH,
        Problem.SPAN_OUT_OF_RANGE,
        Problem.REVISION_MISSING,
        Problem.ACTOR_MISMATCH,
    ]
    assert audit(chat.session, [cited]) == []
    forged = Citation(**{**cited.__dict__, "citation_id": "kcit_" + "f" * 32})
    assert [p.problem for p in audit(chat.session, [forged])] == [Problem.ID_MISMATCH]


def test_edited_messages_keep_both_versions_citable(chat: Open) -> None:
    old, new = chat.revisions("ci-m4")
    first, second = cite_message(chat.session, old), cite_message(chat.session, new)
    assert isinstance(first, Citation) and isinstance(second, Citation)
    assert not first.newest_version and second.newest_version
    assert first.citation_id != second.citation_id


def test_hydrate_adds_a_window_and_rejects_stale_hits(chat: Open) -> None:
    hits = chat.retriever.search("kubernetes cluster", workspace_id=chat.workspace, limit=1).hits
    stale = HybridHit("message", "node_gone", None, ("rev_" + "0" * 32,), 0.0)
    missing_record = HybridHit("record", "krec_" + "0" * 32, None, (), 0.0)
    result = hydrate(chat.session, [*hits, stale, missing_record], window=1)
    [bundle] = result.bundles
    assert bundle.hit.native_node_id == "ci-m2"
    assert [(c.offset, c.native_node_id) for c in bundle.context] == [(-1, "ci-m1"), (1, "ci-m3")]
    assert [c.native_node_id for c in bundle.citations] == ["ci-m2"]  # context is never cited
    assert bundle.passages == (TEXTS[2],)
    assert [(r.key, r.problem) for r in result.rejected] == [
        ("node_gone", Problem.REVISION_MISSING),
        ("krec_" + "0" * 32, Problem.RECORD_MISSING),
    ]
    shed = chat.retriever.search("shed", workspace_id=chat.workspace).hits
    [opening] = hydrate(chat.session, [h for h in shed if h.native_node_id == "ci-m0"]).bundles
    assert [c.offset for c in opening.context] == [1, 2]  # nothing before the first message
    assert hydrate(chat.session, hits, window=0).bundles[0].context == ()


def test_answers_cite_every_sentence_or_abstain(chat: Open) -> None:
    found = chat.ask("what colour did we paint the shed")
    assert found.status == "answered" and found.writer == "extractive-v1"
    assert all(s.citation_ids for s in found.sentences)
    assert found.citations[0].native_node_id == "ci-m0"
    assert audit(chat.session, found.citations) == []
    assert "[1]" in found.text
    unknown = chat.ask("what is the capital of peru")
    assert unknown.status == "unknown" and unknown.citations == ()
    assert [s.text for s in unknown.sentences] == [ABSTAIN_TEXT]
    assert chat.ask("").status == "unknown"


def test_a_model_writer_cannot_cite_what_it_was_not_shown(chat: Open) -> None:
    def reply(request: ModelRequest) -> dict[str, Any]:
        assert "shed" not in request.instructions  # evidence is data, never instructions
        assert "[1]" in request.input_text
        return {
            "sentences": [
                {"text": "Synthetic: the shed was painted red.", "evidence": [1]},
                {"text": "Synthetic: it was also blue.", "evidence": [99]},
                {"text": "Synthetic: an unsupported claim.", "evidence": []},
            ]
        }

    provider = FakeProvider(reply)
    with pytest.raises(EgressDisabledError):
        chat.ask("what colour did we paint the shed", writer=ModelWriter(provider, EGRESS_OFF))
    assert provider.submitted == []  # refused before anything was sent
    allowed = ModelWriter(provider, EgressPolicy(text_llm=True))
    found = chat.ask("what colour did we paint the shed", writer=allowed)
    assert [s.text for s in found.sentences] == ["Synthetic: the shed was painted red."]
    assert found.dropped == ("unknown_citation", "no_citation")
    assert found.writer == "fake:fake-v1"
    silent = ModelWriter(FakeProvider(lambda _: {"sentences": []}), EgressPolicy(text_llm=True))
    assert chat.ask("what colour did we paint the shed", writer=silent).status == "unknown"
    broken = ModelWriter(FakeProvider(lambda _: "not json"), EgressPolicy(text_llm=True))
    assert chat.ask("what colour did we paint the shed", writer=broken).status == "unknown"


def _world(case: str, root: Path) -> Open:
    settings = Settings(workspace_root=root / case)
    import_source(FIXTURES / case / "export", "fixture", settings=settings)
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
    return Open(settings)


def test_decision_answers_show_what_replaced_what(tmp_path: Path) -> None:
    world = _world("engine_switch", tmp_path)
    try:
        reconcile(world.session)
        world.session.commit()
        found = world.ask("What game engine did I decide on?")
        assert found.status == "answered" and found.route == "structured"
        texts = [s.text for s in found.sentences]
        assert [t.split(":")[0] for t in texts] == [
            "Current decision",
            "Current decision",
            "Replaced decision",
        ]
        assert "replaced by:" in texts[-1] and "Godot" in texts[-1]
        assert audit(world.session, found.citations) == []
        assert {c.actor for c in found.citations} >= {"user"}
    finally:
        world.close()


def test_conflicting_decisions_are_reported_as_conflicted(tmp_path: Path) -> None:
    world = _world("extraction_rules", tmp_path)
    try:
        rejection = next(
            KnowledgeRecord.model_validate_json(r.record_json)
            for r in world.session.scalars(
                select(KnowledgeRecordRow).where(KnowledgeRecordRow.record_type == "rejection")
            )
        )
        fields = rejection.model_dump(
            include=set(CandidateRecord.model_fields) - {"record_type", "acceptance"}
        )
        accepted = CandidateRecord(
            **fields, record_type=RecordType.DECISION, acceptance=Acceptance.EXPLICIT
        )
        provenance = Provenance(
            stage_id="extract.test.v1", stage_key="stg_" + "f" * 64, extractor_version="t"
        )
        [decision] = add_candidates(world.session, [accepted], provenance)
        gate(world.session, decision.record_id)
        detect_conflicts(world.session)
        world.session.commit()
        subject = " ".join(re.findall(r"[A-Za-z]+", rejection.assertion))
        found = world.ask(f"What did I decide about {subject}")
        assert found.status == "conflicted"
        assert any(s.text.startswith("In conflict decision:") for s in found.sentences)
    finally:
        world.close()


def test_cli_ask(
    chat: Open,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    from knowledge_engine.cli.main import main

    chat.close()
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(tmp_path / "ws"))
    assert main(["--json", "ask", "what colour did we paint the shed"]) == 0
    [found] = json.loads(capsys.readouterr().out)["data"]["answers"]
    assert found["status"] == "answered" and found["citations"]
    assert all(s["citations"] for s in found["sentences"])
    assert main(["--json", "ask", "what is the capital of peru"]) == 0
    [unknown] = json.loads(capsys.readouterr().out)["data"]["answers"]
    assert unknown["status"] == "unknown" and unknown["answer"] == ABSTAIN_TEXT
    assert isinstance(ExtractiveWriter().name, str)
