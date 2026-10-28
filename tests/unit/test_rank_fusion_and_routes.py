"""RET-004 fusion arithmetic and RET-005 question-type fixtures (no database)."""

from __future__ import annotations

import pytest

from knowledge_engine.extraction.records import RecordType
from knowledge_engine.retrieval.hybrid import RRF_K, fuse
from knowledge_engine.retrieval.planner import Route, codes, plan


def test_agreement_beats_a_single_first_place() -> None:
    fused = fuse({"lexical": ["a", "b", "c"], "semantic": ["d", "b"]})
    assert [f.key for f in fused][:3] == ["b", "a", "d"]  # found twice beats found once
    [b] = [f for f in fused if f.key == "b"]
    assert b.ranks == {"lexical": 2, "semantic": 2}
    assert b.score == pytest.approx(2 / (RRF_K + 2))


def test_fusion_is_deterministic_and_dedups_within_a_list() -> None:
    one = fuse({"lexical": ["x", "y", "x"], "semantic": ["y", "x"]})
    other = fuse({"semantic": ["y", "x"], "lexical": ["x", "y", "x"]})
    assert one == other
    # x and y tie exactly (1st + 2nd each): the key breaks the tie.
    assert [f.key for f in one] == ["x", "y"]
    assert one[0].ranks == {"lexical": 1, "semantic": 2}  # the repeat didn't count
    assert fuse({}) == [] and fuse({"lexical": []}) == []


# The question-type fixtures: question -> expected route.
ROUTES = [
    ("What game engine did I decide on?", Route.STRUCTURED),
    ("which database are we using now", Route.STRUCTURED),
    ("What did I reject for the logo?", Route.STRUCTURED),
    ("my preferences for code style", Route.STRUCTURED),
    ("current requirements for the export", Route.STRUCTURED),
    ("ERR-4012", Route.EXACT),
    ("where did I mention parse_export", Route.EXACT),
    ("find src/importer/run.py", Route.EXACT),
    ('"change of plan"', Route.EXACT),
    ("`retryAttempts`", Route.EXACT),
    ("why does the deploy fail with ERR-4012 on linux", Route.HYBRID),
    ("ideas for marketing a small game", Route.HYBRID),
    ("how do decision trees work", Route.HYBRID),  # decision words, but not about me
    ("python 3.12 pattern matching", Route.HYBRID),  # a version number is not a code
    ("", Route.EMPTY),
    ("   ?!  ", Route.EMPTY),
]


@pytest.mark.parametrize(("question", "route"), ROUTES)
def test_question_types_select_the_expected_route(question: str, route: Route) -> None:
    chosen = plan(question)
    assert chosen.route is route
    assert chosen.reasons  # every plan says why


def test_plans_carry_what_the_route_needs() -> None:
    assert plan("What did I reject for the logo?").record_types == (RecordType.REJECTION,)
    assert plan("do I still prefer tabs").record_types == (RecordType.PREFERENCE,)
    quoted = plan('show me “Synthetic note” and "change of plan"')
    assert quoted.query == "Synthetic note"
    assert quoted.exact_terms == ("Synthetic note", "change of plan")
    mixed = plan("why does the deploy fail with ERR-4012?")
    assert mixed.exact_terms == ("ERR-4012",)  # pinned inside the combined search
    assert plan("where is ERR-4012?").query == "ERR-4012"
    assert codes("see R2D2 and snake_case or camelCase in https://example.invalid/x") == [
        "R2D2",
        "snake_case",
        "camelCase",
        "https://example.invalid/x",
    ]
    assert plan("What game engine did I decide on?") == plan("What game engine did I decide on?")
