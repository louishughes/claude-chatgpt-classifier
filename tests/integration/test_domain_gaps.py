"""TAX-009: chats no domain fits become one proposal per subject, for a reviewer.

Synthetic chats. tax-1 has one domain, Programming. Three cooking chats
and three garden/room makeover chats fit no domain; one Python chat does.
Each uncovered subject becomes one new-domain proposal with quote anchors,
the vocabulary stays at tax-1, and neither a re-run nor a rejection brings
the same suggestion back.
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
from knowledge_engine.cli.main import main
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.importer.run import run_import
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.rendering.transcript import StoredConversation, load_conversation
from knowledge_engine.segmentation.overrides import load_segments
from knowledge_engine.segmentation.segmenter import Segment
from knowledge_engine.settings import Settings
from knowledge_engine.taxonomy.domain_gaps import GAP_VERSION, propose_domains
from knowledge_engine.taxonomy.registry import (
    Dimension,
    TaxonomyRegistry,
    TaxonomySnapshot,
    TermStatus,
)
from knowledge_engine.taxonomy.review import OPEN, proposals, reject

T0 = 1704067200.0
CHATS = {
    "c-cook-1": "cooking pasta for dinner tonight",
    "c-cook-2": "cooking a curry from scratch",
    "c-cook-3": "cooking rice in a heavy pot",
    "c-make-1": "garden makeover with raised planters",
    "c-make-2": "room makeover with paint colours",
    "c-make-3": "bedroom makeover and a woven rug",
    "c-code-1": "python script for parsing server logs",
}


def _chat(cid: str, text: str, day: int) -> dict[str, Any]:
    def node(n: str, parent: str, role: str, body: str, t: float) -> dict[str, Any]:
        return {
            "id": f"{cid}-{n}",
            "parent": parent,
            "children": [],
            "message": {
                "id": f"{cid}-{n}",
                "author": {"role": role},
                "create_time": t,
                "content": {"content_type": "text", "parts": [body]},
                "metadata": {},
            },
        }

    start = T0 + day * 86400
    user = node("u", "root", "user", f"Please help with {text}. " * 5, start)
    reply = node("a", f"{cid}-u", "assistant", f"Here is advice about {text}.", start + 60)
    user["children"] = [reply["id"]]
    mapping = {
        "root": {"id": "root", "parent": None, "children": [user["id"]], "message": None},
        user["id"]: user,
        reply["id"]: reply,
    }
    return {"id": cid, "title": f"Synthetic {cid}", "create_time": start, "mapping": mapping,
            "current_node": reply["id"]}  # fmt: skip


@dataclass
class World:
    settings: Settings
    session: Session
    tax1: TaxonomySnapshot

    def items(self) -> list[tuple[StoredConversation, Segment]]:
        found = []
        for cid in sorted(self.chats().values()):
            chat = load_conversation(self.session, cid)
            found += [(chat, seg) for seg in load_segments(self.session, chat)]
        return found

    def chats(self) -> dict[str, str]:
        rows = self.session.execute(
            select(ConversationRow.native_conversation_id, ConversationRow.conversation_id)
        )
        return dict(rows.tuples().all())

    def segment_of(self, native: str) -> str:
        cid = self.chats()[native]
        [segment] = [s.segment_id for c, s in self.items() if c.conversation_id == cid]
        return segment


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    export = tmp_path / "export"
    export.mkdir()
    body = [_chat(cid, text, day) for day, (cid, text) in enumerate(CHATS.items())]
    (export / "conversations.json").write_text(json.dumps(body), encoding="utf-8")
    settings = Settings(workspace_root=tmp_path / "ws")
    run_import(export, "acct", format_id=None, settings=settings)
    session = Session(create_sqlite_engine(database_path(settings)))
    registry = TaxonomyRegistry(session)
    term = registry.add_term(Dimension.DOMAIN, "Programming", status=TermStatus.APPROVED)
    registry.add_alias(term, "python")
    tax1 = registry.publish("tax-1", author="owner")
    world = World(settings, session, tax1)
    save(session, SegmentClassifier(tax1).classify(world.items()))  # the run, frozen at tax-1
    session.commit()
    yield world
    session.close()


def _open_domains(session: Session) -> dict[str, dict[str, Any]]:
    found = {}
    for row in proposals(session, OPEN):
        payload = json.loads(row.payload_json)
        if payload.get("dimension") == Dimension.DOMAIN.value:
            found[payload["label"]] = json.loads(row.evidence_json)
    return found


def test_each_uncovered_subject_becomes_one_proposal_with_anchors(world: World) -> None:
    session = world.session
    report = propose_domains(session, world.tax1, world.items())
    session.commit()
    assert report.uncovered == 6  # the Python chat has a domain
    assert len(report.proposed) == 2
    found = _open_domains(session)
    assert set(found) == {"Cooking", "Makeover"}
    chats = {c.conversation_id: c for c, _ in world.items()}
    for label, evidence in found.items():
        assert evidence["rule"] == GAP_VERSION and evidence["taxonomy_version"] == "tax-1"
        assert evidence["size"] == 3 and len(evidence["segments"]) == 3
        assert world.segment_of("c-code-1") not in evidence["segments"]
        assert [a["segment_id"] for a in evidence["anchors"]] == evidence["segments"]
        for anchor in evidence["anchors"]:
            [chat] = [c for c, s in world.items() if s.segment_id == anchor["segment_id"]]
            text = chats[chat.conversation_id].messages[anchor["message_id"]].text
            assert text[anchor["start"] : anchor["end"]].lower() == label.lower()
        assert "text" not in json.dumps(evidence)  # IDs and spans only


def test_the_vocabulary_stays_frozen(world: World) -> None:
    session = world.session
    propose_domains(session, world.tax1, world.items())
    session.commit()
    registry = TaxonomyRegistry(session)
    assert registry.versions() == ["tax-1"]
    now = registry.snapshot("tax-1")
    assert now.content_sha256 == world.tax1.content_sha256
    assert [t.label for t in now.dimension(Dimension.DOMAIN)] == ["Programming"]


def test_a_rerun_and_a_rejection_add_nothing(world: World) -> None:
    session = world.session
    first = propose_domains(session, world.tax1, world.items())
    session.commit()
    again = propose_domains(session, world.tax1, world.items())
    assert again.proposed == [] and sorted(again.waiting) == ["Cooking", "Makeover"]

    [cooking] = [
        r.proposal_id
        for r in proposals(session, OPEN)
        if json.loads(r.payload_json)["label"] == "Cooking"
    ]
    assert cooking in first.proposed
    reject(session, cooking, reviewer="reviewer-b", note="too narrow for a domain")
    session.commit()
    after = propose_domains(session, world.tax1, world.items())
    assert after.proposed == [] and after.rejected == ["Cooking"]
    assert set(_open_domains(session)) == {"Makeover"}


def test_a_group_below_the_minimum_is_not_proposed(world: World) -> None:
    session = world.session
    # A reviewer gives one cooking chat a domain: two uncovered cooking chats remain.
    [programming] = world.tax1.dimension(Dimension.DOMAIN)
    record_review(session, world.tax1, world.segment_of("c-cook-1"), "domain",
                  primary=programming.term_id, reviewer="reviewer-c",
                  note="recipe scraper")  # fmt: skip
    session.commit()
    report = propose_domains(session, world.tax1, world.items())
    assert report.uncovered == 5
    assert set(_open_domains(session)) == {"Makeover"}
    assert report.leftover == 2  # the two cooking chats, too few on their own


def test_cli_refresh_files_the_domain_proposals(
    world: World, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(world.settings.workspace_root))
    world.session.commit()
    capsys.readouterr()
    assert main(["--json", "taxonomy", "refresh"]) == 0
    data = json.loads(capsys.readouterr().out)["data"]
    assert data["domains_proposed"] == 2
    assert main(["--json", "taxonomy", "refresh"]) == 0
    assert json.loads(capsys.readouterr().out)["data"]["domains_proposed"] == 0
    capsys.readouterr()
    assert main(["--json", "taxonomy", "refresh", "--min-segments", "4"]) == 0
