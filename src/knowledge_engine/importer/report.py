"""The import report: what one ``import_source`` call found and changed.

The report is the Import module's whole answer, and the one hand-off to
later stages: ``changed_revisions`` lists exactly the messages whose content
is new or different, so the semantic layer (M3) processes those and nothing
else. Everything in it is counts, codes and IDs; no message text, titles or
file names, so it's safe to print, log and store.

Talking points:
    - "The import's whole output is one report: counts, warnings, and the
      exact list of messages that changed."
    - "The report never contains private text, so it can be shown anywhere."
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from knowledge_engine.domain.enums import ImportBatchStatus


@dataclass(frozen=True)
class ImportReport:
    """The result of one import.

    Attributes:
        import_id: The batch's ID in the ledger.
        status: ``succeeded``, ``partial`` (some conversations failed) or
            ``failed``.
        format_id: The adapter used.
        conversations: Delta category -> count.
        messages: Delta category -> count.
        files: ``new`` and ``reused`` snapshot counts.
        warnings: Warning code -> count.
        changed_revisions: Revision IDs that are new or revised, sorted.
        raw_tree_hash_before: Raw tree signature before reading.
        raw_tree_hash_after: Raw tree signature after reading.
        model_calls_triggered: Always 0 in M1: importing never calls a model.
        new_branches: Forks that appeared in this import.
        raw_observations: New raw forms of messages (e.g. metadata drift).
    """

    import_id: str
    status: ImportBatchStatus
    format_id: str
    conversations: Mapping[str, int]
    messages: Mapping[str, int]
    files: Mapping[str, int]
    warnings: Mapping[str, int]
    changed_revisions: tuple[str, ...]
    raw_tree_hash_before: str
    raw_tree_hash_after: str
    model_calls_triggered: int = 0
    new_branches: int = 0
    raw_observations: int = 0
    extra: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-ready dict with sorted, stable content."""
        return {
            "import_id": self.import_id,
            "status": self.status.value,
            "format_id": self.format_id,
            "conversations": dict(sorted(self.conversations.items())),
            "messages": dict(sorted(self.messages.items())),
            "files": dict(sorted(self.files.items())),
            "warnings": dict(sorted(self.warnings.items())),
            "changed_revisions": len(self.changed_revisions),
            "raw_tree_unchanged": self.raw_tree_hash_before == self.raw_tree_hash_after,
            "model_calls_triggered": self.model_calls_triggered,
            "new_branches": self.new_branches,
            "raw_observations": self.raw_observations,
        }
