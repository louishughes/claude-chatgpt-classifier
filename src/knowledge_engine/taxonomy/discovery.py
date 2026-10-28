"""Discovery: suggest vocabulary from the corpus, as proposals only (TAX-006).

Before classifying anything we need categories, and the best source of
candidate categories is the chats themselves. Discovery groups similar
segments and suggests one term per group. It **only ever writes
proposals**: every suggestion goes through the TAX-004 review, so nothing
discovered can become an approved term, or reach a published snapshot,
without a reviewer.

Backends (all behind one small interface, ``DiscoveryBackend``):

* ``TfidfBackend`` (default, deterministic, no extra installs): segments
  that share the most widely shared word form a group, greedily; the
  group's label words are its highest-scoring TF-IDF words. Same input,
  same groups, always.
* ``BertopicBackend`` (optional): wraps the BERTopic library when it is
  installed. It runs locally; nothing is sent anywhere. If the library is
  missing it raises ``BackendUnavailable`` instead of failing halfway.

A group whose label already names an approved term (in the target
dimension) is reported as ``known``, and one already waiting as an open
proposal is not proposed twice.

Talking points:
    - "Discovery suggests; a reviewer decides. Its only write is a proposal."
    - "The default backend is plain TF-IDF so results are repeatable and
      need nothing installed; the clever one is optional."
"""

from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.segmentation.inventory import SegmentText
from knowledge_engine.taxonomy.registry import (
    Dimension,
    TaxonomyAliasRow,
    TaxonomyProposalRow,
    TaxonomyTermRow,
    TermStatus,
    normalise_alias,
)
from knowledge_engine.taxonomy.review import OPEN, Operation, propose

_WORD = re.compile(r"[^\W\d_]{3,}")
# Filler words that never name a subject. A short fixed list (part of the
# backend version) rather than a library, so results never shift with an
# install.
STOP_WORDS = frozenset(
    """
    about above after again all also and any are because been before being
    but can could did does doing for from had has have having her here hers
    him his how into its just like more most much must not now off once only
    other our out over own same she should some such than that the their them
    then there these they this those through too under until very was way
    were what when where which while who whom why will with would you your
    yours please thanks thank want need needs make use using get got
    """.split()
)
# Evidence keeps at most this many segment IDs per suggestion; the size
# field still says how many there were.
MAX_EVIDENCE = 50


class BackendUnavailable(RuntimeError):
    """An optional discovery backend whose library isn't installed."""


@dataclass(frozen=True)
class Cluster:
    """One group of similar segments.

    Attributes:
        label_words: The words that best describe it, most telling first.
        members: Indexes into the input list.
    """

    label_words: tuple[str, ...]
    members: tuple[int, ...]


class DiscoveryBackend(Protocol):
    """Anything that can group segment texts."""

    name: str
    version: str

    def cluster(self, items: Sequence[SegmentText]) -> list[Cluster]:
        """Group the items; every index appears in at most one cluster."""
        ...


class TfidfBackend:
    """Deterministic grouping by the most widely shared word (the default).

    Greedy: take the word found in the most remaining segments (but not in
    more than half of the whole corpus, which rules out "the" and other
    filler), make those segments a group, remove them, repeat. Ties go to
    the alphabetically first word. A segment sharing no word with any other
    ends up in a group of one.
    """

    name = "tfidf"
    version = "tax-006-tfidf-v1"

    def __init__(self, label_words: int = 3, common_share: float = 0.5) -> None:
        """Keep ``label_words`` describing words per group."""
        self.label_words = label_words
        self.common_share = common_share

    def cluster(self, items: Sequence[SegmentText]) -> list[Cluster]:
        """Group items greedily by shared word; label groups by their top TF-IDF words."""
        bags = [Counter(w.casefold() for w in _WORD.findall(item.text)) for item in items]
        spread: Counter[str] = Counter()
        for bag in bags:
            spread.update(set(bag))
        limit = max(1, int(len(items) * self.common_share))
        usable = {w for w, df in spread.items() if df <= limit and w not in STOP_WORDS}
        remaining = set(range(len(items)))
        clusters = []
        while remaining:
            counts: Counter[str] = Counter()
            for index in remaining:
                counts.update(set(bags[index]) & usable)
            best = min(counts.items(), key=lambda pair: (-pair[1], pair[0]), default=None)
            if best is None or best[1] < 2:
                for index in sorted(remaining):  # nothing shared: groups of one
                    clusters.append(Cluster(self._label(bags, [index], spread, ""), (index,)))
                break
            members = sorted(i for i in remaining if best[0] in bags[i])
            clusters.append(Cluster(self._label(bags, members, spread, best[0]), tuple(members)))
            remaining.difference_update(members)
        return clusters

    def _label(
        self, bags: list[Counter[str]], members: list[int], spread: Counter[str], theme: str
    ) -> tuple[str, ...]:
        total: Counter[str] = Counter()
        for index in members:
            total.update(bags[index])
        scored = sorted(
            (-count * math.log(len(bags) / spread[word]), word)
            for word, count in total.items()
            if spread[word] < len(bags) and word != theme and word not in STOP_WORDS
        )
        words = [word for _, word in scored]
        lead = [theme] if theme else words[:1]
        rest = [w for w in words if w not in lead]
        return tuple(lead + rest[: self.label_words - len(lead)])


