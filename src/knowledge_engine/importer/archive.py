"""Archive store (ING-001): keep exact copies of input files, by hash.

Every file the engine imports (an export ZIP, a ``conversations.json``, an
image) is identified by the SHA-256 of its bytes. The store keeps each one
at most once, under a path made from that hash, so the same file seen in
ten exports takes the space of one. Stored files are never overwritten or
edited: if the bytes already exist they are checked, and if they differ
from their name the store reports corruption instead of "fixing" it.

Large media can be kept *by reference* instead (OPEN_DECISIONS OD-02): the
store records the path and hash of a file that stays where it is, typically
inside ``raw/``, and re-checks the hash whenever it is read. Source files
are only ever opened for reading.

Talking points:
    - "Files are stored under their own fingerprint, so storing the same file
      twice is free and a changed file can never hide under an old name."
    - "The store never overwrites. If stored bytes don't match their hash it
      says 'corrupt' and stops; repairing evidence is a human decision."
    - "Big images can stay where they are. I keep their path and hash and
      check the hash again before trusting the file."
"""

from __future__ import annotations

import hashlib
import os
import stat
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from knowledge_engine.domain.ids import sha256_hex

StorageMode = Literal["copy", "reference"]

# 1 MiB chunks keep memory flat however big the file is.
_CHUNK = 1024 * 1024


class BlobStoreError(Exception):
    """Base class for blob store problems."""


class BlobTooLargeError(BlobStoreError):
    """The file is bigger than the configured limit, so it was not read."""


class BlobCorruptError(BlobStoreError):
    """Stored or referenced bytes no longer match their recorded SHA-256."""


class BlobMissingError(BlobStoreError):
    """The stored or referenced file is gone."""


@dataclass(frozen=True)
class StoredBlob:
    """Where a blob's bytes live and what they must hash to.

    Attributes:
        sha256: Lowercase hex SHA-256 of the bytes.
        size: Size in bytes.
        mode: ``copy`` (inside the store) or ``reference`` (left in place).
        location: The file holding the bytes. Private: never written to
            reports or notes, because a reference path can contain private
            file names.
    """

    sha256: str
    size: int
    mode: StorageMode
    location: Path


def hash_file(path: Path, *, max_bytes: int | None = None) -> tuple[str, int]:
    """Return the SHA-256 and size of a file, reading it in chunks.

    Args:
        path: File to hash. Opened read-only.
        max_bytes: Refuse files larger than this, checked before reading.

    Returns:
        ``(sha256 hex, size in bytes)``.

    Raises:
        BlobTooLargeError: If the file is larger than ``max_bytes``.
        BlobMissingError: If the file does not exist.
    """
    try:
        size = path.stat().st_size
    except FileNotFoundError as exc:
        raise BlobMissingError("file not found") from exc
    if max_bytes is not None and size > max_bytes:
        raise BlobTooLargeError(f"file is {size} bytes, limit is {max_bytes}")
    digest = hashlib.sha256()
    read = 0
    with path.open("rb") as handle:
        while chunk := handle.read(_CHUNK):
            digest.update(chunk)
            read += len(chunk)
    # The file grew between stat() and the read: hash what we read, but
    # keep the limit honest.
    if max_bytes is not None and read > max_bytes:
        raise BlobTooLargeError(f"file is {read} bytes, limit is {max_bytes}")
    return digest.hexdigest(), read


