"""The answer key for links between chats, and the scorer behind it (EVAL-012).

The relationship detectors (REL-002, REL-003) propose links such as "chat
B ``forked_from`` chat A" or "chat C ``quotes`` chat A". Until now nothing
said whether those proposals were right, so the release gate's
``relationships.precision`` line could only say BLOCKED. This module adds
the two missing pieces:

* **the key format** (``RelationshipKey``): a closed list of chats, and
  every true link between them, each with the evidence that proves it (a
  message number, who said it, and a word-for-word quote). It is a
  **separate file** from the classification and extraction golden set
  (``gold.py``), so adding it changes nothing in that set;
* **the scorer** (``score``): compares the engine's proposals with the key.

Why a *closed* list of chats: precision asks "of the links the engine
proposed, how many are right?". A proposal between two chats in the list
that the key doesn't contain is a wrong link, because whoever wrote the key
looked at every pair in the list. A proposal that touches a chat outside
the list can't be judged, so it is counted as ``out_of_scope``, never as
right or wrong.

Each proposal inside the list gets exactly one verdict:

* ``correct``: the key has the same link, in the same direction;
* ``wrong_direction``: the key has the same kind of link the other way
  round (B forked from A, but the engine said A forked from B);
* ``wrong_kind``: the key links the same two chats, but with another kind
  (the key says ``continues``, the engine said ``references``);
* ``false_link``: the key has no link between those two chats at all.

``related_to`` and ``same_project`` have no direction, so either order
matches. Links are named by the export's own conversation IDs, because
that is what an independent labelling session reading ``raw/`` sees.

**Independence.** The key records which session and model wrote it, and
must declare ``saw_engine_output: false``: the guardrail is that the
reference is written by a separate session that never sees what it will
score. ``check_evidence`` then proves every quote with code: the cited
message exists on the active path, has the stated speaker, and contains
the quote. Problems are reported by IDs and numbers only, never by text,
because the real key cites private chats.

Talking points:
    - "Precision for links needs a closed world: the key names every chat
      it covers, so a link it doesn't list really is a wrong link."
    - "A wrong direction and a wrong kind are counted separately from a
      made-up link, because they need different fixes."
    - "The answer key is written by a separate session that never saw the
      engine's output, and code checks every quote it cites."
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.graph.offsets import find_quote
from knowledge_engine.relationships.store import (
    ConversationRelationshipRow,
    EvidenceClass,
    RelationKind,
)

RELATIONSHIP_KEY_VERSION: Literal["relkey-v1"] = "relkey-v1"
SCORER_VERSION = "eval-012-v1"
THRESHOLD = 0.9  # TEST_STRATEGY §6: directional relationship precision >= 90%

# Kinds with no direction: "A related_to B" says the same as "B related_to A".
UNDIRECTED = frozenset({RelationKind.RELATED_TO, RelationKind.SAME_PROJECT})
VERDICTS = ("correct", "wrong_direction", "wrong_kind", "false_link")


class _Strict(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class KeyEvidence(_Strict):
    """One cited message that proves a link.

    Attributes:
        conversation: The export's conversation ID (one end of the link).
        message_number: 1-based position on the active path, numbered the
            way the engine numbers (``ConversationGraph.message_number``).
        speaker: Who wrote the message.
        quote: Words copied exactly from that message.
    """

    conversation: str = Field(min_length=1)
    message_number: int = Field(ge=1)
    speaker: Literal["user", "assistant"]
    quote: str = Field(min_length=1)


class KeyLink(_Strict):
    """One true link, read as "<from_conversation> <kind> <to_conversation>"."""

    from_conversation: str = Field(min_length=1)
    kind: RelationKind
    to_conversation: str = Field(min_length=1)
    evidence: tuple[KeyEvidence, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _ends_and_evidence(self) -> KeyLink:
        if self.from_conversation == self.to_conversation:
            raise ValueError("a link needs two different chats")
        ends = {self.from_conversation, self.to_conversation}
        if any(e.conversation not in ends for e in self.evidence):
            raise ValueError("evidence must cite one of the link's two chats")
        return self


class KeyProducer(_Strict):
    """Who wrote the key. ``saw_engine_output`` must be false (no self-grading)."""

    session: str = Field(min_length=1)
    model: str = Field(min_length=1)
    saw_engine_output: Literal[False]


class RelationshipKey(_Strict):
    """A closed list of chats and every true link between them."""

    schema_version: Literal["relkey-v1"] = RELATIONSHIP_KEY_VERSION
    produced_by: KeyProducer
    synthetic: bool  # True for test keys; the gate reports it as the data kind
    conversations: tuple[str, ...] = Field(min_length=2)
    links: tuple[KeyLink, ...] = ()

    @model_validator(mode="after")
    def _closed_and_unique(self) -> RelationshipKey:
        if len(set(self.conversations)) != len(self.conversations):
            raise ValueError("a chat is listed twice")
        listed = set(self.conversations)
        seen: set[tuple[str, str, str]] = set()
        for link in self.links:
            if not {link.from_conversation, link.to_conversation} <= listed:
                raise ValueError("every link must join two listed chats")
            identity = _identity(link.from_conversation, link.kind, link.to_conversation)
            if identity in seen:
                raise ValueError("the same link is listed twice")
            seen.add(identity)
        return self


def load_key(path: Path) -> RelationshipKey:
    """Read and validate a key file (JSON)."""
    return RelationshipKey.model_validate_json(path.read_text(encoding="utf-8"))


def key_schema() -> dict[str, Any]:
    """The key's JSON Schema, for the session that writes one."""
    return RelationshipKey.model_json_schema()


