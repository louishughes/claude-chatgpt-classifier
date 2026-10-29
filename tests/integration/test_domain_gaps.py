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
    "c-cook-1": "cooking a pasta recipe for dinner tonight",
    "c-cook-2": "cooking a curry recipe from scratch",
    "c-cook-3": "cooking a rice recipe in a heavy pot",
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


def _build(tmp_path: Path, chats: dict[str, str]) -> World:
    settings = Settings(workspace_root=tmp_path / "ws")
    _import(tmp_path / "export", settings, chats)
    session = Session(create_sqlite_engine(database_path(settings)))
    registry = TaxonomyRegistry(session)
    term = registry.add_term(Dimension.DOMAIN, "Programming", status=TermStatus.APPROVED)
    registry.add_alias(term, "python")
    tax1 = registry.publish("tax-1", author="owner")
    world = World(settings, session, tax1)
    save(session, SegmentClassifier(tax1).classify(world.items()))  # the run, frozen at tax-1
    session.commit()
    return world


def _import(root: Path, settings: Settings, chats: dict[str, str]) -> None:
    root.mkdir(parents=True)
    body = [_chat(cid, text, day) for day, (cid, text) in enumerate(chats.items())]
    (root / "conversations.json").write_text(json.dumps(body), encoding="utf-8")
    run_import(root, "acct", format_id=None, settings=settings)


def _python(n: int, extra: str = "") -> dict[str, str]:
    return {f"c-code-{k}": f"python task {extra}".strip() for k in range(1, n + 1)}


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    world = _build(tmp_path, CHATS)
    yield world
    world.session.close()


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
        assert "text" not in json.dumps(evidence) and "keywords" not in evidence  # IDs, spans


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
    assert again.proposed == [] and {"Cooking", "Makeover"} <= set(again.waiting)

    [cooking] = [
        r.proposal_id
        for r in proposals(session, OPEN)
        if json.loads(r.payload_json)["label"] == "Cooking"
    ]
    assert cooking in first.proposed
    reject(session, cooking, reviewer="reviewer-b", note="too narrow for a domain")
    session.commit()
    after = propose_domains(session, world.tax1, world.items())
    assert after.proposed == [] and after.rejected == ["Cooking", "Recipe"]  # word, then group
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


def test_a_word_covered_chats_share_does_not_merge_two_subjects(tmp_path: Path) -> None:
    """The review's probe: cooking and garden chats that all say "weekend"."""
    chats = {
        **{f"c-cook-{k}": f"cooking {dish} this weekend" for k, dish in
           enumerate(("pasta", "curry", "rice"), 1)},
        **{f"c-gard-{k}": f"garden {job} this weekend" for k, job in
           enumerate(("pruning", "weeding", "mulching"), 1)},
        **{f"c-code-{k}": "python task" for k in range(1, 8)},
        "c-code-8": "python task this weekend",
    }  # fmt: skip
    world = _build(tmp_path, chats)
    report = propose_domains(world.session, world.tax1, world.items())
    assert set(_open_domains(world.session)) == {"Cooking", "Garden"}
    assert len(report.proposed) == 2 and report.leftover == 0
    world.session.close()


def test_a_rejected_subject_stays_rejected_when_a_new_chat_joins_it(world: World) -> None:
    session = world.session
    propose_domains(session, world.tax1, world.items())
    [cooking] = [r.proposal_id for r in proposals(session, OPEN)
                 if json.loads(r.payload_json)["label"] == "Cooking"]  # fmt: skip
    reject(session, cooking, reviewer="reviewer-b", note="not a domain")
    session.commit()
    _import(world.settings.workspace_root.parent / "export-2", world.settings,
            {**CHATS, "c-cook-4": "cooking a stew recipe"})  # fmt: skip
    session.commit()
    save(session, SegmentClassifier(world.tax1).classify(world.items()))
    session.commit()
    after = propose_domains(session, world.tax1, world.items())
    # "Recipe" names the same four chats, three of them already rejected.
    assert after.proposed == [] and "Recipe" in after.rejected


def test_cli_measures_word_shares_against_every_classified_chat(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from knowledge_engine.segmentation.inventory import corpus_inventory
    from knowledge_engine.taxonomy.refresh import build_refresh_pack, record_pack

    chats = {k: v for k, v in CHATS.items() if not k.startswith("c-make")}
    world = _build(tmp_path, {**chats, **_python(4)})
    session = world.session
    pack = build_refresh_pack(session, world.tax1, list(corpus_inventory(session)), size=5,
                              seed="t")  # fmt: skip
    record_pack(session, pack)
    session.commit()
    # Only the three cooking chats are queued: all of them say "cooking", which
    # a queue-only share would call filler.
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(world.settings.workspace_root))
    capsys.readouterr()
    assert main(["--json", "taxonomy", "refresh"]) == 0
    assert json.loads(capsys.readouterr().out)["data"]["domains_proposed"] == 1
    assert set(_open_domains(session)) == {"Cooking"}
    session.close()


