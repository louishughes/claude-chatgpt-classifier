"""Scoring classification against the golden set (EVAL-003).

For every gold segment, the predicted labels are those of the stored
segment that **contains** the gold segment's first message (segment IDs can
change with the segmenter; message IDs can't). Then, per field:

* **multi-label F1**: the gold ID set (primary plus secondaries) against the
  predicted set, counted over all segments (micro) and averaged per label
  (macro);
* **primary accuracy**: the predicted primary equals the gold primary
  (``None`` = None counts as right: "no label" was expected and given);
* **project accuracy**: primary accuracy on the ``projects`` field, reported
  on its own because it matters most;
* **confusion**: gold primary -> predicted primary -> count, so a reviewer
  can see *which* labels get mixed up.

Ambiguous gold segments aren't scored as right or wrong labels. They count
as **flag hits** when the prediction went to review, and as **misses** when
it didn't: the right behaviour for an undecidable segment is to ask.

The report carries every version it depends on (gold set, schema,
taxonomy, classifier method and stage keys) and numbers only, never text,
so it can be committed as a baseline. It opens with the answer key's
version, hash and reviewer label (``report_labels``).

Talking points:
    - "Scores are per field: F1 for all labels, accuracy for the primary,
      and a confusion table that shows which labels get swapped."
    - "An ambiguous case is scored on whether it was sent to review, not on
      a guess."
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from knowledge_engine.classification.classifier import REVIEW_REQUIRED, SegmentClassification
from knowledge_engine.classification.schema import Rank, assignments
from knowledge_engine.evaluation.gold import FIELDS, GoldSet
from knowledge_engine.evaluation.report_labels import UNSCORED, AnswerKey, key_from_gold
from knowledge_engine.rendering.transcript import StoredConversation
from knowledge_engine.segmentation.segmenter import Segment

EVAL_VERSION = "eval-003-v1"


@dataclass(frozen=True)
class Predicted:
    """One stored segment's labels, as the evaluator needs them.

    Attributes:
        segment_id: The ``seg_`` ID.
        native_conversation_id: Its conversation, as exported.
        messages: Its native message IDs.
        labels: Field -> (primary, secondaries).
        review: True if it was sent to review.
    """

    segment_id: str
    native_conversation_id: str
    messages: tuple[str, ...]
    labels: Mapping[str, tuple[str | None, tuple[str, ...]]]
    review: bool = False


@dataclass
class FieldScore:
    """Scores for one field."""

    segments: int = 0
    true_pos: int = 0
    false_pos: int = 0
    false_neg: int = 0
    primary_right: int = 0
    macro_f1: float = 0.0
    confusion: dict[str, dict[str, int]] = field(default_factory=dict)

    @property
    def precision(self) -> float:
        """Micro precision over all label decisions."""
        return _ratio(self.true_pos, self.true_pos + self.false_pos)

    @property
    def recall(self) -> float:
        """Micro recall."""
        return _ratio(self.true_pos, self.true_pos + self.false_neg)

    @property
    def micro_f1(self) -> float:
        """Micro F1."""
        p, r = self.precision, self.recall
        return _ratio(2 * p * r, p + r)

    @property
    def primary_accuracy(self) -> float:
        """Share of segments whose primary was right."""
        return _ratio(self.primary_right, self.segments)


@dataclass
class ClassificationReport:
    """The whole evaluation, numbers only."""

    eval_version: str
    gold: str
    gold_schema: str
    taxonomy_version: str
    versions: dict[str, str]
    fields: dict[str, FieldScore]
    gold_segments: int
    unmatched_segments: int
    ambiguous_flagged: int
    ambiguous_missed: int
    key: AnswerKey | None = None

    @property
    def project_accuracy(self) -> float:
        """Primary accuracy on the projects field."""
        return self.fields["projects"].primary_accuracy if "projects" in self.fields else 0.0

    def as_markdown(self) -> str:
        """A readable report (IDs and numbers only).

        Raises:
            ValueError: The answer key is missing its version, hash or
                reviewer label (LEG-002, REV-012).
        """
        if self.key is None:
            return f"# Classification baseline ({self.gold}): {UNSCORED}\n\nNo answer key.\n"
        lines = [
            f"# Classification baseline ({self.gold})",
            "",
            *self.key.lines(),
            f"- Evaluator: `{self.eval_version}`; gold schema `{self.gold_schema}`; "
            f"taxonomy `{self.taxonomy_version}`",
            *(f"- {name}: `{value}`" for name, value in sorted(self.versions.items())),
            f"- Gold segments: {self.gold_segments}; not found in the store: "
            f"{self.unmatched_segments}",
            f"- Ambiguous segments sent to review: {self.ambiguous_flagged}; "
            f"not sent: {self.ambiguous_missed}",
            f"- Project accuracy: {self.project_accuracy:.3f}",
            "",
            "| Field | Segments | Micro P | Micro R | Micro F1 | Macro F1 | Primary acc. |",
            "|---|---|---|---|---|---|---|",
        ]
        for name, score in sorted(self.fields.items()):
            lines.append(
                f"| {name} | {score.segments} | {score.precision:.3f} | {score.recall:.3f} | "
                f"{score.micro_f1:.3f} | {score.macro_f1:.3f} | {score.primary_accuracy:.3f} |"
            )
        for name, score in sorted(self.fields.items()):
            lines += ["", f"## Confusion: {name} (gold primary -> predicted primary)", ""]
            lines += ["| Gold | Predicted | Count |", "|---|---|---|"]
            for gold, row in sorted(score.confusion.items()):
                for predicted, count in sorted(row.items()):
                    lines.append(f"| {gold} | {predicted} | {count} |")
        return "\n".join(lines) + "\n"


def _ratio(top: float, bottom: float) -> float:
    return round(top / bottom, 6) if bottom else 0.0


def evaluate_classification(
    gold: GoldSet,
    predicted: Sequence[Predicted],
    versions: Mapping[str, str],
    *,
    key: AnswerKey | None = None,
) -> ClassificationReport:
    """Score stored predictions against the golden set.

    Args:
        gold: The answer keys.
        predicted: Every stored segment of the gold conversations.
        versions: What produced the predictions (method, stage versions...).
        key: The key's version, hash and reviewer (``key_from_file``);
            defaults to a content hash with no review claimed.
    """
    by_message: dict[tuple[str, str], Predicted] = {}
    for item in predicted:
        for message in item.messages:
            by_message[(item.native_conversation_id, message)] = item
    scores: dict[str, FieldScore] = defaultdict(FieldScore)
    per_label: dict[str, dict[str, Counter[str]]] = defaultdict(lambda: defaultdict(Counter))
    total = unmatched = flagged = missed = 0
    for conversation in gold.conversations:
        for segment in conversation.segments:
            total += 1
            match = by_message.get((conversation.native_conversation_id, segment.first_message))
            if match is None:
                unmatched += 1
                continue
            if segment.ambiguous:
                flagged += int(match.review)
                missed += int(not match.review)
                continue
            for name in FIELDS:
                want = segment.labels.get(name)
                got_primary, got_secondary = match.labels.get(name, (None, ()))
                want_primary = want.primary if want else None
                want_set = {x for x in (want_primary, *(want.secondary if want else ())) if x}
                got_set = {x for x in (got_primary, *got_secondary) if x}
                if not want_set and not got_set:
                    continue  # the field doesn't apply here
                score = scores[name]
                score.segments += 1
                score.true_pos += len(want_set & got_set)
                score.false_pos += len(got_set - want_set)
                score.false_neg += len(want_set - got_set)
                score.primary_right += int(want_primary == got_primary)
                row = score.confusion.setdefault(str(want_primary), {})
                row[str(got_primary)] = row.get(str(got_primary), 0) + 1
                for label in want_set | got_set:
                    counts = per_label[name][label]
                    counts["tp"] += int(label in want_set and label in got_set)
                    counts["fp"] += int(label in got_set and label not in want_set)
                    counts["fn"] += int(label in want_set and label not in got_set)
    for name, labels in per_label.items():
        f1s = [_ratio(2 * c["tp"], 2 * c["tp"] + c["fp"] + c["fn"]) for c in labels.values()]
        scores[name].macro_f1 = round(sum(f1s) / len(f1s), 6) if f1s else 0.0
    return ClassificationReport(
        eval_version=EVAL_VERSION,
        gold=gold.name,
        gold_schema=gold.schema_version,
        taxonomy_version=gold.taxonomy_version,
        versions=dict(versions),
        fields=dict(sorted(scores.items())),
        gold_segments=total,
        unmatched_segments=unmatched,
        ambiguous_flagged=flagged,
        ambiguous_missed=missed,
        key=key or key_from_gold(gold),
    )


def stability(runs: Sequence[Sequence[Predicted]]) -> float:
    """Share of segments whose labels were identical in every run (EVAL-001 amendment)."""
    if not runs:
        return 0.0
    seen: dict[str, set[tuple[tuple[str, str | None, tuple[str, ...]], ...]]] = defaultdict(set)
    for run in runs:
        for item in run:
            canonical = tuple(
                (name, primary, tuple(sorted(rest)))
                for name, (primary, rest) in sorted(item.labels.items())
            )
            seen[item.segment_id].add(canonical)
    return _ratio(sum(1 for forms in seen.values() if len(forms) == 1), len(seen))


def predicted_from(
    items: Sequence[tuple[StoredConversation, Segment]],
    results: Sequence[SegmentClassification],
) -> list[Predicted]:
    """Turn classifier results into evaluator input (labels per field)."""
    found = []
    for (conversation, segment), result in zip(items, results, strict=True):
        labels: dict[str, tuple[str | None, tuple[str, ...]]] = {}
        if result.answer is not None:
            grouped: dict[str, list[tuple[str, str]]] = defaultdict(list)
            for name, item in assignments(result.answer):
                grouped[name].append((item["rank"], item.get("term_id") or item["project_id"]))
            for name, pairs in grouped.items():
                primary = next((i for rank, i in pairs if rank == Rank.PRIMARY.value), None)
                labels[name] = (
                    primary,
                    tuple(i for rank, i in pairs if rank != Rank.PRIMARY.value),
                )
        found.append(
            Predicted(
                segment_id=segment.segment_id,
                native_conversation_id=conversation.native_conversation_id,
                messages=segment.messages,
                labels=labels,
                review=result.state == REVIEW_REQUIRED,
            )
        )
    return found
