"""Images in notes: vault-safe embeds, honest missing markers (MED-004).

A note shows each image a message used in one of two ways:

* **available:** an Obsidian embed, ``![[_attachments/ab/<sha256>.png]]``.
  The file is copied into the vault under its fingerprint (OD-14), so the
  vault works anywhere and never points back into ``raw/`` or the private
  store;
* **anything else:** a visible marker naming the pointer and the reason
  (missing, ambiguous, unresolved...). Never a guessed path.

``check_embeds`` is the link checker: it lists every embed in a note whose
file isn't in the vault.

Rendering only reads stored records and copies verified bytes; it never
changes what was imported.

Talking points:
    - "An image in a note is a copy inside the vault, named by its
      fingerprint, so the vault never depends on where my raw files live."
    - "If an image is missing, the note says so and says why, right where
      the image would have been."
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.domain.enums import AssetAvailability
from knowledge_engine.rendering.markdown import Paragraph, escape_text, safe_relative_path

ATTACHMENTS_DIR = "_attachments"

_EXTENSIONS = {
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/gif": "gif",
    "image/webp": "webp",
    "application/pdf": "pdf",
    "audio/mpeg": "mp3",
    "audio/ogg": "ogg",
    "audio/wav": "wav",
    "video/mp4": "mp4",
}
# Plain-language reasons for each resolution rule (MED-002's evidence).
REASONS = {
    "no_matching_file": "no file with this ID is in the export",
    "listed_but_absent": "the export's index lists it, but the file is absent",
    "several_files": "several different files match this ID",
    "unknown_scheme": "this kind of pointer isn't recognised",
    "no_scheme": "this isn't a pointer to a file",
    "too_large": "the file is over the size limit",
}
# An embed that Obsidian would act on: ``![[target]]``, ``![[target|size]]``.
# An escaped ``\[\[`` from chat text never matches.
_EMBED_RE = re.compile(r"(?<!\\)!\[\[([^\]|#^]+)(?:[|#^][^\]]*)?\]\]")
_SHA_RE = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class MediaRef:
    """One image or attachment use, as a note needs it.

    Attributes:
        pointer: The pointer as exported.
        part_index: Its position in the message.
        availability: The stored availability state.
        rule: The resolution rule from the evidence, if recorded.
        blob_sha256: The bytes' fingerprint, when available.
        media_type: From the file header, when available.
    """

    pointer: str
    part_index: int
    availability: str
    rule: str | None = None
    blob_sha256: str | None = None
    media_type: str | None = None


def attachment_path(blob_sha256: str, media_type: str | None) -> PurePosixPath:
    """Return the vault path for some bytes (OD-14).

    Args:
        blob_sha256: The bytes' SHA-256.
        media_type: From the file header; unknown types get ``.bin``.

    Returns:
        ``_attachments/<first 2 hex>/<sha256>.<ext>``.

    Raises:
        ValueError: If ``blob_sha256`` isn't 64 lowercase hex characters.
    """
    if not _SHA_RE.fullmatch(blob_sha256):
        raise ValueError("blob_sha256 must be 64 lowercase hex characters")
    extension = _EXTENSIONS.get(media_type or "", "bin")
    return safe_relative_path(ATTACHMENTS_DIR, blob_sha256[:2], f"{blob_sha256}.{extension}")


def media_block(ref: MediaRef) -> Paragraph:
    """Return the note block for one media use.

    Args:
        ref: The media use.

    Returns:
        An embed for available media, otherwise a marker naming the pointer,
        the state and the reason.
    """
    if ref.availability == AssetAvailability.AVAILABLE.value and ref.blob_sha256:
        target = attachment_path(ref.blob_sha256, ref.media_type)
        return Paragraph(f"![[{target.as_posix()}]]", trusted=True)
    reason = REASONS.get(ref.rule or "", "no reason recorded")
    # The pointer comes from the export: escaped like any imported text.
    return Paragraph(
        f"> [!warning] Image {ref.availability}: {escape_text(ref.pointer)} ({reason})",
        trusted=True,
    )


def load_media_refs(session: Session, revision_ids: Iterable[str]) -> dict[str, list[MediaRef]]:
    """Read the media uses of some message revisions.

    Args:
        session: A read session on the workspace database.
        revision_ids: The revisions a note shows.

    Returns:
        Revision ID -> its media uses, in part order.
    """
    from knowledge_engine.importer.media import AssetOccurrenceRow, MediaAssetRow, MediaBlobRow

    ids = sorted(set(revision_ids))
    refs: dict[str, list[MediaRef]] = {}
    if not ids:
        return refs
    rows = session.execute(
        select(AssetOccurrenceRow, MediaBlobRow.blob_sha256, MediaBlobRow.media_type)
        .outerjoin(MediaAssetRow, MediaAssetRow.asset_id == AssetOccurrenceRow.asset_id)
        .outerjoin(MediaBlobRow, MediaBlobRow.blob_sha256 == MediaAssetRow.blob_sha256)
        .where(AssetOccurrenceRow.revision_id.in_(ids))
        .order_by(
            AssetOccurrenceRow.revision_id,
            AssetOccurrenceRow.content_type == "attachment",
            AssetOccurrenceRow.part_index,
            AssetOccurrenceRow.pointer,
        )
    ).all()
    for occurrence, sha, media_type in rows:
        evidence = json.loads(occurrence.evidence_json) if occurrence.evidence_json else {}
        available = occurrence.availability == AssetAvailability.AVAILABLE.value
        refs.setdefault(occurrence.revision_id, []).append(
            MediaRef(
                pointer=occurrence.pointer,
                part_index=occurrence.part_index,
                availability=occurrence.availability,
                rule=evidence.get("rule"),
                blob_sha256=sha if available else None,
                media_type=media_type if available else None,
            )
        )
    return refs


def blob_sources(session: Session, store_root: Path) -> Callable[[str], Path]:
    """Return a function that finds a blob's bytes on disk.

    Args:
        session: A read session on the workspace database.
        store_root: The workspace's content-addressed store.

    Returns:
        ``sha256 -> path``: the referenced file for ``reference`` blobs,
        the store copy for ``copy`` blobs.
    """
    from knowledge_engine.importer.media import MediaBlobRow

    def find(blob_sha256: str) -> Path:
        row = session.get(MediaBlobRow, blob_sha256)
        if row is not None and row.storage_mode == "reference" and row.location:
            return Path(row.location)
        return store_root / blob_sha256[:2] / blob_sha256

    return find


def export_attachments(
    refs: Iterable[MediaRef], vault_root: Path, source_of: Callable[[str], Path]
) -> dict[str, int]:
    """Copy the available media of some notes into the vault, verified.

    Each file is copied to a temporary name while being hashed, and only
    renamed into place if the hash matches, so a changed or damaged source
    never reaches the vault.

    Args:
        refs: Media uses of the notes being written.
        vault_root: The vault folder.
        source_of: ``sha256 -> path`` (see ``blob_sources``).

    Returns:
        ``copied`` and ``unchanged`` counts.

    Raises:
        ValueError: If a source's bytes don't match their fingerprint.
        FileNotFoundError: If a source file is gone.
    """
    counts = {"copied": 0, "unchanged": 0}
    done: set[str] = set()
    for ref in refs:
        if ref.availability != AssetAvailability.AVAILABLE.value or not ref.blob_sha256:
            continue
        if ref.blob_sha256 in done:
            continue
        done.add(ref.blob_sha256)
        target = vault_root / Path(*attachment_path(ref.blob_sha256, ref.media_type).parts)
        if target.is_file() and _sha256(target) == ref.blob_sha256:
            counts["unchanged"] += 1
            continue
        _copy_verified(source_of(ref.blob_sha256), target, ref.blob_sha256)
        counts["copied"] += 1
    return counts


def check_embeds(vault_root: Path, note_text: str) -> list[str]:
    """List the embeds in a note whose file isn't in the vault.

    Args:
        vault_root: The vault folder.
        note_text: A rendered note.

    Returns:
        Broken embed targets, in order of appearance (empty when all resolve).
    """
    root = vault_root.resolve()
    broken: list[str] = []
    for match in _EMBED_RE.finditer(note_text):
        target = match.group(1).strip()
        path = (root / target).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            broken.append(target)
    return broken


def media_counts(refs: Mapping[str, list[MediaRef]]) -> dict[str, int]:
    """Return availability state -> count over some notes' media uses."""
    counts: dict[str, int] = {}
    for uses in refs.values():
        for ref in uses:
            counts[ref.availability] = counts.get(ref.availability, 0) + 1
    return dict(sorted(counts.items()))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy_verified(source: Path, target: Path, blob_sha256: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(dir=target.parent, prefix=".ke-", suffix=".tmp")
    try:
        digest = hashlib.sha256()
        with os.fdopen(handle, "wb") as out, source.open("rb") as src:
            for chunk in iter(lambda: src.read(1 << 20), b""):
                digest.update(chunk)
                out.write(chunk)
        if digest.hexdigest() != blob_sha256:
            # Name the fingerprint, never the path: it can hold a private name.
            raise ValueError(f"blob {blob_sha256[:12]} does not match its fingerprint")
        os.replace(temp_name, target)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise
