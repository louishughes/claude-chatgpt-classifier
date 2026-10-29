"""Import a Markdown or plain-text note into the archive (ING-012).

ING-008 already reads a note into located blocks, but only for previews.
This module *keeps* it, so a note is searchable and its links are found,
just like a chat:

1. the file's bytes are archived as an immutable snapshot (by SHA-256),
   through the same import ledger as chat exports, so every document
   import has a batch, a report and a stored copy;
2. the document is identified by **where it lives** (a fingerprint of its
   resolved path) and each distinct content is a **revision**: importing
   the same bytes again adds nothing, and changed bytes add a new revision
   while the old one stays as evidence;
3. every block is stored with its exact character range and line locator
   (``L12-L15``), so a search hit can say where in the file it is;
4. every URL becomes a link mention with the document as its source, in
   the same link registry as chat links; a YouTube URL also points at its
   video, so the video's page lists the note.

The source file is only ever read, never written or moved. Imported text
is data: nothing in a note is followed or obeyed.

Only Markdown and plain text for now. DOCX, PDF and web pages come later.

Talking points:
    - "A note goes through the same import ledger as a chat export, so it
      gets the same guarantees: a stored copy, a report, and nothing added
      when nothing changed."
    - "A link in my notes and a link in my chats land in one registry, so a
      YouTube video shows every chat and every note that mentions it."
"""

from __future__ import annotations

import json
import time
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    select,
)
from sqlalchemy.orm import Mapped, Session, mapped_column

from knowledge_engine import __version__
from knowledge_engine.domain.enums import ImportBatchStatus
from knowledge_engine.domain.ids import (
    document_block_id,
    document_id,
    document_link_id,
    document_revision_id,
)
from knowledge_engine.importer.archive import BlobStore
from knowledge_engine.importer.ledger import ImportLedger, root_fingerprint
from knowledge_engine.importer.lock import import_lock
from knowledge_engine.infrastructure.db import (
    Base,
    SessionFactory,
    create_sqlite_engine,
    database_path,
)
from knowledge_engine.infrastructure.migrations import upgrade_to_head
from knowledge_engine.infrastructure.upgrade import require_current
from knowledge_engine.infrastructure.workspace import WorkspaceRepo
from knowledge_engine.ingestion.documents import (
    DOCUMENT_PARSER_VERSION,
    ParsedDocument,
    parse_markdown,
    parse_text,
)
from knowledge_engine.ingestion.inventory import tree_signature
from knowledge_engine.links.extract import find_in_text
from knowledge_engine.links.store import LinkTargetRow, ensure_target
from knowledge_engine.links.youtube import ensure_video, parse_youtube
from knowledge_engine.settings import Settings

DOCUMENT_IMPORT_VERSION = "ing-012-v1"
# The ledger's account label for document batches: notes aren't from a
# chat account, and this keeps them apart from every export's namespace.
DOCUMENT_NAMESPACE = "documents"
# File suffix -> (format name, parser). Anything else is refused.
FORMATS = {
    ".md": ("markdown", parse_markdown),
    ".markdown": ("markdown", parse_markdown),
    ".txt": ("text", parse_text),
}


class UnsupportedDocumentError(ValueError):
    """The file isn't a format this importer reads (Markdown or plain text)."""


