"""Walk the connections around a record, every step with its origin (REC-007).

Retrieval, documents and the UI need one way to ask "what is connected to
this record, and how?". This module gathers every kind of edge the
reconciliation stages store, walks them breadth-first from a starting
record, and labels each record it reaches with its standing from REC-006.

Edge kinds (``Edge.kind``):

* the REC-002 link predicates: ``creates``, ``references``, ``elaborates``,
  ``same_project``;
* the REC-004 transitions: ``accepts``, ``rejects``, ``clarifies``,
  ``revises``, ``supersedes``, ``contradicts``, ``related_to`` (revoked
  events are left out);
* ``same_claim``: a REC-001 pair (undirected);
* ``conflicts_with``: a REC-003 conflict (undirected).

Every edge carries its **origin**: who made it (detector version or
reviewer), its review state, and the source message revisions of both ends.
An edge without source revisions on both ends is never returned: a
directional claim always comes with the messages it rests on.

Filters: which kinds to follow, which review states count (by default,
rejected links, rejected pairs and dismissed or resolved conflicts are left
out), how many steps, and which direction.

Talking points:
    - "One call answers 'what's connected to this decision, and how?',
      with the messages behind every step."
    - "Each record it reaches is labelled current, replaced, in conflict or
      pending, from the same projection the documents use."
"""

from __future__ import annotations

import json
from collections import defaultdict, deque
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.extraction.records import KnowledgeRecord
from knowledge_engine.extraction.store import KnowledgeRecordRow
from knowledge_engine.reconciliation.conflicts import RecordConflictRow
from knowledge_engine.reconciliation.equivalence import RecordEquivalenceRow
from knowledge_engine.reconciliation.projection import Status, project
from knowledge_engine.reconciliation.relations import RecordLinkRow, place
from knowledge_engine.reconciliation.timeline import DecisionEventRow, Transition

SAME_CLAIM = "same_claim"
CONFLICTS_WITH = "conflicts_with"
UNDIRECTED = frozenset({SAME_CLAIM, CONFLICTS_WITH})
# Review states that are left out unless asked for.
CLOSED = frozenset({"rejected", "dismissed", "resolved"})


class Direction(StrEnum):
    """Which way to follow directed edges."""

    OUT = "out"
    IN = "in"
    BOTH = "both"


@dataclass(frozen=True)
class Edge:
    """One connection between two records.

    Attributes:
        edge_id: The stored row's ID (link, event, pair or conflict).
        kind: What connects them (see the module text).
        source: Where it starts (for undirected kinds, the smaller ID).
        target: Where it points.
        origin: Who made it: a detector version or a reviewer.
        state: Its review state (``candidate``, ``accepted``, ``proposed``,
            ``confirmed``, ``unresolved``; events are ``recorded``).
        source_revisions: The messages the starting record rests on.
        target_revisions: The messages the other record rests on.
    """

    edge_id: str
    kind: str
    source: str
    target: str
    origin: str
    state: str
    source_revisions: tuple[str, ...]
    target_revisions: tuple[str, ...]

    @property
    def directed(self) -> bool:
        """False for same_claim and conflicts_with."""
        return self.kind not in UNDIRECTED


@dataclass(frozen=True)
class Step:
    """A record reached by the walk.

    Attributes:
        record_id: The ``krec_`` ID.
        record_type: Its kind.
        status: Its REC-006 standing, or None for kinds the projection
            doesn't judge (proposals, artefacts, references...).
        depth: Steps from the start (0 for the start).
        via: The edge it was reached by (None for the start).
    """

    record_id: str
    record_type: str
    status: Status | None
    depth: int
    via: Edge | None


