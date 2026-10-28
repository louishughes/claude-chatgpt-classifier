"""Named references: games, software, books, films, creators (EXT-006).

A name is only recorded when a **type cue** says what it is ("the game
Hades", "playing Celeste", "using Blender", "the book Dune by Frank
Herbert", "watched Arrival"). A bare capitalised word is not enough: that
would turn every sentence start into an entity. Titles in quotation marks
after a cue ("the book “The Hobbit”") work too.

* **URLs are skipped.** Links, YouTube videos and social accounts come
  from the deterministic link registries (LNK, YTB, SOC); this extractor
  never re-detects them, and a name inside a URL is ignored.
* **Canonical names.** Mentions are grouped by their normalised name
  (TAX-003 rules), so one segment mentioning "Celeste" three times gives
  **one** reference with three pieces of evidence.
* **Matching, not creating.** If the name matches exactly one approved
  taxonomy term or project alias, its ID is attached (``matched_id``). A
  game that isn't a known project **does not create a project** or a
  proposal: this extractor writes nothing to the vocabulary.
* **People** are recorded only as the named creator of a work ("by Frank
  Herbert", kept as the book's ``author`` detail and as its own person
  reference). A name on its own is never guessed to be a person.

Talking points:
    - "A name needs a cue that says what it is; a capital letter isn't
      evidence."
    - "Mentioning a game links it to a project only if that project
      already exists and is approved. Nothing is created."
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from knowledge_engine.domain.models import EvidenceRef
from knowledge_engine.extraction.records import (
    Acceptance,
    CandidateRecord,
    Entity,
    EntityType,
    RecordType,
    Scope,
)
from knowledge_engine.extraction.text import ExtractionMessage, quote
from knowledge_engine.graph.offsets import Span
from knowledge_engine.links.extract import find_in_text
from knowledge_engine.taxonomy.aliases import AliasResolver, MatchStatus
from knowledge_engine.taxonomy.registry import normalise_alias

EXTRACTOR_VERSION = "ext-006-rules-v1"
# A title: capitalised words (or numbers), allowing small joining words
# inside ("Lord of the Rings"), or anything in quotation marks.
_WORD = r"(?:[A-Z0-9][\w'’:-]*)"
_TITLE = rf"(?:{_WORD}(?:\s+(?:of|the|and|in|on|a|&|{_WORD}))*|[\"“][^\"”\n]{{1,80}}[\"”])"
_CUES: tuple[tuple[EntityType, str], ...] = (
    (EntityType.GAME, r"\b(?:the (?:video )?game|playing|played|play)\s+"),
    (EntityType.BOOK, r"\b(?:the (?:book|novel)|reading|read)\s+"),
    (EntityType.FILM, r"\b(?:the (?:film|movie)|watched|watching)\s+"),
    (
        EntityType.SOFTWARE,
        r"\b(?:using|use|installed|install|the (?:app|library|framework|tool|engine|editor))\s+",
    ),
)
_PATTERNS = [
    (
        kind,
        re.compile(cue + rf"(?P<name>{_TITLE})(?:\s+by\s+(?P<by>{_WORD}(?:\s+{_WORD}){{0,3}}))?"),
    )
    for kind, cue in _CUES
]
# Small words that can't end a title ("the book Dune and" -> "Dune").
_TRAILING = re.compile(r"(?:\s+(?:of|the|and|in|on|a|&))+$")


@dataclass
class _Group:
    entity_type: EntityType
    name: str
    first_seen: tuple[int, int]  # (message index, offset): records come out in text order
    evidence: list[EvidenceRef] = field(default_factory=list)
    details: dict[str, str] = field(default_factory=dict)


def extract_entities(
    messages: Sequence[ExtractionMessage],
    *,
    segment_id: str,
    resolver: AliasResolver | None = None,
) -> list[CandidateRecord]:
    """References to named things in one segment, one record per entity.

    Args:
        messages: The segment's messages, in order.
        segment_id: The records' scope.
        resolver: Approved aliases (TAX-003) to attach ``matched_id``; the
            vocabulary is only read.
    """
    groups: dict[tuple[EntityType, str], _Group] = {}
    for position, message in enumerate(messages):
        urls = [link.span for link in find_in_text(message.text)]
        for kind, pattern in _PATTERNS:
            for match in pattern.finditer(message.text):
                name, start = _clean(match.group("name"), match.start("name"))
                inside = (match.start(), start)  # the cue or the name inside a link
                if not name or any(u.start <= i < u.end for u in urls for i in inside):
                    continue
                span = Span(start, start + len(name))
                _add(groups, kind, name, quote(message, span), (position, start))
                if match.group("by") and kind is not EntityType.SOFTWARE:
                    author = match.group("by")
                    groups[(kind, normalise_alias(name))].details["author"] = author
                    by_span = Span(match.start("by"), match.end("by"))
                    _add(
                        groups,
                        EntityType.PERSON,
                        author,
                        quote(message, by_span),
                        (position, by_span.start),
                    )
    ordered = sorted(groups.values(), key=lambda g: g.first_seen)
    return [_record(group, segment_id, resolver) for group in ordered]


def _clean(raw: str, start: int) -> tuple[str, int]:
    if raw[:1] in '"“':  # a quoted title: drop the marks
        return raw[1:-1].strip(), start + 1
    return _TRAILING.sub("", raw).rstrip(".,;:!?"), start


def _add(
    groups: dict[tuple[EntityType, str], _Group],
    kind: EntityType,
    name: str,
    ref: EvidenceRef,
    seen: tuple[int, int],
) -> None:
    key = (kind, normalise_alias(name))
    group = groups.setdefault(key, _Group(kind, name, seen))
    if ref not in group.evidence:
        group.evidence.append(ref)


def _record(group: _Group, segment_id: str, resolver: AliasResolver | None) -> CandidateRecord:
    matched = None
    if resolver is not None:
        resolution = resolver.resolve(group.name)
        if resolution.status is MatchStatus.MATCHED:
            matched = resolution.target_id
    return CandidateRecord.model_validate(
        {
            "record_type": RecordType.REFERENCE,
            "assertion": f"{group.entity_type.value}: {group.name}"[:300],
            # Who mentioned it first; the entity itself belongs to nobody.
            "actor": group.evidence[0].actor,
            "acceptance": Acceptance.NOT_APPLICABLE,
            "scope": Scope.SEGMENT,
            "scope_id": segment_id,
            "evidence": group.evidence,
            "entity": Entity(
                entity_type=group.entity_type,
                name=group.name,
                norm_name=normalise_alias(group.name),
                matched_id=matched,
                details=group.details,
            ),
        }
    )