class DocumentChangedError(RuntimeError):
    """The file changed while it was being read, so nothing was stored."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


class DocumentRow(Base):
    """One imported note or text file, by where it lives."""

    __tablename__ = "source_documents"
    __table_args__ = (UniqueConstraint("workspace_id", "path_fingerprint"),)

    document_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.workspace_id"))
    # SHA-256 of the resolved path: the path itself is private and never stored.
    path_fingerprint: Mapped[str] = mapped_column(String(64))
    # The file name, to show in search results on this computer.
    name: Mapped[str] = mapped_column(Text)
    format: Mapped[str] = mapped_column(String(10))
    # The revision matching the file as it was last imported. Not a foreign
    # key, so the document row can be written before its first revision.
    current_revision_id: Mapped[str] = mapped_column(String(40))
    first_import_id: Mapped[str] = mapped_column(ForeignKey("import_batches.import_id"))
    last_import_id: Mapped[str] = mapped_column(ForeignKey("import_batches.import_id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


class DocumentRevisionRow(Base):
    """One version of a document: its exact bytes, archived."""

    __tablename__ = "document_revisions"
    __table_args__ = (UniqueConstraint("document_id", "sha256"),)

    revision_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("source_documents.document_id"), index=True)
    sha256: Mapped[str] = mapped_column(String(64))
    size: Mapped[int] = mapped_column(BigInteger)
    snapshot_id: Mapped[str] = mapped_column(ForeignKey("source_snapshots.snapshot_id"))
    encoding: Mapped[str | None] = mapped_column(String(20), default=None)
    parser: Mapped[str] = mapped_column(String(30))
    # Parser warning codes (never content), as a JSON list.
    warnings_json: Mapped[str] = mapped_column(Text, default="[]")
    first_import_id: Mapped[str] = mapped_column(ForeignKey("import_batches.import_id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


class DocumentBlockRow(Base):
    """One located block of a revision: its text and exactly where it is."""

    __tablename__ = "document_blocks"
    __table_args__ = (UniqueConstraint("revision_id", "block_index"),)

    block_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    revision_id: Mapped[str] = mapped_column(
        ForeignKey("document_revisions.revision_id"), index=True
    )
    block_index: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(12))
    start: Mapped[int] = mapped_column(Integer)
    end: Mapped[int] = mapped_column(Integer)
    line_start: Mapped[int | None] = mapped_column(Integer, default=None)
    line_end: Mapped[int | None] = mapped_column(Integer, default=None)
    locator: Mapped[str] = mapped_column(String(40))
    heading_path_json: Mapped[str] = mapped_column(Text, default="[]")
    text: Mapped[str] = mapped_column(Text)


class DocumentLinkRow(Base):
    """One URL mention at an exact place in a document revision."""

    __tablename__ = "document_links"

    link_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    revision_id: Mapped[str] = mapped_column(
        ForeignKey("document_revisions.revision_id"), index=True
    )
    block_id: Mapped[str] = mapped_column(ForeignKey("document_blocks.block_id"))
    target_id: Mapped[str] = mapped_column(ForeignKey("link_targets.target_id"), index=True)
    # Code points into the revision's decoded text.
    start: Mapped[int] = mapped_column(Integer)
    end: Mapped[int] = mapped_column(Integer)
    # The URL exactly as written: the evidence. Untrusted, never fetched.
    original_text: Mapped[str] = mapped_column(Text)
    # Set when the URL is a YouTube video link: the video it points at.
    video_id: Mapped[str | None] = mapped_column(
        ForeignKey("youtube_videos.video_id"), default=None, index=True
    )
    t_seconds: Mapped[int | None] = mapped_column(Integer, default=None)
    first_import_id: Mapped[str] = mapped_column(ForeignKey("import_batches.import_id"))


@dataclass(frozen=True)
class DocumentImportReport:
    """What one ``ke import-doc`` did. IDs and counts only, no text.

    Attributes:
        import_id: The ledger batch.
        document_id: The ``doc_`` ID.
        revision_id: The ``docrev_`` ID of the file as it is now.
        outcome: ``new`` (first import), ``revised`` (changed bytes: a new
            revision), ``reverted`` (back to bytes an earlier revision
            already holds: nothing new stored) or ``unchanged``.
        format: ``markdown`` or ``text``.
        counts: ``blocks``, ``links``, ``youtube_mentions``, ``new_targets``
            added by this import (all zero when unchanged).
        warnings: Parser warning codes.
    """

    import_id: str
    document_id: str
    revision_id: str
    outcome: str
    format: str
    counts: dict[str, int]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        """JSON-ready form."""
        return {
            "import_id": self.import_id,
            "document_id": self.document_id,
            "revision_id": self.revision_id,
            "outcome": self.outcome,
            "format": self.format,
            "counts": dict(sorted(self.counts.items())),
            "warnings": list(self.warnings),
        }


def import_document(path: Path, *, settings: Settings) -> DocumentImportReport:
    """Archive one Markdown or text file and store its blocks and links.

    Args:
        path: The file. Only read.
        settings: Workspace settings.

    Returns:
        The report.

    Raises:
        FileNotFoundError: If there's no such file.
        UnsupportedDocumentError: If it isn't ``.md``, ``.markdown`` or ``.txt``,
            or is bigger than the source-file size limit.
        DocumentChangedError: If the file changed while being read.
    """
    if not path.is_file():
        raise FileNotFoundError("no such file")
    found = FORMATS.get(path.suffix.lower())
    if found is None:
        raise UnsupportedDocumentError("only .md, .markdown and .txt files can be imported")
    fmt, parse = found
    if path.stat().st_size > settings.limits.max_source_file_bytes:
        raise UnsupportedDocumentError("the file is bigger than the source-file size limit")
    # Read once, and check the file didn't change underneath us: the stored
    # copy, the hash and the blocks must all describe the same bytes.
    before = tree_signature(path)
    data = path.read_bytes()
    if tree_signature(path) != before:
        raise DocumentChangedError("the file changed while it was being read")
    parsed = parse(data)

    with import_lock(settings.workspace_root, timeout_s=settings.limits.import_lock_timeout_s):
        engine = create_sqlite_engine(database_path(settings))
        try:
            require_current(engine)
            upgrade_to_head(engine)
            factory = SessionFactory(engine)
            archive = BlobStore(
                settings.workspace_root / "archive",
                max_bytes=settings.limits.max_source_file_bytes,
            )
            with factory.transaction() as session:
                return _store(session, archive, path, fmt, data, parsed, before)
        finally:
            engine.dispose()


def _store(
    session: Session,
    archive: BlobStore,
    path: Path,
    fmt: str,
    data: bytes,
    parsed: ParsedDocument,
    tree_hash: str,
) -> DocumentImportReport:
    started = time.perf_counter()
    workspace_id = WorkspaceRepo(session).get_or_create("default").workspace_id
    ledger = ImportLedger(session, archive)
    batch = ledger.start(
        workspace_id=workspace_id,
        account_namespace=DOCUMENT_NAMESPACE,
        root=path,
        format_id=f"document_{fmt}",
        versions={
            "code": __version__,
            "parser": parsed.parser or DOCUMENT_PARSER_VERSION,
            "document_import": DOCUMENT_IMPORT_VERSION,
        },
        tree_hash=tree_hash,
    )
    snapshot, _ = ledger.record_file(batch, path.name, data=data)

    doc_key = document_id(workspace_id, root_fingerprint(path))
    rev_key = document_revision_id(doc_key, parsed.sha256)
    counts: Counter[str] = Counter()
    document = session.get(DocumentRow, doc_key)
    revision = session.get(DocumentRevisionRow, rev_key)
    if document is None:
        outcome = "new"
        document = DocumentRow(
            document_id=doc_key,
            workspace_id=workspace_id,
            path_fingerprint=root_fingerprint(path),
            name=path.name,
            format=fmt,
            current_revision_id=rev_key,
            first_import_id=batch.import_id,
            last_import_id=batch.import_id,
        )
        session.add(document)
        session.flush()
    elif document.current_revision_id == rev_key:
        outcome = "unchanged"
    else:
        # Changed bytes, or a return to an older version: either way the
        # current revision moves, and every earlier one stays.
        outcome = "revised"
    document.current_revision_id = rev_key
    document.last_import_id = batch.import_id
    if revision is None:
        session.add(
            DocumentRevisionRow(
                revision_id=rev_key,
                document_id=doc_key,
                sha256=parsed.sha256,
                size=parsed.size,
                snapshot_id=snapshot.snapshot_id,
                encoding=parsed.encoding,
                parser=parsed.parser,
                warnings_json=json.dumps(list(parsed.warnings)),
                first_import_id=batch.import_id,
            )
        )
        session.flush()
        _store_blocks(session, parsed, rev_key, batch.import_id, counts)
    elif outcome == "revised":
        outcome = "reverted"
    ledger.finish(
        batch,
        ImportBatchStatus.SUCCEEDED,
        counts={
            "document": {"outcome": outcome, **dict(sorted(counts.items()))},
            "timings": {"total": round(time.perf_counter() - started, 3)},
        },
        warnings=dict(Counter(parsed.warnings)),
        tree_hash=tree_hash,
    )
    return DocumentImportReport(
        import_id=batch.import_id,
        document_id=doc_key,
        revision_id=rev_key,
        outcome=outcome,
        format=fmt,
        counts={
            k: counts.get(k, 0) for k in ("blocks", "links", "youtube_mentions", "new_targets")
        },
        warnings=parsed.warnings,
    )


def _store_blocks(
    session: Session,
    parsed: ParsedDocument,
    revision_id: str,
    import_id: str,
    counts: Counter[str],
) -> None:
    """Write a new revision's blocks and the URLs found in them."""
    for block in parsed.blocks:
        block_key = document_block_id(revision_id, block.index)
        session.add(
            DocumentBlockRow(
                block_id=block_key,
                revision_id=revision_id,
                block_index=block.index,
                kind=block.kind.value,
                start=block.start,
                end=block.end,
                line_start=block.line_start,
                line_end=block.line_end,
                locator=block.locator,
                heading_path_json=json.dumps(list(block.heading_path), ensure_ascii=False),
                text=block.text,
            )
        )
        counts["blocks"] += 1
        session.flush()
        for link in find_in_text(block.text):
            # The block's text is document.text[start:end], so a span inside
            # the block plus the block's start is a span in the document.
            start = block.start + link.span.start
            end = block.start + link.span.end
            key = document_link_id(revision_id, start, end)
            if session.get(DocumentLinkRow, key) is not None:
                continue
            target = ensure_target(session, link, import_id=import_id, counts=counts)
            video = parse_youtube(link.original)
            if video is not None:
                ensure_video(session, video.video_id, import_id=import_id)
                target_row = session.get(LinkTargetRow, target)
                if target_row is not None:
                    target_row.kind = "youtube_video"
                counts["youtube_mentions"] += 1
            session.add(
                DocumentLinkRow(
                    link_id=key,
                    revision_id=revision_id,
                    block_id=block_key,
                    target_id=target,
                    start=start,
                    end=end,
                    original_text=link.original,
                    video_id=video.video_id if video is not None else None,
                    t_seconds=video.t_seconds if video is not None else None,
                    first_import_id=import_id,
                )
            )
            session.flush()
            counts["links"] += 1


