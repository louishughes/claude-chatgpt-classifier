"""Related-conversation candidates from shared subjects and similar meaning (REL-003).

REL-002's detectors look for proof that one chat came from another. This
module looks for something weaker: two chats that are *about the same
thing*. It proposes two kinds of candidate, never anything stronger:

* ``same_project``: both chats have a segment labelled with the same
  approved project (a reviewer's label or the classifier's);
* ``related_to``: the chats share a distinctive approved topic, a
  distinctive named entity (a game, book, piece of software...), or their
  words are close in meaning (local embedding similarity).

Every candidate carries its reasons in plain words (``because``) plus the
IDs behind them: the labelled segments, the records naming the entity and
the message revisions they cite. It carries no private text.

Rules that keep this honest:

* **Similarity never proves a fork.** Only ``related_to`` and
  ``same_project`` are ever proposed here; ``continues`` and
  ``forked_from`` need REL-002's exact evidence or a person (ADR-0005).
* **Everything is a candidate.** Nothing is accepted automatically, and a
  pair a person already reviewed (accepted, rejected...) is never touched.
* **Common ground isn't evidence.** A topic or entity found in more than
  ``MAX_SPREAD`` chats says little about any two of them, so it is not used.
* **Pairs already linked by exact evidence are skipped**: a fork or a
  quote says more than "related".
* **Bounded.** Each chat keeps at most ``PER_CHAT`` partners per kind,
  the strongest first, so one busy project can't flood the review queue.

Comparing every pair of chats is quadratic; that is fine for a personal
archive of a few thousand chats, and is why this runs on request
(``ke related suggest``) rather than inside every import.

Talking points:
    - "Two chats about the same project or the same game get a 'related'
      suggestion with the reasons spelt out; a person decides."
    - "Looking alike is never treated as one chat being copied from the
      other: that needs proof, not resemblance."
"""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from itertools import combinations

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from knowledge_engine.classification.schema import PROJECTS_FIELD
from knowledge_engine.classification.store import effective_labels
from knowledge_engine.extraction.preamble import looks_like_preamble
from knowledge_engine.extraction.records import KnowledgeRecord, Trust
from knowledge_engine.extraction.store import KnowledgeRecordRow
from knowledge_engine.graph.nodes import NodeFlag
from knowledge_engine.importer.records import ConversationRow, MessageNodeRow, MessageRevisionRow
from knowledge_engine.relationships.store import (
    ConversationRelationshipRow,
    EvidenceClass,
    RelationKind,
    propose,
)
from knowledge_engine.rendering.transcript import load_conversation
from knowledge_engine.retrieval.embeddings import Embedder, LocalHashEmbedder, cosine, embed
from knowledge_engine.segmentation.overrides import load_segments
from knowledge_engine.settings import EgressPolicy
from knowledge_engine.taxonomy.registry import Dimension, TaxonomySnapshot, UnknownTermError

RELATED_DETECTOR = "related-v1"
SAME_PROJECT_DETECTOR = "same-project-v1"

MIN_SIMILARITY = 0.55  # cosine; the local embedder puts rewordings well above this
MIN_CONFIDENCE = 0.3  # one distinctive shared topic or entity is just enough
MAX_CONFIDENCE = 0.85  # resemblance is never certainty
MAX_SPREAD = 10
PER_CHAT = 5
MAX_CHARS = 20_000  # words per chat fed to the embedder
_SPOKEN = frozenset({"user", "assistant"})
# Detectors whose links already say more than "related" (REL-002).
_EXACT = frozenset({"native-node-v1", "prefix-v1", "chatgpt-url-v1", "quote-v1"})


@dataclass
class _Profile:
    """What one chat is about: labels, named entities and a meaning vector."""

    conversation_id: str
    create_time: float | None
    # Approved ID -> (segment IDs, first-message revisions) carrying it.
    projects: dict[str, tuple[set[str], set[str]]] = field(default_factory=dict)
    reviewed_projects: set[str] = field(default_factory=set)
    topics: dict[str, tuple[set[str], set[str]]] = field(default_factory=dict)
    # Entity key -> (record IDs, evidence revisions).
    entities: dict[str, tuple[set[str], set[str]]] = field(default_factory=dict)
    text: str = ""
    vector: list[float] = field(default_factory=list)