def test_the_latest_review_decides_and_pending_is_not_uncovered(world: World) -> None:
    from dataclasses import replace

    from knowledge_engine.classification.classifier import PENDING
    from knowledge_engine.taxonomy.domain_gaps import domain_status

    session = world.session
    [programming] = world.tax1.dimension(Dimension.DOMAIN)
    code, cook = world.segment_of("c-code-1"), world.segment_of("c-cook-1")
    record_review(session, world.tax1, cook, "domain", primary=programming.term_id,
                  reviewer="reviewer-c")  # fmt: skip
    record_review(session, world.tax1, cook, "domain", primary=None, reviewer="reviewer-d")
    record_review(session, world.tax1, code, "domain", primary=None, reviewer="reviewer-d")
    session.commit()
    answered, covered = domain_status(session, "tax-1")
    assert cook in answered and cook not in covered  # "none fits" came last
    assert code in answered and code not in covered  # it overrides the machine's domain

    _import(world.settings.workspace_root.parent / "export-2", world.settings,
            {**CHATS, "c-cook-4": "cooking a soup recipe"})  # fmt: skip
    session.commit()
    new = [(c, s) for c, s in world.items() if s.segment_id == world.segment_of("c-cook-4")]
    [result] = SegmentClassifier(world.tax1).classify(new)
    save(session, [replace(result, state=PENDING, answer=None, stage_key="stg_" + "p" * 64)])
    session.commit()
    answered, covered = domain_status(session, "tax-1")
    assert world.segment_of("c-cook-4") not in answered
    report = propose_domains(session, world.tax1, world.items())
    assert report.uncovered == 7  # the six subject chats, plus the Python chat a reviewer reset


def test_a_recurring_name_never_becomes_a_label(tmp_path: Path) -> None:
    chats = {
        "c-name-1": "notes for Bramble about the cottage lease",
        "c-name-2": "a birthday card that Bramble will like",
        "c-name-3": "the train times so Bramble can visit",
        **_python(4),
    }
    world = _build(tmp_path, chats)
    report = propose_domains(world.session, world.tax1, world.items())
    assert report.proposed == [] and report.names == 1
    world.session.close()


def _subjects(*kinds: str) -> dict[str, str]:
    words = {
        "cook": ("cooking {} this weekend", ("pasta", "curry", "rice")),
        "gard": ("garden {} this weekend", ("pruning", "weeding", "mulching")),
        "trav": ("travel to {} this weekend", ("lisbon", "porto", "madrid")),
    }
    return {
        f"c-{kind}-{k}": words[kind][0].format(item)
        for kind in kinds
        for k, item in enumerate(words[kind][1], 1)
    }


@pytest.mark.parametrize("kinds", [("cook", "gard"), ("cook", "gard", "trav")])
def test_a_bridge_word_no_covered_chat_uses_is_never_a_subject(
    tmp_path: Path, kinds: tuple[str, ...]
) -> None:
    """Every subject's chats say "weekend" and no covered chat does: still separate."""
    world = _build(tmp_path, {**_subjects(*kinds), **_python(10)})
    report = propose_domains(world.session, world.tax1, world.items())
    expected = {"cook": "Cooking", "gard": "Garden", "trav": "Travel"}
    assert set(_open_domains(world.session)) == {expected[k] for k in kinds}
    assert report.bridges == ["Weekend"]
    world.session.close()


@pytest.mark.parametrize("label", [None, "Food"])
def test_an_approved_subject_is_not_proposed_again(world: World, label: str | None) -> None:
    from knowledge_engine.taxonomy.review import approve

    session = world.session
    propose_domains(session, world.tax1, world.items())
    [cooking] = [r.proposal_id for r in proposals(session, OPEN)
                 if json.loads(r.payload_json)["label"] == "Cooking"]  # fmt: skip
    approve(session, cooking, reviewer="reviewer-b", label=label)
    session.commit()
    after = propose_domains(session, world.tax1, world.items())
    # "Recipe" names the approved cooking chats under another word: still nothing.
    assert after.proposed == [] and set(_open_domains(session)) == {"Makeover"}


def test_reviews_under_another_version_do_not_count(world: World) -> None:
    from knowledge_engine.taxonomy.domain_gaps import domain_status

    session = world.session
    code = world.segment_of("c-code-1")
    record_review(session, world.tax1, code, "domain", primary=None, reviewer="reviewer-d")
    tax2 = TaxonomyRegistry(session).publish("tax-2", author="owner")
    save(session, SegmentClassifier(tax2).classify(world.items()))
    tax3 = TaxonomyRegistry(session).publish("tax-3", author="owner")
    session.commit()
    _, covered = domain_status(session, tax2.version)
    assert code in covered  # tax-1's "none fits" doesn't carry into tax-2
    answered, _ = domain_status(session, tax3.version)
    assert answered == set()  # nothing classified or reviewed under tax-3


def test_a_name_at_a_sentence_start_is_still_a_name(tmp_path: Path) -> None:
    chats = {
        "c-name-1": "notes for Bramble about the lease",
        "c-name-2": "a card that Bramble will like",
        "c-name-3": "the train times. Bramble can visit",
        **_python(4),
    }
    world = _build(tmp_path, chats)
    report = propose_domains(world.session, world.tax1, world.items())
    assert report.proposed == [] and report.names == 1
    world.session.close()
