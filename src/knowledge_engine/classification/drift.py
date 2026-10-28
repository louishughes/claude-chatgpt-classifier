"""Order-independence diagnostic: does processing order change the labels (CLS-005)?

A classifier that keeps hidden state (a growing context, a cache keyed on
the wrong thing, a model that drifts with what it saw last) can label the
same segment differently depending on what came before it. That would make
results depend on luck. ``order_experiment`` checks for it:

1. classify the same segments, under the same pinned taxonomy, in three
   orders: as given, reversed, and a seeded shuffle;
2. reduce each result to a **canonical form**: state, and the sorted
   (field, ID, rank) labels. Confidence is left out on purpose: the
   question is "same labels?", not "same decimals?";
3. compare per segment. Any segment whose canonical form differs between
   orders is listed as **unstable**, a review item with each order's
   labels, never quietly resolved by picking one.

The experiment passes when every segment is stable, or every unstable one
is flagged for review (which ``unstable`` always is).

Talking points:
    - "Same segment, same vocabulary, any order: same labels. If not, it's
      a review item, not a coin toss."
    - "Comparison is on IDs and ranks, not wording or decimals."
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from knowledge_engine.classification.classifier import SegmentClassification
from knowledge_engine.classification.schema import assignments
from knowledge_engine.rendering.transcript import StoredConversation
from knowledge_engine.segmentation.segmenter import Segment

DRIFT_VERSION = "cls-005-v1"

Canonical = tuple[str, tuple[tuple[str, str, str], ...]]


class Classifier(Protocol):
    """Anything with the SegmentClassifier ``classify`` shape."""

    def classify(
        self, items: Sequence[tuple[StoredConversation, Segment]]
    ) -> list[SegmentClassification]:
        """Classify, one result per item in order."""
        ...


def canonical(result: SegmentClassification) -> Canonical:
    """State plus sorted (field, ID, rank) labels: what must not depend on order."""
    labels: list[tuple[str, str, str]] = []
    if result.answer is not None:
        for name, item in assignments(result.answer):
            labels.append((name, item.get("term_id") or item["project_id"], item["rank"]))
    return result.state, tuple(sorted(labels))


@dataclass(frozen=True)
class Unstable:
    """A segment whose labels changed with order: a review item.

    Attributes:
        segment_id: The segment.
        by_order: Order name -> its canonical result.
    """

    segment_id: str
    by_order: dict[str, Canonical]
    review_required: bool = True


@dataclass
class DriftReport:
    """The outcome of one three-order experiment.

    Attributes:
        orders: The order names, e.g. ``given``, ``reversed``, ``shuffled``.
        segments: How many segments were compared.
        stable: Segments with identical canonical results in every order.
        unstable: Segments that differed, each a review item.
    """

    version: str = DRIFT_VERSION
    orders: tuple[str, ...] = ()
    segments: int = 0
    stable: int = 0
    unstable: list[Unstable] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """True when every segment is stable or flagged for review."""
        return all(item.review_required for item in self.unstable)


def _shuffled(count: int, seed: str) -> list[int]:
    order = list(range(count))
    # A string seed hashed to an int: same seed, same shuffle on any machine.
    random.Random(int(hashlib.sha256(seed.encode()).hexdigest(), 16)).shuffle(order)
    return order


def order_experiment(
    classifier: Classifier,
    items: Sequence[tuple[StoredConversation, Segment]],
    *,
    seed: str = "cls-005",
) -> DriftReport:
    """Classify in three orders and list segments whose labels changed.

    Args:
        classifier: Pinned to one taxonomy version for the whole experiment.
        items: (conversation, segment) pairs.
        seed: For the shuffled order.

    Returns:
        The report; ``unstable`` segments are review items.
    """
    orders = {
        "given": list(range(len(items))),
        "reversed": list(reversed(range(len(items)))),
        "shuffled": _shuffled(len(items), seed),
    }
    by_segment: dict[str, dict[str, Canonical]] = {}
    for name, order in orders.items():
        results = classifier.classify([items[i] for i in order])
        for result in results:
            by_segment.setdefault(result.segment_id, {})[name] = canonical(result)
    report = DriftReport(orders=tuple(orders), segments=len(by_segment))
    for segment_id, seen in sorted(by_segment.items()):
        # A segment missing from any order counts as unstable too.
        if len(seen) == len(orders) and len(set(seen.values())) == 1:
            report.stable += 1
        else:
            report.unstable.append(Unstable(segment_id, seen))
    return report
