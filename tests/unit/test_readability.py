"""NOTE-010: the readability rules, on hand-made notes (no database)."""

from __future__ import annotations

from knowledge_engine.documents.rich_note import TEMPLATE_VERSION, body_budget
from knowledge_engine.documents.vault import MARKER
from knowledge_engine.evaluation.readability import check_note

RICH = {"generator": TEMPLATE_VERSION, "messages": 4}


def _checks(properties: dict[str, object] | None, body: str) -> list[str]:
    return [p.check for p in check_note("N.md", properties, body)[1]]


def test_a_rich_note_over_its_budget_fails_and_one_under_passes() -> None:
    limit = body_budget(4)
    assert _checks(RICH, "x" * limit) == []
    assert _checks(RICH, "x" * (limit + 1)) == ["budget"]


def test_what_you_write_below_the_marker_is_not_counted() -> None:
    body = "short note\n" + MARKER + "\n" + "my own notes " * 5_000
    assert _checks(RICH, body) == []


def test_an_evidence_box_needs_an_item_in_its_section() -> None:
    empty = "## Decisions\n*From the chat*\n\nNothing was decided.\n\n> [!quote]- Evidence\n> m1\n"
    item = "## Decisions\n- **Use cedar.** Decided.\n> [!quote]- Evidence\n> m1\n"
    assert _checks(RICH, empty) == ["empty_evidence"]
    assert _checks(RICH, item) == []
    # The rule holds for every note, not only the new layout.
    assert _checks({"generator": "doc-003-v1"}, empty) == ["empty_evidence"]


def test_older_notes_are_not_held_to_the_budget() -> None:
    readable, problems = check_note("Old.md", {"generator": "doc-003-v1"}, "x" * 100_000)
    assert not readable and problems == []
    assert not check_note("Plain.md", None, "x" * 100_000)[0]


def test_front_matter_is_flat_and_free_of_bookkeeping() -> None:
    properties = {
        **RICH,
        "tags": ["timber", "garden"],
        "date": "2024-01-01",
        "content_hash": "abc",
        "source": "0123456789abcdef0123456789abcdef",
        "facets": {"activity": ["advice"]},
        "pairs": [["a", "b"]],
    }
    problems = check_note("N.md", properties, "body")[1]
    flagged = sorted(p.detail.split(":")[0] for p in problems if p.check == "properties")
    assert flagged == ["content_hash", "facets", "pairs", "source"]


def test_a_length_it_cannot_read_is_reported() -> None:
    assert _checks({"generator": TEMPLATE_VERSION, "messages": "many"}, "body") == ["budget"]
