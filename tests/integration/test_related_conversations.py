"""REL-003 + REL-004: related-chat suggestions, and how notes, search and pages show links."""

from __future__ import annotations

import io
import json
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.classification.store import record_review
from knowledge_engine.documents.notes import conversation_note, topic_master
from knowledge_engine.documents.render import project_master
from knowledge_engine.domain.enums import Role
from knowledge_engine.domain.models import EvidenceRef
from knowledge_engine.extraction.records import (
    CandidateRecord,
    Entity,
    EntityType,
    Provenance,
    RecordType,
    Scope,
)
from knowledge_engine.extraction.store import add_candidates
from knowledge_engine.graph.offsets import quote_hash
from knowledge_engine.importer import import_source
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.importer.run import run_import
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.relationships.related import (
    RELATED_DETECTOR,
    SAME_PROJECT_DETECTOR,
    suggest_related,
)
from knowledge_engine.relationships.store import (
    ConversationRelationshipRow,
    RelationKind,
    ReviewAction,
    history,
    review,
)
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

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt"

# Synthetic chats: two about the same shed (x earlier, y later), one about bread.
CHATS = {
    "c-rel-x": (
        1704067200.0,
        "Synthetic: help me plan a timber garden shed with a sloped roof.",
        "Synthetic: a timber shed with a sloped felt roof and a concrete base.",
    ),
    "c-rel-y": (
        1706745600.0,
        "Synthetic: the timber garden shed roof needs felt; which kind?",
        "Synthetic: torch-on felt suits a sloped timber shed roof.",
    ),
    "c-rel-z": (
        1709251200.0,
        "Synthetic: why does my sourdough loaf collapse in the oven?",
        "Synthetic: overproofed dough collapses; shorten the final rise.",
    ),
}


def _export(root: Path) -> Path:
    chats = []
    for cid, (created, question, answer) in CHATS.items():
        # Node IDs differ per chat: shared native IDs would (rightly) read as a fork.
        u, a = f"{cid}-u1", f"{cid}-a1"
        mapping: dict[str, Any] = {
            "root": {"id": "root", "parent": None, "children": [u]},
            u: {"id": u, "parent": "root", "children": [a]},
            a: {"id": a, "parent": u, "children": []},
        }
        for node, role, words, offset in ((u, "user", question, 1), (a, "assistant", answer, 2)):
            mapping[node]["message"] = {
                "id": node,
                "author": {"role": role},
                "create_time": created + offset,
                "content": {"content_type": "text", "parts": [words]},
                "metadata": {},
            }
        chats.append(
            {
                "id": cid,
                "title": f"Synthetic {cid}",
                "create_time": created,
                "mapping": mapping,
                "current_node": a,
            }
        )
    root.mkdir(parents=True)
    (root / "conversations.json").write_text(json.dumps(chats), encoding="utf-8")
    return root


@dataclass
class World:
    settings: Settings
    session: Session
    chats: dict[str, str]  # native -> conv_
    taxonomy: TaxonomySnapshot
    project_id: str
    workspace_id: str


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
    workspace_id = session.scalars(select(ConversationRow.workspace_id)).first() or ""
    registry = TaxonomyRegistry(session)
    garden = registry.add_term(Dimension.TOPIC, "Gardening", status=TermStatus.APPROVED)
    project = registry.add_project("Shed build", status=TermStatus.APPROVED)
    taxonomy = registry.publish("tax-1", author="test")
    for native in ("c-rel-x", "c-rel-y"):
        chat = load_conversation(session, chats[native])
        for segment in load_segments(session, chat):
            for field, primary in (("topic", garden.term_id), ("projects", project.project_id)):
                record_review(
                    session,
                    taxonomy,
                    segment.segment_id,
                    field,
                    primary=primary,
                    reviewer="test",
                    conversation_id=chats[native],
                )
    # x and z both name the same (synthetic) book: entity overlap, nothing else shared.
    provenance = Provenance(
        stage_id="extract.test.v1", stage_key="stg_" + "d" * 64, extractor_version="t"
    )
    candidates = []
    for native in ("c-rel-x", "c-rel-z"):
        chat = load_conversation(session, chats[native])
        candidates.append(
            CandidateRecord(
                record_type=RecordType.REFERENCE,
                assertion="The user mentions a synthetic book.",
                actor=Role.USER,
                scope=Scope.CONVERSATION,
                scope_id=chats[native],
                evidence=(_evidence(chat, f"{native}-u1"),),
                entity=Entity(
                    entity_type=EntityType.BOOK,
                    name="Synthetic Handbook",
                    norm_name="synthetic handbook",
                ),
            )
        )
    for native in ("c-rel-x", "c-rel-y"):
        chat = load_conversation(session, chats[native])
        candidates.append(
            CandidateRecord(
                record_type=RecordType.FACT,
                assertion=f"Synthetic project fact ({native}).",
                actor=Role.USER,
                scope=Scope.GLOBAL,
                project_ids=(project.project_id,),
                term_ids=(garden.term_id,),
                evidence=(_evidence(chat, f"{native}-u1"),),
            )
        )
    add_candidates(session, candidates, provenance)
    session.commit()
    yield World(settings, session, chats, taxonomy, project.project_id, workspace_id)
    session.close()


