"""Scoring knowledge extraction against the golden set (EVAL-004).

A produced record **matches** a gold record when it is in the same
conversation, has the same record type, and its evidence quotes the gold
record's message. Matching is one to one, preferring a candidate whose
actor is also right. Then:

* **per-record-type precision, recall and F1.** Only conversations marked
  ``records_annotated`` are scored: there, an unmatched produced record is
  a false positive and an unmatched gold record a false negative. Records
  from other conversations are counted as *unscored*, never as wrong;
* **actor correctness** (and acceptance, attribution and strength where
  the gold record states them), over matched pairs;
* **evidence anchor validity**: the share of produced records whose every
  quote still points at the exact stored words (the EXT-002 check);
* **forbidden assertions**: produced records that match a ``forbidden``
  entry. Any one that reached current truth fails the evaluation;
* **unsupported truth decisions**: user decisions in current truth
  (supported or confirmed) with a broken anchor, no quote of the user's
  own words, the wrong actor, no acceptance, or a forbidden match. The
  acceptance gate is that this is zero.

"Produced" means every stored record except ``rejected`` ones: a rejected
record is one the system already refused to claim. Like EVAL-003, the
report holds IDs, versions and numbers only, never text.

Talking points:
    - "A found record counts as right only if it's the right kind of thing
      and quotes the message the answer key names."
    - "The hard rule: no user decision in current truth that isn't backed
      by the user's own, still-valid words."
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.domain.enums import Role
from knowledge_engine.evaluation.classification_eval import (
    band_order,
    length_band,
    truncation_text,
)
from knowledge_engine.evaluation.gold import GoldForbidden, GoldRecord, GoldSet
from knowledge_engine.evaluation.report_labels import UNSCORED, AnswerKey, key_from_gold
from knowledge_engine.extraction.evidence import Verdict, check_record
from knowledge_engine.extraction.records import Acceptance, KnowledgeRecord, RecordType, Trust
from knowledge_engine.importer.records import ConversationRow, MessageNodeRow, MessageRevisionRow

EVAL_VERSION = "eval-004-v1"
_TRUTH = (Trust.SUPPORTED, Trust.CONFIRMED)
_ACCEPTED = (Acceptance.EXPLICIT, Acceptance.CONDITIONAL)


@dataclass(frozen=True)
class ScoredRecord:
    """A produced record with what the evaluator needs to know about it.

    Attributes:
        record: The stored record.
        native_conversation_id: Its conversation, from its evidence (None
            when it has none).
        messages: The native message IDs its evidence quotes.
        anchors_valid: Every quote still points at the exact stored words.
        user_words: At least one quote is something the user said.
    """

    record: KnowledgeRecord
    native_conversation_id: str | None
    messages: tuple[str, ...]
    anchors_valid: bool
    user_words: bool = False


@dataclass
class TypeScore:
    """Counts for one record type."""

    true_pos: int = 0
    false_pos: int = 0
    false_neg: int = 0

    @property
    def precision(self) -> float:
        """Share of produced records that were expected."""
        return _ratio(self.true_pos, self.true_pos + self.false_pos)

    @property
    def recall(self) -> float:
        """Share of expected records that were produced."""
        return _ratio(self.true_pos, self.true_pos + self.false_neg)

    @property
    def f1(self) -> float:
        """Harmonic mean of precision and recall."""
        p, r = self.precision, self.recall
        return _ratio(2 * p * r, p + r)


@dataclass
class Agreement:
    """How often a matched record agreed with gold on one attribute."""

    checked: int = 0
    right: int = 0

    @property
    def rate(self) -> float:
        """Share right (0 when nothing was checked)."""
        return _ratio(self.right, self.checked)

    def add(self, right: bool) -> None:
        """Count one comparison."""
        self.checked += 1
        self.right += int(right)


@dataclass
class ExtractionReport:
    """The whole evaluation, numbers and IDs only."""

    eval_version: str
    gold: str
    gold_schema: str
    versions: dict[str, str]
    by_type: dict[str, TypeScore]
    agreement: dict[str, Agreement]
    produced: int
    unscored: int
    anchors_valid: int
    forbidden_produced: list[str] = field(default_factory=list)
    forbidden_in_truth: list[str] = field(default_factory=list)
    unsupported_truth_decisions: list[str] = field(default_factory=list)
    key: AnswerKey | None = None
    truncation_count: int | None = None
    recall_by_band: dict[str, TypeScore] = field(default_factory=dict)

    @property
    def anchor_validity(self) -> float:
        """Share of produced records whose anchors are all valid."""
        return _ratio(self.anchors_valid, self.produced)

    @property
    def total(self) -> TypeScore:
        """All types together (micro)."""
        total = TypeScore()
        for score in self.by_type.values():
            total.true_pos += score.true_pos
            total.false_pos += score.false_pos
            total.false_neg += score.false_neg
        return total

    @property
    def passed(self) -> bool:
        """The hard gate: nothing forbidden or unsupported reached current truth."""
        return not (self.forbidden_in_truth or self.unsupported_truth_decisions)

    def as_markdown(self) -> str:
        """A readable report (record IDs and numbers only).

        Raises:
            ValueError: The answer key is missing its version, hash or
                reviewer label (LEG-002, REV-012).
        """
        if self.key is None:
            return f"# Extraction baseline ({self.gold}): {UNSCORED}\n\nNo answer key.\n"
        total = self.total
        lines = [
            f"# Extraction baseline ({self.gold})",
            "",
            *self.key.lines(),
            f"- Evaluator: `{self.eval_version}`; gold schema `{self.gold_schema}`",
            *(f"- {name}: `{value}`" for name, value in sorted(self.versions.items())),
            f"- Produced records: {self.produced}; in conversations not annotated for "
            f"records (unscored): {self.unscored}",
            f"- Evidence anchor validity: {self.anchor_validity:.3f}",
            f"- Forbidden records produced: {len(self.forbidden_produced)}; "
            f"in current truth: {len(self.forbidden_in_truth)}",
            f"- Unsupported user decisions in current truth: "
            f"{len(self.unsupported_truth_decisions)}",
            f"- **Gate: {'PASSED' if self.passed else 'FAILED'}**",
            "",
            "| Record type | TP | FP | FN | Precision | Recall | F1 |",
            "|---|---|---|---|---|---|---|",
        ]
        rows = [*sorted(self.by_type.items()), ("all", total)]
        for name, s in rows:
            lines.append(
                f"| {name} | {s.true_pos} | {s.false_pos} | {s.false_neg} | "
                f"{s.precision:.3f} | {s.recall:.3f} | {s.f1:.3f} |"
            )
        lines += [
            "",
            f"- Truncated messages: {truncation_text(self.truncation_count)}",
            "",
            "| Chat length | Expected records | Found | Recall |",
            "|---|---|---|---|",
        ]
        for band, b in sorted(self.recall_by_band.items(), key=lambda kv: band_order(kv[0])):
            lines.append(f"| {band} | {b.true_pos + b.false_neg} | {b.true_pos} | {b.recall:.3f} |")
        lines += [
            "",
            "| Attribute (matched records) | Checked | Right | Rate |",
            "|---|---|---|---|",
        ]
        for name, a in sorted(self.agreement.items()):
            lines.append(f"| {name} | {a.checked} | {a.right} | {a.rate:.3f} |")
        failures = self.forbidden_in_truth + self.unsupported_truth_decisions
        if failures:
            lines += ["", "## Gate failures", "", *(f"- `{r}`" for r in sorted(set(failures)))]
        return "\n".join(lines) + "\n"


def _ratio(top: float, bottom: float) -> float:
    return round(top / bottom, 6) if bottom else 0.0


def scored_records(session: Session, records: Sequence[KnowledgeRecord]) -> list[ScoredRecord]:
    """Look up each record's conversation and messages, and re-check its anchors. Read only."""
    revision_ids = {ref.revision_id for r in records for ref in r.evidence}
    where: dict[str, tuple[str, str]] = {}
    if revision_ids:
        rows = session.execute(
            select(
                MessageRevisionRow.revision_id,
                ConversationRow.native_conversation_id,
                MessageNodeRow.native_node_id,
            )
            .join(MessageNodeRow, MessageNodeRow.node_key == MessageRevisionRow.node_key)
            .join(
                ConversationRow, ConversationRow.conversation_id == MessageNodeRow.conversation_id
            )
            .where(MessageRevisionRow.revision_id.in_(sorted(revision_ids)))
        )
        where = {revision: (conv, node) for revision, conv, node in rows}
    scored = []
    for record in records:
        found = [where[ref.revision_id] for ref in record.evidence if ref.revision_id in where]
        conversations = {conv for conv, _ in found}
        # A record with no evidence, or quoting two conversations, can't be
        # placed; it is never matched, and its anchors don't count as valid.
        conversation = next(iter(conversations)) if len(conversations) == 1 else None
        valid = (
            bool(record.evidence) and check_record(session, record).verdict is not Verdict.INVALID
        )
        scored.append(
            ScoredRecord(
                record=record,
                native_conversation_id=conversation,
                messages=tuple(dict.fromkeys(node for _, node in found)),
                anchors_valid=valid,
                user_words=any(ref.actor is Role.USER for ref in record.evidence),
            )
        )
    return scored


