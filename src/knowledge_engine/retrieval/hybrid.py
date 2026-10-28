"""One ranked list from word, meaning and record search (RET-004).

Three **channels** each rank what they find:

* ``lexical``: the word index (RET-001), best BM25 first;
* ``semantic``: the meaning index (RET-003), closest first (optional: the
  vector index can be left out, TR-06);
* ``structured``: stored knowledge records (decisions, requirements...)
  whose assertion shares words with the query, most shared words first.

**Reciprocal rank fusion (RRF).** Each item scores ``1 / (K + rank)`` in
every channel that found it, summed. Ranks, not raw scores, are added, so a
BM25 number and a cosine number never have to be put on one scale, and
something found by two channels beats something found by one. ``K = 60``
is the usual constant: it stops one channel's first place from drowning
everything else.

**Exact text is never lost.** Fusion can push a message that contains a
code like ``ERR-4012`` below the cut when many messages are vaguely
similar. So each *exact term* (by default the whole query; the RET-005
planner passes the codes and quoted text it found) is also looked up
character for character, and those messages are **pinned** first, in the
word index's order, before the fused rest.

**Stable de-duplication.** A message is one hit however many channels or
stored versions (revisions) of it matched: hits are keyed by the message
(``node_key``), the version shown is the best-ranked one (revision ID breaks
ties), and the other matching versions are listed. A record is keyed by its
``krec_`` ID. Ties in the fused score are broken by the key, so the same
query on the same data always gives the same list.

**Scope before and after.** Each channel is asked for one workspace only,
and every fused hit's chat is checked again against that workspace before
it is returned (TR-06); anything else is dropped and counted.

Talking points:
    - "Three searches vote with their rankings; something two of them agree
      on rises to the top."
    - "If the message contains exactly what you typed, it's pinned first,
      so a code never vanishes under fuzzy matches."
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.extraction.records import KnowledgeRecord, Trust
from knowledge_engine.extraction.store import KnowledgeRecordRow
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.reconciliation.equivalence import content_words
from knowledge_engine.reconciliation.relations import place
from knowledge_engine.retrieval.embeddings import stem
from knowledge_engine.retrieval.lexical import LexicalIndex, SearchHit, SearchMode
from knowledge_engine.retrieval.semantic import SemanticHit, SemanticIndex
from knowledge_engine.settings import EgressPolicy

HYBRID_VERSION = "ret-004-v1"
RRF_K = 60


class Channel(StrEnum):
    """Where a ranking came from."""

    LEXICAL = "lexical"
    SEMANTIC = "semantic"
    STRUCTURED = "structured"


@dataclass(frozen=True)
class Fused:
    """One key's fused score and its rank (from 1) in each channel that found it."""

    key: str
    score: float
    ranks: Mapping[str, int]


def fuse(rankings: Mapping[str, Sequence[str]], *, k: int = RRF_K) -> list[Fused]:
    """Reciprocal rank fusion of ranked key lists, best first.

    A key repeated within one list counts once, at its first (best) rank.
    Ties are broken by the key, so the order never depends on dict order.

    Args:
        rankings: Channel name -> its keys, best first.
        k: The RRF constant (higher flattens the advantage of first place).
    """
    score: dict[str, float] = defaultdict(float)
    ranks: dict[str, dict[str, int]] = defaultdict(dict)
    for channel in sorted(rankings):
        rank = 0
        for key in rankings[channel]:
            if channel in ranks[key]:
                continue
            rank += 1
            ranks[key][channel] = rank
            score[key] += 1.0 / (k + rank)
    return sorted(
        (Fused(key, score[key], dict(ranks[key])) for key in score),
        key=lambda f: (-f.score, f.key),
    )


