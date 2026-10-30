"""Delete conversations for good, with everything made from them (OPS-004).

"Delete" here means **purge**: the conversation, every message version,
and everything the engine derived from them go, and a check afterwards
proves that search and the database can no longer find any of it. That
set of derived things is the **closure**:

* the message tree: nodes, versions, edges, import observations;
* images: each occurrence goes; the image itself (bytes included) goes
  only when no remaining chat still shows it;
* links, YouTube mentions and social-account mentions; a link target,
  video (with its transcript) or account goes only when nothing else
  mentions it;
* related-chat links touching the chat, and their review history;
* segments' labels, label reviews, segment corrections, extraction runs,
  the model requests and answers behind them, and their jobs;
* knowledge records that quote it or are scoped to it, plus everything
  attached to those records (trust history, links, equivalences,
  conflicts, timeline events);
* document builds that used any of it (the vault is then re-synced);
* the archived copy of each export file that held the chat, and the
  search indexes (they are rebuilt without it).

How it runs:

1. **Plan** (``plan_purge``): reads only, and lists how many rows of each
   kind would go, what is kept because other chats share it, and what the
   engine *can't* delete (the original export in ``raw/``, images kept by
   reference there, older backups). The plan has a short **token**.
2. **Purge** (``run_purge``): needs that token, so nothing is deleted that
   the person didn't see planned. One database transaction deletes the
   closure, leaves **tombstones** (so the next import skips the chat) and
   writes an audit event with counts only. Then the files go, the
   database is compacted (``VACUUM``) so deleted pages are rewritten, and
   the indexes are rebuilt.
3. **Verify**: before deleting, a few short passages of the chats' own
   text are kept in memory (never written anywhere) as **probes**. After:
   searching for each probe must find nothing, the database file's bytes
   must not contain them, no table may still mention a deleted ID, and
   every planned file must be gone. The result goes in the audit event.

Imported notes (ING-012) are the person's own separate files, so a purge
never changes them, even when a note quotes the chat (ING-015, Louis's
decision). A probe a note also holds is still searched for and still
looked for in the vault (neither can find a note's text), but not in the
database file's bytes, where the note's copy legitimately is. The check
names each note holding a probe (``kept_in_notes``: ID, file name, line
locator and version, never text) so the person can remove it if they want.

Append-only tables (review logs, timeline events, document builds) refuse
deletes by trigger. A purge is the one sanctioned exception: it lifts
those triggers inside its own transaction and puts them back before it
commits, so a crash half-way leaves them in place.

Talking points:
    - "Deleting a chat deletes everything made from it, but an image or
      video another chat still uses stays."
    - "Nothing is deleted without a plan first, and the purge needs the
      plan's token, so I always see what will go."
    - "After the purge I prove it: searching for the chat's own words
      finds nothing, and its IDs appear nowhere in the database."
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import uuid
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from knowledge_engine.importer.archive import remove_stored
from knowledge_engine.infrastructure.db import database_path
from knowledge_engine.retention.tombstones import TombstoneKind, conversation_key
from knowledge_engine.settings import Settings

PURGE_VERSION = "ops-004-v1"
_CHUNK = 500
_MAX_PROBES = 40
_PROBE_WORDS = 6

# Children before parents, so foreign keys hold after every statement.
DELETE_ORDER = (
    "classification_labels",
    "classifications",
    "classification_reviews",
    "extraction_runs",
    "model_outputs",
    "model_requests",
    "jobs",
    "document_dependencies",
    "document_builds",
    "record_link_reviews",
    "record_links",
    "record_equivalence_reviews",
    "record_equivalences",
    "record_conflict_reviews",
    "record_conflicts",
    "decision_events",
    "knowledge_record_events",
    "knowledge_records",
    "relationship_reviews",
    "conversation_relationships",
    "identity_candidates",
    "segment_overrides",
    "override_anchors",
    "youtube_mentions",
    "link_occurrences",
    "transcript_cues",
    "transcript_acquisitions",
    "transcript_snapshots",
    "youtube_videos",
    "link_targets",
    "account_reviews",
    "account_mentions",
    "account_aliases",
    "social_accounts",
    "asset_occurrences",
    "derived_media_artifacts",
    "media_assets",
    "media_blobs",
    "revision_observations",
    "graph_edges",
    "message_revisions",
    "message_nodes",
    "conversations",
)
# Columns that hold ID lists in rows the purge keeps: deleted IDs are
# taken out of them, the rest of the row stays.
SCRUB_COLUMNS = (
    ("extraction_runs", "record_ids_json"),
    ("stage_invalidations", "cited_ids_json"),
    ("taxonomy_proposals", "evidence_json"),
)
# Kept chats' own words may legitimately mention a deleted chat (its URL,
# say). Those mentions are reported, not counted as leftovers.
KEPT_SOURCE_COLUMNS = frozenset(
    {
        ("message_revisions", "content_json"),
        ("link_targets", "canonical_url"),
        ("link_occurrences", "original_text"),
        # ING-015: imported notes are the person's own files and are kept.
        ("document_blocks", "text"),
        ("document_blocks", "heading_path_json"),
        ("document_links", "original_text"),
        ("source_documents", "name"),
    }
)
_PREFIXED_ID = re.compile(r"\b(?:conv|node|rev|seg|krec|cls|occ|lnkocc|amen|stg|asset)_[0-9a-f]+\b")


class PurgeError(ValueError):
    """A purge was refused (the reason is in the message)."""


@dataclass
class PurgePlan:
    """What a purge would delete. IDs stay in memory; reports carry counts."""

    conversations: list[str]
    rows: dict[str, set[int]] = field(default_factory=dict)  # table -> rowids
    ids: dict[str, set[str]] = field(default_factory=dict)  # kind -> IDs
    kept_shared: Counter[str] = field(default_factory=Counter)
    files: set[Path] = field(default_factory=set)  # copies inside the workspace
    outside: Counter[str] = field(default_factory=Counter)  # copies the engine can't delete
    snapshot_hashes: set[str] = field(default_factory=set)
    images: set[tuple[str, str | None]] = field(default_factory=set)  # (sha256, media type)
    other_conversations_in_files: int = 0
    # identity_candidates rows kept, whose existing_conversation_id is cleared.
    unlinked_candidates: set[int] = field(default_factory=set)

    @property
    def token(self) -> str:
        """A short fingerprint of exactly what would be deleted."""
        digest = hashlib.sha256(PURGE_VERSION.encode())
        for table in sorted(self.rows):
            digest.update(f"|{table}:{','.join(map(str, sorted(self.rows[table])))}".encode())
        for path in sorted(self.files):
            digest.update(f"|file:{path.name}".encode())
        return digest.hexdigest()[:12]

    def counts(self) -> dict[str, Any]:
        """JSON-ready counts (no IDs, titles or text)."""
        return {
            "conversations": len(self.conversations),
            "rows": {t: len(self.rows[t]) for t in DELETE_ORDER if self.rows.get(t)},
            "rows_total": sum(len(r) for r in self.rows.values()),
            "files": len(self.files),
            "kept_shared": {k: v for k, v in sorted(self.kept_shared.items()) if v},
            "outside_engine": dict(sorted(self.outside.items())),
            "other_conversations_in_purged_files": self.other_conversations_in_files,
        }


@dataclass
class Verification:
    """What the check after a purge found (all empty: nothing is left)."""

    probes: int = 0
    search_hits: int = 0
    database_bytes_hits: int = 0
    vault_hits: int = 0
    residual_ids: dict[str, int] = field(default_factory=dict)  # "table.column" -> rows
    mentioned_in_kept_sources: dict[str, int] = field(default_factory=dict)
    files_left: int = 0
    vault_images_left: int = 0
    foreign_key_problems: int = 0
    # Notes still holding the chats' words, kept on purpose (ING-015).
    kept_in_notes: list[dict[str, Any]] = field(default_factory=list)
    probes_in_notes: int = 0  # probes left out of the bytes check only

    @property
    def ok(self) -> bool:
        """Nothing deleted can still be found."""
        return not (
            self.search_hits
            or self.database_bytes_hits
            or self.vault_hits
            or self.residual_ids
            or self.files_left
            or self.vault_images_left
            or self.foreign_key_problems
        )

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready (counts and table names only)."""
        return {
            "ok": self.ok,
            "probes": self.probes,
            "search_hits": self.search_hits,
            "database_bytes_hits": self.database_bytes_hits,
            "vault_hits": self.vault_hits,
            "residual_ids": self.residual_ids,
            "mentioned_in_kept_sources": self.mentioned_in_kept_sources,
            "files_left": self.files_left,
            "vault_images_left": self.vault_images_left,
            "foreign_key_problems": self.foreign_key_problems,
            "kept_in_notes": self.kept_in_notes,
            "probes_in_notes": self.probes_in_notes,
        }