@dataclass(frozen=True)
class _Candidate:
    newer: str
    older: str
    kind: RelationKind
    evidence_class: EvidenceClass
    confidence: float
    evidence: dict[str, object]


def suggest_related(
    session: Session,
    *,
    workspace_id: str,
    taxonomy: TaxonomySnapshot | None,
    egress: EgressPolicy,
    embedder: Embedder | None = None,
    import_id: str | None = None,
) -> Counter[str]:
    """Propose ``same_project`` and ``related_to`` candidates for one workspace.

    Safe to run again: known relationships, whatever their review state,
    are never changed or proposed again.

    Args:
        session: A write session.
        workspace_id: Only chats in this workspace are compared.
        taxonomy: The version whose approved labels count; without one,
            only entities and meaning are used.
        egress: Checked before the embedder runs (the local one sends nothing).
        embedder: Defaults to the local, free ``LocalHashEmbedder``.
        import_id: The batch to credit new candidates to, if any.

    Returns:
        Counts of new candidates: ``new_same_project`` and ``new_related_to``.
    """
    profiles = _profiles(session, workspace_id, taxonomy)
    if len(profiles) < 2:
        return Counter()
    vectors = embed(embedder or LocalHashEmbedder(), [p.text for p in profiles], egress)
    for profile, vector in zip(profiles, vectors, strict=True):
        profile.vector = vector
    _attach_entities(session, {p.conversation_id: p for p in profiles})
    linked = _exactly_linked(session, [p.conversation_id for p in profiles])
    spread = _spread(profiles)
    candidates: list[_Candidate] = []
    for a, b in combinations(profiles, 2):
        if frozenset((a.conversation_id, b.conversation_id)) in linked:
            continue
        similarity = cosine(a.vector, b.vector)
        candidates += _judge(a, b, similarity, spread)
    counts: Counter[str] = Counter()
    for candidate in _strongest(candidates):
        detector = (
            SAME_PROJECT_DETECTOR
            if candidate.kind is RelationKind.SAME_PROJECT
            else RELATED_DETECTOR
        )
        if propose(
            session,
            from_conversation_id=candidate.newer,
            kind=candidate.kind,
            to_conversation_id=candidate.older,
            evidence_class=candidate.evidence_class,
            confidence=candidate.confidence,
            detector=detector,
            evidence=candidate.evidence,
            import_id=import_id,
        ):
            counts[f"new_{candidate.kind.value}"] += 1
    return counts


def _profiles(
    session: Session, workspace_id: str, taxonomy: TaxonomySnapshot | None
) -> list[_Profile]:
    ids = session.scalars(
        select(ConversationRow.conversation_id)
        .where(ConversationRow.workspace_id == workspace_id)
        .order_by(ConversationRow.conversation_id)
    ).all()
    profiles = []
    for conversation_id in ids:
        chat = load_conversation(session, conversation_id)
        profile = _Profile(conversation_id, chat.create_time)
        words = []
        for native_id in chat.graph.active_messages:
            node = chat.messages.get(native_id)
            if node is None or node.role not in _SPOKEN or NodeFlag.HIDDEN in node.flags:
                continue
            if looks_like_preamble(node.role, node.text):
                continue  # a shared pasted setup prompt must not make chats look alike
            words.append(node.text)
        profile.text = "\n".join(words)[:MAX_CHARS]
        if taxonomy is not None:
            for segment in load_segments(session, chat):
                first = chat.revisions.get(segment.messages[0]) if segment.messages else None
                labels = effective_labels(session, segment.segment_id, taxonomy)
                for name, target in (
                    (PROJECTS_FIELD, profile.projects),
                    (Dimension.TOPIC.value, profile.topics),
                ):
                    found = labels[name]
                    if found.source not in ("review", "machine"):
                        continue  # no label, or one this version no longer approves
                    for term in (found.primary, *found.secondary):
                        if term is None or not _approved(taxonomy, name, term):
                            continue
                        segments, revisions = target.setdefault(term, (set(), set()))
                        segments.add(segment.segment_id)
                        if first:
                            revisions.add(first)
                        if name == PROJECTS_FIELD and found.source == "review":
                            profile.reviewed_projects.add(term)
        profiles.append(profile)
    return profiles