@dataclass(frozen=True)
class HybridHit:
    """One fused result: a message or a knowledge record.

    Attributes:
        kind: ``message`` or ``record``.
        key: The message's ``node_key``, or the record's ``krec_`` ID.
        conversation_id: The chat it is in (for a record, the chat its
            evidence is in).
        revisions: Message versions: for a message, the one shown first and
            then any other matching versions; for a record, the versions
            its evidence cites.
        score: The fused RRF score (pinned hits keep theirs, too).
        ranks: Rank in each channel that found it, e.g. ``{"lexical": 1}``.
        pinned: True if it contains an exact term and was put first.
        native_node_id: The export's node ID (messages only).
        role: Who wrote it (messages only).
        snippet: The word index's extract, when it matched there.
        record_type: The record's kind (records only).
        trust: The record's trust (records only).
        similarity: The best cosine similarity the meaning index gave it,
            if it found it (the answer service's relevance gate, RET-007).
    """

    kind: str
    key: str
    conversation_id: str | None
    revisions: tuple[str, ...]
    score: float
    ranks: Mapping[str, int] = field(default_factory=dict)
    pinned: bool = False
    native_node_id: str | None = None
    role: str | None = None
    snippet: str | None = None
    record_type: str | None = None
    trust: str | None = None
    similarity: float | None = None

    @property
    def revision_id(self) -> str | None:
        """The version shown first, if any."""
        return self.revisions[0] if self.revisions else None


@dataclass(frozen=True)
class HybridResult:
    """A hybrid search's hits and what was left out.

    Attributes:
        hits: Pinned exact matches first, then the fused rest; at most ``limit``.
        out_of_scope: Hits dropped by the final workspace check (should be 0).
        channels: The channels that ran.
    """

    hits: tuple[HybridHit, ...]
    out_of_scope: int
    channels: tuple[str, ...]


def query_words(text: str) -> frozenset[str]:
    """The stems of a text's content words (shared by the structured channel and RET-005)."""
    return frozenset(stem(w) for w in content_words(text))


@dataclass
class _Message:
    # Gathers every channel's sightings of one message before fusion.
    conversation_id: str
    native_node_id: str
    role: str | None
    best: dict[str, tuple[int, str]] = field(default_factory=dict)  # revision -> (rank, id)
    snippet: str | None = None
    similarity: float | None = None