@dataclass
class PurgeResult:
    """A finished purge: its audit ID, what went and what the check found."""

    purge_id: str
    plan: PurgePlan
    verification: Verification
    vault: dict[str, int] = field(default_factory=dict)


# --------------------------------------------------------------------------- reading


def _chunks(values: Iterable[Any]) -> Iterator[list[Any]]:
    items = list(values)
    for start in range(0, len(items), _CHUNK):
        yield items[start : start + _CHUNK]


def _rows(
    db: sqlite3.Connection, table: str, columns: str, where: str, values: Iterable[Any]
) -> list[tuple[Any, ...]]:
    """``SELECT columns FROM table WHERE where IN (values)``, in chunks."""
    found: list[tuple[Any, ...]] = []
    for chunk in _chunks(set(values)):
        marks = ",".join("?" * len(chunk))
        found.extend(
            db.execute(f'SELECT {columns} FROM "{table}" WHERE {where} IN ({marks})', chunk)
        )
    return found


def _still_used(
    db: sqlite3.Connection, table: str, key: str, ref: str, keys: set[str], going: set[str]
) -> set[str]:
    """The ``keys`` that some row of ``table`` not in ``going`` still points at."""
    return {k for k, r in _rows(db, table, f"{key}, {ref}", key, keys) if r not in going}


def _archived(sha256: str) -> Path:
    """Where the archive keeps a copied file, relative to the workspace."""
    return Path("archive") / sha256[:2] / sha256


def _tables(db: sqlite3.Connection) -> set[str]:
    return {
        name
        for (name,) in db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
    }


def resolve_conversations(db: sqlite3.Connection, refs: Sequence[str]) -> list[str]:
    """Turn ``conv_`` IDs or native IDs into ``conv_`` IDs, refusing anything unclear."""
    found: list[str] = []
    for ref in refs:
        rows = db.execute(
            "SELECT conversation_id FROM conversations "
            "WHERE conversation_id = ? OR native_conversation_id = ?",
            (ref, ref),
        ).fetchall()
        if len(rows) != 1:
            raise PurgeError(
                "no such conversation" if not rows else "that ID matches several conversations"
            )
        if rows[0][0] not in found:
            found.append(rows[0][0])
    return found


def _record_refs(record_json: str) -> tuple[set[str], set[str], str | None]:
    """(evidence revision IDs, asset occurrence IDs, scope ID) of a stored record."""
    record = json.loads(record_json)
    revisions = {e.get("revision_id") for e in record.get("evidence") or ()} - {None}
    return revisions, set(record.get("asset_occurrences") or ()), record.get("scope_id")


