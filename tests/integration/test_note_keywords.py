"""NOTE-021: the rich note shows NOTE-007's keyword candidates, cited, never as tags.

Two synthetic chats, so "rare across the corpus" means something; the
digest comes from ``FakeProvider`` through the NOTE-003 stage, with one
topic that names an approved term and one that names nothing.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.cli.main import main
from knowledge_engine.digest.contract import ConversationDigest
from knowledge_engine.digest.stage import DigestStage
from knowledge_engine.documents.keywords import workspace_keywords
from knowledge_engine.documents.rich_note import rich_conversation_note
from knowledge_engine.evaluation.end_to_end import check_vault
from knowledge_engine.evaluation.note_checks import check_note
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.importer.run import run_import
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.providers.base import FakeProvider, ModelRequest
from knowledge_engine.providers.ledger import ModelStageRunner
from knowledge_engine.rendering.markdown import render_note
from knowledge_engine.rendering.transcript import load_conversation, write_transcript
from knowledge_engine.settings import EgressPolicy, Settings
from knowledge_engine.taxonomy.registry import (
    Dimension,
    TaxonomyRegistry,
    TaxonomySnapshot,
    TermStatus,
)

_TAG = re.compile(r"^\[m:([^\]]+)\] (\w+):\n(.+)$", re.M)


def _chat(cid: str, title: str, texts: list[tuple[str, str]]) -> dict[str, Any]:
    mapping: dict[str, Any] = {
        "root": {"id": "root", "parent": None, "children": [], "message": None}
    }
    parent = "root"
    for i, (role, text) in enumerate(texts):
        node = f"{cid}-{i}"
        mapping[node] = {
            "id": node,
            "parent": parent,
            "children": [],
            "message": {
                "id": node,
                "author": {"role": role},
                "create_time": 1704067200.0 + 60 * i,
                "content": {"content_type": "text", "parts": [text]},
                "metadata": {},
            },
        }
        mapping[parent]["children"].append(node)
        parent = node
    return {
        "id": cid,
        "title": title,
        "create_time": 1704067200.0,
        "mapping": mapping,
        "current_node": parent,
    }


def _export(root: Path) -> Path:
    garden = _chat(
        "c-garden",
        "Synthetic raised bed",
        [
            ("user", "Which timber suits a raised bed, cedar or pine?"),
            ("assistant", "Cedar resists rot, so cedar boards last longer than pine boards."),
            ("user", "Cedar boards it is. How deep should the cedar bed be?"),
            ("assistant", "Make the cedar bed thirty centimetres deep for most vegetables."),
        ],
    )
    shed = _chat(
        "c-shed",
        "Synthetic shed roof",
        [
            ("user", "The shed roof leaks after rain."),
            ("assistant", "Replace the felt on the shed roof and seal the edges."),
        ],
    )
    root.mkdir(parents=True)
    (root / "conversations.json").write_text(json.dumps([garden, shed]), encoding="utf-8")
    return root


def _digest_answer(request: ModelRequest) -> dict[str, Any]:
    tags = _TAG.findall(request.input_text)
    first_id, _, first_text = tags[0]
    start = [{"message_id": first_id, "text": " ".join(first_text.split()[:3])}]
    return {
        "summary": [{"text": "The user asked about a raised bed.", "quotes": start}],
        "purpose": {"text": "Pick a wood for a raised bed.", "quotes": start},
        "status": {"value": "settled", "quotes": start},
        "intent": {"value": "decide", "text": "Choose a wood.", "quotes": start},
        "topics": [
            {"text": "Timber", "quotes": start},
            {"text": "Soil drainage", "quotes": start},
        ],
    }


@dataclass
class World:
    settings: Settings
    session: Session
    garden: str
    digest: ConversationDigest
    taxonomy: TaxonomySnapshot


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[World]:
    settings = Settings(workspace_root=tmp_path / "ws")
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(settings.workspace_root))
    run_import(_export(tmp_path / "export"), "acct", format_id=None, settings=settings)
    session = Session(create_sqlite_engine(database_path(settings)))
    ids = dict(
        session.execute(
            select(ConversationRow.native_conversation_id, ConversationRow.conversation_id)
        )
        .tuples()
        .all()
    )
    registry = TaxonomyRegistry(session)
    registry.add_term(Dimension.TOPIC, "Timber", status=TermStatus.APPROVED)
    taxonomy = registry.publish("tax-1", author="test")
    runner = ModelStageRunner(session, FakeProvider(_digest_answer), EgressPolicy(text_llm=True))
    outcome = DigestStage(runner).run(load_conversation(session, ids["c-garden"]))
    assert outcome.state == "done" and outcome.digest is not None
    session.commit()
    yield World(settings, session, ids["c-garden"], outcome.digest, taxonomy)
    session.close()


def _section(text: str, heading: str) -> str:
    return text.split(f"\n## {heading}\n", 1)[1].split("\n## ", 1)[0]


def _note(world: World) -> str:
    keywords = workspace_keywords(
        world.session,
        taxonomy=world.taxonomy,
        topics={world.garden: [t.text for t in world.digest.topics]},
    )
    note = rich_conversation_note(
        world.session,
        world.garden,
        taxonomy=world.taxonomy,
        digest=world.digest,
        keywords=keywords[world.garden],
    )
    return render_note(note.model)


def test_keywords_are_shown_and_cited_to_messages_that_say_them(world: World) -> None:
    text = _note(world)
    section = _section(text, "Keywords and topics")
    [line] = [x for x in section.splitlines() if x.startswith("- Keywords: ")]
    # "cedar" is said in this chat and not in the other one, so it is suggested,
    # cited to the first message that says it. Keywords from the same message
    # share one citation (as topics do, NOTE-026): find cedar's group.
    groups = line.removeprefix("- Keywords: ").split("; ")
    [group] = [g for g in groups if "cedar" in g.split(" [[")[0].casefold().split(", ")]
    match = re.search(r"\[\[[^\]|]+\|(m\d+)\]\]$", group)
    assert match, line
    chat = load_conversation(world.session, world.garden)
    number = int(match.group(1)[1:])
    [native] = [n for n in chat.graph.active_messages if chat.graph.message_number(n) == number]
    assert "cedar" in chat.messages[native].text.casefold()
    # The shed chat's words aren't this chat's keywords.
    assert "shed" not in line.casefold()
    # Every citation in the note is still a real message (NOTE-011 check).
    assert check_note(world.session, world.garden, text).passed


def test_a_topic_that_names_no_term_is_a_candidate_not_a_tag(world: World) -> None:
    text = _note(world)
    section = _section(text, "Keywords and topics")
    [approved] = [x for x in section.splitlines() if x.startswith("- Topics (approved terms): ")]
    [others] = [x for x in section.splitlines() if x.startswith("- Topic candidates (not tags): ")]
    assert re.search(r": Timber \[\[[^\]]+\]\]$", approved), approved
    assert re.search(r": Soil drainage \[\[[^\]]+\]\]$", others), others
    front = text.split("\n---\n", 1)[0]
    assert "Soil drainage" not in front  # a candidate never reaches the tags


def test_without_keywords_the_section_is_unchanged(world: World) -> None:
    note = rich_conversation_note(
        world.session, world.garden, taxonomy=world.taxonomy, digest=world.digest
    )
    section = _section(render_note(note.model), "Keywords and topics")
    assert "Keywords:" not in section and "Topic" not in section
    assert "Timber" in section and "candidate" not in section


def test_docs_chat_v2_writes_the_keywords_and_the_vault_stays_clean(
    world: World, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    vault = tmp_path / "vault"
    chat = load_conversation(world.session, world.garden)
    write_transcript(world.session, chat, vault, world.settings.workspace_root / "archive")
    code = main(
        [
            "--json",
            "docs",
            "chat",
            world.garden,
            "--vault",
            str(vault),
            "--template",
            "v2",
            "--taxonomy",
            "tax-1",
        ]
    )
    assert code == 0, capsys.readouterr().out
    [note] = (vault / "Knowledge").glob("*.md")
    text = note.read_text(encoding="utf-8")
    assert "- Keywords: " in text and "- Topic candidates (not tags): " in text
    assert check_vault(vault).clean
