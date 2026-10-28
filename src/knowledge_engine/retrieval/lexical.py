"""Word and phrase search over every message, with SQLite FTS5 (RET-001).

FTS5 is SQLite's built-in full-text search: it keeps an inverted index
(word -> the rows that contain it) and ranks matches with BM25, the classic
"rare words that appear often in a short text score highest" formula.

The index is a **separate file**, ``<workspace>/index/search.db``, not part
of ``knowledge.db``. It holds nothing that can't be rebuilt from the
archive, so deleting it is always safe: the next search or import refills
it. Keeping it apart also means a change to how search works never needs a
migration of the archive itself.

One row per message revision, with its workspace, conversation and node, so
every hit points back to the exact version of the exact message it came
from. Search is always scoped to one workspace.

Three modes:

* ``tokens``: every word must appear, in any order (the default);
* ``phrase``: the words must appear together, in order;
* ``exact``: like ``phrase``, then the hit must also contain the query
  character for character, case included. Use it for codes and IDs.

``tokens`` and ``phrase`` ignore case and accents (``cafe`` finds ``café``).
The query is never passed to FTS5 as syntax: each word is quoted, so
``AND``, ``NOT``, quotes or brackets in a query are just text.

Talking points:
    - "The search index is a cache: one file I can delete and rebuild, so
      it can never become the only copy of anything."
    - "User text never reaches the query language. Every word is quoted,
      so a search for 'NOT' finds the word 'not'."
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.graph.nodes import canonical_node
from knowledge_engine.importer.records import ConversationRow, MessageNodeRow, MessageRevisionRow
from knowledge_engine.settings import Settings

# Bump when the schema or tokenizer changes: an index built by another
# version is dropped and rebuilt, never half-used.
SEARCH_INDEX_VERSION = "ret-001-v1"
_WORD = re.compile(r"\w+")
_BATCH = 500

_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    """CREATE TABLE IF NOT EXISTS documents (
        doc_id INTEGER PRIMARY KEY,
        revision_id TEXT NOT NULL UNIQUE,
        workspace_id TEXT NOT NULL,
        conversation_id TEXT NOT NULL,
        node_key TEXT NOT NULL,
        native_node_id TEXT NOT NULL,
        role TEXT,
        text TEXT NOT NULL
    )""",
    "CREATE INDEX IF NOT EXISTS documents_scope ON documents (workspace_id, conversation_id)",
    # External-content FTS5: the words index points at ``documents`` rows
    # instead of storing a second copy of every text.
    """CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
        text, content='documents', content_rowid='doc_id',
        tokenize='unicode61 remove_diacritics 2'
    )""",
    """CREATE TRIGGER IF NOT EXISTS documents_ai AFTER INSERT ON documents BEGIN
        INSERT INTO documents_fts(rowid, text) VALUES (new.doc_id, new.text);
    END""",
    """CREATE TRIGGER IF NOT EXISTS documents_ad AFTER DELETE ON documents BEGIN
        INSERT INTO documents_fts(documents_fts, rowid, text)
        VALUES ('delete', old.doc_id, old.text);
    END""",
)


class SearchMode(StrEnum):
    """How the query's words must appear in a message."""

    TOKENS = "tokens"
    PHRASE = "phrase"
    EXACT = "exact"


@dataclass(frozen=True)
class Passage:
    """One message revision's text, ready to index."""

    revision_id: str
    workspace_id: str
    conversation_id: str
    node_key: str
    native_node_id: str
    role: str | None
    text: str


@dataclass(frozen=True)
class SearchHit:
    """One matching message revision.

    Attributes:
        revision_id: The exact version of the message that matched.
        conversation_id: Its ``conv_`` ID.
        node_key: Its logical ``node_`` ID (anchors in notes and the UI).
        native_node_id: The export's node ID.
        role: Who wrote it.
        snippet: A short extract with matches in ``[brackets]``.
        score: BM25 rank; lower is better (SQLite's convention).
    """

    revision_id: str
    conversation_id: str
    node_key: str
    native_node_id: str
    role: str | None
    snippet: str
    score: float


def search_index_path(settings: Settings) -> Path:
    """Return ``<workspace_root>/index/search.db``."""
    return settings.workspace_root / "index" / "search.db"


def match_expression(query: str, mode: SearchMode) -> str | None:
    """Turn a query into a safe FTS5 MATCH expression, or None if it has no words.

    Each word is wrapped in double quotes, which FTS5 reads as a string to
    tokenise, never as an operator.

    Args:
        query: What the person typed.
        mode: How the words must appear.

    Returns:
        The expression, or None when the query has no letters or digits.
    """
    words = _WORD.findall(query)
    if not words:
        return None
    if mode is SearchMode.TOKENS:
        return " ".join(f'"{word}"' for word in words)
    return '"' + " ".join(words) + '"'


