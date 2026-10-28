"""NOTE-007: per-chat keyword and topic candidates, deterministic, with reasons."""

from __future__ import annotations

import itertools
import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from knowledge_engine.documents.keywords import (
    ChatInput,
    Tier,
    keyword_candidates,
    propose_topics,
)
from knowledge_engine.domain.enums import Role
from knowledge_engine.extraction.text import ExtractionMessage
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.infrastructure.migrations import upgrade_to_head
from knowledge_engine.settings import Settings
from knowledge_engine.taxonomy.aliases import AliasResolver, MatchStatus
from knowledge_engine.taxonomy.registry import SnapshotTerm, TaxonomySnapshot
from knowledge_engine.taxonomy.review import OPEN, proposals

_n = itertools.count(1)


def _msg(role: Role, text: str) -> ExtractionMessage:
    n = next(_n)
    return ExtractionMessage(f"m{n}", f"rev_{n:032x}", role, text)


def _chat(cid: str, title: str, *texts: str, topics: tuple[str, ...] = ()) -> ChatInput:
    roles = [Role.USER, Role.ASSISTANT]
    return ChatInput(cid, title, tuple(_msg(roles[i % 2], t) for i, t in enumerate(texts)), topics)


GAME = _chat(
    "conv_game",
    "Help with Unreal Engine lighting",
    "My scene in Unreal Engine looks flat. How do I fix the lighting?",
    "In Unreal Engine, add a skylight and turn on lumen global illumination. "
    "Lumen global illumination bounces light around the scene.",
    "I tried it in Unreal Engnie and the lumen global illumination is noisy.",
    "Raise the lumen quality setting; noisy lumen global illumination usually needs more samples.",
)
PIRATE = _chat(
    "conv_pirate",
    "Story time",
    "You are a pirate captain on a ghost ship. Always speak like a pirate captain, "
    "never break character, and end every answer with a sea shanty verse. "
    "Stay in character as the pirate captain for the whole chat no matter what I ask.",
    "Arr, aye aye. What be your question, matey?",
    "Write a short bedtime story about a lighthouse keeper and a lighthouse cat.",
    "Once upon a time the lighthouse keeper fed the lighthouse cat every night.",
)
SOUP = _chat(
    "conv_soup",
    "Tomato soup recipe",
    "How do I make tomato soup without cream?",
    "Roast the tomatoes, then blend the roasted tomatoes with stock for tomato soup.",
)


def _terms(result: object, tier: Tier) -> list[str]:
    return [k.term for k in result.tier(tier)]  # type: ignore[attr-defined]


def test_title_words_and_named_things_are_must_and_repeated_phrases_should() -> None:
    result = keyword_candidates([GAME, PIRATE, SOUP])["conv_game"]

    must = _terms(result, Tier.MUST)
    assert "Unreal" in must and "Engine" in must and "lighting" in must  # title words
    assert "Unreal Engine" in must  # a named thing, in its written case
    should = _terms(result, Tier.SHOULD)
    assert "lumen global illumination" in should
    # "global" is only ever said inside the longer phrase, so it isn't listed alone.
    assert "global" not in should
    top = result.tier(Tier.SHOULD)[0]
    assert top.reasons and top.message_ids and top.score > 0


def test_a_misspelt_entity_is_read_as_the_right_term() -> None:
    result = keyword_candidates([GAME, PIRATE, SOUP])["conv_game"]

    [named] = [k for k in result.keywords if k.term == "Unreal Engine"]
    assert "Engnie" not in " ".join(k.term for k in result.keywords)
    assert named.variants == ("Unreal Engnie",)
    assert len(named.message_ids) == 3  # the misspelt mention counts too


def test_a_pasted_preamble_gives_no_keywords_but_says_why() -> None:
    result = keyword_candidates([GAME, PIRATE, SOUP])["conv_pirate"]

    terms = " ".join(k.term for k in result.keywords).casefold()
    assert "pirate" not in terms and "captain" not in terms
    assert "lighthouse keeper" in terms
    reasons = {e.term: e.reason for e in result.excluded}
    assert "pirate captain" in reasons
    assert "role-play" in reasons["pirate captain"]


def test_a_general_title_word_is_excluded_with_a_reason() -> None:
    result = keyword_candidates([GAME, PIRATE, SOUP])["conv_game"]

    assert "help" not in {k.term.casefold() for k in result.keywords}
    assert any(e.term == "help" and "too general" in e.reason for e in result.excluded)


def test_a_phrase_in_most_chats_is_not_specific() -> None:
    chats = [
        _chat(
            f"conv_{i}",
            f"Topic {i}",
            f"Draft the weekly report. The weekly report covers item{i}.",
            "ok",
        )
        for i in range(6)
    ]
    chats += [_chat("conv_x", "Garden", "Plant the tulip bulbs; tulip bulbs like sun.")]
    result = keyword_candidates(chats)["conv_0"]

    assert "weekly report" not in {k.term for k in result.keywords}
    assert any(e.term == "weekly report" and "not specific" in e.reason for e in result.excluded)


def test_same_chats_in_same_keywords_out() -> None:
    first = keyword_candidates([GAME, PIRATE, SOUP])
    again = keyword_candidates([SOUP, PIRATE, GAME])
    assert first == again


def _snapshot() -> TaxonomySnapshot:
    return TaxonomySnapshot(
        version="tax-test",
        content_sha256="0" * 64,
        terms=(
            SnapshotTerm("term_unreal", "topic", "Unreal Engine", None, None, ("UE5", "Unreal")),
            SnapshotTerm("term_cook", "topic", "Cooking", None, None, ("recipes",)),
        ),
        projects=(),
    )


def test_topics_match_approved_terms_or_stay_candidates() -> None:
    chat = _chat(
        "conv_t",
        "Engine",
        "UE5 crashes when I open the level. UE5 again.",
        topics=("Unreal", "Level streaming"),
    )
    result = keyword_candidates([chat], resolver=AliasResolver(_snapshot()))["conv_t"]

    by_text = {t.text: t for t in result.topics}
    assert by_text["Unreal"].term_id == "term_unreal"
    assert by_text["Level streaming"].status is MatchStatus.UNMATCHED
    [ue5] = [k for k in result.keywords if k.term_id == "term_unreal"]
    assert ue5.term == "Unreal Engine" and ue5.tier is Tier.MUST


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    settings = Settings(workspace_root=tmp_path / "ws")
    engine = create_sqlite_engine(database_path(settings))
    upgrade_to_head(engine)
    with Session(engine) as s:
        yield s
    engine.dispose()


def test_unmatched_topics_become_proposals_once_never_labels(session: Session) -> None:
    chats = [
        _chat("conv_a", "A", "text", topics=("Sourdough baking", "Cooking")),
        _chat("conv_b", "B", "text", topics=("sourdough  baking",)),
    ]
    results = keyword_candidates(chats, resolver=AliasResolver(_snapshot())).values()

    created = propose_topics(session, results, proposer="note-007-test")
    assert len(created) == 1  # "Cooking" is approved; the two spellings are one topic
    [row] = proposals(session, OPEN)
    assert json.loads(row.payload_json) == {"dimension": "topic", "label": "Sourdough baking"}
    assert json.loads(row.evidence_json)["conversation_ids"] == ["conv_a", "conv_b"]
    assert propose_topics(session, results, proposer="note-007-test") == []  # already waiting