def _quotes(item: ScoredRecord, conversation: str, message: str) -> bool:
    return item.native_conversation_id == conversation and message in item.messages


def _forbidden_hit(item: ScoredRecord, conversation: str, rule: GoldForbidden) -> bool:
    return (
        _quotes(item, conversation, rule.message_id)
        and item.record.record_type is rule.record_type
        and item.record.actor is rule.actor
    )


def _agreements(gold: GoldRecord, item: ScoredRecord) -> int:
    record = item.record
    return (
        2 * int(record.actor is gold.actor)  # the actor matters most
        + int(gold.acceptance is None or record.acceptance is gold.acceptance)
        + int(record.attributed_to == gold.attributed_to)
        + int(gold.strength is None or record.strength is gold.strength)
    )


def _compare(agreement: dict[str, Agreement], gold: GoldRecord, item: ScoredRecord) -> None:
    record = item.record
    agreement["actor"].add(record.actor is gold.actor)
    if gold.acceptance is not None:
        agreement["acceptance"].add(record.acceptance is gold.acceptance)
    if gold.attributed_to is not None or record.attributed_to is not None:
        agreement["attributed_to"].add(record.attributed_to == gold.attributed_to)
    if gold.strength is not None:
        agreement["strength"].add(record.strength is gold.strength)


