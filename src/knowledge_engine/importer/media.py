"""Images and attachments: stored once, every use recorded (MED-001, MED-003).

ADR-0004 splits "the file" from "a message used it" into separate records:

* a **blob** is some bytes, identified by their SHA-256. Two files with the
  same bytes are one blob;
* an **asset** is the export's logical file, keyed by its file ID (the
  ``file-...`` in ``file-service://file-...``). It points at zero or one blob;
* an **occurrence** is one place a message refers to an asset: (message
  revision, content part, pointer). The same image in three messages is one
  asset with three occurrences, each with its own availability state;
* a **derived artefact** (thumbnail, extracted metadata) hangs off a blob
  and never replaces it. Nothing creates one yet.

Image type and size are read from the file header only. Nothing here looks
at what an image *shows*: no OCR, no vision, nothing sent anywhere.

Occurrences are keyed by the revision, so re-importing an unchanged message
finds its occurrences already recorded and adds nothing.

Talking points:
    - "One image used in five messages is stored once and linked five
      times; each link remembers exactly where it was used."
    - "If the image file isn't in the export, the link is kept and marked
      missing. I never invent a path."
    - "Dimensions come from the file header, never from looking at the
      picture."
"""

from __future__ import annotations

import struct
import zipfile
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, Session, mapped_column

from knowledge_engine.domain.enums import AssetAvailability, SourceSystem
from knowledge_engine.domain.ids import asset_occurrence_id, media_asset_id
from knowledge_engine.graph.nodes import AssetPointer
from knowledge_engine.importer.archive import BlobStore, BlobTooLargeError, StoredBlob
from knowledge_engine.infrastructure.db import Base
from knowledge_engine.ingestion.inventory import sniff_media
from knowledge_engine.ingestion.source import MediaFile

# Enough of a file to find the dimensions of any supported image type: JPEG
# can put large metadata blocks before the frame header.
_HEADER_BYTES = 256 * 1024
_AVAILABILITY_VALUES = ",".join(f"'{state.value}'" for state in AssetAvailability)


def _utc_now() -> datetime:
    return datetime.now(UTC)


