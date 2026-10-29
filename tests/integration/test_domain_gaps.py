"""TAX-009: chats no domain fits become one proposal per subject, for a reviewer.

Synthetic chats. tax-1 has one domain, Programming. Three cooking chats
and three garden/room makeover chats fit no domain; one Python chat does.
Each uncovered subject becomes one new-domain proposal with quote anchors,
the vocabulary stays at tax-1, and neither a re-run nor a rejection brings
the same suggestion back.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
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


Text = str | tuple[str, str]  # a subject for the template, or (user, assistant)


def _chat(cid: str, text: Text, day: int) -> dict[str, Any]:
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
    asked, answer = (
        text
        if isinstance(text, tuple)
        else (f"Please help with {text}. " * 5, f"Here is advice about {text}.")
    )
    user = node("u", "root", "user", asked, start)
    reply = node("a", f"{cid}-u", "assistant", answer, start + 60)
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


def _build(tmp_path: Path, chats: Mapping[str, Text]) -> World:
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


def _import(root: Path, settings: Settings, chats: Mapping[str, Text]) -> None:
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
    # The four cooking chats are one group again, labelled as before.
    assert after.proposed == [] and after.rejected == ["Cooking"]


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
        "c-name-3": "the train times so bramble can visit",  # once in lower case
        **_python(4),
    }
    world = _build(tmp_path, chats)
    report = propose_domains(world.session, world.tax1, world.items())
    # The three chats are alike only through the name: the reviewer names the group.
    assert set(_open_domains(world.session)) == {"Unnamed group 1"} and report.unnamed == 1
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
    propose_domains(world.session, world.tax1, world.items())
    expected = {"cook": "Cooking", "gard": "Garden", "trav": "Travel"}
    assert set(_open_domains(world.session)) == {expected[k] for k in kinds}
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


@pytest.mark.parametrize(
    "texts",
    [
        ("notes for Bramble about the lease", "a card that Bramble will like",
         "the train times. Bramble can visit"),
        ("lease notes. Bramble asked about it", "card ideas. Bramble will like one",
         "train times. Bramble can visit"),
    ],
)  # fmt: skip
def test_a_name_at_a_sentence_start_is_still_a_name(
    tmp_path: Path, texts: tuple[str, str, str]
) -> None:
    chats = {f"c-name-{k}": text for k, text in enumerate(texts, 1)}
    world = _build(tmp_path, {**chats, **_python(4)})
    propose_domains(world.session, world.tax1, world.items())
    assert "Bramble" not in _open_domains(world.session)
    world.session.close()


def test_chats_that_share_their_cooking_words_stay_one_group(tmp_path: Path) -> None:
    """Bake and grill chats share "cooking" and "recipe": one subject, not two."""
    chats = {f"c-b-{i}": f"cooking recipe bake {x} tonight" for i, x in
             enumerate(("bread", "cake", "pie"))}  # fmt: skip
    chats |= {f"c-g-{i}": f"cooking recipe grill {x} tonight" for i, x in
              enumerate(("steak", "fish", "corn"))}  # fmt: skip
    world = _build(tmp_path, {**chats, **_python(10, "tonight")})
    propose_domains(world.session, world.tax1, world.items())
    assert {k: v["size"] for k, v in _open_domains(world.session).items()} == {"Cooking": 6}
    world.session.close()


def test_four_subjects_that_all_say_weekend_stay_apart(tmp_path: Path) -> None:
    subjects = {"cook": "cooking", "gard": "garden", "trav": "travel", "fit": "workout"}
    chats = {
        f"c-{kind}-{k}": f"{word} {kind}{k} this weekend"
        for kind, word in subjects.items()
        for k in ("one", "two", "three")
    }
    world = _build(tmp_path, {**chats, **_python(14)})
    propose_domains(world.session, world.tax1, world.items())
    assert set(_open_domains(world.session)) == {"Cooking", "Garden", "Travel", "Workout"}
    world.session.close()


def test_a_word_with_digits_is_one_word_and_anchors_resolve(tmp_path: Path) -> None:
    chats = {
        f"c-t-{k}": f"covid19 rules for {x}" for k, x in enumerate(("spain", "italy", "japan"))
    }
    world = _build(tmp_path, {**chats, **_python(6)})
    propose_domains(world.session, world.tax1, world.items())
    found = _open_domains(world.session)
    [(label, evidence)] = found.items()
    assert label == "Covid19" and len(evidence["anchors"]) == 3
    chats_by_id = {c.conversation_id: c for c, _ in world.items()}
    for anchor in evidence["anchors"]:
        [chat] = [c for c, s in world.items() if s.segment_id == anchor["segment_id"]]
        text = chats_by_id[chat.conversation_id].messages[anchor["message_id"]].text
        assert text[anchor["start"] : anchor["end"]] == "covid19"
    world.session.close()


def test_a_rejected_group_larger_than_the_display_cap_stays_rejected(tmp_path: Path) -> None:
    from knowledge_engine.taxonomy.domain_gaps import members_sha256

    chats = {f"c-cook-{k}": f"cooking a dish{k} recipe" for k in range(1, 111)}
    world = _build(tmp_path, {**chats, **_python(120)})
    session = world.session
    propose_domains(session, world.tax1, world.items())
    [row] = proposals(session, OPEN)
    evidence = json.loads(row.evidence_json)
    assert evidence["size"] == 110 and len(evidence["members"]) == 110
    assert len(evidence["segments"]) == 50 and len(evidence["anchors"]) == 50
    assert evidence["members_sha256"] == members_sha256(evidence["members"])
    reject(session, row.proposal_id, reviewer="reviewer-b", note="not a domain")
    session.commit()
    after = propose_domains(session, world.tax1, world.items())
    assert after.proposed == [] and after.rejected == ["Cooking"]
    session.close()


def test_a_rerun_after_more_chats_join_or_a_new_version_adds_nothing(world: World) -> None:
    session = world.session
    propose_domains(session, world.tax1, world.items())
    session.commit()
    more = {f"c-cook-{k}": f"cooking a dish{k} recipe" for k in range(4, 12)}
    _import(world.settings.workspace_root.parent / "export-2", world.settings, {**CHATS, **more})
    session.commit()
    save(session, SegmentClassifier(world.tax1).classify(world.items()))
    session.commit()
    assert propose_domains(session, world.tax1, world.items()).proposed == []
    tax2 = TaxonomyRegistry(session).publish("tax-2", author="owner")
    save(session, SegmentClassifier(tax2).classify(world.items()))
    session.commit()
    assert propose_domains(session, tax2, world.items()).proposed == []


# Realistic chats: several sentences each, the user's own wording, and the
# stock lines ChatGPT and its users add to any subject.
CLOSER = " Let me know if you'd like a printable checklist for this."
SIGN_OFF = (
    " Honestly I really don't know what I'm doing here, so any tips would be great."
    " Cheers in advance!"
)
REAL: dict[str, tuple[str, str]] = {
    "gard1": (
        "My tomato plants have yellow leaves at the bottom. I water them every day in the garden "
        "and they get lots of sun. I think it might be the soil.",
        "Yellow lower leaves on tomato plants often mean overwatering or a lack of nitrogen. Feed "
        "the soil and water the plants less often.",
    ),
    "gard2": (
        "When should I prune roses? I have a climbing rose on the garden fence that has got really"
        " out of hand. I don't want to kill it.",
        "Prune climbing roses in late winter. Cut out dead stems and tie the new growth to the "
        "fence horizontally for more flowers.",
    ),
    "gard3": (
        "Slugs are eating all my lettuce seedlings in the vegetable patch. Is there a good way to "
        "stop them without poisoning the birds in the garden?",
        "Try copper tape, beer traps or a night-time hunt with a torch. Raised beds and gritty "
        "soil around the seedlings also help.",
    ),
    "gard4": (
        "What can I plant in a shady corner of the garden? The soil is quite heavy clay and it "
        "stays damp. I really want some colour there.",
        "Ferns, hostas and hellebores like shade and damp clay soil. Add compost when you plant to"
        " improve the drainage.",
    ),
    "cook1": (
        "I'm trying to make a lasagne for my family this weekend and I really don't know how long "
        "to bake it. Should I cover it with foil?",
        "Bake the lasagne covered with foil for about 25 minutes, then uncover it so the cheese "
        "browns. Let it rest before slicing.",
    ),
    "cook2": (
        "How do I stop rice going sticky? Every time I cook rice it turns into a mush in the pan. "
        "Any good tips?",
        "Rinse the rice until the water runs clear, use the right ratio of water, and let it steam"
        " off the heat with the lid on.",
    ),
    "trav1": (
        "I'm planning a trip to Lisbon in April. Is it worth getting a travel card for the trams "
        "and metro, and which area is best to stay in for a first visit?",
        "A rechargeable travel card covers trams and metro. For a first trip, stay in Baixa or "
        "Chiado so you can walk to most sights.",
    ),
    "trav2": (
        "We have a long layover in Singapore airport, about nine hours. Is it worth leaving the "
        "airport, and do I need a visa for a short trip into the city?",
        "Many passports get a visa-free entry. Nine hours is enough for a quick trip to Marina "
        "Bay, but leave time for security on the way back to the airport.",
    ),
    "trav3": (
        "What should I pack for a week of hiking in Scotland in October? I'm flying with only hand"
        " luggage and the weather looks unpredictable for the trip.",
        "Pack waterproof layers, a warm fleece and broken-in boots. For hand luggage only, wear "
        "the boots on the flight and pack light layers.",
    ),
    "money1": (
        "I have about five thousand pounds in savings. Should I pay off my credit card first or "
        "put money into an ISA? The card has twenty percent interest.",
        "Pay off the credit card first: twenty percent interest costs more than an ISA will earn. "
        "Then start saving into the ISA.",
    ),
    "money2": (
        "How do I make a monthly budget that actually works? I always run out of money before "
        "payday even though my salary should be enough.",
        "List your fixed bills, set a weekly spending limit, and move savings out on payday.",
    ),
    "money3": (
        "Is it better to overpay my mortgage or invest the extra money in an index fund? My "
        "mortgage rate is four percent and I have a pension already.",
        "With a four percent mortgage rate an index fund may earn more over time, but overpaying "
        "is a guaranteed return.",
    ),
    "code1": (
        "My python script crashes when it reads a large CSV file. How do I read it in chunks?",
        "Use pandas read_csv with chunksize, or the csv module to stream rows.",
    ),
    "code2": (
        "How do I write a python unit test for a function that calls an API?",
        "Use unittest.mock to patch the API call in python, and return a fake response.",
    ),
}


def _members(world: World) -> dict[str, list[str]]:
    natives = {cid: native for native, cid in world.chats().items()}
    segment_chat = {s.segment_id: natives[c.conversation_id] for c, s in world.items()}
    found = {}
    for row in proposals(world.session, OPEN):
        evidence = json.loads(row.evidence_json)
        label = json.loads(row.payload_json)["label"]
        found[label] = sorted(segment_chat[m] for m in evidence["members"])
    return found


def test_realistic_chats_group_by_subject_and_nothing_else(tmp_path: Path) -> None:
    world = _build(tmp_path, REAL)
    propose_domains(world.session, world.tax1, world.items())
    groups = _members(world)
    assert groups["Garden"] == ["gard1", "gard2", "gard3", "gard4"]
    assert groups["Money"] == ["money1", "money2", "money3"]
    # No group mixes subjects.
    for members in groups.values():
        assert len({m.rstrip("0123456789") for m in members}) == 1
    world.session.close()


def test_stock_closers_and_sign_offs_do_not_merge_subjects(tmp_path: Path) -> None:
    chats: dict[str, Text] = {
        native: (asked + SIGN_OFF, answer + CLOSER)
        for native, (asked, answer) in REAL.items()
        if native[:4] in ("cook", "gard")
    }
    chats |= {f"c-code-{k}": f"python script number {k}" for k in range(1, 9)}
    world = _build(tmp_path, chats)
    report = propose_domains(world.session, world.tax1, world.items())
    groups = _members(world)
    assert "Checklist" not in groups and "Advance" not in groups and "Cheers" not in groups
    for members in groups.values():
        assert len({m.rstrip("0123456789") for m in members}) == 1
    assert groups.get("Garden") == ["gard1", "gard2", "gard3", "gard4"]
    assert report.uncovered == 6
    world.session.close()


def test_linking_two_thousand_segments_is_quick() -> None:
    import random
    import time

    from knowledge_engine.taxonomy.domain_gaps import _components

    rng = random.Random(2)
    words = [f"w{k}x" for k in range(400)]
    vectors = {i: {w: 1.0 for w in rng.sample(words[(i % 4) * 100 : (i % 4) * 100 + 100], 15)}
               for i in range(2000)}  # fmt: skip
    users = {i: set(v) for i, v in vectors.items()}
    started = time.perf_counter()
    groups = _components(vectors, users)
    assert time.perf_counter() - started < 2.0
    # Four subjects of 500; a few random signatures overlap too little to link.
    big = [g for g in groups if len(g) > 1]
    assert len(big) == 4 and sum(map(len, big)) > 1900
    assert all(len({i % 4 for i in g}) == 1 for g in big)
