"""DOC-003 conversation notes and DOC-005 topic masters, on a synthetic export."""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.classification.store import record_review
from knowledge_engine.documents.notes import (
    TopicNotFound,
    conversation_note,
    related_conversations,
    resolve_topic,
    topic_master,
    write_conversation_note,
)
from knowledge_engine.documents.render import evidence_blocks, source_links
from knowledge_engine.domain.enums import Role
from knowledge_engine.domain.models import EvidenceRef
from knowledge_engine.extraction.records import CandidateRecord, Provenance, RecordType, Scope
from knowledge_engine.extraction.store import add_candidates
from knowledge_engine.graph.offsets import quote_hash
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.importer.run import run_import
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.relationships.store import (
    EvidenceClass,
    RelationKind,
    ReviewAction,
    propose,
    review,
)
from knowledge_engine.rendering.markdown import render_note
from knowledge_engine.rendering.media import check_embeds
from knowledge_engine.rendering.transcript import load_conversation, write_transcript
from knowledge_engine.segmentation.overrides import load_segments
from knowledge_engine.settings import Settings
from knowledge_engine.taxonomy.registry import (
    Dimension,
    TaxonomyRegistry,
    TaxonomySnapshot,
    TermStatus,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt"
PNG = FIXTURES / "repeated_image" / "export" / "images" / "file-SYN0001-synthetic.png"
BAKE = "We will bake sourdough on Sundays."
PARSER = "Use Python for the parser."


def _message(node: str, role: str, parts: list[Any], t: float) -> dict[str, Any]:
    kind = "multimodal_text" if any(isinstance(p, dict) for p in parts) else "text"
    return {
        "id": node,
        "author": {"role": role},
        "create_time": t,
        "content": {"content_type": kind, "parts": parts},
        "metadata": {},
    }


def _chat(cid: str, title: str, nodes: list[tuple[str, str | None, str, list[Any]]]) -> Any:
    # nodes: (id, parent, role, parts); children are derived from parents.
    mapping: dict[str, Any] = {
        "root": {"id": "root", "parent": None, "children": [], "message": None}
    }
    for i, (node, parent, role, parts) in enumerate(nodes):
        mapping[node] = {
            "id": node,
            "parent": parent or "root",
            "children": [],
            "message": _message(node, role, parts, 1704067200.0 + 60 * i),
        }
        mapping[parent or "root"]["children"].append(node)
    current = nodes[-1][0]
    return {
        "id": cid,
        "title": title,
        "create_time": 1704067200.0,
        "mapping": mapping,
        "current_node": current,
    }


def _image(pointer: str) -> dict[str, Any]:
    return {"content_type": "image_asset_pointer", "asset_pointer": pointer, "size_bytes": 0}


def _export(root: Path) -> Path:
    recipe = _chat(
        "c-recipe",
        "Synthetic baking",
        [
            (
                "u1",
                None,
                "user",
                [
                    _image("file-service://file-SYN0101"),
                    f"{BAKE} See https://youtu.be/aBcDeFgHiJk?t=30 and "
                    "https://github.com/Synth-Octo",
                ],
            ),
            ("a1b", "u1", "assistant", ["An alternative synthetic reply."]),
            ("a1", "u1", "assistant", ["Sounds good."]),
            ("u2", "a1", "user", [_image("file-service://file-GONE0001"), "Another photo."]),
        ],
    )
    code = _chat(
        "c-code",
        "Synthetic parser",
        [
            ("u1", None, "user", [PARSER]),
            ("a1", "u1", "assistant", ["Fine, Python it is."]),
        ],
    )
    other = _chat("c-other", "Synthetic other", [("u1", None, "user", ["Nothing here."])])
    (root / "images").mkdir(parents=True)
    shutil.copy(PNG, root / "images" / "file-SYN0101-synthetic.png")
    (root / "conversations.json").write_text(json.dumps([recipe, code, other]), encoding="utf-8")
    return root


@dataclass
class World:
    settings: Settings
    session: Session
    chats: dict[str, str]  # native ID -> conv_ ID
    taxonomy: TaxonomySnapshot
    terms: dict[str, str]  # label -> term ID
    records: dict[str, str]  # text -> krec_ ID


def _evidence(session: Session, conversation_id: str, native: str, text: str) -> EvidenceRef:
    chat = load_conversation(session, conversation_id)
    revision = chat.revisions[native]
    message = chat.messages[native]
    start = (message.text or "").index(text)
    return EvidenceRef(
        revision_id=revision,
        start=start,
        end=start + len(text),
        quote_sha256=quote_hash(text),
        actor=Role(message.role),
    )


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
    registry = TaxonomyRegistry(session)
    recipes = registry.add_term(Dimension.TOPIC, "Recipes", status=TermStatus.APPROVED)
    registry.add_alias(recipes, "cooking")
    registry.add_alias(recipes, "food")
    programming = registry.add_term(Dimension.TOPIC, "Programming", status=TermStatus.APPROVED)
    snacks = registry.add_term(Dimension.DOMAIN, "Snacks", status=TermStatus.APPROVED)
    registry.add_alias(snacks, "food")  # "food" now names two terms
    taxonomy = registry.publish("tax-1", author="test")
    terms = {"Recipes": recipes.term_id, "Programming": programming.term_id}
    provenance = Provenance(
        stage_id="extract.test.v1", stage_key="stg_" + "f" * 64, extractor_version="t"
    )
    stored = add_candidates(
        session,
        [
            CandidateRecord(
                record_type=RecordType.FACT,
                assertion="The user bakes sourdough on Sundays.",
                actor=Role.USER,
                term_ids=(recipes.term_id,),
                scope=Scope.CONVERSATION,
                scope_id=chats["c-recipe"],
                evidence=(_evidence(session, chats["c-recipe"], "u1", BAKE),),
            ),
            CandidateRecord(
                record_type=RecordType.FACT,
                assertion="The parser is written in Python.",
                actor=Role.USER,
                term_ids=(programming.term_id,),
                scope=Scope.CONVERSATION,
                scope_id=chats["c-code"],
                evidence=(_evidence(session, chats["c-code"], "u1", PARSER),),
            ),
        ],
        provenance,
    )
    records = {BAKE: stored[0].record_id, PARSER: stored[1].record_id}
    for native, term in (("c-recipe", recipes.term_id), ("c-code", programming.term_id)):
        chat = load_conversation(session, chats[native])
        for segment in load_segments(session, chat):
            record_review(
                session, taxonomy, segment.segment_id, "topic", primary=term, reviewer="test"
            )
    propose(
        session,
        from_conversation_id=chats["c-code"],
        kind=RelationKind.RELATED_TO,
        to_conversation_id=chats["c-recipe"],
        evidence_class=EvidenceClass.SEMANTIC,
        confidence=0.4,
        detector="test-v1",
        evidence={},
        import_id=None,
    )
    propose(
        session,
        from_conversation_id=chats["c-other"],
        kind=RelationKind.CONTINUES,
        to_conversation_id=chats["c-recipe"],
        evidence_class=EvidenceClass.LEXICAL,
        confidence=0.9,
        detector="test-v1",
        evidence={},
        import_id=None,
    )
    rejected = next(
        r for r in related_conversations(session, chats["c-recipe"]) if r.kind == "continues"
    )
    review(session, rejected.relationship_id, ReviewAction.REJECT, reviewer="test")
    session.commit()
    yield World(settings, session, chats, taxonomy, terms, records)
    session.close()


def _section(text: str, heading: str) -> str:
    return text.split(f"\n## {heading}\n", 1)[1].split("\n## ", 1)[0]


def test_conversation_note_shows_everything_the_chat_holds(world: World) -> None:
    session, recipe = world.session, world.chats["c-recipe"]
    note = conversation_note(session, recipe, taxonomy=world.taxonomy)
    text = render_note(note.model)
    headings = re.findall(r"^## (.+)$", text, flags=re.MULTILINE)
    assert headings == [
        "Summary",
        "Classification",
        "Knowledge",
        "Branches",
        "Images",
        "Links",
        "Videos",
        "Accounts",
        "Related conversations",
    ]
    assert "2 image(s) (1 not available), 2 link(s)" in _section(text, "Summary")
    assert f"topic: Recipes (`{world.terms['Recipes']}`) (review)" in _section(
        text, "Classification"
    )
    knowledge = _section(text, "Knowledge")
    assert "The user bakes sourdough on Sundays." in knowledge
    # The exact words, who said them, and a link to the message.
    assert re.search(
        rf"^> {re.escape(BAKE)} \(said by \*\*user\*\*, \[\[.+#\^node-",
        knowledge,
        flags=re.MULTILINE,
    )
    assert "Python" not in knowledge  # another chat's record stays out
    [branch] = _section(text, "Branches").strip().splitlines()
    assert branch.startswith("- regeneration: 1 message(s)") and "branching off after" in branch
    images = _section(text, "Images")
    assert images.count("![[_attachments/") == 1
    assert "[!warning] Image missing: file-service://file-GONE0001" in images
    assert "youtu.be/aBcDeFgHiJk?t=30` (by user" in _section(text, "Links")
    assert "YouTube `aBcDeFgHiJk`, at 30s (by user" in _section(text, "Videos")
    assert "github `" in _section(text, "Accounts").lower()
    related = _section(text, "Related conversations")
    assert "**related_to** this chat (semantic, confidence 0.40, candidate" in related
    assert "**continues**" not in related  # rejected links are left out


def test_evidence_that_no_longer_holds_is_not_quoted(world: World) -> None:
    session = world.session
    good = _evidence(session, world.chats["c-recipe"], "u1", BAKE)
    links = source_links(session, [good.revision_id])
    wrong_speaker = good.model_copy(update={"actor": Role.ASSISTANT})
    wrong_words = good.model_copy(update={"quote_sha256": "0" * 64})
    blocks = evidence_blocks(session, (good, wrong_speaker, wrong_words), links)
    texts = [b.text for b in blocks]  # type: ignore[union-attr]
    assert texts[0].startswith(f"> {BAKE} (said by **user**")
    assert texts[1].startswith("> Evidence not shown: actor_mismatch")
    assert texts[2].startswith("> Evidence not shown: quote_mismatch")


def test_written_notes_resolve_every_embed_and_link(world: World, tmp_path: Path) -> None:
    session, vault = world.session, tmp_path / "vault"
    store = world.settings.workspace_root / "archive"
    for conversation_id in world.chats.values():
        write_transcript(session, load_conversation(session, conversation_id), vault, store)
    path = write_conversation_note(
        session, world.chats["c-recipe"], vault, store, taxonomy=world.taxonomy
    )
    text = (vault / path).read_text(encoding="utf-8")
    assert path.parts[0] == "Knowledge"
    assert check_embeds(vault, text) == []
    for note, anchor in re.findall(r"\[\[([^#\]|]+)#\^([A-Za-z0-9-]+)\]\]", text):
        if note.startswith("_"):
            continue
        [found] = list(vault.glob(f"Sources/{note}.md"))
        assert f"^{anchor}" in found.read_text(encoding="utf-8")
    for note in re.findall(r"(?<!!)\[\[([^#\]|]+)\]\]", text):
        assert list(vault.glob(f"Sources/{note}.md")), note
    again = write_conversation_note(
        session, world.chats["c-recipe"], vault, store, taxonomy=world.taxonomy
    )
    assert again == path and (vault / path).read_text(encoding="utf-8") == text


def test_topic_is_chosen_by_canonical_term_never_guessed(world: World) -> None:
    recipes = world.terms["Recipes"]
    assert resolve_topic(world.taxonomy, recipes) == recipes
    assert resolve_topic(world.taxonomy, "Cooking") == recipes
    with pytest.raises(TopicNotFound, match="several terms"):
        resolve_topic(world.taxonomy, "food")
    with pytest.raises(TopicNotFound, match="no approved term"):
        resolve_topic(world.taxonomy, "sourdough")


def test_topic_master_filters_out_unrelated_sources(world: World) -> None:
    session = world.session
    text = render_note(topic_master(session, "cooking", world.taxonomy))
    assert "The user bakes sourdough on Sundays." in text
    assert f"^> {BAKE}" not in text and f"> {BAKE} (said by **user**" in text
    # The programming chat's record, segments and source never appear.
    assert "Python" not in text and world.records[PARSER] not in text
    code_id, recipe_id = world.chats["c-code"], world.chats["c-recipe"]
    assert code_id not in text and recipe_id in text
    assert "labelled in topic" in _section(text, "Conversations on this topic")
    other = render_note(topic_master(session, "Programming", world.taxonomy))
    assert "sourdough" not in other and recipe_id not in other
    # A reviewer removing the label removes the segment, not the tagged record.
    chat = load_conversation(session, recipe_id)
    for segment in load_segments(session, chat):
        record_review(
            session, world.taxonomy, segment.segment_id, "topic", primary=None, reviewer="test"
        )
    session.commit()
    after = render_note(topic_master(session, "cooking", world.taxonomy))
    assert "no segment is labelled with this topic" in after
    assert "The user bakes sourdough on Sundays." in after


def test_cli_docs_chat_and_topic(
    world: World,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    tmp_path: Path,
) -> None:
    from knowledge_engine.cli.main import main

    world.session.close()
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(world.settings.workspace_root))
    vault = tmp_path / "vault"
    assert (
        main(["--json", "docs", "chat", "c-recipe", "--vault", str(vault), "--taxonomy", "tax-1"])
        == 0
    )
    out = capsys.readouterr().out
    assert "Synthetic baking" not in out  # the private title isn't printed
    [note] = list((vault / "Knowledge").glob("*.md"))
    assert "## Related conversations" in note.read_text(encoding="utf-8")
    assert (
        main(["--json", "docs", "topic", "cooking", "--vault", str(vault), "--taxonomy", "tax-1"])
        == 0
    )
    written = json.loads(capsys.readouterr().out)["data"]["note"]
    assert written.startswith("Topics/") and (vault / written).is_file()
    assert (
        main(["--json", "docs", "topic", "food", "--vault", str(vault), "--taxonomy", "tax-1"]) == 2
    )
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "no_topic"
    assert main(["--json", "docs", "topic", "cooking", "--vault", str(vault)]) == 2
    capsys.readouterr()