def edges(session: Session) -> list[Edge]:
    """Every stored edge that cites sources on both ends, sorted by ID."""
    rows = session.scalars(select(KnowledgeRecordRow).order_by(KnowledgeRecordRow.record_id))
    cited = {
        p.record.record_id: p.revisions
        for p in place(session, [KnowledgeRecord.model_validate_json(r.record_json) for r in rows])
    }
    found: list[Edge] = []

    def add(edge_id: str, kind: str, a: str, b: str, origin: str, state: str) -> None:
        if cited.get(a) and cited.get(b):
            found.append(Edge(edge_id, kind, a, b, origin, state, cited[a], cited[b]))

    for link in session.scalars(select(RecordLinkRow)):
        add(
            link.link_id,
            link.predicate,
            link.from_record,
            link.to_record,
            link.detector,
            link.state,
        )
    events = session.scalars(select(DecisionEventRow)).all()
    withdrawn = {e.revokes_event for e in events if e.revokes_event}
    for event in events:
        if event.event_id in withdrawn or event.to_record is None or event.from_record is None:
            continue
        if event.predicate == Transition.REVOKES:
            continue
        add(
            event.event_id,
            event.predicate,
            event.from_record,
            event.to_record,
            event.actor,
            "recorded",
        )
    for pair in session.scalars(select(RecordEquivalenceRow)):
        add(pair.pair_id, SAME_CLAIM, pair.record_a, pair.record_b, pair.detector, pair.state)
    for conflict in session.scalars(select(RecordConflictRow)):
        add(
            conflict.conflict_id,
            CONFLICTS_WITH,
            conflict.record_a,
            conflict.record_b,
            conflict.detector,
            conflict.state,
        )
    return sorted(found, key=lambda e: e.edge_id)


def walk(
    session: Session,
    start: str,
    *,
    kinds: Iterable[str] | None = None,
    depth: int = 2,
    direction: Direction = Direction.BOTH,
    include_closed: bool = False,
) -> list[Step]:
    """Breadth-first walk from ``start``; each record once, at its shortest depth.

    Args:
        session: A read session.
        start: The ``krec_`` ID to start from.
        kinds: Edge kinds to follow (all if None).
        depth: The most steps away from the start.
        direction: For directed edges: follow them forwards, backwards or both.
            Undirected edges are always followed both ways.
        include_closed: Also follow rejected, dismissed and resolved edges.

    Returns:
        The start first, then the reached records in walk order.

    Raises:
        KeyError: No such record.
    """
    start_row = session.get(KnowledgeRecordRow, start)
    if start_row is None:
        raise KeyError("no such record")
    wanted = set(kinds) if kinds is not None else None
    adjacent: dict[str, list[tuple[str, Edge]]] = defaultdict(list)
    for edge in edges(session):
        if wanted is not None and edge.kind not in wanted:
            continue
        if not include_closed and edge.state in CLOSED:
            continue
        if not edge.directed or direction in (Direction.OUT, Direction.BOTH):
            adjacent[edge.source].append((edge.target, edge))
        if not edge.directed or direction in (Direction.IN, Direction.BOTH):
            adjacent[edge.target].append((edge.source, edge))
    standing = {e.record_id: e.status for e in project(session).entries}
    types = dict((r.record_id, r.record_type) for r in session.scalars(select(KnowledgeRecordRow)))
    steps = [Step(start, types[start], standing.get(start), 0, None)]
    seen = {start}
    queue = deque([(start, 0)])
    while queue:
        node, level = queue.popleft()
        if level >= depth:
            continue
        for neighbour, edge in sorted(adjacent[node], key=lambda pair: pair[1].edge_id):
            if neighbour in seen:
                continue
            seen.add(neighbour)
            steps.append(
                Step(neighbour, types[neighbour], standing.get(neighbour), level + 1, edge)
            )
            queue.append((neighbour, level + 1))
    return steps


def describe(step: Step) -> dict[str, object]:
    """A JSON-ready form of a step (IDs and labels only, no text)."""
    edge = step.via
    return {
        "record_id": step.record_id,
        "record_type": step.record_type,
        "status": step.status.value if step.status else None,
        "depth": step.depth,
        "via": None
        if edge is None
        else {
            "edge_id": edge.edge_id,
            "kind": edge.kind,
            "from": edge.source,
            "to": edge.target,
            "origin": edge.origin,
            "state": edge.state,
            "source_revisions": list(edge.source_revisions),
            "target_revisions": list(edge.target_revisions),
        },
    }


def to_json(steps: Iterable[Step]) -> str:
    """The walk as JSON (for the CLI and tests)."""
    return json.dumps([describe(s) for s in steps], sort_keys=True)
