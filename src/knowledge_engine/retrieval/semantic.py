"""Search by meaning: a local vector index over every message (RET-003).

Like the word index (RET-001), this is a **separate, rebuildable file**,
``<workspace>/index/vectors.db``, never part of the archive. It holds one
vector per message revision, with the same context keys as the word index
(workspace, conversation, node, revision, role), so every hit points at the
exact version of the exact message.

**Versioned.** The file records the embedder's fingerprint, model and
dimension (RET-002). Opening it with a different embedder raises
``StaleIndexError``; ``rebuild=True`` empties it first. Vectors from two
models are never mixed.

**Safe replay.** Each stored vector keeps the SHA-256 of the text it was
made from. A sync only embeds revisions that are new or whose text
changed, so running it twice embeds nothing the second time and costs
nothing (TR: unchanged imports make no embedding writes). Empty texts
(image-only messages) are recorded without a vector and never match.

**Scope.** A search always names one workspace and can be narrowed to some
conversations or roles; nothing outside the scope is even scored.

Search is brute force: every vector in scope is compared with the query
(cosine similarity), best first, ties broken by revision ID so results are
deterministic. That is fast enough for one person's chats (tens of
thousands of messages); a vector library can replace it behind the same
class later.

Talking points:
    - "The meaning index is a cache file stamped with the model that built
      it. Change the model and it refuses to answer until rebuilt."
    - "Re-running the sync re-embeds nothing that hasn't changed, so it's
      free to run after every import."
"""

from __future__ import annotations

import hashlib
import sqlite3
from array import array
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from knowledge_engine.retrieval.embeddings import Embedder, cosine, embed
from knowledge_engine.retrieval.lexical import Passage, passages
from knowledge_engine.settings import EgressPolicy, Settings

SEMANTIC_INDEX_VERSION = "ret-003-v1"
_BATCH = 256

_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    """CREATE TABLE IF NOT EXISTS vectors (
        revision_id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        node_key TEXT NOT NULL,
        native_node_id TEXT NOT NULL,
        role TEXT,
        text_sha256 TEXT NOT NULL,
        vector BLOB
    )""",
    "CREATE INDEX IF NOT EXISTS vectors_scope ON vectors (workspace_id, conversation_id)",
)


class StaleIndexError(RuntimeError):
    """The index was built by another embedder (or another index version)."""


@dataclass(frozen=True)
class SemanticHit:
    """One message revision close in meaning to the query.

    Attributes:
        revision_id: The exact message version.
        conversation_id: Its ``conv_`` ID.
        node_key: Its logical node (anchors in notes and the UI).
        native_node_id: The export's node ID.
        role: Who wrote it.
        score: Cosine similarity, higher is closer (at most 1).
    """

    revision_id: str
    conversation_id: str
    node_key: str
    native_node_id: str
    role: str | None
    score: float


@dataclass(frozen=True)
class SyncReport:
    """What one sync did.

    Attributes:
        embedded: Revisions embedded now (new or changed text).
        unchanged: Revisions already indexed with the same text.
        empty: Revisions with no text, recorded without a vector.
    """

    embedded: int
    unchanged: int
    empty: int


