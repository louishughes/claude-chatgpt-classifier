"""RET-001: queries never reach FTS5 as syntax."""

from __future__ import annotations

import sqlite3

from hypothesis import given
from hypothesis import strategies as st

from knowledge_engine.retrieval.lexical import SearchMode, match_expression


def test_words_are_quoted() -> None:
    assert match_expression('NOT "x" OR y*', SearchMode.TOKENS) == '"NOT" "x" "OR" "y"'
    assert match_expression("a b", SearchMode.PHRASE) == '"a b"'
    assert match_expression(" ( * ) ", SearchMode.TOKENS) is None


@given(st.text(), st.sampled_from(list(SearchMode)))
def test_any_query_is_a_valid_match_expression(query: str, mode: SearchMode) -> None:
    expression = match_expression(query, mode)
    if expression is None:
        return
    db = sqlite3.connect(":memory:")
    db.execute("CREATE VIRTUAL TABLE t USING fts5(x, tokenize='unicode61 remove_diacritics 2')")
    db.execute("INSERT INTO t VALUES ('synthetic text')")
    db.execute("SELECT * FROM t WHERE t MATCH ?", (expression,)).fetchall()  # must not raise
