"""The import sequence behind ``import_source`` (ING-003, IMP-004). Private.

One call does, in order:

1. fingerprint the raw tree (read-only proof, before);
2. pick the adapter and list the source;
3. open a batch in the ledger and snapshot every input file;
4. write conversations in groups, one transaction per group, each opened
   with SQLite's write lock (``BEGIN IMMEDIATE``), so a crash loses at
   most the group in progress;
5. fingerprint the raw tree again and close the batch with its counts.

Re-running after a crash is the resume: groups already committed come
back ``unchanged`` and cost nothing (M1_CONSOLIDATION §5).

Talking points:
    - "One function, one report: callers can't get the order wrong because
      they never see the steps."
    - "A crash loses one group of conversations at most, and re-running the
      same import picks up where it stopped."
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterator
from itertools import islice
from pathlib import Path

from knowledge_engine import __version__
from knowledge_engine.domain.enums import DeltaCategory, ImportBatchStatus
from knowledge_engine.graph.conversation import BRANCH_CLASSIFIER_VERSION
from knowledge_engine.graph.nodes import CANONICAL_HASH_VERSION
from knowledge_engine.importer.archive import BlobStore
from knowledge_engine.importer.delta import MissingNativeIdError, apply_conversation
from knowledge_engine.importer.ledger import ImportBatchRow, ImportLedger
from knowledge_engine.importer.report import ImportReport
from knowledge_engine.infrastructure.db import SessionFactory, create_sqlite_engine, database_path
from knowledge_engine.infrastructure.migrations import upgrade_to_head
from knowledge_engine.infrastructure.workspace import WorkspaceRepo
from knowledge_engine.ingestion.inventory import tree_signature
from knowledge_engine.ingestion.registry import default_adapters
from knowledge_engine.ingestion.source import NativeConversation, SourceListing, select_adapter
from knowledge_engine.settings import Settings

DEFAULT_WORKSPACE_NAME = "default"


def run_import(
    path: Path, account_ns: str, *, format_id: str | None, settings: Settings
) -> ImportReport:
    """Import one source and return its report. See ``importer.import_source``."""
    before = tree_signature(path)
    adapter = select_adapter(path, default_adapters(), format_id)
    listing = adapter.open(path, max_bytes=settings.limits.max_source_file_bytes)

    settings.workspace_root.mkdir(parents=True, exist_ok=True)
    engine = create_sqlite_engine(database_path(settings))
    try:
        upgrade_to_head(engine)
        factory = SessionFactory(engine)
        archive = BlobStore(
            settings.workspace_root / "archive", max_bytes=settings.limits.max_source_file_bytes
        )
        return _run(path, account_ns, listing, before, factory, archive, settings)
    finally:
        engine.dispose()


def _run(
    path: Path,
    account_ns: str,
    listing: SourceListing,
    before: str,
    factory: SessionFactory,
    archive: BlobStore,
    settings: Settings,
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
    group_size = settings.limits.max_conversations_per_batch
    stream = listing.conversations()
    for group in _groups(stream, group_size):
        with factory.transaction() as session:
            for item in group:
                warnings.update(w.code for w in item.warnings)
                if not item.native:
                    conversations[DeltaCategory.FAILED.value] += 1
                    continue
                try:
                    delta = apply_conversation(
                        session,
                        item.native,
                        workspace_id=workspace_id,
                        account_namespace=account_ns,
                        import_id=import_id,
                        snapshot_id=snapshots[item.locator.file],
                    )
                except MissingNativeIdError:
                    # Keying it without a native ID would be a guess.
                    # IMP-002's candidate matching (slice I4) handles these.
                    warnings["missing_native_id"] += 1
                    conversations[DeltaCategory.FAILED.value] += 1
                    continue
                conversations[delta.category.value] += 1
                messages.update(delta.messages)
                warnings.update(delta.warnings)
                changed.extend(delta.changed_revisions)

    after = tree_signature(path)
    if after != before:
        status = ImportBatchStatus.FAILED
        warnings["raw_tree_changed"] += 1
    elif conversations[DeltaCategory.FAILED.value]:
        status = ImportBatchStatus.PARTIAL
    else:
        status = ImportBatchStatus.SUCCEEDED
    report = ImportReport(
        import_id=import_id,
        status=status,
        format_id=listing.format_id,
        conversations=dict(conversations),
        messages=dict(messages),
        files=dict(files),
        warnings=dict(warnings),
        changed_revisions=tuple(sorted(changed)),
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
