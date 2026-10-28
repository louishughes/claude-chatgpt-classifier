"""The import sequence behind ``import_source`` (ING-003, IMP-004). Private.

One call does, in order:

1. fingerprint the raw tree (read-only proof, before);
2. pick the adapter and list the source;
3. take the workspace's import lock, so imports run one at a time;
4. open a batch in the ledger and snapshot every input file;
5. write conversations in groups, one transaction per group, each opened
   with SQLite's write lock (``BEGIN IMMEDIATE``), so a crash loses at
   most the group in progress; each conversation's images and attachments
   are linked in the same transaction;
6. fingerprint the raw tree again and close the batch with its counts.

Re-running after a crash is the resume: groups already committed come
back ``unchanged`` and cost nothing (M1_CONSOLIDATION §5).

Talking points:
    - "One function, one report: callers can't get the order wrong because
      they never see the steps."
    - "A crash loses one group of conversations at most, and re-running the
      same import picks up where it stopped."
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from collections.abc import Iterator
from itertools import islice
from pathlib import Path

from knowledge_engine import __version__
from knowledge_engine.domain.enums import DeltaCategory, ImportBatchStatus, SourceSystem
from knowledge_engine.domain.ids import conversation_id
from knowledge_engine.graph.conversation import BRANCH_CLASSIFIER_VERSION
from knowledge_engine.graph.nodes import CANONICAL_HASH_VERSION
from knowledge_engine.importer.archive import BlobStore
from knowledge_engine.importer.corrections import check_overrides
from knowledge_engine.importer.delta import (
    apply_conversation,
    mark_not_seen,
    native_conversation_id,
)
from knowledge_engine.importer.identity import CandidateReason, conversation_hash, record_candidate
from knowledge_engine.importer.integrity import IntegrityTally
from knowledge_engine.importer.ledger import ImportBatchRow, ImportLedger
from knowledge_engine.importer.lock import import_lock
from knowledge_engine.importer.media import MediaDelta, MediaLibrary, record_occurrences
from knowledge_engine.importer.report import ImportReport
from knowledge_engine.infrastructure.db import SessionFactory, create_sqlite_engine, database_path
from knowledge_engine.infrastructure.migrations import upgrade_to_head
from knowledge_engine.infrastructure.workspace import WorkspaceRepo
from knowledge_engine.ingestion.inventory import tree_signature
from knowledge_engine.ingestion.registry import default_adapters
from knowledge_engine.ingestion.source import NativeConversation, SourceListing, select_adapter
from knowledge_engine.links.social_store import record_accounts
from knowledge_engine.links.store import record_links
from knowledge_engine.relationships.detect import detect_relationships
from knowledge_engine.retention.tombstones import TombstoneKind, conversation_key, is_purged
from knowledge_engine.retrieval.lexical import LexicalIndex, search_index_path, sync_index
from knowledge_engine.settings import Settings

DEFAULT_WORKSPACE_NAME = "default"


def run_import(
    path: Path,
    account_ns: str,
    *,
    format_id: str | None,
    settings: Settings,
    full_export: bool = True,
    limit: int | None = None,
) -> ImportReport:
    """Import one source and return its report. See ``importer.import_source``.

    ``limit`` imports only the first N conversations, for the batch smoke
    test (EVAL-010). A limited run is never a full export, so it marks
    nothing ``not_seen``.
    """
    if limit is not None:
        full_export = False
    before = tree_signature(path)
    adapter = select_adapter(path, default_adapters(), format_id)
    listing = adapter.open(
        path,
        max_bytes=settings.limits.max_source_file_bytes,
        max_entries=settings.limits.max_archive_entries,
    )

    # The whole import holds the workspace lock: "running means crashed" and
    # "not touched by this import means not seen" both assume it's alone.
    with import_lock(settings.workspace_root, timeout_s=settings.limits.import_lock_timeout_s):
        engine = create_sqlite_engine(database_path(settings))
        try:
            upgrade_to_head(engine)
            factory = SessionFactory(engine)
            archive = BlobStore(
                settings.workspace_root / "archive",
                max_bytes=settings.limits.max_source_file_bytes,
            )
            # Same content-addressed folder, but the media size limit.
            media_store = BlobStore(
                settings.workspace_root / "archive",
                max_bytes=settings.limits.max_media_file_bytes,
            )
            library = MediaLibrary(
                path,
                listing.media_files,
                media_store,
                settings.media_storage_mode,
                listing.declared_media,
            )
            return _run(
                path,
                account_ns,
                listing,
                before,
                factory,
                archive,
                library,
                settings,
                full_export,
                limit,
            )
        finally:
            engine.dispose()


def _run(
    path: Path,
    account_ns: str,
    listing: SourceListing,
    before: str,
    factory: SessionFactory,
    archive: BlobStore,
    library: MediaLibrary,
    settings: Settings,
    full_export: bool,
    limit: int | None = None,
) -> ImportReport:
    versions = {
        "code": __version__,
        "adapter": listing.format_id,
        "content_hash": CANONICAL_HASH_VERSION,
        "branch_classifier": BRANCH_CLASSIFIER_VERSION,
    }
    files: Counter[str] = Counter()
    snapshots: dict[str, str] = {}
    with factory.transaction() as session:
        workspace_id = WorkspaceRepo(session).get_or_create(DEFAULT_WORKSPACE_NAME).workspace_id
        ledger = ImportLedger(session, archive)
        batch = ledger.start(
            workspace_id=workspace_id,
            account_namespace=account_ns,
            root=path,
            format_id=listing.format_id,
            versions=versions,
            tree_hash=before,
        )
        import_id = batch.import_id
        if path.is_file():
            # A ZIP is archived whole: one snapshot covers every member.
            snapshot, created = ledger.record_file(batch, path.name, path=path)
            for source in listing.files:
                snapshots[source.path] = snapshot.snapshot_id
            files["new" if created else "reused"] += 1
        else:
            for source in listing.files:
                snapshot, created = ledger.record_file(batch, source.path, path=path / source.path)
                snapshots[source.path] = snapshot.snapshot_id
                files["new" if created else "reused"] += 1

    conversations: Counter[str] = Counter()
    messages: Counter[str] = Counter()
    warnings: Counter[str] = Counter(w.code for w in listing.warnings)
    changed: list[str] = []
    new_branches = 0
    raw_observations = 0
    candidates: Counter[str] = Counter()
    media = MediaDelta()
    link_counts: Counter[str] = Counter()
    account_counts: Counter[str] = Counter()
    tally = IntegrityTally()
    file_ids: set[str] = set()
    # Native ID -> content hash of the first conversation this import saw
    # with it, to tell an exact duplicate from an ID collision.
    seen: dict[str, str] = {}
    group_size = settings.limits.max_conversations_per_batch
    stream = listing.conversations()
    if limit is not None:
        stream = islice(stream, limit)
    for group in _groups(stream, group_size):
        with factory.transaction() as session:
            for item in group:
                tally.conversations_read += 1
                warnings.update(w.code for w in item.warnings)
                if not item.native:
                    conversations[DeltaCategory.FAILED.value] += 1
                    tally.conversations["failed"] += 1
                    continue
                native_id = native_conversation_id(item.native)
                snapshot_id = snapshots[item.locator.file]
                if native_id is None:
                    # Keying it without a native ID would be a guess, so it
                    # isn't imported: it waits for review as a candidate.
                    warnings["missing_native_id"] += 1
                    conversations[DeltaCategory.FAILED.value] += 1
                    record_candidate(
                        session,
                        item.native,
                        reason=CandidateReason.MISSING_NATIVE_ID,
                        workspace_id=workspace_id,
                        account_namespace=account_ns,
                        native_id=None,
                        existing_conversation_id=None,
                        snapshot_id=snapshot_id,
                        source_index=item.locator.index,
                        import_id=import_id,
                    )
                    candidates[CandidateReason.MISSING_NATIVE_ID.value] += 1
                    tally.conversations["failed"] += 1
                    continue
                conv_key = conversation_id(
                    workspace_id, SourceSystem.CHATGPT.value, account_ns, native_id
                )
                if is_purged(session, TombstoneKind.CONVERSATION, conversation_key(conv_key)):
                    # Deleted on purpose (OPS-004): still in the export, never re-imported.
                    conversations["purged"] += 1
                    tally.conversations["purged"] += 1
                    continue
                digest = conversation_hash(item.native)
                if native_id in seen:
                    if seen[native_id] == digest:
                        # The same chat twice in one export: nothing new.
                        warnings["duplicate_conversation_in_source"] += 1
                        tally.conversations["duplicate_in_source"] += 1
                        continue
                    # Same ID, different chat: never merged, kept for review.
                    record_candidate(
                        session,
                        item.native,
                        reason=CandidateReason.ID_COLLISION,
                        workspace_id=workspace_id,
                        account_namespace=account_ns,
                        native_id=native_id,
                        existing_conversation_id=conv_key,
                        snapshot_id=snapshot_id,
                        source_index=item.locator.index,
                        import_id=import_id,
                    )
                    candidates[CandidateReason.ID_COLLISION.value] += 1
                    conversations[DeltaCategory.CANDIDATE_DUPLICATE.value] += 1
                    tally.conversations["candidate"] += 1
                    continue
                seen[native_id] = digest
                delta = apply_conversation(
                    session,
                    item.native,
                    workspace_id=workspace_id,
                    account_namespace=account_ns,
                    import_id=import_id,
                    snapshot_id=snapshot_id,
                )
                conversations[delta.category.value] += 1
                messages.update(delta.messages)
                warnings.update(delta.warnings)
                changed.extend(delta.changed_revisions)
                new_branches += delta.new_branches
                raw_observations += delta.raw_observations
                tally.add(item.native, delta)
                file_ids.update(p.file_id for _, p in delta.pointers if p.file_id)
                record_occurrences(
                    session,
                    delta.pointers,
                    library,
                    media,
                    workspace_id=workspace_id,
                    import_id=import_id,
                    conversation_native_id=native_id,
                )
                link_counts.update(
                    record_links(
                        session,
                        delta.links,
                        conversation_id=delta.conversation_id,
                        import_id=import_id,
                    )
                )
                account_counts.update(
                    record_accounts(
                        session,
                        delta.accounts,
                        conversation_id=delta.conversation_id,
                        import_id=import_id,
                    )
                )

    warnings.update(media.warnings)
    integrity = tally.to_dict(
        media_listed=len(listing.media_files), media_referenced=library.referenced(file_ids)
    )
    if not integrity["reconciled"]:
        warnings["integrity_mismatch"] += 1
    after = tree_signature(path)
    if after == before and full_export:
        with factory.transaction() as session:
            gone, gone_messages = mark_not_seen(
                session,
                workspace_id=workspace_id,
                account_namespace=account_ns,
                import_id=import_id,
            )
        if gone:
            conversations[DeltaCategory.NOT_SEEN.value] += gone
        if gone_messages:
            messages[DeltaCategory.NOT_SEEN.value] += gone_messages
    if after != before:
        status = ImportBatchStatus.FAILED
        warnings["raw_tree_changed"] += 1
    elif conversations[DeltaCategory.FAILED.value]:
        status = ImportBatchStatus.PARTIAL
    else:
        status = ImportBatchStatus.SUCCEEDED
    relationship_counts: Counter[str] = Counter()
    search_added = 0
    correction_counts: Counter[str] = Counter()
    if changed:
        # Whole-workspace and idempotent; skipped when nothing changed, so
        # an identical re-import does no extra work.
        with factory.transaction() as session:
            relationship_counts = detect_relationships(
                session, workspace_id=workspace_id, import_id=import_id
            )
        try:
            with (
                factory.transaction(write=False) as session,
                LexicalIndex(search_index_path(settings)) as index,
            ):
                search_added = sync_index(session, index)
        except sqlite3.Error:
            # The index is a rebuildable cache: the import stands without it,
            # and the next search tries again.
            warnings["search_index_unavailable"] += 1
        # IMP-006: which human corrections still stand on unchanged words.
        with factory.transaction(write=False) as session:
            correction_counts = Counter(c.state.value for c in check_overrides(session))
    report = ImportReport(
        import_id=import_id,
        status=status,
        format_id=listing.format_id,
        conversations=dict(conversations),
        messages=dict(messages),
        files=dict(files),
        warnings=dict(warnings),
        changed_revisions=tuple(sorted(changed)),
        links=dict(sorted(link_counts.items())),
        accounts=dict(sorted(account_counts.items())),
        relationships=dict(sorted(relationship_counts.items())),
        search_indexed=search_added,
        corrections=dict(sorted(correction_counts.items())),
        new_branches=new_branches,
        raw_observations=raw_observations,
        candidate_matches=dict(candidates),
        media=media.counts(),
        asset_occurrences=dict(media.availability),
        duplicate_assets=media.duplicate_assets(),
        integrity=integrity,
        raw_tree_hash_before=before,
        raw_tree_hash_after=after,
    )
    with factory.transaction() as session:
        batch_row = session.get(ImportBatchRow, import_id)
        assert batch_row is not None
        ImportLedger(session, archive).finish(
            batch_row,
            status,
            counts={k: v for k, v in report.to_dict().items() if k != "warnings"},
            warnings=dict(warnings),
            tree_hash=after,
        )
    return report


def _groups(stream: Iterator[NativeConversation], size: int) -> Iterator[list[NativeConversation]]:
    while group := list(islice(stream, size)):
        yield group