def _approved(taxonomy: TaxonomySnapshot, field_name: str, term: str) -> bool:
    if field_name == PROJECTS_FIELD:
        return term in taxonomy.project_ids()
    try:
        taxonomy.term(term)
    except UnknownTermError:
        return False
    return True


def _entity_key(record: KnowledgeRecord) -> str | None:
    """An approved ID when the entity matched one, else a hash of its normal name.

    The hash keeps the (private) name out of the evidence while still
    letting two mentions of the same name meet.
    """
    if record.entity is None:
        return None
    if record.entity.matched_id:
        return record.entity.matched_id
    digest = hashlib.sha256(
        f"{record.entity.entity_type.value}\0{record.entity.norm_name}".encode()
    ).hexdigest()
    return f"ent_{digest[:24]}"


def _attach_entities(session: Session, profiles: dict[str, _Profile]) -> None:
    """Add each named entity to the chats its records' evidence comes from."""
    found: list[tuple[str, str, list[str]]] = []
    for stored in session.scalars(
        select(KnowledgeRecordRow).where(KnowledgeRecordRow.trust != Trust.REJECTED.value)
    ):
        record = KnowledgeRecord.model_validate_json(stored.record_json)
        key = _entity_key(record)
        if key is not None and record.evidence:
            found.append((key, record.record_id, [e.revision_id for e in record.evidence]))
    chat_of = _conversations_of(session, [r for _, _, revs in found for r in revs])
    for key, record_id, revisions in found:
        for revision in revisions:
            profile = profiles.get(chat_of.get(revision, ""))
            if profile is None:
                continue
            records, cited = profile.entities.setdefault(key, (set(), set()))
            records.add(record_id)
            cited.add(revision)


def _conversations_of(session: Session, revision_ids: Iterable[str]) -> dict[str, str]:
    wanted = sorted(set(revision_ids))
    found: dict[str, str] = {}
    for start in range(0, len(wanted), 500):
        found |= dict(
            session.execute(
                select(MessageRevisionRow.revision_id, MessageNodeRow.conversation_id)
                .join(MessageNodeRow, MessageNodeRow.node_key == MessageRevisionRow.node_key)
                .where(MessageRevisionRow.revision_id.in_(wanted[start : start + 500]))
            )
            .tuples()
            .all()
        )
    return found


def _exactly_linked(session: Session, ids: list[str]) -> set[frozenset[str]]:
    """Pairs REL-002 already linked with exact evidence (in any review state)."""
    rows = session.execute(
        select(
            ConversationRelationshipRow.from_conversation_id,
            ConversationRelationshipRow.to_conversation_id,
        ).where(
            ConversationRelationshipRow.detector.in_(sorted(_EXACT)),
            or_(
                ConversationRelationshipRow.from_conversation_id.in_(ids),
                ConversationRelationshipRow.to_conversation_id.in_(ids),
            ),
        )
    )
    return {frozenset(pair) for pair in rows.tuples()}


def _spread(profiles: list[_Profile]) -> Counter[str]:
    """How many chats carry each topic and entity."""
    spread: Counter[str] = Counter()
    for profile in profiles:
        spread.update(set(profile.topics) | set(profile.entities))
    return spread


