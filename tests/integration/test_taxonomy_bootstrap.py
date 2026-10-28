"""NOTE-006: bootstrapping the first taxonomy (pack -> plan -> proposals -> review)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from knowledge_engine.importer.run import run_import
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.segmentation.inventory import SegmentText, corpus_inventory
from knowledge_engine.settings import Settings
from knowledge_engine.taxonomy.bootstrap import (
    EXCERPT_CHARS,
    Decision,
    Plan,
    PlanError,
    PlanTerm,
    Review,
    apply_review,
    boilerplate,
    build_pack,
    file_plan,
    pack_sha256,
    review_sheet,
    summary_markdown,
)
from knowledge_engine.taxonomy.registry import TaxonomyRegistry

TOPICS = [
    ("garden", "raised bed timber cedar soil compost planting"),
    ("shed", "shed roof felt leak timber repair"),
    ("bread", "sourdough starter flour oven proving loaf"),
    ("cake", "sponge cake flour oven icing bake"),
    ("python", "python parser function test module import"),
    ("rust", "rust borrow checker compiler crate module"),
]


def _chat(cid: str, title: str, text: str) -> dict[str, Any]:
    def node(n: str, parent: str, role: str, body: str, t: float) -> dict[str, Any]:
        return {
            "id": n,
            "parent": parent,
            "children": [],
            "message": {
                "id": n,
                "author": {"role": role},
                "create_time": t,
                "content": {"content_type": "text", "parts": [body]},
                "metadata": {},
            },
        }

    mapping = {
        "root": {"id": "root", "parent": None, "children": ["u1"], "message": None},
        "u1": node("u1", "root", "user", f"Help me with {text}. " * 30, 1704067200.0),
        "a1": node("a1", "u1", "assistant", f"Sure, about {text}.", 1704067260.0),
    }
    mapping["u1"]["children"] = ["a1"]
    return {"id": cid, "title": title, "create_time": 1704067200.0, "mapping": mapping,
            "current_node": "a1"}  # fmt: skip


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    export = tmp_path / "export"
    export.mkdir()
    chats = [_chat(f"c-{name}", f"Synthetic {name}", text) for name, text in TOPICS]
    (export / "conversations.json").write_text(json.dumps(chats), encoding="utf-8")
    settings = Settings(workspace_root=tmp_path / "ws")
    run_import(export, "acct", format_id=None, settings=settings)
    with Session(create_sqlite_engine(database_path(settings))) as s:
        yield s


def _pack(session: Session) -> dict[str, Any]:
    return build_pack(list(corpus_inventory(session)), size=6, seed="test")


def _term(label: str, segments: list[str], children: tuple[PlanTerm, ...] = ()) -> PlanTerm:
    return PlanTerm(
        label=label,
        definition=f"Chats about {label.lower()}.",
        segments=tuple(segments),
        children=children,
    )


def _plan(pack: dict[str, Any]) -> Plan:
    seg = [s["segment_id"] for s in pack["segments"]]
    home = _term("Home and garden", seg[:2], (_term("Raised beds", seg[:1]),))
    food = _term("Cooking", seg[2:4], (_term("Bread", seg[2:3]), _term("Cakes", seg[3:4])))
    return Plan(
        pack_sha256=pack_sha256(pack),
        proposer="proposer-session-a",
        categories=(home, food),
        activities=(_term("Advice", seg[:3]),),
    )


def test_pack_is_a_fair_sample_with_short_excerpts(session: Session) -> None:
    pack = _pack(session)
    assert pack["corpus"] == {
        "conversations": 6,
        "segments": 6,
        "sampled": 6,
        "boilerplate_paragraphs": 0,
    }
    assert all(len(s["excerpt"]) <= EXCERPT_CHARS + 2 for s in pack["segments"])
    assert pack_sha256(pack) == pack_sha256(_pack(session))  # same seed, same pack


def test_boilerplate_paragraphs_are_left_out_of_excerpts() -> None:
    preamble = "The user provided the following information about themselves."
    items = [
        SegmentText(f"seg_{i}", f"conv_{i}", "active", 2, f"{preamble}\n\nTopic number {i}.")
        for i in range(7)
    ]
    assert boilerplate(items) == {preamble}
    pack = build_pack(items, size=7, seed="s")
    assert all(s["excerpt"].startswith("Topic number") for s in pack["segments"])


def test_a_plan_that_does_not_fit_the_pack_is_refused(session: Session) -> None:
    pack = _pack(session)
    good = _plan(pack)
    with pytest.raises(PlanError, match="different pack"):
        file_plan(session, good.model_copy(update={"pack_sha256": "0" * 64}), pack)
    stray = _term("Stray", ["seg_notinthepack"])
    with pytest.raises(PlanError, match="not in the pack"):
        file_plan(session, good.model_copy(update={"topics": (stray,)}), pack)
    seg = [pack["segments"][0]["segment_id"]]
    deep = _term("Top", seg, (_term("Mid", seg, (_term("Low", seg),)),))
    with pytest.raises(PlanError, match="third level"):
        file_plan(session, good.model_copy(update={"categories": (deep,)}), pack)
    twice = good.model_copy(update={"categories": (*good.categories, _term("cooking", seg))})
    with pytest.raises(PlanError, match="twice"):
        file_plan(session, twice, pack)
    with pytest.raises(ValidationError):
        Plan.model_validate({**json.loads(good.model_dump_json()), "new_field": 1})
    with pytest.raises(ValidationError):  # a term must rest on at least one sampled segment
        PlanTerm(label="Bare", definition="No evidence at all here.", segments=())
    assert review_sheet(session) == []  # nothing was filed by any refused plan


def test_categories_first_then_subcategories_after_review(session: Session) -> None:
    pack = _pack(session)
    plan = _plan(pack)
    filed = file_plan(session, plan, pack)
    assert len(filed.proposed) == 3 and filed.waiting_for_parent == 3
    sheet = review_sheet(session)
    assert {row["label"] for row in sheet} == {"Home and garden", "Cooking", "Advice"}
    assert all(row["segments"] and row["definition"] for row in sheet)

    # The proposer can't approve its own proposals.
    own = Review(
        reviewer=plan.proposer,
        decisions=tuple(
            Decision(proposal_id=r["proposal_id"], verdict="approve", note="looks right")
            for r in sheet
        ),
    )
    assert set(apply_review(session, own).refused) == {r["proposal_id"] for r in sheet}

    # A separate reviewer approves two (renaming one) and rejects one, with reasons.
    decisions = tuple(
        Decision(
            proposal_id=r["proposal_id"],
            verdict="reject" if r["label"] == "Advice" else "approve",
            note="too vague to be useful" if r["label"] == "Advice" else "clear and supported",
            label="Home" if r["label"] == "Home and garden" else None,
        )
        for r in sheet
    )
    applied = apply_review(session, Review(reviewer="reviewer-session-b", decisions=decisions))
    assert len(applied.approved) == 2 and len(applied.rejected) == 1 and not applied.refused

    # Filing again adds the subcategories under the now-approved categories, once.
    again = file_plan(session, plan, pack)
    assert len(again.proposed) == 3 and again.waiting_for_parent == 0
    children = review_sheet(session)
    assert {(r["label"], r["parent"]) for r in children} == {
        ("Raised beds", "Home"),
        ("Bread", "Cooking"),
        ("Cakes", "Cooking"),
    }
    assert file_plan(session, plan, pack).proposed == []  # nothing filed twice
    apply_review(
        session,
        Review(
            reviewer="reviewer-session-b",
            decisions=tuple(
                Decision(proposal_id=r["proposal_id"], verdict="approve", note="fits the parent")
                for r in children
            ),
        ),
    )
    page = summary_markdown(session)
    assert "- **Cooking**: Chats about cooking." in page
    assert "  - **Bread**: Chats about bread." in page
    assert "Advice: too vague to be useful" in page
    snapshot = TaxonomyRegistry(session).publish("tax-1", author="owner")
    assert {t.label for t in snapshot.terms} == {
        "Home",
        "Raised beds",
        "Cooking",
        "Bread",
        "Cakes",
    }


def test_cli_keeps_private_files_private_and_publishes(
    session: Session,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from knowledge_engine.cli.main import main

    session.close()
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(tmp_path / "ws"))
    public = tmp_path / "docs" / "pack.json"
    assert main(["--json", "taxonomy", "pack", "--out", str(public), "--sample", "6"]) == 2
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "not_private"
    assert not public.exists()
    private = tmp_path / "private" / "pack.json"
    assert main(["--json", "taxonomy", "pack", "--out", str(private), "--sample", "6"]) == 0
    capsys.readouterr()
    pack = json.loads(private.read_text(encoding="utf-8"))
    plan_file = tmp_path / "private" / "plan.json"
    plan_file.write_text(_plan(pack).model_dump_json(), encoding="utf-8")
    assert main(["--json", "taxonomy", "propose", str(plan_file), "--pack", str(private)]) == 0
    assert json.loads(capsys.readouterr().out)["data"]["waiting_for_parent"] == 3
    sheet_file = tmp_path / "private" / "sheet.json"
    assert main(["--json", "taxonomy", "sheet", "--out", str(sheet_file)]) == 0
    capsys.readouterr()
    sheet = json.loads(sheet_file.read_text(encoding="utf-8"))
    review_file = tmp_path / "private" / "review.json"
    review_file.write_text(
        json.dumps(
            {
                "reviewer": "reviewer-session-b",
                "decisions": [
                    {"proposal_id": r["proposal_id"], "verdict": "approve", "note": "supported"}
                    for r in sheet
                ],
            }
        ),
        encoding="utf-8",
    )
    assert main(["--json", "taxonomy", "review", str(review_file)]) == 0
    assert json.loads(capsys.readouterr().out)["data"]["approved"]
    assert main(["--json", "taxonomy", "publish", "tax-1", "--author", "owner"]) == 0
    assert json.loads(capsys.readouterr().out)["data"] == {"version": "tax-1", "terms": 3}
    assert main(["--json", "taxonomy", "publish", "tax-1", "--author", "owner"]) == 2
