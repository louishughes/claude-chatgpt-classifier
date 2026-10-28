"""Matching text to approved terms and projects by alias (TAX-003).

Works only from a published ``TaxonomySnapshot``, so it can only ever
answer with approved IDs. Two jobs:

* ``resolve(text)``: does this whole phrase name something? "UE5",
  "Unreal Engine 5" and "unreal-engine 5" all reach the same ID when those
  are aliases of it. If the same spelling names things in two places (a
  topic and a project, say), the answer is **ambiguous** with every
  candidate listed, unless the caller narrows the scope to one dimension.
* ``find(text)``: where in a longer text are aliases mentioned? Matches are
  whole words only ("UE" never matches inside "queue"), the longest alias
  wins where two overlap, and every match keeps its exact character span.

``collisions()`` lists spellings shared across scopes, for review.

Talking points:
    - "One spelling, one meaning, or the resolver says it's ambiguous. It
      never picks for you."
    - "Only whole words match, and only approved names can."
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum

from knowledge_engine.graph.offsets import Span
from knowledge_engine.taxonomy.registry import Dimension, TaxonomySnapshot, normalise_alias

PROJECT_SCOPE = "project"
_TOKEN = re.compile(r"[^\W_]+")


class MatchStatus(StrEnum):
    """The outcome of resolving one phrase."""

    MATCHED = "matched"
    AMBIGUOUS = "ambiguous"
    UNMATCHED = "unmatched"


@dataclass(frozen=True)
class Candidate:
    """Something an alias can name.

    Attributes:
        target_id: A ``term_`` or ``proj_`` ID.
        scope: The dimension, or ``project``.
        label: Its current label or name (for display only).
    """

    target_id: str
    scope: str
    label: str


@dataclass(frozen=True)
class Resolution:
    """The answer for one phrase."""

    status: MatchStatus
    candidates: tuple[Candidate, ...]

    @property
    def target_id(self) -> str | None:
        """The single match, or None when ambiguous or unmatched."""
        return self.candidates[0].target_id if self.status is MatchStatus.MATCHED else None


@dataclass(frozen=True)
class Mention:
    """An alias found in a text, with its exact span."""

    span: Span
    norm_form: str
    resolution: Resolution


class AliasResolver:
    """Alias lookups over one published snapshot."""

    def __init__(self, snapshot: TaxonomySnapshot) -> None:
        """Index every alias of every approved term and project."""
        self.version = snapshot.version
        index: dict[str, set[Candidate]] = defaultdict(set)
        for term in snapshot.terms:
            candidate = Candidate(term.term_id, term.dimension, term.label)
            for alias in (term.label, *term.aliases):
                if norm := normalise_alias(alias):
                    index[norm].add(candidate)
        for project in snapshot.projects:
            candidate = Candidate(project.project_id, PROJECT_SCOPE, project.name)
            for alias in (project.name, *project.aliases):
                if norm := normalise_alias(alias):
                    index[norm].add(candidate)
        self._index = {
            k: tuple(sorted(v, key=lambda c: (c.scope, c.target_id))) for k, v in index.items()
        }
        self._longest = max((len(k.split()) for k in self._index), default=0)

    def resolve(self, text: str, *, scope: Dimension | str | None = None) -> Resolution:
        """Resolve a whole phrase to one approved ID, if it names exactly one.

        Args:
            text: e.g. ``"UE5"``.
            scope: A dimension or ``"project"`` to narrow the search.

        Returns:
            ``matched`` with one candidate, ``ambiguous`` with several, or
            ``unmatched`` with none.
        """
        found = self._index.get(normalise_alias(text), ())
        if scope is not None:
            wanted = scope.value if isinstance(scope, Dimension) else scope
            found = tuple(c for c in found if c.scope == wanted)
        if not found:
            return Resolution(MatchStatus.UNMATCHED, ())
        if len({c.target_id for c in found}) > 1:
            return Resolution(MatchStatus.AMBIGUOUS, found)
        return Resolution(MatchStatus.MATCHED, found[:1])

    def find(self, text: str, *, scope: Dimension | str | None = None) -> list[Mention]:
        """Find alias mentions in a text: whole words, longest first, no overlaps.

        Args:
            text: Any text, e.g. a message.
            scope: Narrow to one dimension or ``"project"``.

        Returns:
            Mentions in text order, each with its span and resolution.
        """
        tokens = [(m.start(), m.end(), normalise_alias(m.group())) for m in _TOKEN.finditer(text)]
        mentions: list[Mention] = []
        i = 0
        while i < len(tokens):
            for size in range(min(self._longest, len(tokens) - i), 0, -1):
                window = tokens[i : i + size]
                norm = " ".join(t[2] for t in window if t[2])
                if norm not in self._index:
                    continue
                resolution = self.resolve(norm, scope=scope)
                if resolution.status is MatchStatus.UNMATCHED:
                    continue
                mentions.append(Mention(Span(window[0][0], window[-1][1]), norm, resolution))
                i += size
                break
            else:
                i += 1
        return mentions

    def collisions(self) -> dict[str, tuple[Candidate, ...]]:
        """Spellings that name more than one thing, for a reviewer to look at."""
        return {
            norm: found
            for norm, found in sorted(self._index.items())
            if len({c.target_id for c in found}) > 1
        }