def _judge(a: _Profile, b: _Profile, similarity: float, spread: Counter[str]) -> list[_Candidate]:
    newer, older = _newer_older(a, b)
    found = []
    projects = sorted(set(a.projects) & set(b.projects))
    if projects:
        reviewed = all(p in a.reviewed_projects and p in b.reviewed_projects for p in projects)
        found.append(
            _Candidate(
                newer.conversation_id,
                older.conversation_id,
                RelationKind.SAME_PROJECT,
                EvidenceClass.SEMANTIC,
                # A person's labels on both sides are better ground than the classifier's.
                0.7 if reviewed else 0.5,
                {
                    "because": [f"both chats are labelled with project {p}" for p in projects],
                    "project_ids": projects,
                    "similarity": round(similarity, 3),
                    "revisions": _cited((newer.projects, older.projects, projects)),
                },
            )
        )
    topics = sorted(t for t in set(a.topics) & set(b.topics) if spread[t] <= MAX_SPREAD)
    entities = sorted(e for e in set(a.entities) & set(b.entities) if spread[e] <= MAX_SPREAD)
    because = [f"both chats are labelled with topic {t}" for t in topics]
    because += [f"both chats name the same {_entity_word(e)}" for e in entities]
    misses = 1.0
    misses *= 0.7 ** min(len(topics), 2)
    misses *= 0.7 ** min(len(entities), 2)
    if similarity >= MIN_SIMILARITY:
        because.append(f"their words are similar (cosine {similarity:.2f})")
        misses *= 1.0 - 0.6 * similarity
    confidence = min(MAX_CONFIDENCE, round(1.0 - misses, 3))
    if because and confidence >= MIN_CONFIDENCE:
        records = sorted({r for e in entities for r in a.entities[e][0] | b.entities[e][0]})
        evidence: dict[str, object] = {
            "because": because,
            "term_ids": topics,
            "entity_keys": entities,
            "records": records,
            "similarity": round(similarity, 3),
            "revisions": _cited(
                (newer.topics, older.topics, topics), (newer.entities, older.entities, entities)
            ),
        }
        found.append(
            _Candidate(
                newer.conversation_id,
                older.conversation_id,
                RelationKind.RELATED_TO,
                EvidenceClass.SEMANTIC,
                confidence,
                evidence,
            )
        )
    return found


def _entity_word(key: str) -> str:
    return "named thing" if key.startswith("ent_") else f"named thing ({key})"


_Items = dict[str, tuple[set[str], set[str]]]


def _cited(*shared: tuple[_Items, _Items, list[str]]) -> dict[str, list[str]]:
    """The message revisions behind the shared keys, per side ("from" is the newer chat)."""
    sides: dict[str, set[str]] = {"from": set(), "to": set()}
    for newer_items, older_items, keys in shared:
        for key in keys:
            sides["from"] |= newer_items[key][1]
            sides["to"] |= older_items[key][1]
    return {side: sorted(revisions) for side, revisions in sides.items()}


def _newer_older(a: _Profile, b: _Profile) -> tuple[_Profile, _Profile]:
    """Point the link from the later chat to the earlier one (ID order if unknown).

    These kinds have no real direction; a fixed rule just keeps one row per pair.
    """
    if a.create_time is not None and b.create_time is not None and a.create_time != b.create_time:
        return (a, b) if a.create_time > b.create_time else (b, a)
    return (a, b) if a.conversation_id > b.conversation_id else (b, a)


def _strongest(candidates: list[_Candidate]) -> list[_Candidate]:
    """Keep a pair only if it is among the ``PER_CHAT`` strongest of either chat."""
    ranked = sorted(
        candidates,
        key=lambda c: (-c.confidence, -float(c.evidence["similarity"]), c.newer, c.older),  # type: ignore[arg-type]
    )
    taken: dict[tuple[str, RelationKind], int] = defaultdict(int)
    kept = []
    for candidate in ranked:
        ends = [(candidate.newer, candidate.kind), (candidate.older, candidate.kind)]
        if any(taken[end] < PER_CHAT for end in ends):
            kept.append(candidate)
            for end in ends:
                taken[end] += 1
    return kept