def _plan(db: sqlite3.Connection, conversations: list[str], segments: set[str]) -> PurgePlan:
    """Work out the closure. Reads only."""
    plan = PurgePlan(conversations)
    rows: dict[str, set[int]] = {t: set() for t in DELETE_ORDER}
    ids: dict[str, set[str]] = {}
    convs = set(conversations)

    def take(table: str, where: str, values: Iterable[Any], *cols: str) -> list[tuple[Any, ...]]:
        got = _rows(db, table, ",".join(("rowid", *cols)), where, values)
        rows[table].update(r[0] for r in got)
        return [r[1:] for r in got]

    ids["native_conversation"] = {
        r[0] for r in _rows(db, "conversations", "native_conversation_id", "conversation_id", convs)
    }
    take("conversations", "conversation_id", convs)
    nodes = take("message_nodes", "conversation_id", convs, "node_key", "native_node_id")
    node_keys = {n for n, _ in nodes}
    kept_natives = {
        r[0]
        for r in db.execute("SELECT native_node_id FROM message_nodes")
        if r[0] not in {n for _, n in nodes}
    }
    # Native node IDs are only unique inside one chat (a shared root name is
    # common), so only the ones no kept chat uses can be checked for later.
    ids["native_node"] = {n for _, n in nodes} - kept_natives
    revisions = take("message_revisions", "node_key", node_keys, "revision_id", "first_snapshot_id")
    revs = {r for r, _ in revisions}
    snapshots = {s for _, s in revisions}
    snapshots |= {
        s for (s,) in take("revision_observations", "revision_id", revs, "first_snapshot_id")
    }
    take("graph_edges", "conversation_id", convs)

    # Images: occurrences go; the image and its bytes only if nothing else shows it.
    occurrences = take("asset_occurrences", "revision_id", revs, "occurrence_id", "asset_id")
    occ_ids = {o for o, _ in occurrences}
    assets = {a for _, a in occurrences if a}
    kept = _still_used(db, "asset_occurrences", "asset_id", "occurrence_id", assets, occ_ids)
    plan.kept_shared["images_still_shown_elsewhere"] += len(kept)
    gone_assets = assets - kept
    blobs = {b for (b,) in take("media_assets", "asset_id", gone_assets, "blob_sha256") if b}
    kept = _still_used(db, "media_assets", "blob_sha256", "asset_id", blobs, gone_assets)
    plan.kept_shared["image_bytes_shared"] += len(kept)
    gone_blobs = blobs - kept
    for (location,) in take("derived_media_artifacts", "blob_sha256", gone_blobs, "location"):
        plan.files.add(Path(location))
    for sha, mode, media_type in take(
        "media_blobs", "blob_sha256", gone_blobs, "blob_sha256", "storage_mode", "media_type"
    ):
        plan.images.add((sha, media_type))
        if mode == "copy":
            plan.files.add(_archived(sha))
        else:
            plan.outside["images_kept_by_reference"] += 1
    ids["blob"] = gone_blobs

    # Links, videos (with transcripts) and accounts: the mentions go; the
    # thing mentioned only if nothing else mentions it.
    link_occ = take("link_occurrences", "revision_id", revs, "occurrence_id", "target_id")
    link_occ += take("link_occurrences", "conversation_id", convs, "occurrence_id", "target_id")
    link_ids = {o for o, _ in link_occ}
    targets = {t for _, t in link_occ}
    kept = _still_used(db, "link_occurrences", "target_id", "occurrence_id", targets, link_ids)
    # ING-012: a link also in an imported note stays (the note isn't purged).
    kept |= _still_used(db, "document_links", "target_id", "link_id", targets, set())
    plan.kept_shared["links_mentioned_elsewhere"] += len(kept)
    take("link_targets", "target_id", targets - kept)
    videos = {v for (v,) in take("youtube_mentions", "mention_id", link_ids, "video_id")}
    kept = _still_used(db, "youtube_mentions", "video_id", "mention_id", videos, link_ids)
    kept |= _still_used(db, "document_links", "video_id", "link_id", videos, set())
    plan.kept_shared["videos_mentioned_elsewhere"] += len(kept)
    gone_videos = videos - kept
    take("youtube_videos", "video_id", gone_videos)
    take("transcript_acquisitions", "video_id", gone_videos)
    transcripts = take(
        "transcript_snapshots", "video_id", gone_videos, "transcript_id", "file_sha256"
    )
    take("transcript_cues", "transcript_id", {t for t, _ in transcripts})
    plan.files.update(_archived(sha) for _, sha in transcripts)
    mentions = take("account_mentions", "revision_id", revs, "mention_id", "account_id")
    mentions += take("account_mentions", "conversation_id", convs, "mention_id", "account_id")
    mention_ids = {m for m, _ in mentions}
    accounts = {a for _, a in mentions if a}
    kept = _still_used(db, "account_mentions", "account_id", "mention_id", accounts, mention_ids)
    plan.kept_shared["accounts_mentioned_elsewhere"] += len(kept)
    # SOC-004 review history: a link decision goes with its mention, and an
    # account's whole history goes with the account.
    take("account_reviews", "mention_id", mention_ids)
    take("account_reviews", "account_id", accounts - kept)
    take("account_aliases", "account_id", accounts - kept)
    take("social_accounts", "account_id", accounts - kept)

    # Chat-level links, identity candidates and corrections.
    rels = take("conversation_relationships", "from_conversation_id", convs, "relationship_id")
    rels += take("conversation_relationships", "to_conversation_id", convs, "relationship_id")
    take("relationship_reviews", "relationship_id", {r for (r,) in rels})
    cols = "rowid, snapshot_id, assigned_conversation_id"
    candidates = _rows(db, "identity_candidates", cols, "existing_conversation_id", convs)
    candidates += _rows(
        db, "identity_candidates", cols, "native_conversation_id", ids["native_conversation"]
    )
    # An accepted candidate (IMP-009) points at the chat it became.
    candidates += _rows(db, "identity_candidates", cols, "assigned_conversation_id", convs)
    for rowid, snapshot, assigned in candidates:
        if assigned is not None and assigned not in convs:
            # An accepted chat that collided with a purged one is its own chat
            # and stays, with its decision; only the pointer to the purged
            # chat is cleared.
            plan.unlinked_candidates.add(rowid)
            continue
        rows["identity_candidates"].add(rowid)
        if snapshot:
            snapshots.add(snapshot)
    take("segment_overrides", "conversation_id", convs)
    take("override_anchors", "conversation_id", convs)

    # Labels, extraction, and the model calls behind them.
    labelled = take(
        "classifications", "conversation_id", convs, "classification_id", "stage_key", "segment_id"
    )
    segments = set(segments) | {s for _, _, s in labelled}
    labelled += take(
        "classifications", "segment_id", segments, "classification_id", "stage_key", "segment_id"
    )
    take("classification_labels", "classification_id", {c for c, _, _ in labelled})
    take("classification_reviews", "segment_id", segments)
    runs = take("extraction_runs", "segment_id", segments, "stage_key", "record_ids_json")
    stage_keys = {k for _, k, _ in labelled} | {k for k, _ in runs}
    records = {r for _, listed in runs for r in json.loads(listed or "[]")}
    occ_set = occ_ids
    for record_id, stage_key, scope_id, record_json in db.execute(
        "SELECT record_id, stage_key, scope_id, record_json FROM knowledge_records"
    ):
        cited, shown, _ = _record_refs(record_json)
        if (
            record_id in records
            or stage_key in stage_keys
            or scope_id in convs
            or scope_id in segments
            or cited & revs
            or shown & occ_set
        ):
            records.add(record_id)
    for (stage_key,) in take("knowledge_records", "record_id", records, "stage_key"):
        if stage_key:
            stage_keys.add(stage_key)
    take("knowledge_record_events", "record_id", records)
    for table, review in (
        ("record_links", "record_link_reviews"),
        ("record_equivalences", "record_equivalence_reviews"),
        ("record_conflicts", "record_conflict_reviews"),
    ):
        key = {"record_links": "link_id", "record_equivalences": "pair_id"}.get(
            table, "conflict_id"
        )
        found = take(table, "record_a" if table != "record_links" else "from_record", records, key)
        found += take(table, "record_b" if table != "record_links" else "to_record", records, key)
        take(review, key, {f for (f,) in found})
    events = {e for (e,) in take("decision_events", "from_record", records, "event_id")}
    events |= {e for (e,) in take("decision_events", "to_record", records, "event_id")}
    frontier = events
    while frontier:  # an event that revokes a deleted event goes with it
        frontier = {
            e for (e,) in take("decision_events", "revokes_event", frontier, "event_id")
        } - events
        events |= frontier
    plan.kept_shared["kept_segments_sharing_a_deleted_model_answer"] += len(
        {
            seg
            for conv, seg in _rows(
                db, "classifications", "conversation_id, segment_id", "stage_key", stage_keys
            )
            if conv not in convs and seg not in segments
        }
    )
    take("model_outputs", "stage_key", stage_keys)
    take("model_requests", "stage_key", stage_keys)
    take("jobs", "stage_key", stage_keys)

    # Document builds that used any of it (the vault is re-synced after).
    builds = {
        b for (b,) in take("document_builds", "subject_id", convs | records | segments, "build_id")
    }
    builds |= {
        b for (b,) in _rows(db, "document_dependencies", "build_id", "dep_id", records | revs)
    }
    take("document_builds", "build_id", builds)
    take("document_dependencies", "build_id", builds)

    # The archived export files that held the chat go whole.
    for sha, mode in _rows(
        db, "source_snapshots", "sha256, storage_mode", "snapshot_id", snapshots
    ):
        plan.snapshot_hashes.add(sha)
        if mode == "copy":
            plan.files.add(_archived(sha))
        else:
            plan.outside["export_files_kept_by_reference"] += 1
    plan.outside["original_export_files_outside_the_engine"] = len(snapshots)
    if snapshots:
        others = set()
        for chunk in _chunks(snapshots):
            marks = ",".join("?" * len(chunk))
            others |= {
                c
                for (c,) in db.execute(
                    "SELECT DISTINCT n.conversation_id FROM message_revisions r "
                    "JOIN message_nodes n ON n.node_key = r.node_key "
                    f"WHERE r.first_snapshot_id IN ({marks})",
                    chunk,
                )
            }
        plan.other_conversations_in_files = len(others - convs)

    ids.update(
        conversation=convs,
        node=node_keys,
        revision=revs,
        segment=segments,
        record=records,
        occurrence=occ_ids,
        link_occurrence=link_ids,
        account_mention=mention_ids,
        stage_key=stage_keys,
        classification={c for c, _, _ in labelled},
    )
    plan.rows = {t: r for t, r in rows.items() if r}
    plan.ids = ids
    return plan