def evaluate_extraction(
    gold: GoldSet,
    produced: Sequence[ScoredRecord],
    versions: Mapping[str, str],
    *,
    key: AnswerKey | None = None,
    lengths: Mapping[str, int] | None = None,
    truncation_count: int | None = None,
) -> ExtractionReport:
    """Score produced records against the golden set.

    Args:
        gold: The answer keys.
        produced: Stored records, usually every record of the gold
            conversations (``scored_records``). Rejected ones are ignored.
        versions: What produced them (extractor versions, validator...).
        key: The key's version, hash and reviewer (``key_from_file``);
            defaults to a content hash with no review claimed.
        lengths: Native conversation ID -> characters, for recall by
            chat-length band (LEG-005).
        truncation_count: Messages dropped from the extractors' input
            (``segmenter.truncation_count``); must be 0. None: not measured.
    """
    live = [item for item in produced if item.record.trust is not Trust.REJECTED]
    by_type: dict[str, TypeScore] = defaultdict(TypeScore)
    by_band: dict[str, TypeScore] = defaultdict(TypeScore)
    agreement: dict[str, Agreement] = defaultdict(Agreement)
    forbidden_produced: list[str] = []
    forbidden_in_truth: list[str] = []
    unsupported: list[str] = []
    scored_ids: set[str] = set()
    forbidden_ids: set[str] = set()
    for conversation in gold.conversations:
        native = conversation.native_conversation_id
        here = [item for item in live if item.native_conversation_id == native]
        for rule in conversation.forbidden:
            for item in here:
                if _forbidden_hit(item, native, rule):
                    forbidden_ids.add(item.record.record_id)
                    forbidden_produced.append(item.record.record_id)
                    if item.record.trust in _TRUTH:
                        forbidden_in_truth.append(item.record.record_id)
        if not conversation.records_annotated:
            continue
        unmatched = list(here)
        scored_ids |= {item.record.record_id for item in here}
        band = by_band[length_band(lengths.get(native) if lengths else None)]
        for expected in conversation.records:
            candidates = [
                item
                for item in unmatched
                if item.record.record_type is expected.record_type
                and _quotes(item, native, expected.message_id)
            ]
            if not candidates:
                by_type[expected.record_type.value].false_neg += 1
                band.false_neg += 1
                continue
            # Two records of one type can quote the same message (the user's
            # own preference and a client's). Pair each gold record with the
            # candidate that agrees on the most attributes, so a correct
            # record isn't paired with its twin and miscounted.
            best = max(candidates, key=lambda c: _agreements(expected, c))
            unmatched.remove(best)
            by_type[expected.record_type.value].true_pos += 1
            band.true_pos += 1
            _compare(agreement, expected, best)
        for item in unmatched:
            by_type[item.record.record_type.value].false_pos += 1
    for item in live:
        record = item.record
        if record.record_type is not RecordType.DECISION or record.trust not in _TRUTH:
            continue
        if (
            not item.anchors_valid
            or not item.user_words
            or record.actor is not Role.USER
            or record.acceptance not in _ACCEPTED
            or record.record_id in forbidden_ids
        ):
            unsupported.append(record.record_id)
    return ExtractionReport(
        eval_version=EVAL_VERSION,
        gold=gold.name,
        gold_schema=gold.schema_version,
        versions=dict(versions),
        by_type=dict(sorted(by_type.items())),
        agreement=dict(sorted(agreement.items())),
        produced=len(live),
        unscored=len(live) - len(scored_ids),
        anchors_valid=sum(1 for item in live if item.anchors_valid),
        forbidden_produced=sorted(set(forbidden_produced)),
        forbidden_in_truth=sorted(set(forbidden_in_truth)),
        unsupported_truth_decisions=sorted(set(unsupported)),
        key=key or key_from_gold(gold),
        truncation_count=truncation_count,
        recall_by_band=dict(by_band),
    )