class LexicalIndex:
    """The search index file. Open, use, then ``close()`` (or use ``with``)."""

    def __init__(self, path: Path) -> None:
        """Open (or create) the index at ``path``.

        Args:
            path: The index file; its folder is created if missing.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.execute("PRAGMA journal_mode = WAL")
        version = self._version()
        if version is not None and version != SEARCH_INDEX_VERSION:
            self._drop()
        for statement in _SCHEMA:
            self._db.execute(statement)
        self._db.execute(
            "INSERT OR REPLACE INTO meta (key, value) VALUES ('version', ?)",
            (SEARCH_INDEX_VERSION,),
        )
        self._db.commit()

    def __enter__(self) -> LexicalIndex:
        """Use as a context manager."""
        return self

    def __exit__(self, *_: object) -> None:
        """Close on leaving the ``with`` block."""
        self.close()

    def close(self) -> None:
        """Close the file."""
        self._db.close()

    def _version(self) -> str | None:
        try:
            row = self._db.execute("SELECT value FROM meta WHERE key = 'version'").fetchone()
        except sqlite3.OperationalError:
            return None  # a new, empty file
        return str(row[0]) if row else None

    def _drop(self) -> None:
        for name in ("documents_fts", "documents", "meta"):
            self._db.execute(f"DROP TABLE IF EXISTS {name}")
        self._db.commit()

    def indexed(self) -> set[str]:
        """Return the revision IDs already in the index."""
        return {row[0] for row in self._db.execute("SELECT revision_id FROM documents")}

    def add(self, passages: Iterable[Passage]) -> int:
        """Index passages; ones already present are skipped.

        Args:
            passages: Message revisions to add.

        Returns:
            How many were added.
        """
        before = self._count()
        self._db.executemany(
            "INSERT OR IGNORE INTO documents (revision_id, workspace_id, conversation_id, "
            "node_key, native_node_id, role, text) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                (
                    p.revision_id,
                    p.workspace_id,
                    p.conversation_id,
                    p.node_key,
                    p.native_node_id,
                    p.role,
                    p.text,
                )
                for p in passages
            ),
        )
        self._db.commit()
        return self._count() - before

    def _count(self) -> int:
        return int(self._db.execute("SELECT count(*) FROM documents").fetchone()[0])

    def search(
        self,
        query: str,
        *,
        workspace_id: str,
        mode: SearchMode = SearchMode.TOKENS,
        limit: int = 20,
        conversation_id: str | None = None,
    ) -> list[SearchHit]:
        """Find message revisions matching ``query``, best first.

        Args:
            query: What to look for.
            workspace_id: Only this workspace is searched.
            mode: ``tokens``, ``phrase`` or ``exact``.
            limit: At most this many hits.
            conversation_id: Only this conversation, optionally.

        Returns:
            The hits; empty if the query has no words.
        """
        expression = match_expression(query, mode)
        if expression is None or limit <= 0:
            return []
        sql = (
            "SELECT d.revision_id, d.conversation_id, d.node_key, d.native_node_id, d.role, "
            "snippet(documents_fts, 0, '[', ']', '…', 12), rank, d.text "
            "FROM documents_fts JOIN documents d ON d.doc_id = documents_fts.rowid "
            "WHERE documents_fts MATCH ? AND d.workspace_id = ?"
        )
        params: list[object] = [expression, workspace_id]
        if conversation_id is not None:
            sql += " AND d.conversation_id = ?"
            params.append(conversation_id)
        sql += " ORDER BY rank, d.revision_id"
        hits: list[SearchHit] = []
        # Exact mode filters after FTS, so read rows lazily until enough pass.
        for row in self._db.execute(sql, params):
            if mode is SearchMode.EXACT and query.strip() not in row[7]:
                continue
            hits.append(
                SearchHit(
                    revision_id=row[0],
                    conversation_id=row[1],
                    node_key=row[2],
                    native_node_id=row[3],
                    role=row[4],
                    snippet=row[5],
                    score=row[6],
                )
            )
            if len(hits) >= limit:
                break
        return hits


def sync_index(session: Session, index: LexicalIndex) -> int:
    """Add every stored message revision the index doesn't have yet.

    Cheap when the index is current (one set difference of IDs), so it runs
    after each import and before each search.

    Args:
        session: A read session on the archive.
        index: The open search index.

    Returns:
        How many revisions were added.
    """
    have = index.indexed()
    added = 0
    batch: list[Passage] = []
    for passage in _passages(session, have):
        batch.append(passage)
        if len(batch) >= _BATCH:
            added += index.add(batch)
            batch = []
    if batch:
        added += index.add(batch)
    return added


def _passages(session: Session, skip: set[str]) -> Iterator[Passage]:
    rows = session.execute(
        select(
            MessageRevisionRow.revision_id,
            MessageRevisionRow.role,
            MessageRevisionRow.content_json,
            MessageRevisionRow.create_time,
            MessageNodeRow.node_key,
            MessageNodeRow.native_node_id,
            ConversationRow.conversation_id,
            ConversationRow.workspace_id,
        )
        .join(MessageNodeRow, MessageNodeRow.node_key == MessageRevisionRow.node_key)
        .join(ConversationRow, ConversationRow.conversation_id == MessageNodeRow.conversation_id)
        .order_by(MessageRevisionRow.revision_id)
    )
    for revision, role, content, created, node_key, native, conversation, workspace in rows:
        if revision in skip:
            continue
        message = {
            "id": native,
            "author": {"role": role},
            "content": json.loads(content),
            "create_time": created,
        }
        node = canonical_node(native, {"id": native, "message": message})
        if node is None:
            continue
        # Image-only messages are indexed with empty text: they never match,
        # but they're recorded, so the next sync doesn't parse them again.
        yield Passage(revision, workspace, conversation, node_key, native, role, node.text)
