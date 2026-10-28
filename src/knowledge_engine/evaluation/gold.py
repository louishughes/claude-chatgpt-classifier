"""The golden set: hand-made answer keys for classification and extraction (EVAL-001).

A golden set says, for chosen conversations, what a careful person expects:

* per **segment** (named by its first message): the primary and secondary
  labels for each field (a dimension or ``projects``), or ``ambiguous``
  when even a person can't decide (an ambiguous segment is scored as
  "should go to review", never as a right or wrong label);
* the **records** that must be found: type, who holds it, how acceptance
  is known, and the message that carries the evidence;
* the **forbidden** records that must *never* be produced, above all an
  assistant suggestion turned into a user decision.

Two kinds of golden set use the same schema:

* the **synthetic** set lives in ``tests/fixtures/gold/`` and covers the
  synthetic fixture cases. It is safe to commit and runs in CI;
* the **real** set holds the owner's private conversations. It lives in
  the git-ignored workspace (``<workspace>/gold/``), never in Git.
  ``annotation_template`` starts one from a seeded, diverse selection of
  conversations, with IDs only and no message text.

``GOLD_SCHEMA_VERSION`` versions the format; a set records the taxonomy
version its labels use, so scores are only compared under the same
vocabulary. The annotation guide is ``docs/evaluation/ANNOTATION_GUIDE.md``.

Talking points:
    - "The golden set lists what must be found and what must never be
      claimed, and the real one never leaves my machine."
    - "If a person can't decide a label, the answer key says 'ambiguous',
      and the right system behaviour is to ask for review."
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, model_validator

from knowledge_engine.domain.enums import Role
from knowledge_engine.extraction.records import Acceptance, RecordType, Strength
from knowledge_engine.segmentation.inventory import SegmentText, sample
from knowledge_engine.taxonomy.registry import (
    Dimension,
    SnapshotProject,
    SnapshotTerm,
    TaxonomySnapshot,
)

GOLD_SCHEMA_VERSION = "gold-v1"
FIELDS = tuple(d.value for d in Dimension) + ("projects",)


class _Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class GoldLabels(_Strict):
    """Expected labels for one field of one segment."""

    primary: str | None = None
    secondary: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _check(self) -> GoldLabels:
        if self.secondary and self.primary is None:
            raise ValueError("secondary labels need a primary")
        if self.primary in self.secondary or len(set(self.secondary)) != len(self.secondary):
            raise ValueError("a label is listed twice")
        return self


class GoldSegment(_Strict):
    """A segment's expected labels.

    Attributes:
        first_message: The native ID of its first message (segment IDs can
            change with the segmenter version; the first message doesn't).
        labels: Field name -> expected labels. A field left out is "no
            label expected".
        ambiguous: A person couldn't decide; the system should flag review.
        note: Why, in a few words (no private text in the synthetic set).
    """

    first_message: str = Field(min_length=1)
    labels: dict[str, GoldLabels] = Field(default_factory=dict)
    ambiguous: bool = False
    note: str | None = None

    @model_validator(mode="after")
    def _check(self) -> GoldSegment:
        unknown = sorted(set(self.labels) - set(FIELDS))
        if unknown:
            raise ValueError(f"unknown fields {unknown}")
        return self


class GoldRecord(_Strict):
    """A record that must be extracted."""

    record_type: RecordType
    actor: Role
    message_id: str = Field(min_length=1)
    acceptance: Acceptance | None = None
    attributed_to: str | None = None
    strength: Strength | None = None
    # Words copied exactly from the cited message (REV-011). Optional so keys
    # written before the rule stay valid; not scored, it is for reviewers.
    quote: str | None = Field(default=None, min_length=1)


class GoldForbidden(_Strict):
    """A record that must never be produced (EVAL-004 counts any as a failure)."""

    record_type: RecordType
    actor: Role
    message_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    quote: str | None = Field(default=None, min_length=1)  # see GoldRecord.quote


class GoldConversation(_Strict):
    """The answer key for one conversation.

    ``records_annotated`` says the ``records`` list is complete: only then
    is an extracted record that isn't listed a false positive. A
    conversation annotated for labels only leaves it false.
    """

    native_conversation_id: str = Field(min_length=1)
    fixture_case: str | None = None
    annotator: str = Field(min_length=1)
    reviewed_by: str | None = None
    records_annotated: bool = False
    segments: tuple[GoldSegment, ...] = ()
    records: tuple[GoldRecord, ...] = ()
    forbidden: tuple[GoldForbidden, ...] = ()

    @model_validator(mode="after")
    def _check(self) -> GoldConversation:
        if self.reviewed_by and self.reviewed_by.casefold() == self.annotator.casefold():
            raise ValueError("the reviewer must not be the annotator")
        if self.records and not self.records_annotated:
            raise ValueError("records listed, so records_annotated must be true")
        firsts = [s.first_message for s in self.segments]
        if len(set(firsts)) != len(firsts):
            raise ValueError("two segments share a first message")
        return self


class GoldTerm(_Strict):
    """A vocabulary term, for a synthetic set that brings its own taxonomy."""

    term_id: str
    dimension: Dimension
    label: str
    aliases: tuple[str, ...] = ()


class GoldProject(_Strict):
    """A project, for a synthetic set that brings its own taxonomy."""

    project_id: str
    name: str
    aliases: tuple[str, ...] = ()


class GoldSet(_Strict):
    """A whole golden set.

    Attributes:
        schema_version: ``gold-v1``.
        name: e.g. ``golden-synthetic-v1`` or ``golden-v1``.
        synthetic: True only for the committed synthetic set.
        taxonomy_version: The vocabulary version the labels use.
        terms, projects: The vocabulary itself, for a synthetic set only
            (a real set uses a published version from the database).
        conversations: The answer keys.
    """

    schema_version: str = GOLD_SCHEMA_VERSION
    name: str = Field(min_length=1)
    synthetic: bool
    taxonomy_version: str = Field(min_length=1)
    terms: tuple[GoldTerm, ...] = ()
    projects: tuple[GoldProject, ...] = ()
    conversations: tuple[GoldConversation, ...] = ()

    @model_validator(mode="after")
    def _check(self) -> GoldSet:
        if self.schema_version != GOLD_SCHEMA_VERSION:
            raise ValueError(f"expected {GOLD_SCHEMA_VERSION}")
        if (self.terms or self.projects) and not self.synthetic:
            raise ValueError("only a synthetic set brings its own taxonomy")
        if self.terms or self.projects:
            self._check_label_ids()
        return self

    def _check_label_ids(self) -> None:
        # With its own vocabulary, every label must name a term of the right
        # dimension, or a project.
        allowed: dict[str, set[str]] = {f: set() for f in FIELDS}
        for term in self.terms:
            allowed[term.dimension.value].add(term.term_id)
        allowed["projects"] = {p.project_id for p in self.projects}
        for conversation in self.conversations:
            for segment in conversation.segments:
                for name, labels in segment.labels.items():
                    named = {x for x in (labels.primary, *labels.secondary) if x is not None}
                    unknown = named - allowed[name]
                    if unknown:
                        raise ValueError(f"{sorted(unknown)} not in the {name} vocabulary")

    def snapshot(self) -> TaxonomySnapshot:
        """The synthetic set's own vocabulary as a snapshot (for tests and baselines)."""
        if not self.synthetic:
            raise ValueError("a real set uses a published taxonomy version")
        return TaxonomySnapshot(
            self.taxonomy_version,
            "0" * 64,
            tuple(
                SnapshotTerm(t.term_id, t.dimension.value, t.label, None, None, t.aliases)
                for t in sorted(self.terms, key=lambda t: (t.dimension.value, t.term_id))
            ),
            tuple(
                SnapshotProject(p.project_id, p.name, p.aliases)
                for p in sorted(self.projects, key=lambda p: p.project_id)
            ),
        )


def load_gold(path: Path) -> GoldSet:
    """Read and validate a golden set file."""
    return GoldSet.model_validate_json(path.read_text(encoding="utf-8"))


def gold_schema() -> dict[str, object]:
    """The JSON Schema of the format, for editors and reviewers."""
    return GoldSet.model_json_schema()


def annotation_template(
    items: Sequence[SegmentText],
    native_ids: dict[str, str],
    *,
    count: int,
    seed: str,
    taxonomy_version: str,
    annotator: str,
) -> GoldSet:
    """Start a real golden set from a diverse, seeded choice of conversations.

    Segments are sampled with the NRM-006 sampler (themes, lengths, both
    roles), then their conversations are taken in sample order until
    ``count`` are chosen. The template holds IDs only: no titles or text.

    Args:
        items: The corpus inventory.
        native_ids: ``conv_`` ID -> native conversation ID.
        count: How many conversations (the plan says 30 to 50).
        seed: Same seed, same choice.
        taxonomy_version: The version the annotator will label against.
        annotator: Who will annotate.
    """
    chosen: list[str] = []
    for item in sample(items, len(items), seed=seed):
        if item.conversation_id not in chosen:
            chosen.append(item.conversation_id)
        if len(chosen) == count:
            break
    return GoldSet(
        name="golden-v1",
        synthetic=False,
        taxonomy_version=taxonomy_version,
        conversations=tuple(
            GoldConversation(native_conversation_id=native_ids[c], annotator=annotator)
            for c in chosen
        ),
    )


def write_gold(gold: GoldSet, path: Path) -> Path:
    """Write a golden set as stable, readable JSON; never over an existing file.

    Raises:
        FileExistsError: A set is already there. Annotation is hours of
            work, so it is never overwritten; move or rename it first.
    """
    if path.exists():
        raise FileExistsError(path.name)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = gold.model_dump(mode="json")
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