def _identity(from_id: str, kind: str, to_id: str) -> tuple[str, str, str]:
    # Undirected kinds are stored with the two ends sorted, so either order
    # of the same link has the same identity.
    if kind in UNDIRECTED:
        from_id, to_id = sorted((from_id, to_id))
    return (from_id, kind, to_id)


@dataclass(frozen=True)
class Proposal:
    """One link the engine proposed, by export conversation IDs."""

    from_conversation: str
    kind: str
    to_conversation: str


@dataclass
class RelationshipScore:
    """What ``score`` found. ``precision`` is None when nothing was scored."""

    proposed: int = 0
    out_of_scope: int = 0
    verdicts: Counter[str] = field(default_factory=Counter)
    per_kind: dict[str, Counter[str]] = field(default_factory=dict)
    key_links: int = 0
    found: int = 0

    @property
    def scored(self) -> int:
        """Proposals that got a verdict (inside the key's chats)."""
        return sum(self.verdicts.values())

    @property
    def precision(self) -> float | None:
        """Share of scored proposals that are correct."""
        return self.verdicts["correct"] / self.scored if self.scored else None

    @property
    def recall(self) -> float | None:
        """Shown for information; the gate measures precision only."""
        return self.found / self.key_links if self.key_links else None

    @property
    def passed(self) -> bool:
        """Measured, and at or above the threshold."""
        precision = self.precision
        return precision is not None and precision >= THRESHOLD


def score(key: RelationshipKey, proposals: Iterable[Proposal]) -> RelationshipScore:
    """Give every proposal one verdict against the key.

    The same link proposed by two detectors counts once: precision is about
    which links the engine claims, not how many detectors agreed.
    """
    listed = set(key.conversations)
    truth = {_identity(k.from_conversation, k.kind, k.to_conversation) for k in key.links}
    # Unordered pair -> the key's links between those two chats.
    pairs: dict[frozenset[str], set[tuple[str, str, str]]] = {}
    for identity in truth:
        pairs.setdefault(frozenset((identity[0], identity[2])), set()).add(identity)

    result = RelationshipScore(key_links=len(truth))
    distinct = {_identity(p.from_conversation, p.kind, p.to_conversation) for p in proposals}
    result.proposed = len(distinct)
    found: set[tuple[str, str, str]] = set()
    for from_id, kind, to_id in sorted(distinct):
        if not {from_id, to_id} <= listed:
            result.out_of_scope += 1
            continue
        if (from_id, kind, to_id) in truth:
            verdict = "correct"
            found.add((from_id, kind, to_id))
        elif (to_id, kind, from_id) in truth:
            verdict = "wrong_direction"
        elif frozenset((from_id, to_id)) in pairs:
            verdict = "wrong_kind"
        else:
            verdict = "false_link"
        result.verdicts[verdict] += 1
        result.per_kind.setdefault(kind, Counter())[verdict] += 1
    result.found = len(found)
    return result


