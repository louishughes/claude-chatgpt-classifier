"""NOTE-001: the rich conversation note (template v2), on a synthetic export.

The chats are made up here; the knowledge records come from the real rule
extractors (EXT-003..006), so the note is checked against what the engine
actually stores, not against hand-made records.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.classification.store import record_review
from knowledge_engine.documents.rich_note import (
    BUDGET_MAX,
    body_budget,
    body_of,
    meta_path,
    rich_conversation_note,
    write_rich_note,
)
from knowledge_engine.extraction import actions, decisions, entities, preferences
from knowledge_engine.extraction.runner import RuleExtractor, run
from knowledge_engine.extraction.text import segment_extraction_messages
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.importer.run import run_import
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.relationships.store import EvidenceClass, RelationKind, propose
from knowledge_engine.rendering.markdown import Callout, render_note
from knowledge_engine.rendering.transcript import load_conversation, write_transcript
from knowledge_engine.segmentation.overrides import load_segments
from knowledge_engine.settings import Settings
from knowledge_engine.taxonomy.registry import (
    Dimension,
    TaxonomyRegistry,
    TaxonomySnapshot,
    TermStatus,
)

PROPOSAL = "I suggest cedar boards because they resist rot."
ACCEPT = "Yes, let's do that."
COMMIT = "I'll order the cedar boards tomorrow."
CODE = "Here is a planting helper:\n\n```python\nprint('water daily')\n```"


def _message(node: str, role: str, text: str, t: float) -> dict[str, Any]:
    return {
        "id": node,
        "author": {"role": role},
        "create_time": t,
        "content": {"content_type": "text", "parts": [text]},
        "metadata": {},
    }


def _chat(cid: str, title: str, nodes: list[tuple[str, str | None, str, str]]) -> Any:
    # nodes: (id, parent, role, text). The last node is the current one, so a
    # node listed earlier under the same parent becomes an alternate branch.
    mapping: dict[str, Any] = {
        "root": {"id": "root", "parent": None, "children": [], "message": None}
    }
    for i, (node, parent, role, text) in enumerate(nodes):
        mapping[node] = {
            "id": node,
            "parent": parent or "root",
            "children": [],
            "message": _message(node, role, text, 1704067200.0 + 60 * i),
        }
        mapping[parent or "root"]["children"].append(node)
    return {
        "id": cid,
        "title": title,
        "create_time": 1704067200.0,
        "mapping": mapping,
        "current_node": nodes[-1][0],
    }


def _export(root: Path) -> Path:
    garden = _chat(
        "c-garden",
        "Synthetic garden | beds",  # a pipe in the title must not break the card table
        [
            ("u1", None, "user", "Which wood should the raised bed use, cedar or pine?"),
            ("a1b", "u1", "assistant", "Pine is cheaper, an alternative reply."),
            ("a1", "u1", "assistant", PROPOSAL),
            ("u2", "a1", "user", f"{ACCEPT} {COMMIT}"),
            ("a2", "u2", "assistant", CODE),
        ],
    )
    shed = _chat(
        "c-shed",
        "Synthetic shed",
        [("u1", None, "user", "The shed roof leaks."), ("a1", "u1", "assistant", "Check it.")],
    )
    empty = _chat("c-empty", "Synthetic hello", [("u1", None, "user", "Hello there.")])
    root.mkdir(parents=True)
    (root / "conversations.json").write_text(json.dumps([garden, shed, empty]), encoding="utf-8")
    return root


@dataclass
class World:
    settings: Settings
    session: Session
    chats: dict[str, str]  # native ID -> conv_ ID
    taxonomy: TaxonomySnapshot


def _extract(session: Session) -> None:
    chats = [
        load_conversation(session, c)
        for c in session.scalars(select(ConversationRow.conversation_id))
    ]
    segments = [
        (seg.segment_id, segment_extraction_messages(chat, seg))
        for chat in chats
        for seg in load_segments(session, chat)
    ]
    revisions = [r for chat in chats for r in chat.revisions.values()]
    occurrences = actions.load_occurrences(session, revisions)
    extractors = [
        RuleExtractor("decisions", decisions.EXTRACTOR_VERSION, decisions.extract_decisions),
        RuleExtractor(
            "preferences", preferences.EXTRACTOR_VERSION, preferences.extract_preferences
        ),
        RuleExtractor(
            "actions",
            actions.EXTRACTOR_VERSION,
            partial(actions.extract_actions, occurrences=occurrences),
        ),
        RuleExtractor("entities", entities.EXTRACTOR_VERSION, entities.extract_entities),
    ]
    run(session, segments, extractors)


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    settings = Settings(workspace_root=tmp_path / "ws")
    run_import(_export(tmp_path / "export"), "acct", format_id=None, settings=settings)
    session = Session(create_sqlite_engine(database_path(settings)))
    chats = dict(
        session.execute(
            select(ConversationRow.native_conversation_id, ConversationRow.conversation_id)
        )
        .tuples()
        .all()
    )
    _extract(session)
    registry = TaxonomyRegistry(session)
    home = registry.add_term(Dimension.DOMAIN, "Home and garden", status=TermStatus.APPROVED)
    beds = registry.add_term(
        Dimension.DOMAIN, "Raised beds", status=TermStatus.APPROVED, parent_id=home.term_id
    )
    advice = registry.add_term(Dimension.PURPOSE, "Advice", status=TermStatus.APPROVED)
    wood = registry.add_term(Dimension.TOPIC, "Timber", status=TermStatus.APPROVED)
    taxonomy = registry.publish("tax-1", author="test")
    for segment in load_segments(session, load_conversation(session, chats["c-garden"])):
        for field, term in (("domain", beds), ("purpose", advice), ("topic", wood)):
            record_review(
                session, taxonomy, segment.segment_id, field, primary=term.term_id, reviewer="t"
            )
    propose(
        session,
        from_conversation_id=chats["c-shed"],
        kind=RelationKind.RELATED_TO,
        to_conversation_id=chats["c-garden"],
        evidence_class=EvidenceClass.SEMANTIC,
        confidence=0.5,
        detector="test-v1",
        evidence={},
        import_id=None,
    )
    session.commit()
    yield World(settings, session, chats, taxonomy)
    session.close()


def _headings(text: str) -> list[str]:
    return re.findall(r"^## (.+)$", text, flags=re.MULTILINE)


def _section(text: str, heading: str) -> str:
    return text.split(f"\n## {heading}\n", 1)[1].split("\n## ", 1)[0]


def test_readable_sections_come_first_in_a_fixed_order(world: World) -> None:
    note = rich_conversation_note(world.session, world.chats["c-garden"], taxonomy=world.taxonomy)
    text = render_note(note.model)
    body = body_of(text)
    # The summary box opens the note, before any heading.
    assert body.split("\n## ", 1)[0].count("> [!summary] Summary") == 1
    assert _headings(text) == [
        "Knowledge card",
        "Decisions",
        "Suggestions",
        "Action items",
        "Open questions",
        "Requirements and preferences",
        "Insights",
        "Tensions and trade-offs",
        "Next steps",
        "Category and subcategory",
        "Keywords and topics",
        "Related chats",
        "Branches",
        "Source",
    ]


def test_records_land_in_the_section_a_reader_expects(world: World) -> None:
    text = render_note(
        rich_conversation_note(
            world.session, world.chats["c-garden"], taxonomy=world.taxonomy
        ).model
    )
    decisions_part = _section(text, "Decisions")
    suggestions = _section(text, "Suggestions")
    action_items = _section(text, "Action items")
    # The assistant's suggestion is shown as a suggestion, never as a decision.
    assert "cedar boards because they resist rot" in suggestions
    assert "Suggested by the assistant" in suggestions
    # The user's "yes" turns it into a decision, cited to the reply and the
    # proposal it answers, in transcript order; the suggestion says so.
    [decided] = re.findall(r"^- .+$", decisions_part, flags=re.MULTILINE)
    assert "Decided" in decided and decided.index("|m2]]") < decided.index("|m3]]")
    assert "taken up (see Decisions)" in suggestions
    # The user's own commitment is an action item, cited to message 3.
    assert "order the cedar boards tomorrow" in action_items
    assert "|m3]]" in action_items


def test_citations_use_transcript_numbers_and_alt_off_the_path(world: World) -> None:
    session = world.session
    chat = load_conversation(session, world.chats["c-garden"])
    note = rich_conversation_note(session, chat.conversation_id, taxonomy=world.taxonomy)
    text = render_note(note.model)
    cited = re.findall(r"#\^([A-Za-z0-9-]+)\|(m\d+|alt)\]\]", text)
    assert cited
    for anchor, label in re.findall(r"#\^([A-Za-z0-9-]+)\|(m\d+|alt)\]\]", text):
        native = next(n for n, k in chat.node_keys.items() if k.replace("_", "-", 1) == anchor)
        number = chat.graph.message_number(native)
        assert label == (f"m{number}" if number is not None else "alt")


def test_evidence_is_folded_quoted_and_capped(world: World) -> None:
    note = rich_conversation_note(world.session, world.chats["c-garden"], taxonomy=world.taxonomy)
    boxes = [b for b in note.model.blocks if isinstance(b, Callout) and b.kind == "quote"]
    assert boxes, "items with evidence get an evidence box"
    for box in boxes:
        assert box.collapsed and box.title == "Evidence"
        assert 1 <= len(box.lines) <= 3  # at most two quotes plus "and N more"
        for line in box.lines:
            assert re.match(r"^(m\d+|alt|elsewhere)", line)
    text = render_note(note.model)
    assert "> [!quote]- Evidence" in text
    # No hashes or record IDs in the reader's way: they live in the sidecar.
    assert "krec_" not in text and "sha256" not in text


def test_empty_sections_are_one_sentence(world: World) -> None:
    note = rich_conversation_note(world.session, world.chats["c-empty"], taxonomy=world.taxonomy)
    text = render_note(note.model)
    assert "Nothing was decided in this chat." in _section(text, "Decisions")
    assert "> [!quote]" not in text
    for heading in ("Insights", "Tensions and trade-offs", "Next steps"):
        part = _section(text, heading)
        assert "Generated (check before relying on it)" in part
        assert "digest step hasn't run" in part
    assert "No segment is labelled under tax-1 yet." in _section(text, "Category and subcategory")
    assert "Branches" not in _headings(text)  # optional sections only appear with content


def test_card_and_front_matter_carry_the_rolled_up_labels(world: World) -> None:
    note = rich_conversation_note(world.session, world.chats["c-garden"], taxonomy=world.taxonomy)
    props = note.model.properties
    assert props["category"] == "Home and garden"
    assert props["subcategory"] == "Raised beds"
    assert props["activity"] == ["Advice"]
    assert props["tags"] == ["Timber"]
    assert props["taxonomy_version"] == "tax-1"
    assert props["generator"] == "note-001-v2"
    text = render_note(note.model)
    card = _section(text, "Knowledge card")
    assert "| **Category** | Home and garden › Raised beds |" in card
    assert "code block (python)" in card
    # Every card row has exactly the two cells: nothing inside split a row.
    rows = [line for line in card.splitlines() if line.startswith("| **")]
    assert rows and all(len(re.split(r"(?<!\\)\|", r)) == 4 for r in rows)
    untagged = rich_conversation_note(world.session, world.chats["c-garden"], taxonomy=None)
    assert untagged.model.properties["category"] == "unclassified"


def test_related_chats_link_to_the_other_knowledge_note(world: World) -> None:
    note = rich_conversation_note(world.session, world.chats["c-garden"], taxonomy=world.taxonomy)
    related = [str(r) for r in note.model.properties["related"]]  # type: ignore[union-attr]
    assert any(r.startswith("[[Synthetic shed knowledge (conv-") for r in related), related
    assert all(" knowledge (conv-" in r for r in related)  # always the other knowledge note
    text = render_note(note.model)
    assert "related to" in _section(text, "Related chats")


def test_notes_stay_within_budget(world: World) -> None:
    for native, conversation_id in world.chats.items():
        note = rich_conversation_note(world.session, conversation_id, taxonomy=world.taxonomy)
        messages = int(note.model.properties["messages"])  # type: ignore[arg-type]
        assert len(body_of(render_note(note.model))) <= body_budget(messages), native
    assert body_budget(10_000) == BUDGET_MAX


def test_written_vault_resolves_every_link_and_writes_the_sidecar(
    world: World, tmp_path: Path
) -> None:
    session, vault = world.session, tmp_path / "vault"
    store = world.settings.workspace_root / "archive"
    for conversation_id in world.chats.values():
        write_transcript(session, load_conversation(session, conversation_id), vault, store)
        write_rich_note(session, conversation_id, vault, store, taxonomy=world.taxonomy)
    garden = world.chats["c-garden"]
    title = session.get_one(ConversationRow, garden).title
    [path] = [p for p in (vault / "Knowledge").glob("*.md") if "garden" in p.name]
    text = path.read_text(encoding="utf-8")
    for note, anchor in re.findall(r"\[\[([^#\]|]+)#\^([A-Za-z0-9-]+)(?:\|[^\]]*)?\]\]", text):
        [found] = list(vault.glob(f"Sources/{note}.md"))
        assert f"^{anchor}" in found.read_text(encoding="utf-8")
    for note in re.findall(r"(?<!!)\[\[([^#\]|]+)\]\]", text):
        assert list(vault.glob(f"*/{note}.md")), note
    meta = json.loads((vault / meta_path(garden, title)).read_text(encoding="utf-8"))
    assert meta["conversation_id"] == garden and meta["record_ids"]
    assert all(r.startswith("krec_") for r in meta["record_ids"])
    # Writing again changes nothing.
    write_rich_note(session, garden, vault, store, taxonomy=world.taxonomy)
    assert path.read_text(encoding="utf-8") == text


def test_cli_template_v2_prints_no_title_and_no_ellipsis(
    world: World,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    from knowledge_engine.cli.main import main

    world.session.close()
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(world.settings.workspace_root))
    vault = tmp_path / "vault"
    args = ["--json", "docs", "chat", "c-garden", "--vault", str(vault), "--taxonomy", "tax-1"]
    assert main([*args, "--template", "v2"]) == 0
    out = capsys.readouterr().out
    shown = json.loads(out)["data"]["note"]
    assert "garden" not in out.lower()  # the private title isn't printed
    assert shown.isascii() and shown.startswith("Knowledge/... (conv-")
    [note] = list((vault / "Knowledge").glob("*.md"))
    assert "generator: note-001-v2" in note.read_text(encoding="utf-8")