class HybridRetriever:
    """Runs the channels over open indexes and fuses them. Reads only.

    The caller opens and syncs the indexes (``sync_index``,
    ``sync_semantic``) and closes them.
    """

    def __init__(
        self,
        session: Session,
        lexical: LexicalIndex,
        semantic: SemanticIndex | None,
        egress: EgressPolicy,
    ) -> None:
        """Use these indexes; ``semantic`` may be None (word and record search only)."""
        self._session = session
        self._lexical = lexical
        self._semantic = semantic
        self._egress = egress

    def search(
        self,
        query: str,
        *,
        workspace_id: str,
        limit: int = 20,
        conversation_id: str | None = None,
        exact_terms: Sequence[str] | None = None,
        channels: Iterable[Channel] | None = None,
    ) -> HybridResult:
        """Fused hits for ``query`` in one workspace, best first.

        Args:
            query: What to look for.
            workspace_id: Only this workspace.
            limit: At most this many hits.
            conversation_id: Only this chat, optionally.
            exact_terms: Texts whose exact matches are pinned first (default:
                the whole query).
            channels: Which channels to run (default: all available).

        Returns:
            The hits, plus how many failed the final scope check.
        """
        wanted = set(channels) if channels is not None else set(Channel)
        if self._semantic is None:
            wanted.discard(Channel.SEMANTIC)
        if not query.strip() or limit <= 0:
            return HybridResult((), 0, tuple(sorted(wanted)))
        depth = max(3 * limit, 30)
        messages: dict[str, _Message] = {}
        rankings: dict[str, list[str]] = {}

        def seen(channel: Channel, rank: int, hit: SearchHit | SemanticHit) -> str:
            entry = messages.setdefault(
                hit.node_key, _Message(hit.conversation_id, hit.native_node_id, hit.role)
            )
            entry.best.setdefault(hit.revision_id, (rank, hit.revision_id))
            entry.best[hit.revision_id] = min(entry.best[hit.revision_id], (rank, hit.revision_id))
            if isinstance(hit, SearchHit) and entry.snippet is None:
                entry.snippet = hit.snippet
            if isinstance(hit, SemanticHit):
                entry.similarity = max(entry.similarity or hit.score, hit.score)
            return hit.node_key

        if Channel.LEXICAL in wanted:
            found = self._lexical.search(
                query, workspace_id=workspace_id, limit=depth, conversation_id=conversation_id
            )
            rankings[Channel.LEXICAL] = [
                seen(Channel.LEXICAL, i, h) for i, h in enumerate(found, 1)
            ]
        if Channel.SEMANTIC in wanted and self._semantic is not None:
            close = self._semantic.search(
                query,
                workspace_id=workspace_id,
                egress=self._egress,
                limit=depth,
                conversation_ids=[conversation_id] if conversation_id else None,
            )
            rankings[Channel.SEMANTIC] = [
                seen(Channel.SEMANTIC, i, h) for i, h in enumerate(close, 1)
            ]
        records: dict[str, HybridHit] = {}
        if Channel.STRUCTURED in wanted:
            for record_hit in self._records(query, workspace_id, conversation_id, depth):
                records[record_hit.key] = record_hit
            rankings[Channel.STRUCTURED] = list(records)

        pinned_keys: list[str] = []
        for term in exact_terms if exact_terms is not None else [query]:
            for hit in self._lexical.search(
                term,
                workspace_id=workspace_id,
                mode=SearchMode.EXACT,
                limit=depth,
                conversation_id=conversation_id,
            ):
                seen(Channel.LEXICAL, depth + 1, hit)  # recorded, but never ranks it
                if hit.node_key not in pinned_keys:
                    pinned_keys.append(hit.node_key)

        fused = {f.key: f for f in fuse(rankings)}

        def build(key: str, pinned: bool) -> HybridHit:
            ranking = fused.get(key)
            score, ranks = (ranking.score, ranking.ranks) if ranking else (0.0, {})
            if key in records:
                record = records[key]
                return HybridHit(
                    "record",
                    key,
                    record.conversation_id,
                    record.revisions,
                    score,
                    ranks,
                    record_type=record.record_type,
                    trust=record.trust,
                )
            entry = messages[key]
            versions = tuple(r for _, r in sorted(entry.best.values()))
            return HybridHit(
                "message",
                key,
                entry.conversation_id,
                versions,
                score,
                ranks,
                pinned=pinned,
                native_node_id=entry.native_node_id,
                role=entry.role,
                snippet=entry.snippet,
                similarity=entry.similarity,
            )

        ordered = [build(k, True) for k in pinned_keys]
        ordered += [build(f.key, False) for f in fused.values() if f.key not in pinned_keys]
        in_scope = self._workspaces({h.conversation_id for h in ordered if h.conversation_id})
        kept = [h for h in ordered if in_scope.get(h.conversation_id or "") == workspace_id]
        return HybridResult(tuple(kept[:limit]), len(ordered) - len(kept), tuple(sorted(rankings)))

    def _workspaces(self, conversation_ids: set[str]) -> dict[str, str]:
        if not conversation_ids:
            return {}
        return {
            conversation: workspace
            for conversation, workspace in self._session.execute(
                select(ConversationRow.conversation_id, ConversationRow.workspace_id).where(
                    ConversationRow.conversation_id.in_(sorted(conversation_ids))
                )
            )
        }

    def _records(
        self, query: str, workspace_id: str, conversation_id: str | None, depth: int
    ) -> list[HybridHit]:
        # The structured channel: records sharing content words with the query.
        wanted = query_words(query)
        if not wanted:
            return []
        rows = self._session.scalars(
            select(KnowledgeRecordRow).order_by(KnowledgeRecordRow.record_id)
        )
        candidates = []
        for row in rows:
            record = KnowledgeRecord.model_validate_json(row.record_json)
            if record.trust is Trust.REJECTED:
                continue  # a reviewer said it isn't so: never retrieved as knowledge
            shared = len(wanted & query_words(record.assertion))
            if shared:
                candidates.append((shared, record))
        placed = place(self._session, [record for _, record in candidates])
        shared_by = {record.record_id: shared for shared, record in candidates}
        chats = self._workspaces({p.conversation_id for p in placed if p.conversation_id})
        hits = [
            HybridHit(
                "record",
                p.record.record_id,
                p.conversation_id,
                tuple(p.revisions),
                0.0,
                record_type=p.record.record_type.value,
                trust=p.record.trust.value,
            )
            for p in placed
            if p.conversation_id
            and chats.get(p.conversation_id) == workspace_id
            and (conversation_id is None or p.conversation_id == conversation_id)
        ]
        hits.sort(key=lambda h: (-shared_by[h.key], h.key))
        return hits[:depth]