def proposals_from_db(session: Session) -> list[Proposal]:
    """Every detector proposal in the workspace, by export conversation IDs.

    Links a person added (evidence class ``human``) are left out: they are
    not the engine's claims. Review state is ignored on purpose, so a
    reviewer rejecting bad links can't raise the engine's precision.
    """
    from knowledge_engine.importer.records import ConversationRow

    native = {
        row.conversation_id: row.native_conversation_id
        for row in session.scalars(select(ConversationRow))
    }
    rows = session.scalars(
        select(ConversationRelationshipRow).where(
            ConversationRelationshipRow.evidence_class != EvidenceClass.HUMAN.value
        )
    )
    return [
        Proposal(native[r.from_conversation_id], r.kind, native[r.to_conversation_id]) for r in rows
    ]


def check_evidence(session: Session, key: RelationshipKey) -> list[str]:
    """Prove every cited quote against the archive. Empty list = all good.

    Each problem names the link, conversation and message number only, so
    the report is safe to share even when the key cites private chats.
    """
    from knowledge_engine.importer.records import ConversationRow
    from knowledge_engine.rendering.transcript import load_conversation

    logical = {
        row.native_conversation_id: row.conversation_id
        for row in session.scalars(select(ConversationRow))
    }
    problems = [f"chat {c} is not in the archive" for c in key.conversations if c not in logical]
    # Message number -> (role, text) per chat, built once per chat.
    messages: dict[str, dict[int, tuple[str | None, str]]] = {}
    for index, link in enumerate(key.links, start=1):
        for evidence in link.evidence:
            where = f"link {index}, {evidence.conversation} message {evidence.message_number}"
            if evidence.conversation not in logical:
                continue  # already reported above
            if evidence.conversation not in messages:
                stored = load_conversation(session, logical[evidence.conversation])
                numbered: dict[int, tuple[str | None, str]] = {}
                for native_id in stored.graph.active_messages:
                    number = stored.graph.message_number(native_id)
                    node = stored.messages.get(native_id)
                    if number is not None and node is not None:
                        numbered[number] = (node.role, node.text)
                messages[evidence.conversation] = numbered
            found = messages[evidence.conversation].get(evidence.message_number)
            if found is None:
                problems.append(f"{where}: no such message on the active path")
            elif found[0] != evidence.speaker:
                problems.append(f"{where}: speaker is {found[0]}, key says {evidence.speaker}")
            elif not find_quote(found[1], evidence.quote):
                problems.append(f"{where}: quote not found in the message")
    return problems


def to_dict(key: RelationshipKey, result: RelationshipScore) -> dict[str, Any]:
    """JSON-ready numbers. No quotes and no chat text."""
    return {
        "version": SCORER_VERSION,
        "key_version": key.schema_version,
        "key_by": {"session": key.produced_by.session, "model": key.produced_by.model},
        "data": "synthetic" if key.synthetic else "real",
        "threshold": THRESHOLD,
        "precision": result.precision,
        "passed": result.passed,
        "recall": result.recall,
        "proposed": result.proposed,
        "scored": result.scored,
        "out_of_scope": result.out_of_scope,
        "verdicts": {v: result.verdicts[v] for v in VERDICTS},
        "per_kind": {
            kind: {v: counts[v] for v in VERDICTS}
            for kind, counts in sorted(result.per_kind.items())
        },
    }


def to_markdown(key: RelationshipKey, result: RelationshipScore) -> str:
    """A short report: the headline number, then the verdicts per kind."""
    data = to_dict(key, result)
    precision = "n/a (nothing to score)" if result.precision is None else f"{result.precision:.3f}"
    recall = "n/a" if result.recall is None else f"{result.recall:.3f}"
    lines = [
        "# Relationship precision (EVAL-012)",
        "",
        f"- Scorer `{SCORER_VERSION}`, key `{key.schema_version}` ({data['data']} data)",
        f"- Key written by session `{key.produced_by.session}` ({key.produced_by.model}),"
        " without seeing the engine's output",
        f"- Precision: **{precision}** (threshold {THRESHOLD:.2f}):"
        f" {'PASS' if result.passed else 'FAIL'}",
        f"- Recall, for information: {recall} ({result.found} of {result.key_links} key links)",
        f"- Proposals: {result.proposed} distinct, {result.scored} scored,"
        f" {result.out_of_scope} outside the key's chats",
        "",
        "| Kind | " + " | ".join(VERDICTS) + " |",
        "|---|" + "---|" * len(VERDICTS),
    ]
    for kind, counts in data["per_kind"].items():
        lines.append(f"| {kind} | " + " | ".join(str(counts[v]) for v in VERDICTS) + " |")
    return "\n".join(lines) + "\n"
