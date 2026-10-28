"""Keyword scoring and primary/secondary ranking, with no model (CLS-003).

How often a name appears is a weak clue. An assistant can repeat "Unity"
five times while comparing engines, and the user can settle the question
once: "I've decided to go with Godot". This scorer counts frequency as
**one feature among several**:

* ``mentions``: how often the term's approved names occur (log-scaled, so
  the fifth mention adds little);
* ``distinctiveness``: how rare the term is across the corpus (a name found
  in every segment says little about this one);
* ``user``: the user named it, not only the assistant;
* ``decisive``: the user named it in a sentence with a decision cue
  ("decided", "going with", "switch to", "my project"...), and no "not"
  or "never" just before the name;
* ``semantic``: an optional 0..1 similarity from elsewhere (an embedding or
  a model), 0 when there is none. Never required.

``rank`` turns scores into labels per field (each dimension, and projects):
the best score at or above ``min_score`` is primary; others at or above it
are secondary. When the top two are within ``tie_margin`` of each other the
choice is not made silently: the higher ID-sorted one is kept as primary
(a fixed, repeatable tie-break) and the answer is flagged for review.

The result is an answer in the same shape a model must give (CLS-001), so
everything after this treats keyword and model answers alike.

Talking points:
    - "Saying something once and decisively beats saying it five times in
      passing: frequency is one feature, not the score."
    - "A near-tie isn't guessed. It is broken the same way every time and
      sent to review."
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field

from pydantic import BaseModel

from knowledge_engine.classification.schema import (
    MAX_EVIDENCE,
    PROJECTS_FIELD,
    Rank,
    SegmentMessageText,
    output_model,
)
from knowledge_engine.taxonomy.aliases import AliasResolver, MatchStatus, Mention
from knowledge_engine.taxonomy.registry import TaxonomySnapshot

SCORER_VERSION = "cls-003-v1"
# A decision cue and a negation, matched within one sentence of a user
# message. Fixed lists: part of the scorer version.
_CUES = re.compile(
    r"\b(?:decided|decide|going with|go with|went with|settled on|chose|choose|picked|"
    r"switch(?:ed|ing)? to|move(?:d)? to|i'?ll use|we'?ll use|let'?s use|i'?m using|"
    r"we'?re using|stick(?:ing)? with|my project|our project)\b",
    re.IGNORECASE,
)
_NEGATION = re.compile(r"\b(?:not|never|no longer|don'?t|won'?t|isn'?t|aren'?t)\b", re.I)
_SENTENCE = re.compile(r"[^.!?\n]+")
_NEGATION_REACH = 20  # characters before a mention that a negation can cancel


@dataclass(frozen=True)
class Weights:
    """How much each feature counts. Frequency is deliberately small."""

    mentions: float = 0.5
    distinctiveness: float = 0.5
    user: float = 1.0
    decisive: float = 2.0
    semantic: float = 1.0


@dataclass(frozen=True)
class Signals:
    """The evidence for one term or project in one segment.

    Attributes:
        target_id: ``term_`` or ``proj_`` ID.
        scope: The answer field: a dimension name or ``projects``.
        mentions: Approved-name matches in the segment.
        user_mentions: How many of those are in user messages.
        decisive: True if a user sentence names it with a decision cue.
        distinctiveness: 0..1, rarer in the corpus is higher.
        semantic: 0..1 from an optional outside score.
        score: The weighted total.
        evidence: Message IDs of the mentions, in order, no repeats.
    """

    target_id: str
    scope: str
    mentions: int
    user_mentions: int
    decisive: bool
    distinctiveness: float
    semantic: float
    score: float
    evidence: tuple[str, ...]


def corpus_frequencies(resolver: AliasResolver, texts: Iterable[str]) -> tuple[Counter[str], int]:
    """How many segments mention each target, and how many segments there are."""
    found: Counter[str] = Counter()
    count = 0
    for text in texts:
        count += 1
        found.update({m.resolution.target_id or "" for m in _matched(resolver, text)} - {""})
    return found, count


def _matched(resolver: AliasResolver, text: str) -> list[Mention]:
    return [m for m in resolver.find(text) if m.resolution.status is MatchStatus.MATCHED]


@dataclass
class KeywordScorer:
    """Scores every approved term and project mentioned in a segment."""

    snapshot: TaxonomySnapshot
    corpus_df: Mapping[str, int] = field(default_factory=dict)
    corpus_size: int = 0
    weights: Weights = field(default_factory=Weights)

    def __post_init__(self) -> None:
        """Index the snapshot's names."""
        self.resolver = AliasResolver(self.snapshot)
        self._scope = {t.term_id: t.dimension for t in self.snapshot.terms}
        self._scope.update({p.project_id: PROJECTS_FIELD for p in self.snapshot.projects})

    def score(
        self,
        messages: Sequence[SegmentMessageText],
        semantic: Mapping[str, float] | None = None,
    ) -> list[Signals]:
        """Score the segment's mentions; highest score first, ties by ID."""
        counts: Counter[str] = Counter()
        users: Counter[str] = Counter()
        decisive: set[str] = set()
        evidence: dict[str, list[str]] = defaultdict(list)
        for message in messages:
            is_user = message.role == "user"
            for mention in _matched(self.resolver, message.text):
                target = mention.resolution.target_id
                assert target is not None  # MATCHED always has one
                counts[target] += 1
                if message.message_id not in evidence[target]:
                    evidence[target].append(message.message_id)
                if is_user:
                    users[target] += 1
                    if _decisive(message.text, mention.span.start):
                        decisive.add(target)
        semantic = semantic or {}
        w = self.weights
        found = []
        for target, n in counts.items():
            distinct = self._distinctiveness(target)
            sim = max(0.0, min(1.0, semantic.get(target, 0.0)))
            total = (
                w.mentions * math.log1p(n)
                + w.distinctiveness * distinct
                + w.user * (1.0 if users[target] else 0.0)
                + w.decisive * (1.0 if target in decisive else 0.0)
                + w.semantic * sim
            )
            found.append(
                Signals(
                    target,
                    self._scope[target],
                    n,
                    users[target],
                    target in decisive,
                    round(distinct, 6),
                    sim,
                    round(total, 6),
                    tuple(evidence[target][:MAX_EVIDENCE]),
                )
            )
        return sorted(found, key=lambda s: (-s.score, s.target_id))

    def _distinctiveness(self, target: str) -> float:
        if self.corpus_size <= 1:
            return 0.5  # no corpus to compare with: neutral
        df = self.corpus_df.get(target, 0)
        return math.log((self.corpus_size + 1) / (df + 1)) / math.log(self.corpus_size + 1)