class MediaBlobRow(Base):
    """Some bytes, stored or referenced once however often they're used."""

    __tablename__ = "media_blobs"
    __table_args__ = (
        CheckConstraint("storage_mode IN ('copy','reference')", name="storage_mode_valid"),
    )

    blob_sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    size: Mapped[int] = mapped_column(Integer)
    storage_mode: Mapped[str] = mapped_column(String(10))
    # Reference mode only: where the bytes stay. Private (can hold a file
    # name), so it's never copied into reports or notes.
    location: Mapped[str | None] = mapped_column(Text, default=None)
    # Header facts: what the bytes say about themselves, read without
    # decoding the picture.
    media_type: Mapped[str | None] = mapped_column(String(60), default=None)
    width: Mapped[int | None] = mapped_column(Integer, default=None)
    height: Mapped[int | None] = mapped_column(Integer, default=None)
    first_import_id: Mapped[str] = mapped_column(ForeignKey("import_batches.import_id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


class MediaAssetRow(Base):
    """The export's logical file, keyed by its file ID."""

    __tablename__ = "media_assets"
    __table_args__ = (UniqueConstraint("workspace_id", "source_system", "native_file_id"),)

    asset_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.workspace_id"))
    source_system: Mapped[str] = mapped_column(String(20))
    native_file_id: Mapped[str | None] = mapped_column(String(200), default=None)
    # None until some export supplies the bytes.
    blob_sha256: Mapped[str | None] = mapped_column(
        ForeignKey("media_blobs.blob_sha256"), default=None
    )
    first_import_id: Mapped[str] = mapped_column(ForeignKey("import_batches.import_id"))


class AssetOccurrenceRow(Base):
    """One place where one message revision refers to an asset."""

    __tablename__ = "asset_occurrences"
    __table_args__ = (
        UniqueConstraint("revision_id", "part_index", "pointer"),
        CheckConstraint(f"availability IN ({_AVAILABILITY_VALUES})", name="availability_valid"),
    )

    occurrence_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    revision_id: Mapped[str] = mapped_column(
        ForeignKey("message_revisions.revision_id"), index=True
    )
    part_index: Mapped[int] = mapped_column(Integer)
    # The pointer exactly as exported: the evidence for this occurrence.
    pointer: Mapped[str] = mapped_column(Text)
    content_type: Mapped[str | None] = mapped_column(String(60), default=None)
    # None when the pointer names no file ID (an unknown scheme).
    asset_id: Mapped[str | None] = mapped_column(
        ForeignKey("media_assets.asset_id"), default=None, index=True
    )
    availability: Mapped[str] = mapped_column(String(12))
    # How many files matched the pointer: 0 missing, 1 available, 2+ ambiguous.
    candidate_count: Mapped[int] = mapped_column(Integer, default=0)
    declared_size: Mapped[int | None] = mapped_column(Integer, default=None)
    declared_width: Mapped[int | None] = mapped_column(Integer, default=None)
    declared_height: Mapped[int | None] = mapped_column(Integer, default=None)
    first_import_id: Mapped[str] = mapped_column(ForeignKey("import_batches.import_id"))
    # The import that last decided ``availability`` (a later export can
    # supply a file that was missing before).
    resolved_import_id: Mapped[str] = mapped_column(ForeignKey("import_batches.import_id"))


class DerivedMediaArtifactRow(Base):
    """Something made from a blob (e.g. a thumbnail). Never replaces it."""

    __tablename__ = "derived_media_artifacts"
    __table_args__ = (
        UniqueConstraint("blob_sha256", "kind", "generator_version"),
        CheckConstraint("kind IN ('thumbnail','header_metadata')", name="kind_valid"),
    )

    artifact_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    blob_sha256: Mapped[str] = mapped_column(ForeignKey("media_blobs.blob_sha256"), index=True)
    kind: Mapped[str] = mapped_column(String(30))
    generator_version: Mapped[str] = mapped_column(String(40))
    location: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


@dataclass
class MediaDelta:
    """What one import did with media.

    Attributes:
        new_blobs: Distinct byte contents stored for the first time.
        new_assets: Logical files seen for the first time.
        new_occurrences: Message-to-asset links recorded for the first time.
        availability: Availability state -> count, over every occurrence
            this import saw (new or not).
        warnings: Warning code -> count.
    """

    new_blobs: int = 0
    new_assets: int = 0
    new_occurrences: int = 0
    availability: Counter[str] = field(default_factory=Counter)
    warnings: Counter[str] = field(default_factory=Counter)

    def counts(self) -> dict[str, int]:
        """Return the ``new_*`` counts as a dict."""
        return {
            "new_assets": self.new_assets,
            "new_blobs": self.new_blobs,
            "new_occurrences": self.new_occurrences,
        }


class MediaLibrary:
    """The media files of one source, matched and stored for one import."""

    def __init__(self, root: Path, files: Sequence[MediaFile], store: BlobStore, mode: str) -> None:
        """Index a source's media files.

        Args:
            root: The source folder, or the ZIP file.
            files: The media files the adapter listed.
            store: Where copies go (``copy`` mode, and always for ZIP
                members, which can't be referenced in place).
            mode: ``reference`` or ``copy`` (OD-02).
        """
        self._root = root
        self._store = store
        self._mode = mode
        self._by_name = sorted(files, key=lambda f: f.path)
        self._stored: dict[str, tuple[StoredBlob, bytes]] = {}

    def candidates(self, file_id: str) -> list[MediaFile]:
        """Return the files whose name belongs to ``file_id``.

        A file belongs to an ID when its name is the ID, or the ID followed
        by ``-`` or ``.`` (``file-abc-photo.png``). The separator matters:
        without it ``file-abc`` would also claim ``file-abcd.png``.

        Args:
            file_id: The ID from the pointer.

        Returns:
            Matching files, sorted by path.
        """
        return [
            media
            for media in self._by_name
            if media.name == file_id or media.name.startswith((f"{file_id}-", f"{file_id}."))
        ]

    def store(self, media: MediaFile) -> tuple[StoredBlob, bytes]:
        """Store (or reference) one file, once per import.

        Args:
            media: A listed media file.

        Returns:
            The stored blob and the file's first bytes (for header facts).

        Raises:
            BlobTooLargeError: If the file is over the media size limit.
        """
        cached = self._stored.get(media.path)
        if cached is not None:
            return cached
        if self._root.is_file():
            with zipfile.ZipFile(self._root) as archive:
                limit = self._store.max_bytes
                if limit is not None and archive.getinfo(media.path).file_size > limit:
                    raise BlobTooLargeError("media file is over the size limit")
                data = archive.read(media.path)
            blob, head = self._store.put_bytes(data), data[:_HEADER_BYTES]
        else:
            source = self._root / PurePosixPath(media.path)
            blob = (
                self._store.put_reference(source)
                if self._mode == "reference"
                else self._store.put_file(source)
            )
            with source.open("rb") as handle:
                head = handle.read(_HEADER_BYTES)
        self._stored[media.path] = (blob, head)
        return blob, head


def record_occurrences(
    session: Session,
    pointers: Sequence[tuple[str, AssetPointer]],
    library: MediaLibrary,
    delta: MediaDelta,
    *,
    workspace_id: str,
    import_id: str,
) -> None:
    """Record every asset occurrence of some message revisions.

    An occurrence already ``available`` is left alone. One that wasn't is
    re-resolved, because a later export may contain the file.

    Args:
        session: The batch's write session.
        pointers: ``(revision_id, pointer)`` pairs, in message order.
        library: This import's media files.
        delta: Updated in place.
        workspace_id: The workspace.
        import_id: The running batch.
    """
    for revision_id, pointer in pointers:
        occurrence_key = asset_occurrence_id(revision_id, pointer.part_index, pointer.pointer)
        row = session.get(AssetOccurrenceRow, occurrence_key)
        if row is not None and row.availability == AssetAvailability.AVAILABLE.value:
            delta.availability[row.availability] += 1
            continue
        asset_id, state, candidates = _resolve(
            session, pointer, library, delta, workspace_id=workspace_id, import_id=import_id
        )
        if row is None:
            session.add(
                AssetOccurrenceRow(
                    occurrence_id=occurrence_key,
                    revision_id=revision_id,
                    part_index=pointer.part_index,
                    pointer=pointer.pointer,
                    content_type=pointer.content_type,
                    asset_id=asset_id,
                    availability=state.value,
                    candidate_count=candidates,
                    declared_size=pointer.size_bytes,
                    declared_width=pointer.width,
                    declared_height=pointer.height,
                    first_import_id=import_id,
                    resolved_import_id=import_id,
                )
            )
            delta.new_occurrences += 1
        elif row.availability != state.value or row.candidate_count != candidates:
            row.asset_id = asset_id
            row.availability = state.value
            row.candidate_count = candidates
            row.resolved_import_id = import_id
        delta.availability[state.value] += 1
    session.flush()


def _resolve(
    session: Session,
    pointer: AssetPointer,
    library: MediaLibrary,
    delta: MediaDelta,
    *,
    workspace_id: str,
    import_id: str,
) -> tuple[str | None, AssetAvailability, int]:
    if pointer.file_id is None:
        return None, AssetAvailability.UNRESOLVED, 0
    asset = _asset(session, pointer.file_id, delta, workspace_id=workspace_id, import_id=import_id)
    candidates = library.candidates(pointer.file_id)
    if not candidates:
        return asset.asset_id, AssetAvailability.MISSING, 0
    if len(candidates) > 1:
        return asset.asset_id, AssetAvailability.AMBIGUOUS, len(candidates)
    try:
        stored, head = library.store(candidates[0])
    except BlobTooLargeError:
        delta.warnings["media_too_large"] += 1
        return asset.asset_id, AssetAvailability.UNSUPPORTED, 1
    _blob(session, stored, head, delta, import_id=import_id)
    if asset.blob_sha256 is None:
        asset.blob_sha256 = stored.sha256
    elif asset.blob_sha256 != stored.sha256:
        # Same file ID, different bytes: keep the first and flag it rather
        # than silently swapping evidence.
        delta.warnings["asset_bytes_changed"] += 1
    return asset.asset_id, AssetAvailability.AVAILABLE, 1


def _asset(
    session: Session, file_id: str, delta: MediaDelta, *, workspace_id: str, import_id: str
) -> MediaAssetRow:
    key = media_asset_id(workspace_id, SourceSystem.CHATGPT.value, native_file_id=file_id)
    asset = session.get(MediaAssetRow, key)
    if asset is None:
        asset = MediaAssetRow(
            asset_id=key,
            workspace_id=workspace_id,
            source_system=SourceSystem.CHATGPT.value,
            native_file_id=file_id,
            first_import_id=import_id,
        )
        session.add(asset)
        session.flush()
        delta.new_assets += 1
    return asset


def _blob(
    session: Session, stored: StoredBlob, head: bytes, delta: MediaDelta, *, import_id: str
) -> None:
    if session.get(MediaBlobRow, stored.sha256) is not None:
        return
    media_type, width, height = image_header(head)
    session.add(
        MediaBlobRow(
            blob_sha256=stored.sha256,
            size=stored.size,
            storage_mode=stored.mode,
            location=str(stored.location) if stored.mode == "reference" else None,
            media_type=media_type,
            width=width,
            height=height,
            first_import_id=import_id,
        )
    )
    session.flush()
    delta.new_blobs += 1


def image_header(head: bytes) -> tuple[str | None, int | None, int | None]:
    """Read an image's type and pixel size from its header bytes.

    Only the header is parsed; the picture itself is never decoded.

    Args:
        head: The first bytes of the file (up to 256 KiB is plenty).

    Returns:
        ``(media_type, width, height)``; the size is None when the header
        doesn't give it or the type isn't a supported image.
    """
    media_type = sniff_media(head[:16])
    size: tuple[int, int] | None = None
    try:
        if media_type == "image/png" and head[12:16] == b"IHDR":
            size = struct.unpack(">II", head[16:24])
        elif media_type == "image/gif":
            size = struct.unpack("<HH", head[6:10])
        elif media_type == "image/jpeg":
            size = _jpeg_size(head)
        elif media_type == "image/webp":
            size = _webp_size(head)
    except struct.error:
        size = None
    if size is None:
        return media_type, None, None
    return media_type, size[0], size[1]


def _jpeg_size(head: bytes) -> tuple[int, int] | None:
    # Walk the segment list to the first frame header (SOF0..SOF15, except
    # the DHT/JPG/DAC markers that share the range).
    index = 2
    while index + 9 < len(head):
        if head[index] != 0xFF:
            return None
        marker = head[index + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            index += 2
            continue
        length = struct.unpack(">H", head[index + 2 : index + 4])[0]
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height, width = struct.unpack(">HH", head[index + 5 : index + 9])
            return width, height
        index += 2 + length
    return None


def _webp_size(head: bytes) -> tuple[int, int] | None:
    chunk = head[12:16]
    if chunk == b"VP8X":
        width = int.from_bytes(head[24:27], "little") + 1
        height = int.from_bytes(head[27:30], "little") + 1
        return width, height
    if chunk == b"VP8L":
        bits = int.from_bytes(head[21:25], "little")
        return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    if chunk == b"VP8 ":
        width, height = struct.unpack("<HH", head[26:30])
        return width & 0x3FFF, height & 0x3FFF
    return None