def _suggest(w: World) -> dict[str, int]:
    counts = suggest_related(
        w.session, workspace_id=w.workspace_id, taxonomy=w.taxonomy, egress=w.settings.egress
    )
    w.session.commit()
    return dict(counts)


def _rows(session: Session) -> list[ConversationRelationshipRow]:
    return list(
        session.scalars(
            select(ConversationRelationshipRow).where(
                ConversationRelationshipRow.detector.in_([RELATED_DETECTOR, SAME_PROJECT_DETECTOR])
            )
        )
    )


def test_suggestions_explain_themselves_and_never_claim_a_fork(world: World) -> None:
    x, y, z = (world.chats[c] for c in ("c-rel-x", "c-rel-y", "c-rel-z"))
    assert _suggest(world) == {"new_same_project": 1, "new_related_to": 2}
    rows = {(r.from_conversation_id, r.kind, r.to_conversation_id): r for r in _rows(world.session)}
    assert set(rows) == {
        (y, "same_project", x),  # later chat -> earlier chat
        (y, "related_to", x),
        (z, "related_to", x),
    }
    for row in rows.values():
        assert row.review_state == "candidate"  # nothing is accepted on its own
        assert row.evidence_class == "semantic"
        assert row.confidence <= 0.85
    same = json.loads(rows[(y, "same_project", x)].evidence_json)
    assert same["project_ids"] == [world.project_id]
    assert same["because"] == [f"both chats are labelled with project {world.project_id}"]
    shed = json.loads(rows[(y, "related_to", x)].evidence_json)
    assert any("topic" in b for b in shed["because"])
    assert any("similar" in b for b in shed["because"])
    assert shed["revisions"]["from"] and shed["revisions"]["to"]  # cites the labelled messages
    book = json.loads(rows[(z, "related_to", x)].evidence_json)
    assert book["because"] == ["both chats name the same named thing"]
    assert len(book["records"]) == 2
    assert "Synthetic Handbook" not in rows[(z, "related_to", x)].evidence_json.lower()
    assert "synthetic handbook" not in rows[(z, "related_to", x)].evidence_json
    # Running again proposes nothing new and changes nothing reviewed.
    review(
        world.session, rows[(z, "related_to", x)].relationship_id, ReviewAction.REJECT, reviewer="t"
    )
    world.session.commit()
    assert _suggest(world) == {}
    assert (
        world.session.get(
            ConversationRelationshipRow, rows[(z, "related_to", x)].relationship_id
        ).review_state
        == "rejected"
    )  # type: ignore[union-attr]


def test_similar_but_unrelated_fixture_is_at_most_a_candidate(tmp_path: Path) -> None:
    settings = Settings(workspace_root=tmp_path / "ws")
    import_source(FIXTURES / "similar_unrelated" / "export", "fixture", settings=settings)
    with Session(create_sqlite_engine(database_path(settings))) as session:
        workspace_id = session.scalars(select(ConversationRow.workspace_id)).first() or ""
        suggest_related(session, workspace_id=workspace_id, taxonomy=None, egress=settings.egress)
        session.commit()
        every = list(session.scalars(select(ConversationRelationshipRow)))
    assert all(r.kind == RelationKind.RELATED_TO.value for r in every)
    assert all(r.review_state == "candidate" for r in every)
    assert not any(r.kind in ("continues", "forked_from") for r in every)


