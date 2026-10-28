"""NOTE-014: the taxonomy keeps up as new chats arrive.

Synthetic chats. Import 1 has gardening and baking chats; tax-1 names
both subjects. Import 2 adds two beekeeping chats, a subject tax-1 has no
word for, so they come out unlabelled. The refresh pack holds only those;
a proposer session plans "Beekeeping", a different reviewer approves it,
the owner publishes tax-2, and the relabel redoes only the beekeeping
segments (plus one old garden chat that mentions a hive). Everything else
is carried over, tax-1's rows stay as they were, and a reviewer's
correction still stands.
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

from knowledge_engine.classification.classifier import DONE, SegmentClassifier
from knowledge_engine.classification.store import (
    ClassificationRow,
    effective_labels,
    record_review,
    save,
)
from knowledge_engine.cli.main import main
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.importer.run import run_import
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.rendering.transcript import StoredConversation, load_conversation
from knowledge_engine.segmentation.inventory import corpus_inventory
from knowledge_engine.segmentation.overrides import load_segments
from knowledge_engine.segmentation.segmenter import Segment
from knowledge_engine.settings import Settings
from knowledge_engine.taxonomy.bootstrap import (
    Decision,
    PlanTerm,
    Review,
    apply_review,
    file_plan,
    pack_sha256,
)
from knowledge_engine.taxonomy.refresh import (
    CARRIED,
    NEW_CHAT,
    UNLABELLED,
    NothingToRefresh,
    RefreshPlan,
    build_refresh_pack,
    queue,
    record_pack,
    refresh_status,
    relabel,
)
from knowledge_engine.taxonomy.registry import (
    Dimension,
    TaxonomyRegistry,
    TaxonomySnapshot,
    TermStatus,
)

T0 = 1704067200.0
FIRST = {
    "c-garden-1": "garden compost for the raised garden bed",
    "c-garden-2": "garden shed beside the garden, and a bee hive on the fence",
    "c-bread-1": "sourdough bread with a lively sourdough starter",
    "c-bread-2": "bread flour for a sourdough loaf",
}
SECOND = {
    "c-bees-1": "beekeeping in spring: inspecting the beekeeping frames",
    "c-bees-2": "beekeeping kit and a beekeeping veil for the apiary",
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


def _export(root: Path, chats: dict[str, str]) -> Path:
    root.mkdir(parents=True)
    # Each chat keeps its own date in every export, as in a real re-export.
    order = [*FIRST, *SECOND, "c-garden-3"]
    body = [_chat(cid, text, order.index(cid)) for cid, text in chats.items()]
    (root / "conversations.json").write_text(json.dumps(body), encoding="utf-8")
    return root


@dataclass
class World:
    tmp: Path
    settings: Settings
    session: Session
    tax1: TaxonomySnapshot
    corrected: str  # the segment a reviewer corrected under tax-1

    def chats(self) -> dict[str, str]:
        rows = self.session.execute(
            select(ConversationRow.native_conversation_id, ConversationRow.conversation_id)
        )
        return dict(rows.tuples().all())

    def items(self) -> list[tuple[StoredConversation, Segment]]:
        found = []
        for cid in sorted(self.chats().values()):
            chat = load_conversation(self.session, cid)
            found += [(chat, seg) for seg in load_segments(self.session, chat)]
        return found

    def segments_of(self, *natives: str) -> set[str]:
        ids = {self.chats()[n] for n in natives}
        return {seg.segment_id for chat, seg in self.items() if chat.conversation_id in ids}

    def import_second(self) -> None:
        both = {**FIRST, **SECOND}  # the user re-exports everything, plus the new chats
        run_import(_export(self.tmp / "export-2", both), "acct", format_id=None,
                   settings=self.settings)  # fmt: skip
        self.session.commit()  # end the read snapshot so the new import shows


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    settings = Settings(workspace_root=tmp_path / "ws")
    run_import(_export(tmp_path / "export-1", FIRST), "acct", format_id=None, settings=settings)
    session = Session(create_sqlite_engine(database_path(settings)))
    registry = TaxonomyRegistry(session)
    for label, aliases in (("Gardening", ("garden",)), ("Baking", ("sourdough", "bread"))):
        term = registry.add_term(Dimension.TOPIC, label, status=TermStatus.APPROVED)
        for alias in aliases:
            registry.add_alias(term, alias)
    tax1 = registry.publish("tax-1", author="owner")
    world = World(tmp_path, settings, session, tax1, "")
    save(session, SegmentClassifier(tax1).classify(world.items()))
    # A reviewer says one bread chat is also about gardening (a correction).
    [world.corrected] = world.segments_of("c-bread-1")
    garden, baking = (t.term_id for t in sorted(tax1.terms, key=lambda t: t.label))
    record_review(session, tax1, world.corrected, "topic", primary=baking, secondary=[garden],
                  reviewer="reviewer-c", note="mentions the allotment")  # fmt: skip
    session.commit()
    yield world
    session.close()


def _tax1_rows(session: Session) -> list[tuple[str, str, str | None]]:
    return [
        (r.stage_key, r.state, r.answer_json)
        for r in session.scalars(
            select(ClassificationRow)
            .where(ClassificationRow.taxonomy_version == "tax-1")
            .order_by(ClassificationRow.stage_key)
        )
    ]


def _bootstrap_tax2(world: World) -> TaxonomySnapshot:
    """The refresh round: pack -> proposer plan -> separate reviewer -> owner publishes."""
    session = world.session
    pack = build_refresh_pack(
        session, world.tax1, list(corpus_inventory(session)), size=10, seed="t"
    )
    record_pack(session, pack)
    cited = tuple(s["segment_id"] for s in pack["segments"])
    plan = RefreshPlan(
        pack_sha256=pack_sha256(pack),
        proposer="proposer-session-a",
        topics=(
            PlanTerm(
                label="Beekeeping",
                definition="Keeping honey bees: hives, frames, kit.",
                aliases=("hive", "apiary"),
                segments=cited,
            ),
        ),
    )
    filed = file_plan(session, plan, pack)
    assert len(filed.proposed) == 1 and refresh_status(session).candidates == 1
    applied = apply_review(
        session,
        Review(
            reviewer="reviewer-session-b",
            decisions=(
                Decision(proposal_id=filed.proposed[0], verdict="approve", note="a real subject"),
            ),
        ),
    )
    assert applied.approved == filed.proposed
    tax2 = TaxonomyRegistry(session).publish("tax-2", author="owner")
    session.commit()
    return tax2


def test_new_chats_on_a_new_subject_are_queued_and_counted(world: World) -> None:
    session = world.session
    with pytest.raises(NothingToRefresh):  # everything from import 1 is labelled
        build_refresh_pack(session, world.tax1, list(corpus_inventory(session)), size=5, seed="t")
    world.import_second()
    status = refresh_status(session)
    # Not classified yet: the two new chats have no label under tax-1.
    assert (status.version, status.chats, status.unlabelled_chats) == ("tax-1", 6, 2)
    assert status.new_chats == 2 and status.candidates == 0

    # A classification run under the frozen tax-1 can't label them either.
    new = [(c, s) for c, s in world.items() if s.segment_id in world.segments_of(*SECOND)]
    save(session, SegmentClassifier(world.tax1).classify(new))
    session.commit()
    assert refresh_status(session).unlabelled_chats == 2
    reasons = queue(session, world.tax1, list(corpus_inventory(session)))
    assert reasons == dict.fromkeys(world.segments_of(*SECOND), UNLABELLED)

    pack = build_refresh_pack(
        session, world.tax1, list(corpus_inventory(session)), size=10, seed="t"
    )
    assert {s["segment_id"] for s in pack["segments"]} == world.segments_of(*SECOND)
    assert pack["refresh"]["vocabulary"] == {"topic": ["Baking", "Gardening"]}
    record_pack(session, pack)
    session.commit()
    assert refresh_status(session).new_chats == 0  # the pack moved the mark


def test_a_labelled_chat_from_a_later_import_is_queued_as_new(world: World) -> None:
    world.import_second()
    session = world.session
    extra = {"c-garden-3": "garden path edging for the garden"}
    run_import(_export(world.tmp / "export-3", {**FIRST, **SECOND, **extra}), "acct",
               format_id=None, settings=world.settings)  # fmt: skip
    session.commit()
    save(session, SegmentClassifier(world.tax1).classify(world.items()))
    session.commit()
    reasons = queue(session, world.tax1, list(corpus_inventory(session)))
    [garden3] = world.segments_of("c-garden-3")
    assert reasons[garden3] == NEW_CHAT  # labelled, but nobody has looked for new subjects in it


def test_refresh_proposes_a_term_and_tax2_relabels_only_what_it_changes(world: World) -> None:
    session = world.session
    world.import_second()
    new = [(c, s) for c, s in world.items() if s.segment_id in world.segments_of(*SECOND)]
    save(session, SegmentClassifier(world.tax1).classify(new))
    session.commit()
    before = _tax1_rows(session)

    tax2 = _bootstrap_tax2(world)
    report = relabel(session, world.tax1, SegmentClassifier(tax2), world.items())
    session.commit()

    bees = world.segments_of(*SECOND)
    [hive] = world.segments_of("c-garden-2")  # an old chat that mentions a hive
    assert report.relabelled == {**dict.fromkeys(bees, UNLABELLED), hive: "mentions_new_term"}
    assert set(report.carried) == world.segments_of("c-garden-1", "c-bread-1", "c-bread-2")
    assert report.invalidated == []  # tax-2 only added a term: no old answer is stale
    assert report.states == {DONE: 3}

    # Old labels stay: every tax-1 row is exactly as it was.
    assert _tax1_rows(session) == before
    # The new subject is labelled under tax-2.
    beekeeping = next(t.term_id for t in tax2.terms if t.label == "Beekeeping")
    for segment in bees:
        assert effective_labels(session, segment, tax2)["topic"].primary == beekeeping
    # Carried answers are the same answers, now under tax-2.
    [garden1] = world.segments_of("c-garden-1")
    labels = effective_labels(session, garden1, tax2)["topic"]
    assert (labels.primary, labels.source) == (
        effective_labels(session, garden1, world.tax1)["topic"].primary,
        "machine",
    )
    # The reviewer's correction still stands under tax-2.
    corrected = effective_labels(session, world.corrected, tax2)["topic"]
    assert corrected.source == "review" and len(corrected.secondary) == 1
    status = refresh_status(session)
    assert (status.version, status.unlabelled_chats, status.candidates) == ("tax-2", 0, 0)

    # Running it again changes nothing.
    count = len(session.scalars(select(ClassificationRow)).all())
    again = relabel(session, world.tax1, SegmentClassifier(tax2), world.items())
    session.commit()
    assert len(session.scalars(select(ClassificationRow)).all()) == count
    assert set(again.relabelled) == set(report.relabelled)
    carried = session.scalars(
        select(ClassificationRow).where(ClassificationRow.method == CARRIED)
    ).all()
    assert {r.segment_id for r in carried} == set(report.carried)


def test_relabel_marks_answers_citing_a_changed_term_stale(world: World) -> None:
    session = world.session
    registry = TaxonomyRegistry(session)
    baking = next(t for t in world.tax1.terms if t.label == "Baking")
    from knowledge_engine.taxonomy.registry import TaxonomyTermRow

    row = session.get(TaxonomyTermRow, baking.term_id)
    assert row is not None
    row.definition = "Bread, cakes and pastry."  # a changed definition is a changed term
    tax2 = registry.publish("tax-2", author="owner")
    report = relabel(session, world.tax1, SegmentClassifier(tax2), world.items())
    session.commit()
    bread = world.segments_of("c-bread-1", "c-bread-2")
    assert {s for s, why in report.relabelled.items() if why == "cites_changed"} == bread
    assert len(report.invalidated) == 2
    assert set(report.carried) == world.segments_of("c-garden-1", "c-garden-2")


def _cli(capsys: pytest.CaptureFixture[str], *args: str) -> tuple[int, dict[str, Any]]:
    capsys.readouterr()
    code = main(["--json", *args])
    return code, json.loads(capsys.readouterr().out)


def test_cli_status_pack_and_relabel_with_notes(
    world: World, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(world.settings.workspace_root))
    world.import_second()
    world.session.commit()

    code, status = _cli(capsys, "taxonomy", "refresh")
    assert code == 0 and status["data"]["unlabelled_chats"] == 2

    outside = world.tmp / "pack.json"
    code, refused = _cli(capsys, "taxonomy", "refresh", "--out", str(outside))
    assert (code, refused["error"]["code"]) == (2, "not_private")

    pack_path = world.tmp / "private" / "refresh.json"
    code, written = _cli(capsys, "taxonomy", "refresh", "--out", str(pack_path))
    assert code == 0 and written["data"]["queued"] == {UNLABELLED: 2}
    pack = json.loads(pack_path.read_text(encoding="utf-8"))
    plan = RefreshPlan(
        pack_sha256=pack_sha256(pack),
        proposer="proposer-session-a",
        topics=(
            PlanTerm(label="Beekeeping", definition="Keeping honey bees and hives.",
                     segments=tuple(s["segment_id"] for s in pack["segments"])),
        ),
    )  # fmt: skip
    plan_path = world.tmp / "private" / "plan.json"
    plan_path.write_text(plan.model_dump_json(), encoding="utf-8")
    code, filed = _cli(capsys, "taxonomy", "propose", str(plan_path), "--pack", str(pack_path))
    assert code == 0 and len(filed["data"]["proposed"]) == 1  # no categories needed

    review_path = world.tmp / "private" / "review.json"
    review = Review(
        reviewer="reviewer-session-b",
        decisions=(Decision(proposal_id=filed["data"]["proposed"][0], verdict="approve",
                            note="a real subject"),),
    )  # fmt: skip
    review_path.write_text(review.model_dump_json(), encoding="utf-8")
    assert _cli(capsys, "taxonomy", "review", str(review_path))[0] == 0
    assert _cli(capsys, "taxonomy", "publish", "tax-2", "--author", "owner")[0] == 0

    vault = world.tmp / "vault"
    code, done = _cli(capsys, "taxonomy", "relabel", "tax-1", "tax-2", "--vault", str(vault))
    assert code == 0
    assert done["data"]["reasons"] == {UNLABELLED: 2}
    assert done["data"]["carried"] == 4 and done["data"]["chats_relabelled"] == 2
    assert done["data"]["vault"]["created"] > 0
    code, again = _cli(capsys, "taxonomy", "relabel", "tax-1", "tax-2", "--vault", str(vault))
    assert again["data"]["vault"]["created"] == 0 and again["data"]["vault"]["written"] == 0


def test_dashboard_shows_what_the_vocabulary_does_not_cover(world: World) -> None:
    import io
    import re

    from knowledge_engine.ui.app import make_app

    world.import_second()
    captured: dict[str, str] = {}

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        captured["status"] = status

    environ = {"REQUEST_METHOD": "GET", "PATH_INFO": "/", "QUERY_STRING": "",
               "HTTP_HOST": "127.0.0.1:8765", "wsgi.input": io.BytesIO()}  # fmt: skip
    page = b"".join(make_app(world.settings)(environ, start_response)).decode("utf-8")
    assert captured["status"] == "200 OK"
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page))
    assert "tax-1" in text
    assert "2 chats with no label yet" in text
    assert "2 new since the last refresh" in text