def _segments(settings: Settings, conversations: Sequence[str]) -> set[str]:
    """The current segment IDs of each conversation (segments aren't stored)."""
    from sqlalchemy.orm import Session

    from knowledge_engine.infrastructure.db import create_sqlite_engine
    from knowledge_engine.rendering.transcript import load_conversation
    from knowledge_engine.segmentation.overrides import load_segments

    engine = create_sqlite_engine(database_path(settings))
    try:
        with Session(engine) as session:
            return {
                s.segment_id
                for c in conversations
                for s in load_segments(session, load_conversation(session, c))
            }
    finally:
        engine.dispose()


def _connect(settings: Settings) -> sqlite3.Connection:
    path = database_path(settings)
    if not path.is_file():
        raise PurgeError("no database (nothing imported yet)")
    # isolation_level=None: this code says BEGIN and COMMIT itself, so the
    # trigger changes below are inside the same transaction as the deletes.
    db = sqlite3.connect(path, isolation_level=None)
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA busy_timeout = 5000")
    if "purge_events" not in _tables(db):
        db.close()
        raise PurgeError("the database is older than this code: run `ke db upgrade` first")
    return db


def plan_purge(settings: Settings, refs: Sequence[str]) -> PurgePlan:
    """What purging these conversations (``conv_`` or native IDs) would delete. Reads only."""
    db = _connect(settings)
    try:
        conversations = resolve_conversations(db, refs)
        return _plan(db, conversations, _segments(settings, conversations))
    finally:
        db.close()


def _probes(db: sqlite3.Connection, plan: PurgePlan) -> list[str]:
    """Short exact passages of the deleted text that no kept message or record contains.

    Held in memory only, to check afterwards that nothing can find them.
    """
    texts: list[str] = []
    for (content,) in _rows(
        db, "message_revisions", "content_json", "revision_id", plan.ids["revision"]
    ):
        texts.extend(p for p in json.loads(content).get("parts") or () if isinstance(p, str))
    for (record,) in _rows(db, "knowledge_records", "record_json", "record_id", plan.ids["record"]):
        texts.append(json.loads(record).get("assertion") or "")
    probes: list[str] = []
    for text in texts:
        words = [m.span() for m in re.finditer(r"\S+", text)]
        if len(words) < _PROBE_WORDS:
            continue
        first = (len(words) - _PROBE_WORDS) // 2
        probe = text[words[first][0] : words[first + _PROBE_WORDS - 1][1]]
        if len(probe) < 20 or probe in probes or _kept_contains(db, plan, probe):
            continue
        probes.append(probe)
        if len(probes) >= _MAX_PROBES:
            break
    return probes


