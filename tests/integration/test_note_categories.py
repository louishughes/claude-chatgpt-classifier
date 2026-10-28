"""NOTE-008: a two-subject chat's note shows both categories, the larger as primary.

Synthetic chat: four messages (user turns over 40 characters, so each
starts an exchange) about a raised bed, a seven-hour pause (so
the segmenter starts a new segment), then two about soup. The keyword
classifier labels each segment; a reviewer then agrees with one.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.classification.classifier import SegmentClassifier
from knowledge_engine.classification.store import record_review, save
from knowledge_engine.documents.categories import (
    PRIMARY,
    SECONDARY,
    category_shares,
    waiting_candidates,
)
from knowledge_engine.documents.rich_note import rich_conversation_note
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.importer.run import run_import
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.rendering.markdown import render_note
from knowledge_engine.rendering.transcript import StoredConversation, load_conversation
from knowledge_engine.segmentation.overrides import load_segments
from knowledge_engine.settings import Settings
from knowledge_engine.taxonomy.registry import (
    Dimension,
    TaxonomyRegistry,
    TaxonomySnapshot,
    TermStatus,
)
from knowledge_engine.taxonomy.review import Operation, propose

T0 = 1704067200.0
HOUR = 3600.0


def _export(root: Path) -> Path:
    nodes = [
        ("u1", "user", "How deep should a raised bed be for vegetables?", T0),
        ("a1", "assistant", "A raised bed works well at 30 cm deep.", T0 + 60),
        ("u2", "user", "Should the raised bed have a liner underneath it?", T0 + 120),
        ("a2", "assistant", "Yes, line the raised bed with fabric.", T0 + 180),
        ("u3", "user", "Different thing: what is a good soup for a cold winter?", T0 + 7 * HOUR),
        ("a3", "assistant", "Try a lentil soup with cumin.", T0 + 7 * HOUR + 60),
    ]
    mapping: dict[str, Any] = {
        "root": {"id": "root", "parent": None, "children": [], "message": None}
    }
    parent = "root"
    for node, role, text, t in nodes:
        mapping[node] = {
            "id": node,
            "parent": parent,
            "children": [],
            "message": {
                "id": node,
                "author": {"role": role},
                "create_time": t,
                "content": {"content_type": "text", "parts": [text]},
                "metadata": {},
            },
        }
        mapping[parent]["children"].append(node)
        parent = node
    chat = {
        "id": "c-mixed",
        "title": "Synthetic mixed chat",
        "create_time": T0,
        "mapping": mapping,
        "current_node": parent,
    }
    root.mkdir(parents=True)
    (root / "conversations.json").write_text(json.dumps([chat]), encoding="utf-8")
    return root


@dataclass
class World:
    session: Session
    chat: StoredConversation
    taxonomy: TaxonomySnapshot
    terms: dict[str, str]


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    settings = Settings(workspace_root=tmp_path / "ws")
    run_import(_export(tmp_path / "export"), "acct", format_id=None, settings=settings)
    session = Session(create_sqlite_engine(database_path(settings)))
    [cid] = session.scalars(select(ConversationRow.conversation_id)).all()
    registry = TaxonomyRegistry(session)
    home = registry.add_term(Dimension.DOMAIN, "Home and garden", status=TermStatus.APPROVED)
    beds = registry.add_term(
        Dimension.DOMAIN,
        "Raised beds",
        status=TermStatus.APPROVED,
        parent_id=home.term_id,
    )
    registry.add_alias(beds, "raised bed")
    food = registry.add_term(Dimension.DOMAIN, "Cooking", status=TermStatus.APPROVED)
    registry.add_alias(food, "soup")
    taxonomy = registry.publish("tax-1", author="test")
    chat = load_conversation(session, cid)
    session.commit()
    yield World(session, chat, taxonomy, {"beds": beds.term_id, "food": food.term_id})
    session.close()


def _classify(world: World) -> None:
    segments = load_segments(world.session, world.chat)
    assert len(segments) == 2, "the pause should start a second segment"
    save(
        world.session,
        SegmentClassifier(world.taxonomy).classify([(world.chat, s) for s in segments]),
    )


def test_two_subjects_larger_is_primary_and_both_show(world: World) -> None:
    _classify(world)
    segments = load_segments(world.session, world.chat)
    # The second segment's classifier answer is overruled to Cooking by a reviewer.
    record_review(
        world.session,
        world.taxonomy,
        segments[1].segment_id,
        Dimension.DOMAIN.value,
        primary=world.terms["food"],
        reviewer="test",
    )
    shares = category_shares(world.session, world.chat, world.taxonomy)

    assert [(s.term_id, s.rank) for s in shares[:2]] == [
        (world.terms["beds"], PRIMARY),
        (world.terms["food"], SECONDARY),
    ]
    assert shares[0].share == pytest.approx(4 / 6) and shares[1].share == pytest.approx(2 / 6)
    assert shares[0].label == "Home and garden › Raised beds"
    assert shares[0].evidence  # the classifier's cited messages
    assert "not reviewed" in shares[0].verdicts[0]

    note = rich_conversation_note(
        world.session, world.chat.conversation_id, taxonomy=world.taxonomy
    )
    text = render_note(note.model)
    part = text.split("\n## Category and subcategory\n", 1)[1].split("\n## ", 1)[0]
    assert "*Classification under tax-1*" in part
    lines = [line for line in part.splitlines() if line.startswith("- **")]
    assert lines[1].startswith("- **Home and garden › Raised beds**, primary, 67% of labelled")
    assert lines[2].startswith("- **Cooking**, secondary, 33% of labelled")
    assert "|m1]]" in lines[1]  # cited to the transcript's numbering


def test_waiting_candidates_are_shown_as_candidates_not_labels(world: World) -> None:
    _classify(world)
    [first, _] = load_segments(world.session, world.chat)
    propose(
        world.session,
        Operation.ADD,
        {"dimension": "domain", "label": "Soil science"},
        proposer="test",
        evidence={"segments": [first.segment_id]},
    )
    propose(
        world.session,
        Operation.ADD,
        {"dimension": "domain", "label": "Unrelated"},
        proposer="test",
        evidence={"segments": ["seg_elsewhere"]},
    )
    assert waiting_candidates(world.session, world.chat) == ["Soil science"]
    note = rich_conversation_note(
        world.session, world.chat.conversation_id, taxonomy=world.taxonomy
    )
    text = render_note(note.model)
    assert 'Candidates waiting for review (not labels): "Soil science".' in text
    assert note.model.properties["category"] == "Home and garden"  # a candidate is never a label
