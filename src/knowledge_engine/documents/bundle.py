"""Project bundles: one project's notes, records and evidence in one ZIP (DOC-007, DOC-008).

``export_bundle`` writes, for one **approved** project:

* ``manifest.json``: the bundle format, the project's ID and name, the
  taxonomy version, the engine version, counts, and the SHA-256 of every
  other member;
* ``records.jsonl``: one line per record the project master shows, with
  its standing, the record as stored and each evidence span with its
  quote (the cited words only, never the whole chat);
* the project master and the knowledge note of every chat it draws on, at
  their vault paths, so the wikilinks between them still resolve;
* with ``with_transcripts`` only, those chats' full transcripts.

The same workspace gives a byte-identical ZIP: members are written in a
fixed order with a fixed timestamp, so a bundle's own hash says whether
anything changed.

``verify_bundle`` and ``show_bundle`` read a bundle as **untrusted input**:
member names must pass the importer's ``safe_member_name`` check; member
count, each member's size and the unpacked total stay inside the OPS-002
limits (members are hashed as a stream, and only the manifest and records
are held); a damaged or encrypted member is a problem, not a crash; every
member must match its manifest hash; and every quote must match its own
hash. Problems name members by a hash of the path, never the path. Nothing in a
bundle is ever imported into a workspace: its records were checked
against another workspace's sources, not this one's.

Talking points:
    - "A bundle is a project you can hand to someone: the notes, the
      claims and the exact words behind each one, in one file."
    - "Checking a bundle never trusts it: every file and every quote is
      re-hashed, and a bad name or an oversized file is refused."
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import tempfile
import zipfile
import zlib
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine import __version__
from knowledge_engine.documents.model import DocumentKind, build_document, chats_of
from knowledge_engine.documents.notes import conversation_note, knowledge_path
from knowledge_engine.documents.render import project_master, project_path
from knowledge_engine.extraction.records import KnowledgeRecord, RecordType, Trust
from knowledge_engine.extraction.store import KnowledgeRecordRow
from knowledge_engine.graph.offsets import quote_hash
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.ingestion.source import safe_member_name, sha256_of
from knowledge_engine.reconciliation.projection import Status
from knowledge_engine.rendering.markdown import render_note
from knowledge_engine.rendering.transcript import (
    load_conversation,
    transcript_model,
    transcript_path,
)
from knowledge_engine.retrieval.citations import Citation, quote, resolve
from knowledge_engine.settings import Limits
from knowledge_engine.taxonomy.registry import ProjectRow, TaxonomyRegistry, TermStatus

BUNDLE_FORMAT = "bundle-v1"
MANIFEST = "manifest.json"
RECORDS = "records.jsonl"
# ZIP's earliest date: a fixed stamp keeps the archive byte-identical.
_STAMP = (1980, 1, 1, 0, 0, 0)


class BundleError(ValueError):
    """The bundle can't be written (unknown project, or an unsafe target)."""


@dataclass(frozen=True)
class BundleSummary:
    """What an export wrote (counts only: member paths hold chat titles)."""

    path: Path
    records: int
    chats: int
    transcripts: int
    sha256: str


def _project(session: Session, project_id: str) -> ProjectRow:
    row = session.get(ProjectRow, project_id)
    if row is None or row.status != TermStatus.APPROVED.value:
        raise BundleError("no approved project with that ID")
    return row