def _in_notes(
    db: sqlite3.Connection, probes: Sequence[str]
) -> tuple[set[str], list[dict[str, Any]]]:
    """Which probes an imported note (any version) holds, and where (ING-015).

    One scan per probe, so at most ``_MAX_PROBES`` scans. Each place is the
    note's ID, file name, line locator, version and whether that version is
    the current one (an old version's text is kept as evidence too).
    """
    if "document_blocks" not in _tables(db):
        return set(), []  # a workspace from before ING-012
    held: set[str] = set()
    places: set[tuple[str, str, str, str, bool]] = set()
    for probe in probes:
        rows = db.execute(
            "SELECT d.document_id, d.name, b.locator, r.revision_id, "
            "d.current_revision_id = r.revision_id FROM document_blocks b "
            "JOIN document_revisions r ON r.revision_id = b.revision_id "
            "JOIN source_documents d ON d.document_id = r.document_id "
            "WHERE instr(b.text, ?) > 0",
            (probe,),
        ).fetchall()
        if rows:
            held.add(probe)
            places.update((i, n, loc, rev, bool(cur)) for i, n, loc, rev, cur in rows)
    keys = ("document_id", "name", "locator", "revision_id", "current")
    return held, [dict(zip(keys, p, strict=True)) for p in sorted(places)]


def _forms(probe: str) -> set[str]:
    """The ways a passage can be spelled in storage: plain, or escaped inside JSON."""
    return {probe, json.dumps(probe)[1:-1], json.dumps(probe, ensure_ascii=False)[1:-1]}


def _kept_contains(db: sqlite3.Connection, plan: PurgePlan, probe: str) -> bool:
    """Whether a kept message or record holds the same passage (then it's not a probe)."""
    for form in _forms(probe):
        for table, key, column, gone in (
            ("message_revisions", "revision_id", "content_json", plan.ids["revision"]),
            ("knowledge_records", "record_id", "record_json", plan.ids["record"]),
        ):
            for (found,) in db.execute(
                f"SELECT {key} FROM {table} WHERE instr({column}, ?) > 0", (form,)
            ):
                if found not in gone:
                    return True
    return False


def _scrub(value: Any, dead: set[str]) -> Any:
    """``value`` without any list item or dict entry that names a deleted ID."""
    if isinstance(value, list):
        return [_scrub(v, dead) for v in value if not _names(v, dead)]
    if isinstance(value, dict):
        return {k: _scrub(v, dead) for k, v in value.items() if not _names(v, dead)}
    return value


def _names(value: Any, dead: set[str]) -> bool:
    return isinstance(value, str) and (
        value in dead or any(m in dead for m in _PREFIXED_ID.findall(value))
    )


def _dead_ids(plan: PurgePlan) -> set[str]:
    kinds = (
        "conversation",
        "node",
        "revision",
        "segment",
        "record",
        "occurrence",
        "link_occurrence",
        "account_mention",
        "stage_key",
        "classification",
    )
    return set().union(*(plan.ids.get(k, set()) for k in kinds))


def _delete(db: sqlite3.Connection, plan: PurgePlan) -> None:
    """Delete the planned rows and scrub kept ID lists. Inside the caller's transaction."""
    tables = sorted(plan.rows)
    marks = ",".join("?" * len(tables))
    triggers = db.execute(
        f"SELECT name, sql FROM sqlite_master WHERE type = 'trigger' AND tbl_name IN ({marks})",
        tables,
    ).fetchall()
    # Append-only guards are lifted for this transaction only (see the module notes).
    for name, _ in triggers:
        db.execute(f'DROP TRIGGER "{name}"')
    for chunk in _chunks(plan.unlinked_candidates):
        db.execute(
            "UPDATE identity_candidates SET existing_conversation_id = NULL "
            f"WHERE rowid IN ({','.join('?' * len(chunk))})",
            chunk,
        )
    for table in DELETE_ORDER:
        for chunk in _chunks(plan.rows.get(table, ())):
            db.execute(
                f'DELETE FROM "{table}" WHERE rowid IN ({",".join("?" * len(chunk))})', chunk
            )
    for _, sql in triggers:
        db.execute(sql)
    dead = _dead_ids(plan)
    present = _tables(db)
    for table, column in SCRUB_COLUMNS:
        if table not in present:
            continue
        for rowid, text in db.execute(f'SELECT rowid, "{column}" FROM "{table}"').fetchall():
            if not text or not any(m in dead for m in _PREFIXED_ID.findall(text)):
                continue
            cleaned = json.dumps(_scrub(json.loads(text), dead), sort_keys=True)
            db.execute(f'UPDATE "{table}" SET "{column}" = ? WHERE rowid = ?', (cleaned, rowid))