def current_blocks(session: Session) -> list[tuple[DocumentBlockRow, DocumentRow]]:
    """Every block of every document's current revision, in a stable order.

    The search index holds exactly these: an older revision is kept as
    evidence but isn't searched, so a changed note never shows up twice.
    """
    return [
        (block, document)
        for block, document in session.execute(
            select(DocumentBlockRow, DocumentRow)
            .join(DocumentRow, DocumentRow.current_revision_id == DocumentBlockRow.revision_id)
            .order_by(DocumentBlockRow.block_id)
        ).tuples()
    ]


def video_document_mentions(session: Session, video_id: str) -> list[dict[str, Any]]:
    """Every link to a video from an imported document's current revision.

    Returns:
        One dict per mention: ``document_id``, ``name``, ``locator``,
        ``written`` (the URL as written) and ``t_seconds``.
    """
    rows = session.execute(
        select(DocumentLinkRow, DocumentBlockRow, DocumentRow)
        .join(DocumentBlockRow, DocumentBlockRow.block_id == DocumentLinkRow.block_id)
        .join(DocumentRow, DocumentRow.current_revision_id == DocumentLinkRow.revision_id)
        .where(DocumentLinkRow.video_id == video_id)
        .order_by(DocumentRow.name, DocumentLinkRow.start)
    ).tuples()
    return [
        {
            "document_id": document.document_id,
            "name": document.name,
            "locator": block.locator,
            "written": link.original_text,
            "t_seconds": link.t_seconds,
        }
        for link, block, document in rows
    ]
