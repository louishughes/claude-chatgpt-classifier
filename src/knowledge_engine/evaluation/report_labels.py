"""What every accuracy number was scored against, and who checked it (LEG-002, REV-012).

Older attempts printed AI-made verdicts under owner-sounding headings. So
every scored report now starts with an ``AnswerKey`` block:

* the answer key's **version** (name and schema) and **SHA-256**;
* the **reviewer label**, from ``ReviewerKind``:
  ``owner`` -> "owner-approved";
  ``ai_session`` -> "agent-reviewed, not owner-approved";
  ``same_model`` -> "checked by the same model that made it, not owner-approved";
  ``none`` -> "not reviewed, not owner-approved";
* the **review file's SHA-256** when someone reviewed it.

The heading "Owner verdict" prints **only** for ``owner``. Every other
kind prints "AI check (not owner-verified)". A key that is missing its
version, hash or label refuses to render, and a report with no key at all
prints "unscored" instead of numbers.

Talking points:
    - "Every score says which answer key it used, its fingerprint, and
      whether I approved the key or an AI reviewed it."
    - "Only my own review can produce the words 'Owner verdict'."
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from knowledge_engine.evaluation.gold import GoldSet, load_gold

OWNER_HEADING = "Owner verdict"
AI_HEADING = "AI check (not owner-verified)"
UNSCORED = "unscored"
_SHA = re.compile(r"[0-9a-f]{64}")


class ReviewerKind(StrEnum):
    """Who reviewed the answer key."""

    OWNER = "owner"
    AI_SESSION = "ai_session"
    SAME_MODEL = "same_model"
    NONE = "none"


REVIEW_LABELS = {
    ReviewerKind.OWNER: "owner-approved",
    ReviewerKind.AI_SESSION: "agent-reviewed, not owner-approved",
    ReviewerKind.SAME_MODEL: "checked by the same model that made it, not owner-approved",
    ReviewerKind.NONE: "not reviewed, not owner-approved",
}


@dataclass(frozen=True)
class AnswerKey:
    """The answer key a report was scored against.

    Attributes:
        version: e.g. ``golden-synthetic-v1 (gold-v1)``.
        sha256: The key's fingerprint (file bytes, or canonical content).
        reviewer_kind: Who reviewed it.
        review_sha256: The review file's fingerprint; required for every
            kind except ``none``, so a "reviewed" claim points at a record.
    """

    version: str
    sha256: str
    reviewer_kind: ReviewerKind
    review_sha256: str | None = None

    def __post_init__(self) -> None:
        """Turn a plain string kind into the enum, or refuse an unknown one."""
        # "owner" as a plain string must not slip past the ``is OWNER`` check.
        object.__setattr__(self, "reviewer_kind", ReviewerKind(self.reviewer_kind))

    @property
    def heading(self) -> str:
        """``Owner verdict`` for the owner's own review only."""
        return OWNER_HEADING if self.reviewer_kind is ReviewerKind.OWNER else AI_HEADING

    @property
    def label(self) -> str:
        """The reviewer label, e.g. "agent-reviewed, not owner-approved"."""
        return REVIEW_LABELS[self.reviewer_kind]

    def lines(self) -> list[str]:
        """The block every scored report starts with.

        Raises:
            ValueError: The version, hash or label is missing, or a review
                is claimed without a review hash.
        """
        if not self.version.strip():
            raise ValueError("a scored report needs the answer-key version")
        if not _SHA.fullmatch(self.sha256):
            raise ValueError("a scored report needs the answer-key SHA-256")
        if self.reviewer_kind not in REVIEW_LABELS:
            raise ValueError("a scored report needs a reviewer label")
        if self.reviewer_kind is not ReviewerKind.NONE and not (
            self.review_sha256 and _SHA.fullmatch(self.review_sha256)
        ):
            raise ValueError("a reviewed key needs its review file's SHA-256")
        lines = [
            f"## {self.heading}",
            "",
            f"- Answer key: `{self.version}`, SHA-256 `{self.sha256}`",
            f"- Reviewer: {self.label} (`{self.reviewer_kind.value}`)",
        ]
        if self.review_sha256:
            lines.append(f"- Review file SHA-256: `{self.review_sha256}`")
        return [*lines, ""]


def sha256_file(path: Path) -> str:
    """A file's SHA-256."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def key_from_gold(gold: GoldSet) -> AnswerKey:
    """A key for an in-memory set: canonical-content hash, no review claimed."""
    content = json.dumps(gold.model_dump(mode="json"), sort_keys=True, ensure_ascii=False)
    return AnswerKey(
        version=f"{gold.name} ({gold.schema_version})",
        sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        reviewer_kind=ReviewerKind.NONE,
    )


def key_from_file(
    path: Path, reviewer_kind: ReviewerKind, review_file: Path | None = None
) -> AnswerKey:
    """A key for a gold file on disk, with who reviewed it and the review's hash."""
    gold = load_gold(path)
    return AnswerKey(
        version=f"{gold.name} ({gold.schema_version})",
        sha256=sha256_file(path),
        reviewer_kind=reviewer_kind,
        review_sha256=sha256_file(review_file) if review_file is not None else None,
    )