def run_purge(
    settings: Settings,
    refs: Sequence[str],
    *,
    confirm: str,
    reason: str,
    actor: str = "owner",
    vault: Path | None = None,
    taxonomy_version: str | None = None,
) -> PurgeResult:
    """Purge conversations and their closure, then prove nothing is left.

    Args:
        settings: The workspace.
        refs: ``conv_`` or native conversation IDs.
        confirm: The token of the plan the person saw (``plan_purge``).
        reason: Why (kept in the audit log; don't put the private text here).
        actor: Who asked.
        vault: A vault to re-sync afterwards, so its notes lose the chats too.
        taxonomy_version: The published taxonomy that vault is rendered with, if any.

    Raises:
        PurgeError: Unknown ID, no reason, or the plan no longer matches the
            token (something changed since it was shown). Nothing is deleted.
    """
    from knowledge_engine.importer.lock import import_lock

    if not reason.strip():
        raise PurgeError("a purge needs a reason for the audit log")
    root = settings.workspace_root.resolve()
    with import_lock(root, timeout_s=settings.limits.import_lock_timeout_s):
        db = _connect(settings)
        try:
            conversations = resolve_conversations(db, refs)
            known = "SELECT 1 FROM taxonomy_versions WHERE version = ?"
            if taxonomy_version and not db.execute(known, (taxonomy_version,)).fetchone():
                raise PurgeError("no such taxonomy version")
            segments = _segments(settings, conversations)
            db.execute("BEGIN IMMEDIATE")
            try:
                plan = _plan(db, conversations, segments)
                if plan.token != confirm:
                    raise PurgeError("the plan doesn't match that token; plan again")
                probes = _probes(db, plan)
                held, notes = _in_notes(db, probes)
                _delete(db, plan)
                purge_id = uuid.uuid4().hex
                keys = [(TombstoneKind.CONVERSATION, conversation_key(c)) for c in conversations]
                keys += [(TombstoneKind.SNAPSHOT, sha) for sha in sorted(plan.snapshot_hashes)]
                db.executemany(
                    "INSERT OR IGNORE INTO purge_tombstones (kind, key_sha256, purge_id, "
                    "created_at) VALUES (?, ?, ?, datetime('now'))",
                    [(k.value, key, purge_id) for k, key in keys],
                )
                db.execute(
                    "INSERT INTO purge_events (purge_id, actor, reason, plan_sha256, status, "
                    "counts_json, verification_json, created_at) "
                    "VALUES (?, ?, ?, ?, 'purged', ?, '{}', datetime('now'))",
                    (purge_id, actor, reason, plan.token, json.dumps(plan.counts())),
                )
                if db.execute("PRAGMA foreign_key_check").fetchall():
                    raise PurgeError("the purge would break a link between tables; nothing deleted")
                db.execute("COMMIT")
            except BaseException:
                db.execute("ROLLBACK")
                raise
            for path in plan.files:
                target = (root / path).resolve()
                if root in target.parents:  # never touch anything outside the workspace
                    remove_stored(target)
            for index in (root / "index").glob("*.db*"):
                index.unlink()  # rebuilt from the database, now without the chats
            # Rewrites the whole file, so deleted rows don't linger in free pages.
            db.execute("VACUUM")
            db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            synced: dict[str, int] = {}
            if vault is not None:
                synced = _sync_vault(settings, vault, taxonomy_version, plan)
            verification = _verify(settings, db, plan, probes, vault, held)
            verification.kept_in_notes = notes
            db.execute(
                "UPDATE purge_events SET status = ?, verification_json = ? WHERE purge_id = ?",
                (
                    "verified" if verification.ok else "residual",
                    json.dumps(verification.to_dict()),
                    purge_id,
                ),
            )
        finally:
            db.close()
    return PurgeResult(purge_id, plan, verification, synced)


def _sync_vault(
    settings: Settings, vault: Path, taxonomy_version: str | None, plan: PurgePlan
) -> dict[str, int]:
    """Re-sync the vault, then take out the engine's copies of the purged images.

    ``sync_vault`` leaves image files alone (it doesn't track who put them
    there), so the purge removes exactly its own copies: the file at the
    engine's attachment path whose bytes still hash to a purged image.
    """
    from sqlalchemy.orm import Session

    from knowledge_engine.documents.vault import sync_vault
    from knowledge_engine.infrastructure.db import create_sqlite_engine
    from knowledge_engine.rendering.media import attachment_path
    from knowledge_engine.taxonomy.registry import TaxonomyRegistry

    engine = create_sqlite_engine(database_path(settings))
    try:
        with Session(engine) as session:
            taxonomy = None
            if taxonomy_version is not None:
                taxonomy = TaxonomyRegistry(session).snapshot(taxonomy_version)
            report = sync_vault(
                session, vault, settings.workspace_root / "archive", taxonomy=taxonomy
            )
    finally:
        engine.dispose()
    removed = 0
    for sha, media_type in sorted(plan.images, key=lambda image: image[0]):
        copy = vault / Path(*attachment_path(sha, media_type).parts)
        if copy.is_file() and hashlib.sha256(copy.read_bytes()).hexdigest() == sha:
            copy.unlink()
            removed += 1
    return {**report.counts(), "attachments_removed": removed}