def _record_lines(session: Session, project_id: str) -> tuple[list[str], list[str]]:
    document = build_document(session, DocumentKind.PROJECT, project_id)
    standing = {item.record_id: item for s in document.sections for item in s.items}
    lines = []
    for record_id in document.record_ids:
        row = session.get(KnowledgeRecordRow, record_id)
        if row is None:
            continue
        record = KnowledgeRecord.model_validate_json(row.record_json)
        quotes = []
        for ref in record.evidence:
            found = resolve(
                session, ref.revision_id, ref.start, ref.end, ref.quote_sha256, actor=ref.actor
            )
            if isinstance(found, Citation):
                text, problem = quote(session, found), None
            else:
                text, problem = None, found.problem.value
            quotes.append({**ref.model_dump(mode="json"), "text": text, "problem": problem})
        item = standing.get(record_id)
        lines.append(
            json.dumps(
                {
                    "record_id": record_id,
                    "record_type": item.record_type if item else record.record_type.value,
                    "status": item.status if item else "unknown",
                    "record": json.loads(record.model_dump_json()),
                    "quotes": quotes,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    chats = sorted(set(chats_of(session, list(document.revision_ids)).values()))
    return lines, chats


def bundle_members(
    session: Session, project_id: str, *, with_transcripts: bool = False
) -> dict[str, bytes]:
    """Every member of the project's bundle, by its path in the ZIP. Reads only.

    Raises:
        BundleError: No approved project has that ID.
    """
    project = _project(session, project_id)
    registry = TaxonomyRegistry(session)
    versions = registry.versions()
    taxonomy = registry.snapshot(versions[-1]) if versions else None
    lines, chats = _record_lines(session, project_id)
    members: dict[str, bytes] = {
        RECORDS: "".join(f"{line}\n" for line in lines).encode("utf-8"),
        project_path(project_id).as_posix(): render_note(
            project_master(session, project_id)
        ).encode("utf-8"),
    }
    transcripts = 0
    for conversation_id in chats:
        title = session.scalar(
            select(ConversationRow.title).where(ConversationRow.conversation_id == conversation_id)
        )
        note = conversation_note(session, conversation_id, taxonomy=taxonomy)
        members[knowledge_path(conversation_id, title).as_posix()] = render_note(note.model).encode(
            "utf-8"
        )
        if with_transcripts:
            chat = load_conversation(session, conversation_id)
            members[transcript_path(conversation_id, title).as_posix()] = render_note(
                transcript_model(chat)
            ).encode("utf-8")
            transcripts += 1
    manifest = {
        "format": BUNDLE_FORMAT,
        "project_id": project_id,
        "project_name": project.name,
        "taxonomy_version": taxonomy.version if taxonomy else None,
        "engine_version": __version__,
        "counts": {"records": len(lines), "chats": len(chats), "transcripts": transcripts},
        "members": {name: sha256_of(data) for name, data in sorted(members.items())},
    }
    members[MANIFEST] = json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8")
    return members


def _zip_bytes(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        # The manifest first, so a reader meets the rules before the content.
        for name in [MANIFEST, *sorted(n for n in members if n != MANIFEST)]:
            info = zipfile.ZipInfo(name, date_time=_STAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, members[name])
    return buffer.getvalue()


def export_bundle(
    session: Session, project_id: str, target: Path, *, with_transcripts: bool = False
) -> BundleSummary:
    """Write the project's bundle to ``target`` (a ``.zip`` file), replacing it whole.

    The file is written beside ``target`` and moved into place, so nothing
    else is touched and a reader never sees half a bundle.

    Raises:
        BundleError: Unknown or unapproved project, a target that isn't a
            ``.zip`` path, is a link or a folder, or whose folder is missing.
    """
    if target.suffix.lower() != ".zip":
        raise BundleError("the bundle must be a .zip file")
    if target.is_symlink() or target.is_dir():
        raise BundleError("the target is a link or a folder")
    if not target.parent.is_dir():
        raise BundleError("the target's folder does not exist")
    members = bundle_members(session, project_id, with_transcripts=with_transcripts)
    data = _zip_bytes(members)
    # A fresh, exclusively created temp name: a planted link can't redirect the write.
    handle, temp = tempfile.mkstemp(prefix=".bundle-", suffix=".partial", dir=target.parent)
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(data)
        os.replace(temp, target)
    except BaseException:
        Path(temp).unlink(missing_ok=True)
        raise
    manifest = json.loads(members[MANIFEST])
    counts = manifest["counts"]
    return BundleSummary(
        target, counts["records"], counts["chats"], counts["transcripts"], sha256_of(data)
    )


@dataclass
class BundleCheck:
    """What ``verify_bundle`` found. ``problems`` names each one (no content)."""

    problems: list[str] = field(default_factory=list)
    members: int = 0
    records: int = 0
    by_type: Counter[str] = field(default_factory=Counter)
    by_status: Counter[str] = field(default_factory=Counter)

    @property
    def ok(self) -> bool:
        """No problem found."""
        return not self.problems


# Members whose bytes are kept for reading; every other member is only hashed.
_KEPT = frozenset({MANIFEST, RECORDS})
_CHUNK = 1 << 20
_STATUSES = frozenset(
    {s.value for s in Status} | {t.value for t in Trust} | {"accepted", "rejected", "open"}
)
_TYPES = frozenset(t.value for t in RecordType)


def member_label(name: str) -> str:
    """How a problem names a member: its path holds a chat title, so a short hash."""
    if name in _KEPT:
        return name
    return "member " + hashlib.sha256(name.encode("utf-8", "replace")).hexdigest()[:12]


def _read(
    path: Path, limits: Limits, check: BundleCheck
) -> tuple[dict[str, str], dict[str, bytes], set[str]] | None:
    """Hash every member as a stream; keep only the manifest and records.

    Returns the hashes, the kept bytes and the names already reported.
    """
    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile):
        check.problems.append("not a readable ZIP file")
        return None
    hashes: dict[str, str] = {}
    kept: dict[str, bytes] = {}
    reported: set[str] = set()
    total = 0
    with archive:
        infos = archive.infolist()
        if len(infos) > limits.max_archive_entries:
            check.problems.append(f"too many members ({len(infos)})")
            return None
        # Names and declared sizes first, so every one of those is reported
        # even if the unpacked total later stops the reading.
        readable, seen = [], set()
        for info in infos:
            label = member_label(info.filename)
            reported.add(info.filename)
            if not safe_member_name(info.filename):
                check.problems.append(f"unsafe member name: {label}")
            elif info.file_size > limits.max_source_file_bytes:
                check.problems.append(f"member too large: {label}")
            elif info.filename in seen:
                check.problems.append(f"member listed twice: {label}")
            else:
                readable.append(info)
            seen.add(info.filename)
        for info in readable:
            label = member_label(info.filename)
            digest, held = hashlib.sha256(), bytearray()
            try:
                with archive.open(info) as stream:
                    while chunk := stream.read(_CHUNK):
                        total += len(chunk)
                        if total > limits.max_source_file_bytes:
                            check.problems.append("bundle too large when unpacked")
                            return None
                        digest.update(chunk)
                        if info.filename in _KEPT:
                            held += chunk
            except (zipfile.BadZipFile, zlib.error, EOFError):
                check.problems.append(f"member damaged: {label}")
                continue
            except RuntimeError:  # zipfile's error for an encrypted member
                check.problems.append(f"member encrypted: {label}")
                continue
            except NotImplementedError:
                check.problems.append(f"member uses unsupported compression: {label}")
                continue
            reported.discard(info.filename)
            hashes[info.filename] = digest.hexdigest()
            if info.filename in _KEPT:
                kept[info.filename] = bytes(held)
    return hashes, kept, reported


def verify_bundle(path: Path, limits: Limits | None = None) -> BundleCheck:
    """Check a bundle without trusting it: names, sizes, hashes and every quote.

    Problems name a member by a short hash of its path (``member_label``)
    or a record by its ID, never by path or text: paths hold chat titles.
    """
    limits = limits or Limits()
    check = BundleCheck()
    read = _read(path, limits, check)
    if read is None:
        return check
    hashes, kept, reported = read
    check.members = len(hashes)
    try:
        manifest: Any = json.loads(kept[MANIFEST])
    except (KeyError, ValueError):
        check.problems.append("no readable manifest.json")
        return check
    if not isinstance(manifest, dict):
        check.problems.append("manifest.json is not an object")
        return check
    if manifest.get("format") != BUNDLE_FORMAT:
        check.problems.append("unknown bundle format")
        return check
    listed = manifest.get("members")
    if not isinstance(listed, dict) or not all(isinstance(v, str) for v in listed.values()):
        check.problems.append("manifest.json members is not a name-to-hash map")
        return check
    if RECORDS not in hashes and RECORDS not in reported:
        check.problems.append(f"missing member: {RECORDS}")
    for name in sorted(set(listed) | (set(hashes) - {MANIFEST})):
        label = member_label(name)
        if name not in hashes:
            if name != RECORDS and name not in reported:
                check.problems.append(f"missing member: {label}")
        elif name not in listed:
            check.problems.append(f"member not in the manifest: {label}")
        elif hashes[name] != listed[name]:
            check.problems.append(f"member changed: {label}")
    _check_records(kept.get(RECORDS, b""), check)
    return check


def _check_records(data: bytes, check: BundleCheck) -> None:
    for number, line in enumerate(data.decode("utf-8", "replace").splitlines(), start=1):
        try:
            entry = json.loads(line)
            record_id = str(entry["record_id"])
            quotes = list(entry["quotes"])
        except (ValueError, KeyError, TypeError):
            check.problems.append(f"records.jsonl line {number} is not a record")
            continue
        check.records += 1
        # Only known words are counted by name: the bundle is untrusted text.
        kind, status = entry.get("record_type"), entry.get("status")
        check.by_type[kind if kind in _TYPES else "other"] += 1
        check.by_status[status if status in _STATUSES else "other"] += 1
        for cited in quotes:
            if not isinstance(cited, dict):
                check.problems.append(f"a quote is not an object: {record_id}")
                continue
            text = cited.get("text")
            if text is None:
                if cited.get("problem") is None:
                    check.problems.append(f"a quote has no text and no problem: {record_id}")
                continue  # not resolvable when exported; its problem is recorded
            if not isinstance(text, str) or quote_hash(text) != cited.get("quote_sha256"):
                check.problems.append(f"quote does not match its hash: {record_id}")


def show_bundle(path: Path, limits: Limits | None = None) -> BundleCheck:
    """Counts by record type and status (the same reading as ``verify_bundle``)."""
    return verify_bundle(path, limits)