class BlobStore:
    """A folder of immutable files named by their SHA-256.

    Layout: ``<root>/<first 2 hex>/<full sha256>``. The two-character
    sub-folder keeps any one directory from holding hundreds of thousands
    of files, which some file systems and tools handle badly.
    """

    def __init__(self, root: Path, *, max_bytes: int | None = None) -> None:
        """Open (and create if needed) a store.

        Args:
            root: Store folder, inside the workspace. Never inside ``raw/``;
                ``Settings`` already refuses that overlap.
            max_bytes: Largest file accepted; ``None`` for no limit.
        """
        self._root = root
        self._max_bytes = max_bytes
        root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        """The store folder."""
        return self._root

    @property
    def max_bytes(self) -> int | None:
        """Largest file accepted, or None for no limit."""
        return self._max_bytes

    def path_for(self, sha256: str) -> Path:
        """Return where a blob with this hash lives in the store.

        Args:
            sha256: Lowercase hex SHA-256.

        Returns:
            The path (which may not exist yet).

        Raises:
            ValueError: If ``sha256`` is not 64 lowercase hex characters.
        """
        if len(sha256) != 64 or any(c not in "0123456789abcdef" for c in sha256):
            raise ValueError("sha256 must be 64 lowercase hex characters")
        return self._root / sha256[:2] / sha256

    def put_file(self, source: Path) -> StoredBlob:
        """Copy a file into the store, unless identical bytes are already there.

        The bytes are copied to a temporary file in the store, hashed while
        copying, then moved into place in one step. A crash mid-copy leaves
        only a temporary file, never a half-written blob under a real name.

        Args:
            source: File to store. Opened read-only.

        Returns:
            The stored blob.

        Raises:
            BlobTooLargeError: If the file exceeds the store's limit.
            BlobMissingError: If ``source`` does not exist.
            BlobCorruptError: If a blob with the same hash exists but its
                bytes no longer match (it is left untouched).
        """
        try:
            size = source.stat().st_size
        except FileNotFoundError as exc:
            raise BlobMissingError("file not found") from exc
        if self._max_bytes is not None and size > self._max_bytes:
            raise BlobTooLargeError(f"file is {size} bytes, limit is {self._max_bytes}")

        with source.open("rb") as handle:
            return self._store(iter(lambda: handle.read(_CHUNK), b""))

    def put_bytes(self, data: bytes) -> StoredBlob:
        """Store some bytes (e.g. a ZIP member), unless already stored.

        Args:
            data: The bytes.

        Returns:
            The stored blob.

        Raises:
            BlobTooLargeError: If ``data`` exceeds the store's limit.
            BlobCorruptError: If a blob with the same hash exists but its
                bytes no longer match.
        """
        if self._max_bytes is not None and len(data) > self._max_bytes:
            raise BlobTooLargeError(f"data is {len(data)} bytes, limit is {self._max_bytes}")
        return self._store(iter((data,)))

    def _store(self, chunks: Iterator[bytes]) -> StoredBlob:
        digest = hashlib.sha256()
        written = 0
        fd, tmp_name = tempfile.mkstemp(prefix=".incoming-", dir=self._root)
        tmp = Path(tmp_name)
        try:
            with os.fdopen(fd, "wb") as out:
                for chunk in chunks:
                    written += len(chunk)
                    if self._max_bytes is not None and written > self._max_bytes:
                        raise BlobTooLargeError(
                            f"file grew past the limit of {self._max_bytes} bytes"
                        )
                    digest.update(chunk)
                    out.write(chunk)
                out.flush()
                os.fsync(out.fileno())
            sha = digest.hexdigest()
            target = self.path_for(sha)
            if target.exists():
                # Already stored: check it rather than trusting the name.
                self._check(target, sha)
                return StoredBlob(sha, written, "copy", target)
            target.parent.mkdir(exist_ok=True)
            try:
                # Atomic: readers see either no blob or the whole blob. If
                # another import stored the same bytes a moment ago, the
                # replace swaps in identical bytes, which is harmless.
                os.replace(tmp, target)
            except PermissionError:
                # Windows can't replace a read-only file; that means the
                # blob is already there, so check it instead.
                self._check(target, sha)
            _make_read_only(target)
            return StoredBlob(sha, written, "copy", target)
        finally:
            tmp.unlink(missing_ok=True)

    def put_reference(self, source: Path) -> StoredBlob:
        """Record a file that stays where it is, by path and hash.

        Nothing is written. Use for large media in ``raw/`` (OD-02).

        Args:
            source: File to reference. Opened read-only.

        Returns:
            A blob in ``reference`` mode pointing at ``source``.

        Raises:
            BlobTooLargeError: If the file exceeds the store's limit.
            BlobMissingError: If ``source`` does not exist.
        """
        sha, size = hash_file(source, max_bytes=self._max_bytes)
        return StoredBlob(sha, size, "reference", source)

    def verify(self, blob: StoredBlob) -> None:
        """Check that a blob's bytes still match its hash.

        Args:
            blob: A blob from ``put_file`` or ``put_reference``.

        Raises:
            BlobMissingError: If the file is gone.
            BlobCorruptError: If the bytes changed.
        """
        self._check(blob.location, blob.sha256)

    def read_bytes(self, blob: StoredBlob) -> bytes:
        """Return a blob's bytes after checking them against the hash.

        Meant for small files. Large files should be streamed by the caller
        after ``verify``.

        Args:
            blob: The blob to read.

        Returns:
            The verified bytes.

        Raises:
            BlobMissingError: If the file is gone.
            BlobCorruptError: If the bytes changed.
        """
        try:
            data = blob.location.read_bytes()
        except FileNotFoundError as exc:
            raise BlobMissingError(f"blob {blob.sha256[:12]} is missing") from exc
        if sha256_hex(data) != blob.sha256:
            raise BlobCorruptError(f"blob {blob.sha256[:12]} does not match its hash")
        return data

    def _check(self, path: Path, sha256: str) -> None:
        # Errors name the hash prefix, never the path: a reference path can
        # contain a private file name.
        try:
            actual, _ = hash_file(path)
        except BlobMissingError as exc:
            raise BlobMissingError(f"blob {sha256[:12]} is missing") from exc
        if actual != sha256:
            raise BlobCorruptError(f"blob {sha256[:12]} does not match its hash")


def _make_read_only(path: Path) -> None:
    # A stored blob is evidence. Read-only permissions won't stop a
    # determined user, but they stop accidental edits by tools and scripts.
    path.chmod(stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)
