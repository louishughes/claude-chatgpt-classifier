"""IMP-006: corrections on unchanged words survive a re-import; on revised words, flagged."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import Session

from knowledge_engine.classification.store import effective_labels, record_review
from knowledge_engine.domain.enums import Role
from knowledge_engine.domain.models import EvidenceRef
from knowledge_engine.extraction.records import CandidateRecord, Provenance, RecordType, Scope
from knowledge_engine.extraction.store import Decision, add_candidates, decide, gate
from knowledge_engine.graph.offsets import quote_hash
from knowledge_engine.importer.corrections import (
    OverrideKind,
    OverrideState,
    check_overrides,
)
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.importer.run import run_import
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.relationships.store import (
    ConversationRelationshipRow,
    EvidenceClass,
    RelationKind,
    ReviewAction,
    propose,
    review,
)
from knowledge_engine.rendering.transcript import StoredConversation, load_conversation
from knowledge_engine.segmentation.overrides import Action, load_segments, record_override
from knowledge_engine.settings import Settings
from knowledge_engine.taxonomy.registry import Dimension, TaxonomyRegistry, TermStatus

MESSAGES = {
    "u1": ("user", "Synthetic: plan the garden beds for spring."),
    "a1": ("assistant", "Synthetic: raised beds along the south fence."),
    "u2": ("user", "Synthetic: now choose a paint colour for the shed."),
    "a2": ("assistant", "Synthetic: sage green suits the shed."),
}


def _export(root: Path, revised: bool) -> Path:
    chats = []
    for cid in ("c-imp-x", "c-imp-y"):
        mapping: dict[str, Any] = {"root": {"id": "root", "parent": None, "children": ["u1"]}}
        order = ["root", *MESSAGES]
        for i, node in enumerate(order[1:], 1):
            role, words = MESSAGES[node]
            if revised and cid == "c-imp-x" and node == "u2":
                words = "Synthetic: now choose a paint colour for the garage."
            mapping[node] = {
                "id": node,
                "parent": order[i - 1],
                "children": [order[i + 1]] if i + 1 < len(order) else [],
                "message": {
                    "id": node,
                    "author": {"role": role},
                    "create_time": 1704067200.0 + 60 * i,
                    "content": {"content_type": "text", "parts": [words]},
                    "metadata": {},
                },
            }
        chats.append(
            {
                "id": cid,
                "title": f"Synthetic {cid}",
                "create_time": 1704067200.0,
                "mapping": mapping,
                "current_node": "a2",
            }
        )
    root.mkdir(parents=True)
    (root / "conversations.json").write_text(json.dumps(chats), encoding="utf-8")
    return root


@dataclass
class Setup:
    settings: Settings
    tmp: Path
    chats: dict[str, str]  # native ID -> conv_ ID
    splits: dict[str, str]  # native chat -> override_id
    reviews: dict[tuple[str, str], str]  # (chat, first message of segment) -> review_id
    records: dict[str, str]  # chat -> krec_ ID
    relationships: dict[str, str]  # "cited" | "bare" -> rel_ ID


def _evidence(chat: StoredConversation, native: str) -> EvidenceRef:
    words = chat.messages[native].text or ""
    return EvidenceRef(
        revision_id=chat.revisions[native],
        start=0,
        end=len(words),
        quote_sha256=quote_hash(words),
        actor=Role(chat.messages[native].role),
    )


@pytest.fixture
def setup(tmp_path: Path) -> Iterator[Setup]:
    settings = Settings(workspace_root=tmp_path / "ws")
    run_import(_export(tmp_path / "v1", revised=False), "acct", format_id=None, settings=settings)
    engine = create_sqlite_engine(database_path(settings))
    with Session(engine) as session:
        chats = dict(
            session.execute(
                select(ConversationRow.native_conversation_id, ConversationRow.conversation_id)
            )
            .tuples()
            .all()
        )
        registry = TaxonomyRegistry(session)
        garden = registry.add_term(Dimension.TOPIC, "Gardening", status=TermStatus.APPROVED)
        taxonomy = registry.publish("tax-1", author="test")
        splits, reviews, records = {}, {}, {}
        for native, conversation_id in chats.items():
            chat = load_conversation(session, conversation_id)
            # A person splits the chat where the shed question starts...
            row = record_override(session, chat, "u2", Action.SPLIT, reviewer="test")
            splits[native] = str(row.override_id)
            # ...labels both parts...
            for segment in load_segments(session, chat):
                review_row = record_review(
                    session,
                    taxonomy,
                    segment.segment_id,
                    "topic",
                    primary=garden.term_id,
                    reviewer="test",
                    conversation_id=conversation_id,
                )
                reviews[(native, segment.messages[0])] = str(review_row.review_id)
            # ...and confirms a record taken from the shed question.
            [stored] = add_candidates(
                session,
                [
                    CandidateRecord(
                        record_type=RecordType.FACT,
                        assertion=f"The user asked about paint ({native}).",
                        actor=Role.USER,
                        scope=Scope.CONVERSATION,
                        scope_id=conversation_id,
                        evidence=(_evidence(chat, "u2"),),
                    )
                ],
                Provenance(
                    stage_id="extract.test.v1", stage_key="stg_" + "c" * 64, extractor_version="t"
                ),
            )
            gate(session, stored.record_id)
            decide(session, stored.record_id, Decision.CONFIRM, reviewer="test")
            records[native] = stored.record_id
        x = load_conversation(session, chats["c-imp-x"])
        relationships = {}
        for name, evidence in (("cited", {"revisions": [x.revisions["u2"]]}), ("bare", {})):
            detector = f"test-{name}-v1"
            propose(
                session,
                from_conversation_id=chats["c-imp-x"],
                kind=RelationKind.RELATED_TO,
                to_conversation_id=chats["c-imp-y"],
                evidence_class=EvidenceClass.HUMAN,
                confidence=1.0,
                detector=detector,
                evidence=evidence,
                import_id=None,
            )
            rel = session.scalars(
                select(ConversationRelationshipRow).where(
                    ConversationRelationshipRow.detector == detector
                )
            ).one()
            review(session, rel.relationship_id, ReviewAction.ACCEPT, reviewer="test")
            relationships[name] = rel.relationship_id
        session.commit()
    engine.dispose()
    yield Setup(settings, tmp_path, chats, splits, reviews, records, relationships)


def _states(session: Session) -> dict[tuple[OverrideKind, str], Any]:
    return {(c.kind, c.override_ref): c for c in check_overrides(session)}


def test_everything_stands_before_any_change(setup: Setup) -> None:
    with Session(create_sqlite_engine(database_path(setup.settings))) as session:
        states = _states(session)
    assert len(states) == 2 + 4 + 2 + 2
    unanchored = {k for k, c in states.items() if c.state is OverrideState.UNANCHORED}
    assert unanchored == {(OverrideKind.RELATIONSHIP, setup.relationships["bare"])}
    assert all(c.state is OverrideState.KEPT for k, c in states.items() if k not in unanchored)


def test_revised_words_flag_their_corrections_with_both_revisions(setup: Setup) -> None:
    engine = create_sqlite_engine(database_path(setup.settings))
    with Session(engine) as session:
        x_before = load_conversation(session, setup.chats["c-imp-x"])
    report = run_import(
        _export(setup.tmp / "v2", revised=True), "acct", format_id=None, settings=setup.settings
    )
    assert report.messages.get("revised") == 1
    assert report.to_dict()["corrections"] == {"kept": 5, "review_required": 4, "unanchored": 1}
    with Session(engine) as session:
        x_now = load_conversation(session, setup.chats["c-imp-x"])
        states = _states(session)
        flagged = {k for k, c in states.items() if c.state is OverrideState.REVIEW_REQUIRED}
        assert flagged == {
            (OverrideKind.SEGMENT, setup.splits["c-imp-x"]),
            (OverrideKind.CLASSIFICATION, setup.reviews[("c-imp-x", "u2")]),
            (OverrideKind.RECORD, setup.records["c-imp-x"]),
            (OverrideKind.RELATIONSHIP, setup.relationships["cited"]),
        }
        for key in flagged:
            [change] = states[key].changes
            # Both versions are named, so a reviewer can compare them.
            assert change.node_key == x_now.node_keys["u2"]
            assert change.decided_on == x_before.revisions["u2"]
            assert change.now == x_now.revisions["u2"] != change.decided_on
        # Untouched words keep their corrections, still in force.
        kept = {k for k, c in states.items() if c.state is OverrideState.KEPT}
        assert (OverrideKind.SEGMENT, setup.splits["c-imp-y"]) in kept
        assert (OverrideKind.CLASSIFICATION, setup.reviews[("c-imp-x", "u1")]) in kept
        taxonomy = TaxonomyRegistry(session).snapshot("tax-1")
        first, second = load_segments(session, x_now)
        assert second.messages[0] == "u2"  # the split still applies, though flagged
        assert effective_labels(session, first.segment_id, taxonomy)["topic"].source == "review"
        # The revised part's old review isn't silently carried over.
        assert effective_labels(session, second.segment_id, taxonomy)["topic"].source == "none"
        with pytest.raises(DatabaseError, match="append-only"):
            session.execute(text("DELETE FROM override_anchors"))
        session.rollback()
    # Importing the same export again changes nothing.
    again = run_import(
        _export(setup.tmp / "v2-again", revised=True),
        "acct",
        format_id=None,
        settings=setup.settings,
    )
    assert again.messages.get("revised", 0) == 0
    engine.dispose()


def test_cli_corrections(
    setup: Setup, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from knowledge_engine.cli.main import main

    run_import(
        _export(setup.tmp / "v2", revised=True), "acct", format_id=None, settings=setup.settings
    )
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(setup.settings.workspace_root))
    assert main(["--json", "corrections"]) == 0
    data = json.loads(capsys.readouterr().out)["data"]
    assert data["counts"] == {"kept": 5, "review_required": 4, "unanchored": 1}
    assert {f["kind"] for f in data["review_required"]} == {k.value for k in OverrideKind}
    assert all(len(f["changes"]) == 1 for f in data["review_required"])