def semantic_index_path(settings: Settings) -> Path:
    """Return ``<workspace_root>/index/vectors.db``."""
    return settings.workspace_root / "index" / "vectors.db"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class SemanticIndex:
    """The vector index file for one embedder. Open, use, ``close()`` (or ``with``)."""

    def __init__(self, path: Path, embedder: Embedder, *, rebuild: bool = False) -> None:
        """Open (or create) the index for ``embedder``.

        Args:
            path: The index file; its folder is created if missing.
            embedder: The embedder whose vectors this file holds.
            rebuild: Empty a file built by another embedder instead of refusing it.

        Raises:
            StaleIndexError: The file belongs to another embedder or index
                version, and ``rebuild`` is False.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        self._embedder = embedder
        self._db = sqlite3.connect(path)
        for statement in _SCHEMA:
            self._db.execute(statement)
        identity = embedder.identity
        wanted = {
            "index_version": SEMANTIC_INDEX_VERSION,
            "fingerprint": identity.fingerprint,
            "provider_id": identity.provider_id,
            "model": identity.model,
            "dimension": str(identity.dimension),
        }
        stored = dict(self._db.execute("SELECT key, value FROM meta").fetchall())
        if stored and any(stored.get(k) != v for k, v in wanted.items()):
            if not rebuild:
                self._db.close()
                raise StaleIndexError(
                    f"index built by {stored.get('model')} ({stored.get('dimension')} dims); "
                    f"now {identity.model} ({identity.dimension} dims): rebuild it"
                )
            self._db.execute("DELETE FROM vectors")
            self._db.execute("DELETE FROM meta")
        self._db.executemany(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", wanted.items()
        )
        self._db.commit()

    def __enter__(self) -> SemanticIndex:
        """Use as a context manager."""
        return self

    def __exit__(self, *_: object) -> None:
        """Close on leaving the ``with`` block."""
        self.close()

    def close(self) -> None:
        """Close the file."""
        self._db.close()

    def _known(self) -> dict[str, str]:
        return dict(self._db.execute("SELECT revision_id, text_sha256 FROM vectors").fetchall())

    def upsert(self, items: Iterable[Passage], egress: EgressPolicy) -> SyncReport:
        """Embed and store passages that are new or whose text changed.

        Args:
            items: Message revisions.
            egress: Checked before any embedder that sends data is called.

        Returns:
            Counts of embedded, unchanged and empty passages.
        """
        known = self._known()
        embedded = unchanged = empty = 0
        pending: list[Passage] = []

        def flush() -> int:
            if not pending:
                return 0
            found = embed(self._embedder, [p.text for p in pending], egress)
            self._db.executemany(
                "INSERT OR REPLACE INTO vectors VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    (
                        p.revision_id,
                        p.workspace_id,
                        p.conversation_id,
                        p.node_key,
                        p.native_node_id,
                        p.role,
                        _sha(p.text),
                        array("f", vector).tobytes(),
                    )
                    for p, vector in zip(pending, found, strict=True)
                ),
            )
            self._db.commit()
            count = len(pending)
            pending.clear()
            return count

        for passage in items:
            digest = _sha(passage.text)
            if known.get(passage.revision_id) == digest:
                unchanged += 1
                continue
            if not passage.text.strip():
                self._db.execute(
                    "INSERT OR REPLACE INTO vectors VALUES (?, ?, ?, ?, ?, ?, ?, NULL)",
                    (
                        passage.revision_id,
                        passage.workspace_id,
                        passage.conversation_id,
                        passage.node_key,
                        passage.native_node_id,
                        passage.role,
                        digest,
                    ),
                )
                empty += 1
                continue
            pending.append(passage)
            if len(pending) >= _BATCH:
                embedded += flush()
        embedded += flush()
        self._db.commit()
        return SyncReport(embedded, unchanged, empty)

    def search(
        self,
        query: str,
        *,
        workspace_id: str,
        egress: EgressPolicy,
        limit: int = 20,
        conversation_ids: Sequence[str] | None = None,
        roles: Sequence[str] | None = None,
        min_score: float = 0.0,
    ) -> list[SemanticHit]:
        """The ``limit`` message revisions closest to ``query`` in scope, best first.

        Args:
            query: What to look for.
            workspace_id: Only this workspace is searched.
            egress: Checked before embedding the query with a sending embedder.
            limit: At most this many hits.
            conversation_ids: Only these conversations, optionally.
            roles: Only messages by these roles (``user``, ``assistant``...).
            min_score: Leave out hits scoring below this.

        Returns:
            The hits; empty for an empty query.
        """
        if not query.strip() or limit <= 0:
            return []
        [target] = embed(self._embedder, [query], egress)
        sql = (
            "SELECT revision_id, conversation_id, node_key, native_node_id, role, vector "
            "FROM vectors WHERE workspace_id = ? AND vector IS NOT NULL"
        )
        params: list[object] = [workspace_id]
        if conversation_ids is not None:
            sql += f" AND conversation_id IN ({','.join('?' * len(conversation_ids))})"
            params += list(conversation_ids)
        if roles is not None:
            sql += f" AND role IN ({','.join('?' * len(roles))})"
            params += list(roles)
        scored = []
        for revision, conversation, node_key, native, role, blob in self._db.execute(sql, params):
            vector = array("f")
            vector.frombytes(blob)
            score = cosine(target, vector)
            if score > min_score:
                scored.append(SemanticHit(revision, conversation, node_key, native, role, score))
        scored.sort(key=lambda hit: (-hit.score, hit.revision_id))
        return scored[:limit]


def sync_semantic(session: Session, index: SemanticIndex, egress: EgressPolicy) -> SyncReport:
    """Bring the index up to date with every stored message revision."""
    return index.upsert(passages(session, set()), egress)