def test_notes_show_reviewed_links_with_evidence_in_their_direction(world: World) -> None:
    x, y, z = (world.chats[c] for c in ("c-rel-x", "c-rel-y", "c-rel-z"))
    _suggest(world)
    rows = {(r.from_conversation_id, r.kind): r for r in _rows(world.session)}
    accepted = rows[(y, "related_to")].relationship_id
    rejected = rows[(y, "same_project")].relationship_id
    review(world.session, accepted, ReviewAction.ACCEPT, reviewer="test")
    review(world.session, rejected, ReviewAction.REJECT, reviewer="test", note="not really")
    world.session.commit()

    x_note = render_note(conversation_note(world.session, x, taxonomy=world.taxonomy).model)
    related = x_note.split("## Related conversations", 1)[1]
    accepted_line = next(line for line in related.splitlines() if accepted in line)
    # y points at x, so in x's note it reads "[[y]] related_to this chat".
    assert accepted_line.index("(conv-") < accepted_line.index("**related_to** this chat")
    assert "accepted" in accepted_line and "because both chats are labelled with topic" in (
        accepted_line
    )
    assert "Evidence: [[" in accepted_line and "#^" in accepted_line
    assert rejected not in x_note and "same_project" not in x_note  # rejected: hidden...
    assert [h.action for h in history(world.session, rejected)] == ["reject"]  # ...but kept

    project = render_note(project_master(world.session, world.project_id))
    assert "## Related conversations" in project and accepted in project
    assert rejected not in project
    project_line = next(line for line in project.splitlines() if accepted in line)
    assert "this chat" not in project_line  # both ends named in a master note
    topic = render_note(topic_master(world.session, "Gardening", world.taxonomy))
    assert accepted in topic and rejected not in topic
    assert z not in rows[(y, "related_to")].to_conversation_id


def test_search_and_pages_list_related_chats(
    world: World, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from knowledge_engine.cli.main import main
    from knowledge_engine.ui.app import make_app

    x, y = world.chats["c-rel-x"], world.chats["c-rel-y"]
    _suggest(world)
    rows = {(r.from_conversation_id, r.kind): r for r in _rows(world.session)}
    review(
        world.session, rows[(y, "same_project")].relationship_id, ReviewAction.REJECT, reviewer="t"
    )
    world.session.commit()
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(world.settings.workspace_root))
    assert main(["--json", "find", "felt shed roof"]) == 0
    data = json.loads(capsys.readouterr().out)["data"]
    links = data["related"][x]
    assert {link["kind"] for link in links} == {"related_to"}  # the rejected one is left out
    shed = next(link for link in links if link["other"] == y)
    assert (shed["from"], shed["to"], shed["direction"]) == (y, x, "from")
    assert shed["because"]

    app = make_app(world.settings)
    captured: dict[str, Any] = {}

    def get(path: str, query: str = "") -> str:
        environ = {
            "REQUEST_METHOD": "GET",
            "PATH_INFO": path,
            "QUERY_STRING": query,
            "HTTP_HOST": "127.0.0.1:8765",
            "CONTENT_LENGTH": "0",
            "wsgi.input": io.BytesIO(b""),
        }
        body = app(environ, lambda status, headers: captured.update(status=status))
        assert captured["status"] == "200 OK"
        return b"".join(body).decode("utf-8")

    page = get(f"/chats/{x}")
    assert "Related chats" in page and f'href="/chats/{y}"' in page
    assert "is in the same project as" not in page
    assert "this chat (suggested" in page
    found = get("/search", "q=felt")
    assert f'href="/chats/{y}"' in found and "is related to" in found


def test_cli_related_suggest(
    world: World, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from knowledge_engine.cli.main import main

    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(world.settings.workspace_root))
    world.session.close()
    assert main(["--json", "related", "suggest", "--taxonomy", "tax-1"]) == 0
    out = capsys.readouterr().out
    assert json.loads(out)["data"]["new"] == {"new_related_to": 2, "new_same_project": 1}
    assert "Synthetic c-rel" not in out  # IDs and counts only
    assert main(["--json", "related", "suggest", "--taxonomy", "tax-9"]) == 2
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "no_taxonomy"
