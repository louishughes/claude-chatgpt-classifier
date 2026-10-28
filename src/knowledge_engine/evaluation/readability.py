"""Readability checks for a vault's notes, read from the files alone (NOTE-010).

The rich-note layout (``docs/plans/RICH_NOTES_GAP_ANALYSIS.md`` §7) makes
three promises a program can check without the database:

* **budget**: a note stays short enough to read. A chat's rich note has a
  body budget that grows with the chat's length (``body_budget``), so a
  three-message chat fits on a screen or two;
* **empty_evidence**: an empty section is one plain sentence. An evidence
  box (``> [!quote]``) in a section with no item has nothing to support,
  which is the padding the old v2 notes were full of;
* **properties**: the front matter holds only what Obsidian and Dataview
  query: plain values and lists of plain values, no nested maps (Dataview
  can't filter on them easily), and no hashes or run IDs (those belong in
  the ``.meta`` JSON sidecar, out of the reader's way).

``ke docs check`` runs these next to the link checks. Budgets and the
properties rule only apply to notes whose ``generator`` promises the new
layout; older notes (DOC-003, DOC-005) are counted as not checked rather
than failed, because they were never written to that standard. The
evidence rule applies to every note, since an empty evidence box is never
right.

Nothing here opens the database or calls a model, and a problem names the
note and the section, never chat text.

Talking points:
    - "`ke docs check` now fails a note that is too long for its chat, or
      that shows an evidence box with nothing above it."
    - "It reads the files the way Obsidian does, so it works on any vault."
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from knowledge_engine.documents.rich_note import TEMPLATE_VERSION, body_budget
from knowledge_engine.documents.vault import MARKER

READABILITY_VERSION = "note-010-v1"

# Property names that hold machine bookkeeping. They are fine in the sidecar,
# but in the front matter they are noise a reader scrolls past.
BOOKKEEPING = frozenset(
    {"content_hash", "document_id", "record_ids", "revision_ids", "stage_key", "run_id"}
)
# A long hex string is a hash, whatever the property is called.
_HASH = re.compile(r"^[0-9a-f]{32,}$")
_HEADING = re.compile(r"^## (.+)$", re.MULTILINE)


def _rich_note_budget(properties: Mapping[str, object]) -> int | None:
    messages = properties.get("messages")
    return body_budget(messages) if isinstance(messages, int) and messages >= 0 else None


# generator -> how to work out the note's body budget from its own properties.
# A generator listed here has promised the §7 layout.
BUDGETS: dict[str, Callable[[Mapping[str, object]], int | None]] = {
    TEMPLATE_VERSION: _rich_note_budget,
}


@dataclass(frozen=True)
class ReadabilityProblem:
    """One problem in one note (paths and section titles only, no chat text)."""

    note: str  # path in the vault
    check: str  # budget, empty_evidence or properties
    detail: str


def check_note(
    key: str, properties: Mapping[str, object] | None, body: str
) -> tuple[bool, list[ReadabilityProblem]]:
    """Check one note.

    Args:
        key: The note's path in the vault (for the report).
        properties: Its parsed front matter, or None when it has none.
        body: Everything after the front matter.

    Returns:
        Whether the note promised the §7 layout (so its budget and
        properties were checked), and the problems found.
    """
    # What you write below the vault's marker line is yours: it isn't the
    # engine's note, so it never counts against the budget.
    body = body.split(f"\n{MARKER}", 1)[0]
    problems = [
        ReadabilityProblem(key, "empty_evidence", f"{title}: evidence box with no item")
        for title in _empty_evidence(body)
    ]
    generator = str((properties or {}).get("generator", ""))
    budget_of = BUDGETS.get(generator)
    if budget_of is None or properties is None:
        return False, problems
    limit = budget_of(properties)
    if limit is None:
        problems.append(ReadabilityProblem(key, "budget", "no usable length property"))
    elif len(body) > limit:
        problems.append(
            ReadabilityProblem(key, "budget", f"{len(body)} characters, budget {limit}")
        )
    problems += [ReadabilityProblem(key, "properties", p) for p in _property_problems(properties)]
    return True, problems


def _empty_evidence(body: str) -> list[str]:
    """Titles of sections that hold an evidence box but no item for it to support."""
    parts = _HEADING.split(body)
    found = []
    for title, content in zip(parts[1::2], parts[2::2], strict=True):
        lines = content.splitlines()
        has_box = any(line.startswith("> [!quote]") for line in lines)
        # An item is a bullet or a table row; the box hangs under one of them.
        has_item = any(line.startswith(("- ", "| ")) for line in lines)
        if has_box and not has_item:
            found.append(title.strip())
    return found


def _property_problems(properties: Mapping[str, object]) -> list[str]:
    """What in the front matter Dataview can't use, or a reader doesn't need."""
    problems = []
    for name, value in properties.items():
        if name in BOOKKEEPING:
            problems.append(f"{name}: bookkeeping belongs in the .meta sidecar")
            continue
        values = value if isinstance(value, list) else [value]
        if isinstance(value, dict) or any(isinstance(v, dict | list) for v in values):
            problems.append(f"{name}: nested values; use a flat list of plain values")
        elif any(isinstance(v, str) and _HASH.fullmatch(v) for v in values):
            problems.append(f"{name}: looks like a hash; it belongs in the .meta sidecar")
    return problems