class BertopicBackend:
    """Optional: BERTopic, run locally, when the library is installed."""

    name = "bertopic"
    version = "tax-006-bertopic-v1"

    def __init__(self, seed: int = 42) -> None:
        """Fail early, and clearly, if BERTopic isn't installed."""
        try:
            import bertopic  # type: ignore[import-not-found]  # noqa: F401
        except ImportError as error:
            raise BackendUnavailable("install the 'bertopic' extra to use this backend") from error
        self.seed = seed

    def cluster(self, items: Sequence[SegmentText]) -> list[Cluster]:  # pragma: no cover
        """Group with BERTopic; topic -1 (outliers) is left out."""
        from bertopic import BERTopic
        from umap import UMAP  # type: ignore[import-not-found]

        model = BERTopic(umap_model=UMAP(random_state=self.seed))
        topics, _ = model.fit_transform([item.text for item in items])
        groups: dict[int, list[int]] = defaultdict(list)
        for index, topic in enumerate(topics):
            if topic != -1:
                groups[int(topic)].append(index)
        return [
            Cluster(tuple(word for word, _ in model.get_topic(topic)[:3]), tuple(members))
            for topic, members in sorted(groups.items())
        ]


@dataclass
class DiscoveryReport:
    """What one discovery run suggested.

    Attributes:
        proposed: New proposal IDs.
        known: Labels that already name an approved term (no proposal).
        waiting: Labels already waiting as open proposals (not repeated).
        too_small: How many groups were below ``min_size``.
    """

    proposed: list[str] = field(default_factory=list)
    known: list[str] = field(default_factory=list)
    waiting: list[str] = field(default_factory=list)
    too_small: int = 0


def discover(
    session: Session,
    items: Sequence[SegmentText],
    *,
    backend: DiscoveryBackend | None = None,
    dimension: Dimension = Dimension.TOPIC,
    min_size: int = 2,
    proposer: str = "discovery",
) -> DiscoveryReport:
    """Group segments and file one ``add`` proposal per new group.

    Args:
        session: The caller commits. Only proposal rows are written.
        items: Segments (usually a ``sample`` of the inventory).
        backend: How to group; ``TfidfBackend`` if omitted.
        dimension: Which dimension the suggestions are for.
        min_size: Groups smaller than this are skipped (counted).
        proposer: Recorded on each proposal; a reviewer must be someone else.

    Returns:
        What was proposed, already known, already waiting, or too small.
    """
    chosen = backend or TfidfBackend()
    report = DiscoveryReport()
    known = _approved_aliases(session, dimension)
    waiting = _open_add_labels(session, dimension)
    for cluster in chosen.cluster(items):
        if len(cluster.members) < min_size:
            report.too_small += 1
            continue
        label = cluster.label_words[0].capitalize()
        norm = normalise_alias(label)
        if norm in known:
            report.known.append(label)
            continue
        if norm in waiting:
            report.waiting.append(label)
            continue
        segment_ids = sorted(items[i].segment_id for i in cluster.members)
        proposal = propose(
            session,
            Operation.ADD,
            {"dimension": dimension.value, "label": label},
            proposer=proposer,
            evidence={
                "backend": chosen.name,
                "backend_version": chosen.version,
                "keywords": list(cluster.label_words),
                "size": len(segment_ids),
                "segments": segment_ids[:MAX_EVIDENCE],
            },
        )
        waiting.add(norm)
        report.proposed.append(proposal.proposal_id)
    return report


def _approved_aliases(session: Session, dimension: Dimension) -> set[str]:
    return set(
        session.scalars(
            select(TaxonomyAliasRow.norm_form)
            .join(TaxonomyTermRow, TaxonomyTermRow.term_id == TaxonomyAliasRow.term_id)
            .where(
                TaxonomyAliasRow.dimension == dimension.value,
                TaxonomyTermRow.status == TermStatus.APPROVED.value,
            )
        )
    )


def _open_add_labels(session: Session, dimension: Dimension) -> set[str]:
    labels = set()
    for row in session.scalars(
        select(TaxonomyProposalRow).where(
            TaxonomyProposalRow.status == OPEN,
            TaxonomyProposalRow.operation == Operation.ADD.value,
        )
    ):
        payload = json.loads(row.payload_json)
        if payload.get("dimension") == dimension.value:
            labels.add(normalise_alias(payload.get("label", "")))
    return labels
