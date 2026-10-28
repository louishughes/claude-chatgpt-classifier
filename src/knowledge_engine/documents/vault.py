"""The managed vault: safe export and incremental regeneration (DOC-006).

``sync_vault`` writes every note the engine owns into an Obsidian vault:
source transcripts (``Sources/``), chat knowledge notes (``Knowledge/``),
project masters (``Projects/``) and, given a taxonomy, topic masters
(``Topics/``), video notes (``Videos/``) and the account registry with one
note per account (``Accounts/``), plus the images they embed
(``_attachments/``).

Three promises make it safe to run again and again on a vault people use:

* **Your notes are never touched.** The engine only writes paths listed in
  its manifest (``.ke/manifest.json``). A file of yours at a path it wants
  is reported as ``occupied`` and left alone.
* **Your additions are kept.** Every managed note ends with a marker line.
  Anything written below it is copied into each new version. Imported
  text can't fake the marker, because ``%%`` in chat text is escaped.
* **Hand edits above the marker are not overwritten.** The manifest holds
  the fingerprint of what the engine last wrote above the marker. If the
  file no longer matches it, the note is reported as a ``conflict`` and
  kept as it is. Delete it (or undo the edit) to let the engine rebuild it.

A rebuild where nothing changed writes nothing: every note and image is
compared byte for byte first. A managed note the engine no longer makes
(say, a chat's title changed, so its file name did) is removed only if
nobody edited it; otherwise it is kept and reported.

Talking points:
    - "The vault is shared between me and the engine: it only rewrites
      files it made, keeps whatever I add below the line, and refuses to
      overwrite a note I've edited."
    - "Running it twice in a row writes nothing the second time."
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.documents.model import DocumentKind, build_all
from knowledge_engine.documents.notes import (
    conversation_note,
    knowledge_path,
    topic_master,
    topic_path,
)
from knowledge_engine.documents.registries import (
    account_note,
    account_path,
    account_registry_note,
    registry_path,
    video_note,
    video_path,
)
from knowledge_engine.documents.render import project_master, project_path
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.links.social_store import SocialAccountRow, ambiguous_handles
from knowledge_engine.links.youtube import YouTubeVideoRow
from knowledge_engine.rendering.markdown import render_note, safe_relative_path, write_note
from knowledge_engine.rendering.media import (
    MediaRef,
    blob_sources,
    check_embeds,
    export_attachments,
)
from knowledge_engine.rendering.transcript import (
    load_conversation,
    transcript_model,
    transcript_path,
)
from knowledge_engine.taxonomy.registry import TaxonomySnapshot, UnknownTermError

VAULT_VERSION = "doc-006-v1"
MARKER = "%% ke:manual (write below this line; it is kept on every rebuild) %%"
MANIFEST = safe_relative_path(".ke", "manifest.json")
_SPLIT = f"\n{MARKER}\n"


@dataclass(frozen=True)
class PlannedNote:
    """One note the engine owns: where it goes, what it says, what it embeds."""

    path: PurePosixPath
    kind: str  # transcript | knowledge | project | topic | video | accounts | account
    text: str
    media: tuple[MediaRef, ...] = ()


def plan_vault(session: Session, *, taxonomy: TaxonomySnapshot | None = None) -> list[PlannedNote]:
    """Every managed note, rendered but not written. Reads only."""
    return sorted(_planned(session, taxonomy), key=lambda n: n.path.as_posix())


def _planned(session: Session, taxonomy: TaxonomySnapshot | None) -> Iterator[PlannedNote]:
    for conversation_id, title in session.execute(
        select(ConversationRow.conversation_id, ConversationRow.title).order_by(
            ConversationRow.conversation_id
        )
    ):
        chat = load_conversation(session, conversation_id)
        uses = tuple(ref for refs in chat.media.values() for ref in refs)
        yield PlannedNote(
            transcript_path(conversation_id, title),
            "transcript",
            render_note(transcript_model(chat)),
            uses,
        )
        note = conversation_note(session, conversation_id, taxonomy=taxonomy)
        yield PlannedNote(
            knowledge_path(conversation_id, title),
            "knowledge",
            render_note(note.model),
            note.media,
        )
    documents = build_all(session)
    for document in documents:
        if document.kind is DocumentKind.PROJECT:
            yield PlannedNote(
                project_path(document.subject_id),
                "project",
                render_note(project_master(session, document.subject_id)),
            )
        elif document.kind is DocumentKind.TOPIC and taxonomy is not None:
            try:
                path = topic_path(taxonomy, document.subject_id)
            except UnknownTermError:
                continue  # tagged with a term this version doesn't approve
            yield PlannedNote(
                path, "topic", render_note(topic_master(session, document.subject_id, taxonomy))
            )
    for video_id in session.scalars(
        select(YouTubeVideoRow.video_id).order_by(YouTubeVideoRow.video_id)
    ):
        yield PlannedNote(video_path(video_id), "video", render_note(video_note(session, video_id)))
    accounts = session.scalars(
        select(SocialAccountRow.account_id).order_by(SocialAccountRow.account_id)
    ).all()
    if accounts or ambiguous_handles(session):  # no registry note for an archive without any
        yield PlannedNote(registry_path(), "accounts", render_note(account_registry_note(session)))
    for account_id in accounts:
        yield PlannedNote(
            account_path(account_id), "account", render_note(account_note(session, account_id))
        )


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def split_manual(text: str) -> tuple[str, str] | None:
    """(engine part, your part) of a managed note, or None if the marker is gone."""
    at = text.find(_SPLIT)
    if at < 0:
        return None
    return text[: at + 1], text[at + len(_SPLIT) :]


@dataclass
class SyncReport:
    """What ``sync_vault`` did (paths can hold private titles: counts are safe to print)."""

    created: list[str] = field(default_factory=list)
    written: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)  # edited above the marker: kept
    occupied: list[str] = field(default_factory=list)  # someone else's file: kept
    removed: list[str] = field(default_factory=list)  # no longer made, unedited
    kept_stale: list[str] = field(default_factory=list)  # no longer made, but edited
    broken_embeds: dict[str, list[str]] = field(default_factory=dict)
    attachments: dict[str, int] = field(default_factory=dict)

    def counts(self) -> dict[str, int]:
        """Counts only, for logs and the CLI."""
        return {
            "created": len(self.created),
            "written": len(self.written),
            "unchanged": len(self.unchanged),
            "conflicts": len(self.conflicts),
            "occupied": len(self.occupied),
            "removed": len(self.removed),
            "kept_stale": len(self.kept_stale),
            "broken_embeds": sum(len(v) for v in self.broken_embeds.values()),
            **{f"attachments_{k}": v for k, v in sorted(self.attachments.items())},
        }


def _load_manifest(vault_root: Path) -> dict[str, dict[str, str]]:
    path = vault_root / Path(*MANIFEST.parts)
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    notes: dict[str, dict[str, str]] = data.get("notes", {})
    return notes


def sync_vault(
    session: Session,
    vault_root: Path,
    store_root: Path,
    *,
    taxonomy: TaxonomySnapshot | None = None,
) -> SyncReport:
    """Bring the vault's managed notes and images up to date, safely.

    Args:
        session: A read session.
        vault_root: The vault folder (created if missing).
        store_root: The workspace's content-addressed store (image bytes).
        taxonomy: The version to label and build topics under, if any.

    Returns:
        What was created, rewritten, left alone and why.
    """
    report = SyncReport()
    manifest = _load_manifest(vault_root)
    planned = plan_vault(session, taxonomy=taxonomy)
    report.attachments = export_attachments(
        [ref for note in planned for ref in note.media],
        vault_root,
        blob_sources(session, store_root),
    )
    new_manifest: dict[str, dict[str, str]] = {}
    for note in planned:
        key = note.path.as_posix()
        text = note.text if note.text.endswith("\n") else note.text + "\n"  # marker on its own line
        target = vault_root / Path(*note.path.parts)
        entry = {"kind": note.kind, "sha256": _sha(text)}
        if not target.exists():
            write_note(vault_root, note.path, text + MARKER + "\n")
            report.created.append(key)
            new_manifest[key] = entry
        elif key not in manifest:
            report.occupied.append(key)  # not ours: never touched, never claimed
            continue
        else:
            parts = split_manual(target.read_text(encoding="utf-8"))
            if parts is None or _sha(parts[0]) != manifest[key]["sha256"]:
                report.conflicts.append(key)
                new_manifest[key] = manifest[key]  # still ours; still the old fingerprint
                continue
            outcome = write_note(vault_root, note.path, text + MARKER + "\n" + parts[1])
            (report.written if outcome == "written" else report.unchanged).append(key)
            new_manifest[key] = entry
        broken = check_embeds(vault_root, text)
        if broken:
            report.broken_embeds[key] = broken
    for key in sorted(set(manifest) - set(new_manifest)):
        target = vault_root / Path(*PurePosixPath(key).parts)
        if not target.exists():
            continue
        parts = split_manual(target.read_text(encoding="utf-8"))
        if parts is not None and _sha(parts[0]) == manifest[key]["sha256"] and not parts[1]:
            target.unlink()
            report.removed.append(key)
        else:
            report.kept_stale.append(key)  # edited: it's the user's now, unmanaged
    body = json.dumps(
        {"generator": VAULT_VERSION, "notes": dict(sorted(new_manifest.items()))},
        indent=1,
        sort_keys=True,
        ensure_ascii=False,
    )
    write_note(vault_root, MANIFEST, body + "\n")
    return report
