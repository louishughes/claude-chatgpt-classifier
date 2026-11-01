"""NOTE-040: a note shows each keyword idea once, without filler or title fragments.

The candidate list (NOTE-007) keeps everything with its reasons; these tests
check only what ``shown_keywords`` picks for the note, and that the full
list is left as it was.
"""

from __future__ import annotations

import itertools

from knowledge_engine.documents.keywords import (
    ChatInput,
    Tier,
    keyword_candidates,
    shown_keywords,
)
from knowledge_engine.domain.enums import Role
from knowledge_engine.extraction.text import ExtractionMessage
from knowledge_engine.taxonomy.aliases import AliasResolver
from knowledge_engine.taxonomy.registry import SnapshotTerm, TaxonomySnapshot

_n = itertools.count(1)


def _chat(cid: str, title: str, *texts: str) -> ChatInput:
    roles = [Role.USER, Role.ASSISTANT]
    messages = []
    for i, text in enumerate(texts):
        n = next(_n)
        messages.append(ExtractionMessage(f"m{n}", f"rev_{n:032x}", roles[i % 2], text))
    return ChatInput(cid, title, tuple(messages))


BED = _chat(
    "conv_bed",
    "Raised bed build",
    "Which wood suits the bed, cedar or pine? I prefer options that last.",
    "Cedar resists rot. Cedar boards and pine boards both work.",
    "Cedar Boards then, not pine boards. Is one board enough?",
    "A single board is too low; the bed needs boards stacked two high.",
    "Fine, stacked boards it is.",
)
OTHER = _chat("conv_other", "Soup", "Tomato soup without cream?", "Roast tomatoes first.")


def _shown(chat: ChatInput, resolver: AliasResolver | None = None) -> list[str]:
    result = keyword_candidates([chat, OTHER], resolver=resolver)[chat.conversation_id]
    return [k.term for k in shown_keywords(result, should=8)]


def test_a_case_or_plural_variant_is_shown_once() -> None:
    # "strategy" and "strategies" are more than one typing slip apart, so
    # the candidate list keeps both (the spelling fix only joins near misses).
    chat = _chat(
        "conv_plan",
        "Plan",
        "Which strategy wins? Each strategy has a cost.",
        "Two strategies stand out. Both strategies need wood.",
    )
    result = keyword_candidates([chat, OTHER])["conv_plan"]
    assert {"strategy", "strategies"} <= {k.term.casefold() for k in result.keywords}
    shown = _shown(chat)
    assert len([t for t in shown if t in ("strategy", "strategies")]) == 1
    # A capitalised spelling is shown in lower case, like the other words.
    assert "Cedar Boards" not in _shown(BED) and "cedar boards" in _shown(BED)


def test_a_word_only_said_inside_a_longer_keyword_is_left_out() -> None:
    chat = _chat(
        "conv_boards",
        "Wood",
        "Cedar boards or pine boards? Cedar resists rot.",
        "Cedar boards last; pine boards are cheaper. Cedar costs more.",
    )
    result = keyword_candidates([chat, OTHER])["conv_boards"]
    # "boards" is a candidate (said 4 times) ...
    assert "boards" in {k.term.casefold() for k in result.keywords}
    shown = _shown(chat)
    assert {"cedar boards", "pine boards"} <= set(shown)
    # ... but every time it is part of "cedar boards" or "pine boards".
    assert "boards" not in shown
    # "cedar" is also said on its own ("Cedar resists rot"), so it stays.
    assert "cedar" in shown


def test_a_title_word_the_chat_never_repeats_is_left_out() -> None:
    shown = _shown(BED)
    assert "raised" not in shown and "build" not in shown
    assert "bed" in shown  # a title word the chat keeps talking about stays


def test_filler_words_are_never_keywords() -> None:
    result = keyword_candidates([BED, OTHER])["conv_bed"]
    every = {k.term.casefold() for k in result.keywords}
    assert not every & {"prefer", "options", "prefer options"}


def test_the_full_candidate_list_is_unchanged() -> None:
    result = keyword_candidates([BED, OTHER])["conv_bed"]
    shown = shown_keywords(result, should=8)
    # Everything shown is a candidate, and the left-out ones are still there.
    assert {k.term.casefold() for k in shown} <= {k.term.casefold() for k in result.keywords}
    assert "raised" in {k.term.casefold() for k in result.keywords}


def test_an_approved_term_is_never_left_out() -> None:
    snapshot = TaxonomySnapshot(
        version="t",
        content_sha256="0" * 64,
        terms=(SnapshotTerm("trm_raised", "topic", "Raised", None, None, ()),),
        projects=(),
    )
    shown = shown_keywords(
        keyword_candidates([BED, OTHER], resolver=AliasResolver(snapshot))["conv_bed"],
        should=8,
    )
    [raised] = [k for k in shown if k.term_id == "trm_raised"]
    assert raised.term == "Raised"  # an approved term keeps its own spelling


def test_the_should_limit_counts_only_what_is_shown() -> None:
    result = keyword_candidates([BED, OTHER])["conv_bed"]
    shown = shown_keywords(result, should=1)
    assert sum(k.tier is Tier.SHOULD for k in shown) <= 1