def _bytes_hits(paths: Iterable[Path], probes: Sequence[str]) -> int:
    """How many files hold any probe's bytes, in any spelling."""
    needles = [f.encode() for p in probes for f in _forms(p)]
    if not needles:
        return 0
    overlap = max(map(len, needles))
    hits = 0
    for path in paths:
        if not path.is_file():
            continue
        tail = b""
        with path.open("rb") as handle:
            while chunk := handle.read(1 << 24):
                window = tail + chunk
                if any(n in window for n in needles):
                    hits += 1
                    break
                tail = window[-overlap:]
    return hits


def residual_ids(db: sqlite3.Connection, plan: PurgePlan) -> tuple[dict[str, int], dict[str, int]]:
    """Rows still naming a deleted ID: (leftovers, mentions in kept chats' own text)."""
    dead = _dead_ids(plan)
    natives = {
        n
        for n in plan.ids.get("native_conversation", set()) | plan.ids.get("native_node", set())
        if len(n) >= 16  # a short native ID ("m1") would match ordinary words
    }
    native = re.compile("|".join(map(re.escape, sorted(natives)))) if natives else None
    left: Counter[str] = Counter()
    kept: Counter[str] = Counter()
    for table in sorted(_tables(db) - {"purge_events", "purge_tombstones", "alembic_version"}):
        columns = [
            name
            for _, name, kind, *_ in db.execute(f'PRAGMA table_info("{table}")')
            if not kind or any(t in kind.upper() for t in ("CHAR", "TEXT", "CLOB"))
        ]
        if not columns:
            continue
        quoted = ", ".join(f'"{c}"' for c in columns)
        for row in db.execute(f'SELECT {quoted} FROM "{table}"'):
            for column, value in zip(columns, row, strict=True):
                if not isinstance(value, str):
                    continue
                if any(m in dead for m in _PREFIXED_ID.findall(value)) or (
                    native is not None and native.search(value)
                ):
                    bucket = kept if (table, column) in KEPT_SOURCE_COLUMNS else left
                    bucket[f"{table}.{column}"] += 1
    return dict(sorted(left.items())), dict(sorted(kept.items()))


def _verify(
    settings: Settings,
    db: sqlite3.Connection,
    plan: PurgePlan,
    probes: Sequence[str],
    vault: Path | None,
    in_notes: frozenset[str] | set[str] = frozenset(),
) -> Verification:
    """Search, scan and look for every trace of the purged chats.

    ``in_notes`` are probes an imported note holds: they are still searched
    for and looked for in the vault, but the database file's bytes hold the
    note's own copy, so they are left out of that one scan (ING-015).
    """
    from sqlalchemy.orm import Session

    from knowledge_engine.infrastructure.db import create_sqlite_engine
    from knowledge_engine.retrieval.lexical import (
        LexicalIndex,
        SearchMode,
        search_index_path,
        sync_index,
    )

    check = Verification(probes=len(probes))
    check.residual_ids, check.mentioned_in_kept_sources = residual_ids(db, plan)
    check.foreign_key_problems = len(db.execute("PRAGMA foreign_key_check").fetchall())
    root = settings.workspace_root.resolve()
    check.files_left = sum(1 for p in plan.files if (root / p).exists())
    workspaces = [w for (w,) in db.execute("SELECT workspace_id FROM workspaces")]
    gone = plan.ids["revision"]
    engine = create_sqlite_engine(database_path(settings))
    try:
        with Session(engine) as session, LexicalIndex(search_index_path(settings)) as index:
            sync_index(session, index)
            for probe in probes:
                for workspace in workspaces:
                    hits = index.search(
                        probe, workspace_id=workspace, mode=SearchMode.PHRASE, limit=100
                    )
                    check.search_hits += sum(1 for h in hits if h.revision_id in gone)
    finally:
        engine.dispose()
    database = database_path(settings)
    check.probes_in_notes = len(in_notes)
    check.database_bytes_hits = _bytes_hits(
        [database, database.with_name(database.name + "-wal")],
        [p for p in probes if p not in in_notes],
    )
    if vault is not None and vault.is_dir():
        check.vault_hits = _bytes_hits(sorted(vault.rglob("*.md")), probes)
        blobs = plan.ids.get("blob", set())
        check.vault_images_left = sum(
            1
            for path in vault.rglob("*")
            if path.is_file()
            and path.suffix != ".md"
            and hashlib.sha256(path.read_bytes()).hexdigest() in blobs
        )
    return check


def purge_log(settings: Settings) -> list[dict[str, Any]]:
    """Every purge so far, oldest first (counts and checks, never content)."""
    db = _connect(settings)
    try:
        return [
            {
                "purge_id": row[0],
                "actor": row[1],
                "reason": row[2],
                "plan": row[3],
                "status": row[4],
                "counts": json.loads(row[5]),
                "verification": json.loads(row[6] or "{}"),
                "created_at": row[7],
            }
            for row in db.execute(
                "SELECT purge_id, actor, reason, plan_sha256, status, counts_json, "
                "verification_json, created_at FROM purge_events ORDER BY created_at, purge_id"
            )
        ]
    finally:
        db.close()