def _decisive(text: str, offset: int) -> bool:
    for sentence in _SENTENCE.finditer(text):
        if sentence.start() <= offset < sentence.end():
            # "going with Godot, not Unity": the cue counts for Godot, and
            # the "not" just before Unity cancels it for Unity only.
            before = text[max(sentence.start(), offset - _NEGATION_REACH) : offset]
            return bool(_CUES.search(sentence.group())) and not _NEGATION.search(before)
    return False


@dataclass(frozen=True)
class Ranking:
    """Labels chosen from scores, before they are put in answer form."""

    labels: Mapping[str, tuple[tuple[Signals, Rank], ...]]
    ties: tuple[str, ...]


def rank(signals: Sequence[Signals], *, min_score: float = 1.0, tie_margin: float = 0.1) -> Ranking:
    """Pick a primary and secondaries per field.

    Args:
        signals: From ``KeywordScorer.score``.
        min_score: Below this a mention is too weak to label anything.
        tie_margin: Top two closer than this are a tie, flagged for review.

    Returns:
        Labels per field, and the fields where the primary was a near tie.
    """
    by_scope: dict[str, list[Signals]] = defaultdict(list)
    for item in signals:
        if item.score >= min_score:
            by_scope[item.scope].append(item)
    labels = {}
    ties = []
    for scope, items in sorted(by_scope.items()):
        items.sort(key=lambda s: (-s.score, s.target_id))
        if len(items) > 1 and items[0].score - items[1].score < tie_margin:
            ties.append(scope)
        labels[scope] = tuple(
            (item, Rank.PRIMARY if i == 0 else Rank.SECONDARY) for i, item in enumerate(items)
        )
    return Ranking(labels, tuple(ties))


def as_answer(snapshot: TaxonomySnapshot, ranking: Ranking) -> BaseModel:
    """Put a ranking in the CLS-001 answer shape (validated like a model's)."""
    data: dict[str, object] = {}
    model = output_model(snapshot)
    for name in model.model_fields:
        if name in ("needs_review", "review_reason"):
            continue
        id_field = "project_id" if name == PROJECTS_FIELD else "term_id"
        data[name] = [
            {
                id_field: item.target_id,
                "rank": label.value,
                # A bounded, monotone stand-in for confidence: higher score,
                # closer to 1. It is a heuristic, and named as such in docs.
                "confidence": round(item.score / (item.score + 1.0), 3),
                "evidence": list(item.evidence),
            }
            for item, label in ranking.labels.get(name, ())
        ]
    if ranking.ties:
        data["needs_review"] = True
        data["review_reason"] = "near tie for primary in " + ", ".join(ranking.ties)
    return model.model_validate(data)
