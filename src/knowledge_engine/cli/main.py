"""``ke``: the command-line entry point, with fixed output and exit-code contracts.

Every command returns a ``CommandResult``. The same result is printed either
as readable text or, with ``--json``, as one JSON object with sorted keys, so
scripts and tests can rely on its exact shape. Exit codes are a closed list
(``ExitCode``), so a script can tell "you typed it wrong" from "the config is
invalid" from "not built yet" without reading messages.

A command that isn't built yet exits with ``NOT_IMPLEMENTED`` and names
its ticket, so the interface can be tried and tested early.
Nothing here prints raw-folder paths, conversation text or secrets: ``status``
shows counts and labels only.

Talking points:
    - "My CLI has a contract: text for people, sorted JSON for scripts, and a
      fixed table of exit codes."
    - "Unbuilt commands exist as honest placeholders that say so and exit with
      their own code."
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from enum import IntEnum
from pathlib import Path
from typing import Any, NoReturn

from pydantic import ValidationError

from knowledge_engine import __version__
from knowledge_engine.settings import Capability, Settings, load_settings

JSON_SCHEMA_VERSION = 1


class ExitCode(IntEnum):
    """Process exit codes. Values are part of the public contract; never renumber."""

    OK = 0
    ERROR = 1  # unexpected failure
    USAGE = 2  # bad arguments (also argparse's own code)
    CONFIG = 3  # settings file or environment invalid
    NOT_IMPLEMENTED = 4  # command exists but isn't built yet
    BLOCKED = 5  # refused by policy, e.g. an outbound switch is off


@dataclass
class CommandResult:
    """What a command hands back to be printed.

    Attributes:
        command: The command name, e.g. ``"status"``.
        exit_code: The process exit code.
        data: Structured output (JSON-serialisable).
        message: One human-readable line.
        error_code: Short machine-readable error name when not OK.
    """

    command: str
    exit_code: ExitCode = ExitCode.OK
    data: dict[str, Any] = field(default_factory=dict)
    message: str = ""
    error_code: str | None = None

    def as_json(self) -> str:
        """Render the stable JSON form (one object, sorted keys)."""
        payload: dict[str, Any] = {
            "schema_version": JSON_SCHEMA_VERSION,
            "command": self.command,
            "ok": self.exit_code is ExitCode.OK,
            "exit_code": int(self.exit_code),
            "data": self.data,
            "message": self.message,
            "error": None if self.error_code is None else {"code": self.error_code},
        }
        return json.dumps(payload, sort_keys=True, ensure_ascii=False)

    def as_text(self) -> str:
        """Render the human-readable form."""
        lines = [self.message] if self.message else []
        lines += [f"  {key}: {_text_value(value)}" for key, value in sorted(self.data.items())]
        return "\n".join(lines)


def _text_value(value: Any, *, nested: bool = False) -> str:
    if isinstance(value, dict):
        text = ", ".join(f"{k}={_text_value(v, nested=True)}" for k, v in sorted(value.items()))
        # Brackets keep a dict inside a dict readable: a=(b=1, c=2), d=3.
        return (f"({text})" if nested else text) if text else "-"
    if isinstance(value, list):
        return ", ".join(_text_value(v, nested=True) for v in value) or "-"
    return str(value)


class _UsageError(Exception):
    """Raised by the parser instead of exiting, so JSON mode can report it."""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise _UsageError(message)


# ---------------------------------------------------------------- commands


def _status(settings: Settings, _args: argparse.Namespace) -> CommandResult:
    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
    from knowledge_engine.infrastructure.migrations import current_revision, head_revision

    db = database_path(settings)
    revision: str | None = None
    if db.exists():
        engine = create_sqlite_engine(db)
        try:
            revision = current_revision(engine)
        finally:
            engine.dispose()
    latest = head_revision()
    data: dict[str, Any] = {
        "version": __version__,
        "workspace": str(settings.workspace_root),
        "database": {
            "exists": db.exists(),
            "revision": revision or "none",
            "latest": latest,
        },
        # Labels and counts only: raw folder paths are private and never printed.
        "raw_roots": [root.account_namespace for root in settings.raw_roots],
        "media_storage_mode": settings.media_storage_mode,
        "egress_enabled": [c.value for c in Capability if settings.egress.allows(c)],
        "api_key_configured": settings.anthropic_api_key is not None,
    }
    up_to_date = revision == latest
    message = "Knowledge Engine status" + ("" if up_to_date else " (run `ke db upgrade`)")
    return CommandResult("status", data=data, message=message)


def _db_upgrade(settings: Settings, args: argparse.Namespace) -> CommandResult:
    from knowledge_engine.infrastructure.backup import BackupError
    from knowledge_engine.infrastructure.upgrade import (
        SchemaMismatchError,
        default_backup_root,
        safe_upgrade,
    )

    root = None if args.no_backup else (args.backup_to or default_backup_root(settings))
    try:
        data = safe_upgrade(settings, root)
    except (SchemaMismatchError, BackupError) as error:
        return CommandResult(
            "db upgrade", ExitCode.ERROR, message=str(error), error_code="upgrade_refused"
        )
    if not data["changed"]:
        message = "Database is up to date"
    elif data["backup"]:
        message = f"Database upgraded (backup {data['backup']} taken first)"
    else:
        message = "Database upgraded"
    return CommandResult("db upgrade", data=data, message=message)


def _inventory(settings: Settings, args: argparse.Namespace) -> CommandResult:
    from knowledge_engine.ingestion.inventory import inventory

    limit = max(settings.limits.max_source_file_bytes, settings.limits.max_media_file_bytes)
    try:
        report = inventory(args.root, max_bytes=limit)
    except FileNotFoundError:
        return CommandResult(
            "raw inventory", ExitCode.USAGE, message="raw root not found", error_code="not_found"
        )
    data = report.to_dict(show_names=args.show_names)
    if not args.json:
        # The per-file rows are for scripts; people get the summary.
        data.pop("entries")
    if not report.unchanged:
        return CommandResult(
            "raw inventory",
            ExitCode.ERROR,
            data=data,
            message="the raw root changed during the inventory; do not trust this report",
            error_code="raw_changed",
        )
    return CommandResult("raw inventory", data=data, message="Raw source inventory (read-only)")


def _imports_report(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """Print a stored import report. Reads the ledger only; recomputes nothing."""
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from knowledge_engine.importer.ledger import ImportBatchRow
    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path

    db = database_path(settings)
    if not db.exists():
        return CommandResult(
            "imports report", ExitCode.ERROR, message="no imports yet", error_code="no_imports"
        )
    query = select(ImportBatchRow)
    if args.which == "latest":
        query = query.order_by(ImportBatchRow.started_at.desc()).limit(1)
    else:
        query = query.where(ImportBatchRow.import_id == args.which)
    engine = create_sqlite_engine(db)
    try:
        with Session(engine) as session:
            batch = session.scalars(query).first()
            if batch is not None:
                session.expunge(batch)
    finally:
        engine.dispose()
    if batch is None:
        return CommandResult(
            "imports report", ExitCode.ERROR, message="no such import", error_code="not_found"
        )
    data: dict[str, Any] = {
        "import_id": batch.import_id,
        "status": batch.status,
        "started_at": batch.started_at.isoformat(),
        "finished_at": batch.finished_at.isoformat() if batch.finished_at else None,
        **json.loads(batch.counts_json or "{}"),
        "warnings": json.loads(batch.warnings_json or "{}"),
    }
    message = f"Import report ({batch.status})"
    timings = data.get("timings") or {}
    if timings:
        message += "\nHow long it took: " + ", ".join(
            f"{stage.replace('_', ' ')} {seconds:.3f}s" for stage, seconds in timings.items()
        )
    return CommandResult("imports report", data=data, message=message)


def _imports_candidates(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """List identity candidates, or decide one (IMP-009). Hashes and positions only, no text."""
    from sqlalchemy.orm import Session

    from knowledge_engine.importer.identity import (
        CandidateAction,
        CandidateDecidedError,
        decide,
        list_candidates,
    )
    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path

    reviewing = getattr(args, "candidates_command", None) == "review"
    name = "imports candidates review" if reviewing else "imports candidates"
    db = database_path(settings)
    if not db.exists():
        return CommandResult(
            name, ExitCode.ERROR, message="no imports yet", error_code="no_imports"
        )
    engine = create_sqlite_engine(db)
    try:
        with Session(engine) as session:
            if reviewing:
                if not args.reviewer.strip() or len(args.reviewer) > 100:
                    return CommandResult(
                        name,
                        ExitCode.USAGE,
                        message="--reviewer needs a name of 1 to 100 characters",
                        error_code="bad_reviewer",
                    )
                try:
                    row = decide(
                        session,
                        args.candidate,
                        CandidateAction(args.decision),
                        reviewer=args.reviewer,
                    )
                except KeyError:
                    return CommandResult(
                        name,
                        ExitCode.USAGE,
                        message="no such candidate",
                        error_code="unknown_candidate",
                    )
                except CandidateDecidedError as error:
                    return CommandResult(
                        name, ExitCode.ERROR, message=str(error), error_code="already_decided"
                    )
                session.commit()
                data = _candidate_data(row)
                message = (
                    "Accepted: the next import of that export brings the chat in as "
                    f"{row.assigned_conversation_id}"
                    if row.status == "accepted"
                    else "Rejected: later imports leave the chat out"
                )
                return CommandResult(name, data=data, message=message)
            rows = list_candidates(session, status=args.status)
            listed = [_candidate_data(row) for row in rows]
    finally:
        engine.dispose()
    waiting = sum(1 for c in listed if c["status"] == "review_required")
    return CommandResult(
        name,
        data={"candidates": listed},
        message=f"{len(listed)} candidate(s), {waiting} waiting for review",
    )


def _candidate_data(row: Any) -> dict[str, Any]:
    # IDs, hashes and positions only: a candidate's title or words never print.
    return {
        "candidate_id": row.candidate_id,
        "reason": row.reason,
        "status": row.status,
        "account_namespace": row.account_namespace,
        "snapshot_id": row.snapshot_id,
        "source_index": row.source_index,
        "conversation_hash": row.conversation_hash,
        "existing_conversation_id": row.existing_conversation_id,
        "assigned_conversation_id": row.assigned_conversation_id,
        "decided_by": row.decided_by,
        "decided_at": row.decided_at.isoformat() if row.decided_at else None,
        "first_import_id": row.first_import_id,
    }


def _import(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """Import one export and print its report (ING-003, wired in UI-002)."""
    from knowledge_engine.importer import import_source
    from knowledge_engine.importer.failures import describe_failure

    if not args.source.exists():
        return CommandResult(
            "import",
            ExitCode.ERROR,
            message="that file or folder doesn't exist",
            error_code="not_found",
        )
    account = args.account or settings.account_for(args.source)
    try:
        report = import_source(
            args.source,
            account,
            format=None if args.format == "auto" else args.format,
            settings=settings,
            full_export=not args.partial,
        )
    except Exception as error:  # noqa: BLE001 - known errors become plain messages
        failure = describe_failure(error)
        if failure is None:
            raise
        return CommandResult(
            "import", ExitCode.ERROR, message=failure.message, error_code=failure.code
        )
    data = report.to_dict()
    code = ExitCode.OK if report.status.value == "succeeded" else ExitCode.ERROR
    return CommandResult(
        "import",
        code,
        data=data,
        message=f"Import {report.status.value}: see `ke imports report {report.import_id}`",
        error_code=None if code == ExitCode.OK else report.status.value,
    )


def _watch(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """Import exports as they land in a folder, once each (INT-003)."""
    import time

    from sqlalchemy.orm import Session

    from knowledge_engine.importer import import_source
    from knowledge_engine.importer.failures import describe_failure
    from knowledge_engine.importer.report import ImportReport
    from knowledge_engine.importer.watch import FolderWatcher, TickReport, WatchError
    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path

    def importer(source: Path) -> ImportReport:
        account = args.account or settings.account_for(source)
        return import_source(source, account, settings=settings, full_export=not args.partial)

    def describe(error: BaseException) -> str | None:
        failure = describe_failure(error) if isinstance(error, Exception) else None
        return failure.code if failure else None

    stages = {}
    if args.vault is not None:
        vault: Path = args.vault

        def sync() -> dict[str, int]:
            from knowledge_engine.documents.vault import sync_vault

            engine = create_sqlite_engine(database_path(settings))
            try:
                with Session(engine) as session:
                    return sync_vault(session, vault, settings.workspace_root / "archive").counts()
            finally:
                engine.dispose()

        stages["vault"] = sync
    try:
        watcher = FolderWatcher(
            settings, args.folder, importer, settle_s=args.settle, stages=stages, describe=describe
        )
    except WatchError as error:
        return CommandResult("watch", ExitCode.USAGE, message=str(error), error_code="bad_folder")

    total = TickReport()

    def add(tick: TickReport) -> None:
        total.unchanged, total.waiting = tick.unchanged, tick.waiting
        total.same_contents += tick.same_contents
        total.imported += tick.imported
        total.changed_revisions += tick.changed_revisions
        for code, count in tick.failed.items():
            total.failed[code] = total.failed.get(code, 0) + count
        total.stages.update(tick.stages)

    add(watcher.tick())
    if args.once:
        # One pass still needs two looks, so a half-copied export waits.
        time.sleep(args.settle)
        add(watcher.tick())
    else:
        try:
            while True:
                time.sleep(args.interval)
                tick = watcher.tick()
                add(tick)
                if tick.busy and not args.json:
                    print(  # noqa: T201 - progress for a long-running command
                        f"imported {len(tick.imported)}, unchanged contents "
                        f"{tick.same_contents}, failed {sum(tick.failed.values())}",
                        flush=True,
                    )
        except KeyboardInterrupt:
            pass
    data = total.to_dict()
    return CommandResult(
        "watch",
        ExitCode.ERROR if total.failed else ExitCode.OK,
        data=data,
        message=(
            f"{data['imported']} imported, {total.unchanged} unchanged, "
            f"{total.same_contents} same contents, {total.waiting} still changing, "
            f"{sum(total.failed.values())} failed"
        ),
        error_code="import_failed" if total.failed else None,
    )


def _transcript_add(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """Attach a user-supplied transcript to a linked video (YTB-002)."""
    from sqlalchemy.orm import Session

    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
    from knowledge_engine.ingestion.transcripts import TranscriptFormat, TranscriptTooLargeError
    from knowledge_engine.links.video_transcripts import (
        UnknownVideoError,
        attach_user_transcript,
        read_file,
    )

    db = database_path(settings)
    if not db.exists():
        return CommandResult(
            "transcript add", ExitCode.ERROR, message="no imports yet", error_code="no_imports"
        )
    if not args.file.is_file():
        return CommandResult(
            "transcript add",
            ExitCode.ERROR,
            message="that file doesn't exist",
            error_code="not_found",
        )
    engine = create_sqlite_engine(db)
    try:
        with Session(engine) as session, session.begin():
            try:
                snapshot = attach_user_transcript(
                    session,
                    settings,
                    args.video,
                    read_file(args.file, settings),
                    format=None if args.format == "auto" else TranscriptFormat(args.format),
                    language=args.language,
                    source_url=args.source_url,
                    note=args.note,
                )
            except UnknownVideoError:
                return CommandResult(
                    "transcript add",
                    ExitCode.ERROR,
                    message="that video isn't linked in any imported chat",
                    error_code="unknown_video",
                )
            except TranscriptTooLargeError:
                return CommandResult(
                    "transcript add",
                    ExitCode.ERROR,
                    message="the file is over the size limit",
                    error_code="too_large",
                )
            data = _transcript_data(session, snapshot.transcript_id)
    finally:
        engine.dispose()
    return CommandResult("transcript add", data=data, message="Transcript attached")


def _transcript_fetch(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """Ask the YouTube Data API for a video's captions, if allowed (INT-002)."""
    from sqlalchemy.orm import Session

    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
    from knowledge_engine.ingestion.transcripts import TranscriptTooLargeError
    from knowledge_engine.links.video_transcripts import UnknownVideoError, request_transcript
    from knowledge_engine.links.youtube_captions import YouTubeCaptionsProvider

    name = "transcript fetch"
    db = database_path(settings)
    if not db.exists():
        return CommandResult(
            name, ExitCode.ERROR, message="no imports yet", error_code="no_imports"
        )
    if settings.youtube_access_token is None:
        return CommandResult(
            name,
            ExitCode.USAGE,
            message="set KE_YOUTUBE_ACCESS_TOKEN (an OAuth token for your YouTube account) first",
            error_code="no_token",
        )
    provider = YouTubeCaptionsProvider(settings.youtube_access_token, language=args.language)
    engine = create_sqlite_engine(db)
    try:
        with Session(engine) as session, session.begin():
            try:
                row = request_transcript(session, settings, args.video, provider)
            except UnknownVideoError:
                return CommandResult(
                    name,
                    ExitCode.ERROR,
                    message="that video isn't linked in any imported chat",
                    error_code="unknown_video",
                )
            except TranscriptTooLargeError:
                return CommandResult(
                    name,
                    ExitCode.ERROR,
                    message="the captions are over the size limit",
                    error_code="too_large",
                )
            data = {"status": row.status, "reason": row.last_error, "attempts": row.attempts}
            if row.transcript_id:
                data |= _transcript_data(session, row.transcript_id)
    finally:
        engine.dispose()
    return CommandResult(name, data=data, message=f"transcript: {data['status']}")


def _transcript_status(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """Show a video's transcript status and attached transcripts (counts only)."""
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
    from knowledge_engine.links.video_transcripts import (
        TranscriptAcquisitionRow,
        TranscriptSnapshotRow,
    )
    from knowledge_engine.links.youtube import YouTubeVideoRow

    db = database_path(settings)
    if not db.exists():
        return CommandResult(
            "transcript status", ExitCode.ERROR, message="no imports yet", error_code="no_imports"
        )
    engine = create_sqlite_engine(db)
    try:
        with Session(engine) as session:
            video = session.get(YouTubeVideoRow, args.video)
            if video is None:
                return CommandResult(
                    "transcript status",
                    ExitCode.ERROR,
                    message="that video isn't linked in any imported chat",
                    error_code="unknown_video",
                )
            acquisitions = session.scalars(
                select(TranscriptAcquisitionRow)
                .where(TranscriptAcquisitionRow.video_id == args.video)
                .order_by(TranscriptAcquisitionRow.method)
            ).all()
            snapshots = session.scalars(
                select(TranscriptSnapshotRow.transcript_id).where(
                    TranscriptSnapshotRow.video_id == args.video
                )
            ).all()
            data = {
                "video_id": video.video_id,
                "transcript_status": video.transcript_status,
                "acquisitions": [
                    {
                        "method": a.method,
                        "status": a.status,
                        "attempts": a.attempts,
                        "reason": a.last_error,
                    }
                    for a in acquisitions
                ],
                "transcripts": [_transcript_data(session, t) for t in snapshots],
            }
    finally:
        engine.dispose()
    return CommandResult("transcript status", data=data, message="Transcript status")


def _transcript_find(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """Find transcript lines; each hit names the moment and every chat citing the video."""
    from sqlalchemy.orm import Session

    from knowledge_engine.documents.registries import find_cues
    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path

    db = database_path(settings)
    if not db.exists():
        return CommandResult(
            "transcript find", ExitCode.ERROR, message="no imports yet", error_code="no_imports"
        )
    engine = create_sqlite_engine(db)
    try:
        with Session(engine) as session:
            hits = [
                {
                    "video_id": h.video_id,
                    "transcript_id": h.transcript_id,
                    "cue": h.ordinal,
                    "start_seconds": h.start_seconds,
                    "url": h.url,
                    "text": h.text,
                    "conversations": list(h.conversations),
                    "revisions": list(h.revisions),
                }
                for h in find_cues(session, args.words, limit=args.limit)
            ]
    finally:
        engine.dispose()
    return CommandResult(
        "transcript find", data={"hits": hits}, message=f"{len(hits)} transcript line(s)"
    )


def _transcript_data(session: Any, transcript_id: str) -> dict[str, Any]:
    from sqlalchemy import func, select

    from knowledge_engine.links.video_transcripts import TranscriptCueRow, TranscriptSnapshotRow

    snapshot = session.get(TranscriptSnapshotRow, transcript_id)
    cues = session.scalar(
        select(func.count()).where(TranscriptCueRow.transcript_id == transcript_id)
    )
    timed = session.scalar(
        select(func.count()).where(
            TranscriptCueRow.transcript_id == transcript_id, TranscriptCueRow.start_ms.is_not(None)
        )
    )
    return {
        "transcript_id": transcript_id,
        "video_id": snapshot.video_id,
        "format": snapshot.format,
        "language": snapshot.language,
        "file_sha256": snapshot.file_sha256,
        "cues": int(cues or 0),
        "timed_cues": int(timed or 0),
        "warnings": json.loads(snapshot.warnings_json),
    }


def _accounts(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """List the social account registry (SOC-002), or record a review (SOC-004)."""
    from sqlalchemy.orm import Session

    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
    from knowledge_engine.links.social_store import account_summaries, ambiguous_handles

    action = getattr(args, "accounts_command", None)
    name = f"accounts {action}" if action else "accounts"
    db = database_path(settings)
    if not db.exists():
        return CommandResult(
            name, ExitCode.ERROR, message="no imports yet", error_code="no_imports"
        )
    engine = create_sqlite_engine(db)
    try:
        with Session(engine) as session:
            if action is not None:
                return _accounts_review(session, name, args)
            if args.ambiguous:
                return CommandResult(
                    "accounts",
                    data={"ambiguous": ambiguous_handles(session)},
                    message="Bare @handles (no platform; linked only by `ke accounts link`)",
                )
            accounts_list = account_summaries(
                session, platform=args.platform, include_rejected=args.all
            )
    finally:
        engine.dispose()
    return CommandResult(
        "accounts", data={"accounts": accounts_list}, message="Social accounts (never contacted)"
    )


def _accounts_review(session: Any, name: str, args: argparse.Namespace) -> CommandResult:
    """Confirm, reject or link inside one transaction; the history is append-only."""
    from knowledge_engine.links.social_store import (
        AccountAction,
        AccountReviewError,
        link_mention,
        review_account,
    )

    try:
        if args.accounts_command == "link":
            entry = link_mention(
                session, args.mention, args.account, reviewer=args.reviewer, note=args.note
            )
            message = "Linked: the mention now counts toward the account"
        else:
            entry = review_account(
                session,
                args.account,
                AccountAction(args.decision),
                reviewer=args.reviewer,
                note=args.note,
            )
            message = f"Account {entry.to_state}"
    except KeyError as error:
        # An unknown ID is a usage mistake (exit 2), like a bad argument.
        return CommandResult(
            name, ExitCode.USAGE, message=str(error.args[0]), error_code="not_found"
        )
    except AccountReviewError as error:
        return CommandResult(name, ExitCode.USAGE, message=str(error), error_code="refused")
    session.commit()
    data = {
        "account_id": entry.account_id,
        "mention_id": entry.mention_id,
        "action": entry.action,
        "from_state": entry.from_state,
        "to_state": entry.to_state,
        "reviewer": entry.reviewer,
        "at": entry.at.isoformat(),
    }
    return CommandResult(name, data=data, message=message)


def _segments(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """Show a conversation's topic segments; record a reviewer split or merge (NRM-004/005)."""
    from sqlalchemy.orm import Session

    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
    from knowledge_engine.rendering.transcript import load_conversation
    from knowledge_engine.segmentation.overrides import (
        Action,
        OverrideError,
        load_segments,
        orphaned,
        record_override,
        revalidation,
    )
    from knowledge_engine.segmentation.segmenter import (
        SEGMENTER_VERSION,
        segment_conversation,
        truncation_count,
    )

    db = database_path(settings)
    if not db.exists():
        return CommandResult(
            "segments", ExitCode.ERROR, message="no imports yet", error_code="no_imports"
        )
    engine = create_sqlite_engine(db)
    try:
        with Session(engine) as session:
            try:
                conversation = load_conversation(session, args.conversation)
            except KeyError:
                return CommandResult(
                    "segments",
                    ExitCode.ERROR,
                    message="no such conversation",
                    error_code="unknown_conversation",
                )
            redo = None
            chosen = [(a, args_value) for a in Action if (args_value := getattr(args, a.value))]
            if chosen:
                if len(chosen) > 1 or not args.reviewer:
                    return CommandResult(
                        "segments",
                        ExitCode.USAGE,
                        message="give one of --split/--merge/--clear, and --reviewer",
                        error_code="bad_override",
                    )
                before = load_segments(session, conversation)
                ((action, native),) = chosen
                try:
                    record_override(
                        session,
                        conversation,
                        native,
                        action,
                        reviewer=args.reviewer,
                        note=args.note,
                    )
                except OverrideError as error:
                    return CommandResult(
                        "segments", ExitCode.ERROR, message=str(error), error_code="bad_override"
                    )
                redo = revalidation(session, before, load_segments(session, conversation))
                session.commit()
            found = load_segments(session, conversation)
            lost = orphaned(session, conversation)
            automatic = len(segment_conversation(conversation))
    finally:
        engine.dispose()
    data = {
        "segmenter": SEGMENTER_VERSION,
        "automatic_segments": automatic,
        "orphaned_overrides": lost,
        "truncation_count": truncation_count(found),
        "segments": [
            {
                "segment_id": s.segment_id,
                "section": s.section,
                "sequence": s.sequence,
                "reason": s.reason,
                "derived_from": list(s.derived_from),
                "first_message": s.messages[0],
                "messages": len(s.messages),
                "parts": [
                    {
                        "messages": len(p.messages),
                        "characters": p.characters,
                        "oversized": p.oversized,
                    }
                    for p in s.parts
                ],
            }
            for s in found
        ],
    }
    if redo is not None:
        data["revalidation"] = {
            "retired": list(redo.retired),
            "added": list(redo.added),
            "classifications_to_redo": len(redo.classifications),
            "extraction_runs_to_redo": len(redo.extraction_runs),
        }
    return CommandResult("segments", data=data, message=f"{len(found)} segment(s)")


def _corpus(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """Summarise the corpus by segment and draw a seeded sample (NRM-006); no text shown."""
    from dataclasses import asdict

    from sqlalchemy.orm import Session

    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
    from knowledge_engine.segmentation.inventory import (
        corpus_inventory,
        sample,
        sample_ids,
        summarise,
    )

    db = database_path(settings)
    if not db.exists():
        return CommandResult(
            "corpus", ExitCode.ERROR, message="no imports yet", error_code="no_imports"
        )
    engine = create_sqlite_engine(db)
    try:
        with Session(engine) as session:
            items = list(corpus_inventory(session))
    finally:
        engine.dispose()
    summary = summarise(items)
    data: dict[str, Any] = asdict(summary)
    if args.sample:
        data["sample"] = {
            "seed": args.seed,
            "segment_ids": sample_ids(sample(items, args.sample, seed=args.seed)),
        }
    return CommandResult(
        "corpus",
        data=data,
        message=f"{summary.segments} segment(s) in {summary.conversations} chat(s), "
        f"{summary.themes} theme(s)",
    )


def _gold_template(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """Write a private golden-set template into the workspace (EVAL-001); IDs only."""
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from knowledge_engine.evaluation.gold import annotation_template, write_gold
    from knowledge_engine.importer.records import ConversationRow
    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
    from knowledge_engine.segmentation.inventory import corpus_inventory

    db = database_path(settings)
    if not db.exists():
        return CommandResult(
            "gold", ExitCode.ERROR, message="no imports yet", error_code="no_imports"
        )
    engine = create_sqlite_engine(db)
    try:
        with Session(engine) as session:
            items = list(corpus_inventory(session))
            rows = session.execute(
                select(ConversationRow.conversation_id, ConversationRow.native_conversation_id)
            )
            native = {conversation_id: native_id for conversation_id, native_id in rows}
    finally:
        engine.dispose()
    gold = annotation_template(
        items,
        native,
        count=args.count,
        seed=args.seed,
        taxonomy_version=args.taxonomy,
        annotator=args.annotator,
    )
    # Always inside the git-ignored workspace: a real golden set is private.
    try:
        path = write_gold(gold, settings.workspace_root / "gold" / f"{gold.name}.json")
    except FileExistsError:
        return CommandResult(
            "gold",
            ExitCode.ERROR,
            message="a golden set already exists in the workspace; it is never overwritten",
            error_code="exists",
        )
    return CommandResult(
        "gold",
        data={"conversations": len(gold.conversations), "file": path.name},
        message=f"{len(gold.conversations)} conversation(s) chosen; template in the workspace",
    )


def _gold_convert(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """Turn a per-chat answer key folder into one golden set file (EVAL-014); counts only.

    The key folder is only read. The output must be outside it, and an
    existing file is never overwritten.
    """
    from sqlalchemy.orm import Session

    from knowledge_engine.evaluation.answer_key import convert_answer_key
    from knowledge_engine.evaluation.gold import write_gold
    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path

    name = "gold convert"
    db = database_path(settings)
    if not db.exists():
        return CommandResult(
            name, ExitCode.ERROR, message="no imports yet", error_code="no_imports"
        )
    key = args.key.resolve()
    if not key.is_dir() or not any(key.glob("*.json")):
        return CommandResult(
            name,
            ExitCode.USAGE,
            message="no key files (*.json) in that folder",
            error_code="missing",
        )
    out = (args.out or settings.workspace_root / "gold" / f"{args.name}.json").resolve()
    if out.is_relative_to(key):
        return CommandResult(
            name,
            ExitCode.USAGE,
            message="the output must be outside the answer key folder",
            error_code="inside_key",
        )
    if out.exists():
        return CommandResult(
            name, ExitCode.USAGE, message=f"already exists: {out.name}", error_code="exists"
        )
    engine = create_sqlite_engine(db)
    try:
        with Session(engine) as session:
            gold, report = convert_answer_key(
                session,
                key,
                name=args.name,
                taxonomy_version=args.taxonomy,
                annotator=args.annotator,
            )
    finally:
        engine.dispose()
    write_gold(gold, out)
    data = {**report.as_dict(), "file": out.name}
    unmapped = sum(report.unmapped.values())
    skipped = sum(report.skipped.values())
    return CommandResult(
        name,
        data=data,
        message=(
            f"{report.records} records from {report.found} of {report.files} chats; "
            f"{unmapped} unmapped, {skipped} skipped, {report.unverified} unverified left out"
        ),
    )


def _gold_score(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """Score this workspace's records against a private answer key; numbers only."""
    from sqlalchemy.orm import Session

    from knowledge_engine.evaluation.extraction_eval import parse_count_as
    from knowledge_engine.evaluation.report_labels import ReviewerKind
    from knowledge_engine.evaluation.workspace_score import score_extraction
    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path

    db = database_path(settings)
    if not db.exists():
        return CommandResult(
            "gold score", ExitCode.ERROR, message="no imports yet", error_code="no_imports"
        )
    try:
        count_as = parse_count_as(args.count_as or [])
    except ValueError as problem:
        return CommandResult(
            "gold score", ExitCode.USAGE, message=str(problem), error_code="bad_count_as"
        )
    for path in (args.gold, args.review):
        if path is not None and not path.is_file():
            return CommandResult(
                "gold score",
                ExitCode.USAGE,
                message=f"not found: {path.name}",
                error_code="missing",
            )
    engine = create_sqlite_engine(db)
    try:
        with Session(engine) as session:
            score = score_extraction(
                session,
                args.gold,
                ReviewerKind(args.reviewer),
                review_file=args.review,
                run_rules=not args.no_rules,
                count_as=count_as,
            )
            session.commit()
    finally:
        engine.dispose()
    report = score.report
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(report.as_markdown(), encoding="utf-8")
    total = report.total
    data = {
        "key_conversations": score.key_conversations,
        "found_conversations": score.found_conversations,
        "rule_runs": score.rules_run,
        "produced": report.produced,
        "precision": round(total.precision, 3),
        "recall": round(total.recall, 3),
        "f1": round(total.f1, 3),
        "by_type": {
            name: {"precision": round(t.precision, 3), "recall": round(t.recall, 3)}
            for name, t in sorted(report.by_type.items())
        },
        "anchor_validity": round(report.anchor_validity, 3),
        "forbidden_produced": len(report.forbidden_produced),
        "forbidden_in_truth": len(report.forbidden_in_truth),
        "unsupported_truth_decisions": len(report.unsupported_truth_decisions),
        "gate_passed": report.passed,
        "count_as": report.count_as,
    }
    message = (
        f"{score.found_conversations} of {score.key_conversations} key chats found; "
        f"P {data['precision']} R {data['recall']} F1 {data['f1']}; "
        f"gate {'passed' if report.passed else 'FAILED'}"
    )
    if score.found_conversations < score.key_conversations:
        message += " (import the missing chats for a full score)"
    return CommandResult("gold score", data=data, message=message)


def _file_read(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """Read a Markdown, text, Word or PDF file into located blocks (ING-008/009). Reads only."""
    import collections

    from knowledge_engine.ingestion.structured import UnsafeDocumentError, read_document

    if not args.path.is_file():
        return CommandResult(
            "file read", ExitCode.USAGE, message="file not found", error_code="missing"
        )
    try:
        document = read_document(args.path, max_bytes=settings.limits.max_source_file_bytes)
    except UnsafeDocumentError as error:
        return CommandResult(
            "file read", ExitCode.ERROR, message=f"refused: {error}", error_code="unsafe"
        )
    except ValueError as error:
        return CommandResult(
            "file read", ExitCode.USAGE, message=str(error), error_code="unsupported"
        )
    data = {
        "format": document.format,
        "parser": document.parser,
        "sha256": document.sha256,
        "size": document.size,
        "encoding": document.encoding,
        "pages": document.pages,
        "frontmatter_keys": sorted(document.frontmatter or {}),
        "blocks": len(document.blocks),
        "kinds": dict(collections.Counter(b.kind.value for b in document.blocks)),
        "assets": [a.target for a in document.assets],
        "warnings": list(document.warnings),
        "outline": [
            {
                "level": b.level,
                "title": b.text.splitlines()[0].lstrip("# ").rstrip(" #"),
                "at": b.locator,
            }
            for b in document.headings()
        ],
    }
    if args.blocks:
        data["located"] = [
            {"at": b.locator, "kind": b.kind.value, "start": b.start, "end": b.end}
            for b in document.blocks
        ]
    return CommandResult(
        "file read",
        data=data,
        message=f"{document.format}: {len(document.blocks)} block(s), "
        f"{len(document.warnings)} warning(s)",
    )


def _tenant(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """Create and list separate workspaces for the API (PROD-003)."""
    from knowledge_engine.access.accounts import AccessError
    from knowledge_engine.access.tenants import (
        TenantError,
        create_tenant,
        delete_tenant,
        list_tenants,
        tenant_inbox,
    )

    name = f"tenant {args.tenant_command}"
    try:
        if args.tenant_command == "delete":
            removed = delete_tenant(settings, args.name, args.confirm)
            return CommandResult(
                name, data={"removed": removed}, message=f"deleted workspace {args.name}"
            )
        if args.tenant_command == "list":
            names = list_tenants(settings)
            return CommandResult(
                name, data={"workspaces": names}, message=f"{len(names)} workspace(s)"
            )
        token = create_tenant(settings, args.name, args.owner)
    except (TenantError, AccessError) as error:
        return CommandResult(name, ExitCode.USAGE, message=str(error), error_code="refused")
    return CommandResult(
        name,
        data={"workspace": args.name, "owner": args.owner, "token": token},
        message=(
            f"created workspace {args.name}; put exports in {tenant_inbox(settings, args.name)}; "
            f"{args.owner}'s API token (shown once, keep it secret)"
        ),
    )


def _access(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """Accounts, API tokens and workspace roles (PROD-002)."""
    from sqlalchemy.orm import Session

    from knowledge_engine.access import accounts as acc
    from knowledge_engine.access.policy import AccountKind, Role
    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
    from knowledge_engine.infrastructure.migrations import upgrade_to_head
    from knowledge_engine.infrastructure.upgrade import SchemaMismatchError, require_current

    name = f"access {args.access_command}"
    engine = create_sqlite_engine(database_path(settings))
    try:
        try:
            require_current(engine)
        except SchemaMismatchError as error:
            return CommandResult(name, ExitCode.ERROR, message=str(error), error_code="schema")
        upgrade_to_head(engine)  # a brand-new workspace; a current one is left as is
        with Session(engine) as session:
            command = args.access_command
            data: dict[str, Any]
            if command == "list":
                rows = acc.members(session)
                return CommandResult(
                    name, data={"accounts": rows}, message=f"{len(rows)} account(s)"
                )
            if command == "log":
                events = acc.authz_log(session, args.limit)
                return CommandResult(
                    name, data={"events": events}, message=f"{len(events)} event(s)"
                )
            try:
                if command == "add":
                    kind = AccountKind.SERVICE if args.service else AccountKind.PERSON
                    acc.add_account(session, args.name, kind)
                    data, message = (
                        {"name": args.name, "kind": kind.value},
                        (
                            f"added {kind.value} account {args.name}; API checking is now on "
                            f"(give it a role: ke access grant {args.name} <role>)"
                        ),
                    )
                elif command == "token":
                    token = acc.issue_token(session, args.name)
                    data = {"name": args.name, "token": token}
                    message = f"API token for {args.name} (shown once, keep it secret)"
                elif command == "rotate":
                    token = acc.rotate_token(session, args.name)
                    data = {"name": args.name, "token": token}
                    message = f"old tokens revoked; new API token for {args.name} (shown once)"
                elif command == "delete":
                    if args.confirm != args.name:
                        raise acc.AccessError("repeat the account name with --confirm")
                    short = acc.delete_account(session, args.name, by="cli")
                    data = {"deleted": short}
                    message = f"account erased; the log now shows it as deleted-{short}"
                elif command == "revoke":
                    count = acc.revoke_tokens(session, args.name)
                    data, message = {"revoked": count}, f"revoked {count} token(s)"
                elif command == "disable":
                    acc.disable_account(session, args.name)
                    data, message = {"name": args.name}, f"{args.name} can no longer log in"
                elif command == "grant":
                    acc.grant(session, args.name, args.workspace, Role(args.role), by="cli")
                    data = {"name": args.name, "role": args.role, "workspace": args.workspace}
                    message = f"{args.name} is now {args.role} in {args.workspace}"
                else:  # remove
                    removed = acc.remove_member(session, args.name, args.workspace, by="cli")
                    data = {"removed": removed}
                    message = f"{args.name} removed" if removed else f"{args.name} wasn't a member"
            except acc.AccessError as error:
                return CommandResult(name, ExitCode.USAGE, message=str(error), error_code="refused")
            session.commit()
            return CommandResult(name, data=data, message=message)
    finally:
        engine.dispose()


def _digest(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """Ask for chat digests through request files a Claude session answers (NOTE-004).

    Run it once to write the request files; a session fills the response
    files (docs/runbooks/LABELLING_SESSION.md); run it again to collect,
    check every quote and, with ``--vault``, write the rich notes.
    """
    from collections import Counter

    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from knowledge_engine.digest.stage import DigestStage
    from knowledge_engine.documents.keywords import workspace_keywords
    from knowledge_engine.documents.rich_note import write_rich_note
    from knowledge_engine.importer.records import ConversationRow
    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
    from knowledge_engine.providers.file_batch import FileBatchProvider
    from knowledge_engine.providers.ledger import ModelStageRunner
    from knowledge_engine.rendering.transcript import find_conversation, load_conversation
    from knowledge_engine.settings import EgressDisabledError
    from knowledge_engine.taxonomy.registry import TaxonomyRegistry

    name = "digest run"
    db = database_path(settings)
    if not db.exists():
        return CommandResult(
            name, ExitCode.ERROR, message="no imports yet", error_code="no_imports"
        )
    engine = create_sqlite_engine(db)
    try:
        with Session(engine) as session:
            if args.all:
                ids = list(
                    session.scalars(
                        select(ConversationRow.conversation_id).order_by(
                            ConversationRow.conversation_id
                        )
                    )
                )
            else:
                found = [find_conversation(session, ref) for ref in args.conversations]
                if None in found or not found:
                    return CommandResult(
                        name, ExitCode.USAGE, message="no such conversation", error_code="not_found"
                    )
                ids = [cid for cid in found if cid is not None]
            # Notes show labels under one published version: the one asked
            # for, or the newest (NOTE-020; before, notes had no labels).
            registry = TaxonomyRegistry(session)
            published = registry.versions()
            version: str | None = args.taxonomy or (published[-1] if published else None)
            try:
                taxonomy = registry.snapshot(version) if version else None
            except (KeyError, ValueError):
                return CommandResult(
                    name,
                    ExitCode.USAGE,
                    message="no such published taxonomy version",
                    error_code="no_taxonomy",
                )
            provider = FileBatchProvider(settings.model_batch_root, args.run_id, settings.egress)
            stage = DigestStage(ModelStageRunner(session, provider, settings.egress))
            counts: Counter[str] = Counter()
            try:
                chats = [load_conversation(session, cid) for cid in ids]
                outcomes = stage.run_all(chats)
                session.commit()  # the requests and answers are kept before any note is written
                keywords = (
                    workspace_keywords(
                        session,
                        topics={
                            cid: [t.text for t in outcome.digest.topics]
                            for cid, outcome in zip(ids, outcomes, strict=True)
                            if outcome.digest is not None
                        },
                    )
                    if args.vault is not None
                    else {}
                )
                for conversation_id, outcome in zip(ids, outcomes, strict=True):
                    counts[outcome.state] += 1
                    # A chat with no text still gets its note, saying so (NOTE-031).
                    if outcome.state in ("done", "no_content") and args.vault is not None:
                        write_rich_note(
                            session,
                            conversation_id,
                            args.vault,
                            settings.workspace_root / "archive",
                            taxonomy=taxonomy,
                            digest=outcome.digest,
                            keywords=keywords.get(conversation_id),
                        )
                        counts["notes"] += 1
            except EgressDisabledError:
                return CommandResult(
                    name,
                    ExitCode.USAGE,
                    message="text_llm is off: turn it on in [egress] to write request files",
                    error_code="egress_off",
                )
    finally:
        engine.dispose()
    data = {k: counts.get(k, 0) for k in ("done", "pending", "review_required", "notes")}
    if counts["no_content"]:  # NOTE-031: only shown when a chat had no text
        data["no_content"] = counts["no_content"]
    data["chats"] = len(ids)
    return CommandResult(
        name,
        data=data,
        message=(
            f"{data['done']} done, {data['pending']} waiting for answers, "
            f"{data['review_required']} need review, "
            + (f"{data['no_content']} with no text to summarise, " if "no_content" in data else "")
            + f"{data['notes']} note(s) written"
            + (f" (labels under {version})" if data["notes"] and version else "")
        ),
    )


def _classify(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """Classify chats under one published taxonomy, through request files (step 4).

    The same request-file flow as ``ke digest run``: the first run writes one
    request per segment for a Claude session on the subscription to answer
    (docs/runbooks/LABELLING_SESSION.md); the next run collects, validates
    against the pinned version (CLS-001) and stores the results (CLS-004).
    The vocabulary is fixed for the whole run: one ``--taxonomy`` version.
    """
    if args.classify_command == "review":
        return _classify_review(settings, args)
    from collections import Counter

    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from knowledge_engine.classification.classifier import SegmentClassifier
    from knowledge_engine.classification.store import save
    from knowledge_engine.importer.records import ConversationRow
    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
    from knowledge_engine.providers.file_batch import FileBatchProvider
    from knowledge_engine.providers.ledger import ModelStageRunner
    from knowledge_engine.rendering.transcript import find_conversation, load_conversation
    from knowledge_engine.segmentation.overrides import load_segments
    from knowledge_engine.settings import EgressDisabledError
    from knowledge_engine.taxonomy.registry import TaxonomyRegistry

    name = "classify run"
    db = database_path(settings)
    if not db.exists():
        return CommandResult(
            name, ExitCode.ERROR, message="no imports yet", error_code="no_imports"
        )
    refs = list(args.conversations)
    if args.ids_file is not None:
        refs += [
            line.strip()
            for line in args.ids_file.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        ]
    engine = create_sqlite_engine(db)
    try:
        with Session(engine) as session:
            try:
                snapshot = TaxonomyRegistry(session).snapshot(args.taxonomy)
            except (KeyError, ValueError):
                return CommandResult(
                    name,
                    ExitCode.USAGE,
                    message="no such published taxonomy version",
                    error_code="no_taxonomy",
                )
            if args.all:
                ids = list(
                    session.scalars(
                        select(ConversationRow.conversation_id).order_by(
                            ConversationRow.conversation_id
                        )
                    )
                )
            else:
                found = [find_conversation(session, ref) for ref in refs]
                if not found or None in found:
                    return CommandResult(
                        name, ExitCode.USAGE, message="no such conversation", error_code="not_found"
                    )
                ids = sorted({cid for cid in found if cid is not None})
            provider = FileBatchProvider(settings.model_batch_root, args.run_id, settings.egress)
            runner = ModelStageRunner(session, provider, settings.egress)
            chats = [load_conversation(session, cid) for cid in ids]
            items = [(chat, seg) for chat in chats for seg in load_segments(session, chat)]
            try:
                results = SegmentClassifier(snapshot, runner=runner).classify(items)
            except EgressDisabledError:
                return CommandResult(
                    name,
                    ExitCode.USAGE,
                    message="text_llm is off: turn it on in [egress] to write request files",
                    error_code="egress_off",
                )
            save(session, results, provider_id=provider.identity.provider_id)
            session.commit()
    finally:
        engine.dispose()
    states = Counter(r.state for r in results)
    data = {
        "chats": len(ids),
        "segments": len(results),
        "done": states.get("done", 0),
        "pending": states.get("pending", 0),
        "review_required": states.get("review_required", 0),
        "taxonomy": args.taxonomy,
    }
    return CommandResult(
        name,
        data=data,
        message=(
            f"{data['done']} done, {data['pending']} waiting for answers, "
            f"{data['review_required']} need review ({len(ids)} chats, {len(results)} segments)"
        ),
    )


def _classify_review(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """Send segments waiting for review to a reviewer session (NOTE-018).

    Same request files as ``classify run``, in their own ``--run-id`` folder
    so a different session answers them. Clean answers are stored as
    reviews naming that session; the rest stay in the queue for a person.
    """
    from sqlalchemy.orm import Session

    from knowledge_engine.classification.review_session import review_flagged
    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
    from knowledge_engine.providers.file_batch import FileBatchProvider
    from knowledge_engine.providers.ledger import ModelStageRunner
    from knowledge_engine.settings import EgressDisabledError
    from knowledge_engine.taxonomy.registry import TaxonomyRegistry

    name = "classify review"
    db = database_path(settings)
    if not db.exists():
        return CommandResult(
            name, ExitCode.ERROR, message="no imports yet", error_code="no_imports"
        )
    engine = create_sqlite_engine(db)
    try:
        with Session(engine) as session:
            try:
                snapshot = TaxonomyRegistry(session).snapshot(args.taxonomy)
            except (KeyError, ValueError):
                return CommandResult(
                    name,
                    ExitCode.USAGE,
                    message="no such published taxonomy version",
                    error_code="no_taxonomy",
                )
            provider = FileBatchProvider(settings.model_batch_root, args.run_id, settings.egress)
            runner = ModelStageRunner(session, provider, settings.egress)
            try:
                report = review_flagged(session, snapshot, runner, provider.identity.provider_id)
            except EgressDisabledError:
                return CommandResult(
                    name,
                    ExitCode.USAGE,
                    message="text_llm is off: turn it on in [egress] to write request files",
                    error_code="egress_off",
                )
            session.commit()
    finally:
        engine.dispose()
    data = {
        "queued": report.queued,
        "reviewed": report.reviewed,
        "unsure": report.unsure,
        "pending": report.pending,
        "failed": report.failed,
        "missing": report.missing,
        "taxonomy": args.taxonomy,
    }
    return CommandResult(
        name,
        data=data,
        message=(
            f"{report.reviewed} reviewed, {report.pending} waiting for answers, "
            f"{report.unsure + report.failed} left for a person ({report.queued} queued)"
        ),
    )


def _extract(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """Run the model-backed knowledge extractor through request files (NOTE-015).

    The same request-file flow as ``ke digest run``: the first run writes one
    request per segment (or part of a long one) for a Claude session on the
    subscription to answer (docs/runbooks/LABELLING_SESSION.md); the next run
    collects the answers, applies the NOTE-005 attribution checks and the
    EXT-002 evidence gate, and stores the records. Segments already done are
    skipped, so running it again asks for nothing new.
    """
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from knowledge_engine.extraction.clean import workspace_cleaner
    from knowledge_engine.extraction.model_knowledge import knowledge_extractor
    from knowledge_engine.extraction.runner import run
    from knowledge_engine.extraction.text import segment_extraction_messages
    from knowledge_engine.importer.records import ConversationRow
    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
    from knowledge_engine.providers.file_batch import FileBatchProvider
    from knowledge_engine.providers.ledger import ModelStageRunner
    from knowledge_engine.rendering.transcript import find_conversation, load_conversation
    from knowledge_engine.segmentation.overrides import load_segments

    name = "extract run"
    if not settings.egress.text_llm:
        # Checked first: the runner would record a refused request as a
        # failed attempt, and three of those give up on the segment.
        return CommandResult(
            name,
            ExitCode.USAGE,
            message="text_llm is off: turn it on in [egress] to write request files",
            error_code="egress_off",
        )
    db = database_path(settings)
    if not db.exists():
        return CommandResult(
            name, ExitCode.ERROR, message="no imports yet", error_code="no_imports"
        )
    refs = list(args.conversations)
    if args.ids_file is not None:
        refs += [
            line.strip()
            for line in args.ids_file.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        ]
    engine = create_sqlite_engine(db)
    try:
        with Session(engine) as session:
            if args.all:
                ids = list(
                    session.scalars(
                        select(ConversationRow.conversation_id).order_by(
                            ConversationRow.conversation_id
                        )
                    )
                )
            else:
                found = [find_conversation(session, ref) for ref in refs]
                if not found or None in found:
                    return CommandResult(
                        name, ExitCode.USAGE, message="no such conversation", error_code="not_found"
                    )
                ids = sorted({cid for cid in found if cid is not None})
            provider = FileBatchProvider(settings.model_batch_root, args.run_id, settings.egress)
            extractor = knowledge_extractor(ModelStageRunner(session, provider, settings.egress))
            # NOTE-016: pasted profiles, setup prompts and assistant drafts are
            # blanked (same lengths, so evidence offsets still hold).
            cleaner = workspace_cleaner(session)
            segments = []
            for conversation_id in ids:
                chat = load_conversation(session, conversation_id)
                segments += [
                    (seg.segment_id, cleaner.clean(segment_extraction_messages(chat, seg)))
                    for seg in load_segments(session, chat)
                ]
            report = run(session, segments, [extractor])
            session.commit()
    finally:
        engine.dispose()
    data = {
        "chats": len(ids),
        "segments": len(segments),
        "done": len(report.done),
        "already_done": len(report.skipped),
        "pending": len(report.pending),
        "failed": len(report.failed) + len(report.gave_up),
        "records": report.records,
    }
    return CommandResult(
        name,
        data=data,
        message=(
            f"{data['done']} done now, {data['already_done']} already done, "
            f"{data['pending']} waiting for answers, {data['failed']} failed; "
            f"{data['records']} record(s) stored ({len(ids)} chats, {len(segments)} segments)"
        ),
    )


def _web(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """Fetch one web page safely and show where it came from (INT-001)."""
    from knowledge_engine.ingestion.web import WebFetchError, fetch_page, save_snapshot
    from knowledge_engine.settings import EgressDisabledError

    name = "web fetch"
    try:
        page = fetch_page(args.url, settings.egress, settings.web_allowlist)
    except EgressDisabledError:
        return CommandResult(
            name,
            ExitCode.USAGE,
            message="network_fetch is off: turn it on in [egress] to fetch pages",
            error_code="egress_off",
        )
    except WebFetchError as error:
        return CommandResult(name, ExitCode.ERROR, message=str(error), error_code=error.code)
    document = page.document
    data = {
        "final_url": page.final_url,
        "declared_canonical": page.declared_canonical,
        "redirects": list(page.redirects),
        "sha256": document.sha256,
        "bytes": document.size,
        "title": (document.frontmatter or {}).get("title"),
        "blocks": len(document.blocks),
        "headings": [b.text for b in document.headings()][:20],
        "warnings": list(document.warnings),
        "snapshot": str(save_snapshot(page, settings.workspace_root)) if args.save else None,
    }
    return CommandResult(name, data=data, message=f"read {len(document.blocks)} block(s)")


def _purge(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """Plan, run or list purges of whole conversations (OPS-004)."""
    from knowledge_engine.retention.purge import PurgeError, plan_purge, purge_log, run_purge

    command = f"purge {args.purge_command}"
    try:
        if args.purge_command == "log":
            events = purge_log(settings)
            return CommandResult(
                command, data={"purges": events}, message=f"{len(events)} purge(s)"
            )
        if args.purge_command == "plan":
            plan = plan_purge(settings, args.conversations)
            counts = plan.counts()
            return CommandResult(
                command,
                data={"token": plan.token, **counts},
                message=(
                    f"would delete {counts['conversations']} conversation(s), "
                    f"{counts['rows_total']} row(s) and {counts['files']} file(s); "
                    f'to go ahead: ke purge run ... --confirm {plan.token} --reason "..."'
                ),
            )
        result = run_purge(
            settings,
            args.conversations,
            confirm=args.confirm,
            reason=args.reason,
            vault=args.vault,
            taxonomy_version=args.taxonomy,
        )
    except PurgeError as error:
        return CommandResult(command, ExitCode.USAGE, message=str(error), error_code="refused")
    check = result.verification
    data = {
        "purge_id": result.purge_id,
        **result.plan.counts(),
        "verification": check.to_dict(),
        "vault": result.vault,
    }
    outside = sum(result.plan.counts()["outside_engine"].values())
    note = (
        f"; {outside} copy(ies) outside the engine (your original export, older backups) "
        "still hold it"
        if outside
        else ""
    )
    if not check.ok:
        return CommandResult(
            command,
            ExitCode.ERROR,
            data=data,
            message=f"purged, but the check found traces left (purge {result.purge_id})",
            error_code="residual",
        )
    return CommandResult(
        command,
        data=data,
        message=(
            f"purged and checked (purge {result.purge_id}): {check.probes} probe(s), "
            f"nothing found{note}"
        ),
    )


def _backup(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """Create, verify or restore a local backup (OPS-003). Never overwrites anything."""
    from knowledge_engine.infrastructure.backup import (
        BackupError,
        check_to_dict,
        create_backup,
        restore_backup,
        verify_backup,
    )

    command = f"backup {args.backup_command}"
    try:
        if args.backup_command == "create":
            manifest = create_backup(settings, args.to)
            data = {
                "folder": manifest["folder"],
                "files": len(manifest["files"]),
                "rows": sum(manifest["tables"].values()),
                "schema_revision": manifest["schema_revision"],
            }
            return CommandResult(
                command,
                data=data,
                message=f"backup {manifest['folder']}: {data['files']} file(s), "
                f"{data['rows']} row(s); search indexes are rebuilt with `ke index`",
            )
        if args.backup_command == "verify":
            check = verify_backup(args.folder)
        else:
            check = restore_backup(args.folder, args.to)
    except BackupError as error:
        return CommandResult(command, ExitCode.ERROR, message=str(error), error_code="refused")
    data = check_to_dict(check)
    if not check.ok:
        return CommandResult(
            command,
            ExitCode.ERROR,
            data=data,
            message="MISMATCH: "
            + "; ".join(f"{len(v)} {k}" for k, v in data.items() if isinstance(v, list) and v),
            error_code="mismatch",
        )
    done = "restored and checked" if args.backup_command == "restore" else "verified"
    return CommandResult(
        command,
        data=data,
        message=f"{done}: {check.files} file(s) and {check.rows} row(s) match the manifest",
    )


def _bundle(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """Export one project as a ZIP bundle, or check and count one (DOC-007, DOC-008)."""
    from knowledge_engine.documents.bundle import BundleError, export_bundle, verify_bundle

    command = f"bundle {args.bundle_command}"
    if args.bundle_command == "export":
        from sqlalchemy.orm import Session

        from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path

        db = database_path(settings)
        if not db.exists():
            return CommandResult(
                command, ExitCode.ERROR, message="no imports yet", error_code="no_imports"
            )
        engine = create_sqlite_engine(db)
        try:
            with Session(engine) as session:
                summary = export_bundle(
                    session, args.project, args.to, with_transcripts=args.with_transcripts
                )
        except BundleError as error:
            return CommandResult(command, ExitCode.USAGE, message=str(error), error_code="refused")
        finally:
            engine.dispose()
        return CommandResult(
            command,
            data={
                "records": summary.records,
                "chats": summary.chats,
                "transcripts": summary.transcripts,
                "sha256": summary.sha256,
            },
            message=f"bundle written: {summary.records} record(s) from {summary.chats} chat(s)"
            + (f", {summary.transcripts} transcript(s)" if summary.transcripts else ""),
        )
    check = verify_bundle(args.file, settings.limits)
    by_type = dict(sorted(check.by_type.items()))
    by_status = dict(sorted(check.by_status.items()))
    data: dict[str, Any] = {
        "ok": check.ok,
        "problems": check.problems,
        "members": check.members,
        "records": check.records,
        "by_type": by_type,
        "by_status": by_status,
    }
    if not check.ok:
        return CommandResult(
            command,
            ExitCode.ERROR,
            data=data,
            message="PROBLEMS: " + "; ".join(check.problems),
            error_code="bad_bundle",
        )
    if args.bundle_command == "verify":
        return CommandResult(
            command,
            data=data,
            message=f"sound: {check.members} member(s) and {check.records} record(s) match",
        )
    counts = ", ".join(f"{n} {k}" for k, n in by_type.items()) or "no records"
    states = ", ".join(f"{n} {k}" for k, n in by_status.items())
    return CommandResult(
        command, data=data, message=f"{counts}" + (f" ({states})" if states else "")
    )


def _gold_schema(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """The golden-set JSON Schema (EVAL-001)."""
    from knowledge_engine.evaluation.gold import gold_schema

    return CommandResult("gold", data=gold_schema(), message="golden set schema (gold-v1)")


def _logs(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """Search the structured run log by ID (OPS-001); reads only.

    Log events hold IDs, versions, counts and timings only, so they are
    safe to print.
    """
    from knowledge_engine.infrastructure.logs import search, totals

    match = {
        name: value
        for name, value in (
            ("stage_key", args.stage_key),
            ("job_id", args.job_id),
            ("segment_id", args.segment_id),
            ("event", args.event),
        )
        if value
    }
    events = search(settings.workspace_root / "logs", **match)
    lines = [json.dumps(e, sort_keys=True) for e in events[-args.limit :]]
    return CommandResult(
        "logs",
        data={"events": events[-args.limit :], "count": len(events), "totals": totals(events)},
        message="\n".join(lines) if lines else "no matching events",
    )


def _taxonomy_report(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """Taxonomy health and review activity (TAX-008); reads only."""
    from dataclasses import asdict

    from sqlalchemy.orm import Session

    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
    from knowledge_engine.taxonomy.governance import governance_report

    db = database_path(settings)
    if not db.exists():
        return CommandResult(
            "taxonomy", ExitCode.ERROR, message="no database yet", error_code="no_database"
        )
    engine = create_sqlite_engine(db)
    try:
        with Session(engine) as session:
            report = governance_report(session)
    finally:
        engine.dispose()
    kinds = report.kinds()
    summary = ", ".join(f"{n} {kind}" for kind, n in sorted(kinds.items())) or "no issues"
    return CommandResult(
        "taxonomy",
        data=asdict(report),
        message=f"{summary}; {sum(report.open_proposals.values())} open proposal(s)",
    )


def _private_target(settings: Settings, path: Path) -> bool:
    """A file holding chat text may only go in the workspace or a ``private`` folder."""
    target = path.resolve()
    if target.is_relative_to(settings.workspace_root.resolve()):
        return True
    return any(part.lower() == "private" for part in target.parent.parts)


def _write_private(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _taxonomy_bootstrap(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """NOTE-006: pack, propose, sheet, review, summary and publish (one handler)."""
    from dataclasses import asdict

    from pydantic import ValidationError
    from sqlalchemy.orm import Session

    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
    from knowledge_engine.segmentation.inventory import corpus_inventory
    from knowledge_engine.taxonomy import bootstrap
    from knowledge_engine.taxonomy.refresh import plan_for
    from knowledge_engine.taxonomy.registry import TaxonomyRegistry

    command = f"taxonomy {args.taxonomy_command}"
    db = database_path(settings)
    if not db.exists():
        return CommandResult(
            command, ExitCode.ERROR, message="no database yet", error_code="no_database"
        )
    out: Path | None = getattr(args, "out", None)
    if out is not None and not _private_target(settings, out):
        return CommandResult(
            command,
            ExitCode.USAGE,
            message="this file can hold private text: write it in the workspace or private/",
            error_code="not_private",
        )
    kind = args.taxonomy_command
    engine = create_sqlite_engine(db)
    try:
        with Session(engine) as session:
            if kind == "pack" and out is not None:
                pack = bootstrap.build_pack(
                    list(corpus_inventory(session)), size=args.sample, seed=args.seed
                )
                _write_private(out, json.dumps(pack, ensure_ascii=False, indent=1))
                return CommandResult(
                    command,
                    data={"sha256": bootstrap.pack_sha256(pack), **pack["corpus"]},
                    message=f"pack written ({pack['corpus']['sampled']} segments)",
                )
            if kind == "propose":
                pack = json.loads(args.pack.read_text(encoding="utf-8"))
                try:
                    # A refresh pack (NOTE-014) takes a plan whose categories are optional.
                    plan = plan_for(pack, args.plan.read_text(encoding="utf-8"))
                    filed = bootstrap.file_plan(session, plan, pack)
                except (ValidationError, bootstrap.PlanError) as problem:
                    session.rollback()
                    return CommandResult(
                        command, ExitCode.USAGE, message=str(problem)[:2000], error_code="bad_plan"
                    )
                session.commit()
                return CommandResult(
                    command,
                    data=asdict(filed),
                    message=(
                        f"{len(filed.proposed)} proposed, {filed.waiting_for_parent} waiting for "
                        "an approved category"
                    ),
                )
            if kind == "sheet" and out is not None:
                sheet = bootstrap.review_sheet(session)
                _write_private(out, json.dumps(sheet, ensure_ascii=False, indent=1))
                return CommandResult(
                    command, data={"open": len(sheet)}, message=f"{len(sheet)} open proposal(s)"
                )
            if kind == "review":
                try:
                    review = bootstrap.Review.model_validate_json(
                        args.review.read_text(encoding="utf-8")
                    )
                except ValidationError as problem:
                    return CommandResult(
                        command,
                        ExitCode.USAGE,
                        message=str(problem)[:2000],
                        error_code="bad_review",
                    )
                applied = bootstrap.apply_review(session, review)
                session.commit()
                return CommandResult(
                    command,
                    data=asdict(applied),
                    message=(
                        f"{len(applied.approved)} approved, {len(applied.rejected)} rejected, "
                        f"{len(applied.refused)} refused"
                    ),
                )
            if kind == "summary" and out is not None:
                _write_private(out, bootstrap.summary_markdown(session))
                return CommandResult(command, data={}, message="summary written")
            try:
                snapshot = TaxonomyRegistry(session).publish(
                    args.version, author=args.author, note=args.note
                )
            except ValueError as problem:
                return CommandResult(
                    command, ExitCode.USAGE, message=str(problem), error_code="bad_version"
                )
            session.commit()
            return CommandResult(
                command,
                data={"version": snapshot.version, "terms": len(snapshot.terms)},
                message=f"published {snapshot.version} ({len(snapshot.terms)} terms)",
            )
    finally:
        engine.dispose()


def _taxonomy_refresh(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """NOTE-014: file new topic candidates, count what the vocabulary doesn't cover, pack it.

    Every run files the queued chats' unmatched digest topics as proposals
    (NOTE-007); ``--out`` also writes a refresh pack for a proposer session.
    """
    from dataclasses import asdict

    from sqlalchemy.orm import Session

    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
    from knowledge_engine.rendering.transcript import load_conversation
    from knowledge_engine.segmentation.inventory import corpus_inventory
    from knowledge_engine.taxonomy import refresh
    from knowledge_engine.taxonomy.bootstrap import pack_sha256
    from knowledge_engine.taxonomy.registry import TaxonomyRegistry

    command = "taxonomy refresh"
    db = database_path(settings)
    if not db.exists():
        return CommandResult(
            command, ExitCode.ERROR, message="no database yet", error_code="no_database"
        )
    out: Path | None = args.out
    if out is not None and not _private_target(settings, out):
        return CommandResult(
            command,
            ExitCode.USAGE,
            message="this file can hold private text: write it in the workspace or private/",
            error_code="not_private",
        )
    engine = create_sqlite_engine(db)
    try:
        with Session(engine) as session:
            # NOTE-007: the queued chats' digest topics that match no term
            # become proposals for a reviewer (never labels).
            current = refresh.latest_version(session)
            proposed = []
            if current is not None:
                queued = sorted(refresh.queued_chats(session, current))
                proposed = refresh.collect_topics(
                    session, current, (load_conversation(session, cid) for cid in queued)
                )
                session.commit()
            status = refresh.refresh_status(session)
            counts = {k: v for k, v in asdict(status).items() if k != "last_pack_at"}
            counts["topics_proposed"] = len(proposed)
            counts["last_pack_at"] = (
                status.last_pack_at.isoformat() if status.last_pack_at else None
            )
            words = (
                f"{status.unlabelled_chats} of {status.chats} chats have no label under "
                f"{status.version}, {status.review_chats} wait for review, "
                f"{status.new_chats} are new since the last pack; "
                f"{status.candidates} proposal(s) wait for a reviewer "
                f"({len(proposed)} new from chat topics)"
            )
            if out is None:
                return CommandResult(command, data=counts, message=words)
            version = args.taxonomy or status.version
            if version is None:
                return CommandResult(
                    command,
                    ExitCode.USAGE,
                    message="publish a first version before refreshing it (ke taxonomy publish)",
                    error_code="no_taxonomy",
                )
            try:
                snapshot = TaxonomyRegistry(session).snapshot(version)
            except KeyError:
                return CommandResult(
                    command,
                    ExitCode.USAGE,
                    message="no such taxonomy version",
                    error_code="no_taxonomy",
                )
            try:
                pack = refresh.build_refresh_pack(
                    session,
                    snapshot,
                    list(corpus_inventory(session)),
                    size=args.sample,
                    seed=args.seed,
                )
            except refresh.NothingToRefresh as nothing:
                return CommandResult(command, data=counts, message=str(nothing))
            _write_private(out, json.dumps(pack, ensure_ascii=False, indent=1))
            refresh.record_pack(session, pack)
            session.commit()
    finally:
        engine.dispose()
    return CommandResult(
        command,
        data={
            **counts,
            "sha256": pack_sha256(pack),
            "queued": pack["refresh"]["queued"],
            "sampled": pack["corpus"]["sampled"],
        },
        message=f"refresh pack written ({pack['corpus']['sampled']} segments); {words}",
    )


def _taxonomy_relabel(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """NOTE-014: after publishing, relabel only what the new version changes, then the notes.

    Keyword classifier by default (local, free). With ``--run-id`` the
    changed segments go out as request files for a Claude session on the
    subscription, the same flow as ``ke classify run``; run the command again
    to collect the answers.
    """
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from knowledge_engine.classification.classifier import SegmentClassifier
    from knowledge_engine.importer.records import ConversationRow
    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
    from knowledge_engine.rendering.transcript import load_conversation
    from knowledge_engine.segmentation.overrides import load_segments
    from knowledge_engine.settings import EgressDisabledError
    from knowledge_engine.taxonomy.refresh import relabel
    from knowledge_engine.taxonomy.registry import TaxonomyRegistry

    command = "taxonomy relabel"
    db = database_path(settings)
    if not db.exists():
        return CommandResult(
            command, ExitCode.ERROR, message="no database yet", error_code="no_database"
        )
    engine = create_sqlite_engine(db)
    try:
        with Session(engine) as session:
            registry = TaxonomyRegistry(session)
            try:
                old, new = registry.snapshot(args.old), registry.snapshot(args.new)
            except KeyError:
                return CommandResult(
                    command,
                    ExitCode.USAGE,
                    message="no such taxonomy version",
                    error_code="no_taxonomy",
                )
            provider_id = None
            runner = None
            if args.run_id:
                from knowledge_engine.providers.file_batch import FileBatchProvider
                from knowledge_engine.providers.ledger import ModelStageRunner

                provider = FileBatchProvider(
                    settings.model_batch_root, args.run_id, settings.egress
                )
                runner = ModelStageRunner(session, provider, settings.egress)
                provider_id = provider.identity.provider_id
            chats = [
                load_conversation(session, cid)
                for cid in session.scalars(
                    select(ConversationRow.conversation_id).order_by(
                        ConversationRow.conversation_id
                    )
                )
            ]
            items = [(chat, seg) for chat in chats for seg in load_segments(session, chat)]
            try:
                report = relabel(
                    session,
                    old,
                    SegmentClassifier(new, runner=runner),
                    items,
                    provider_id=provider_id,
                )
            except EgressDisabledError:
                return CommandResult(
                    command,
                    ExitCode.USAGE,
                    message="text_llm is off: turn it on in [egress] to write request files",
                    error_code="egress_off",
                )
            session.commit()
            vault: dict[str, int] = {}
            if args.vault is not None:
                from knowledge_engine.documents.vault import sync_vault

                # DOC-006 rewrites only notes whose content changed.
                vault = sync_vault(
                    session, args.vault, settings.workspace_root / "archive", taxonomy=new
                ).counts()
    finally:
        engine.dispose()
    reasons: dict[str, int] = {}
    for why in report.relabelled.values():
        reasons[why] = reasons.get(why, 0) + 1
    data = {
        "from": report.from_version,
        "to": report.to_version,
        "relabelled": len(report.relabelled),
        "reasons": dict(sorted(reasons.items())),
        "carried": len(report.carried),
        "invalidated": len(report.invalidated),
        "states": report.states,
        "chats_relabelled": len(report.conversations),
        "vault": vault,
    }
    message = (
        f"{data['relabelled']} segment(s) relabelled, {data['carried']} carried over "
        f"unchanged into {report.to_version}"
    )
    if report.states.get("pending"):
        message += f"; {report.states['pending']} wait for answers (run again to collect)"
    if vault:
        message += f"; notes: {vault['created']} created, {vault['written']} updated"
    return CommandResult(command, data=data, message=message)


def _search(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """Search message text (RET-001). Brings the search index up to date first."""
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
    from knowledge_engine.infrastructure.workspace import WorkspaceRow
    from knowledge_engine.retrieval.filters import (
        BadFilterDate,
        BadFilterRole,
        UnknownFilterTerm,
        build_filters,
    )
    from knowledge_engine.retrieval.lexical import (
        LexicalIndex,
        SearchMode,
        search_index_path,
        sync_index,
    )

    db = database_path(settings)
    if not db.exists():
        return CommandResult(
            "search", ExitCode.ERROR, message="no imports yet", error_code="no_imports"
        )
    engine = create_sqlite_engine(db)
    try:
        with Session(engine) as session, LexicalIndex(search_index_path(settings)) as index:
            try:
                filters = build_filters(
                    session,
                    since=args.since,
                    until=args.until,
                    role=args.role,
                    term=args.term,
                    taxonomy=args.taxonomy,
                )
            except (BadFilterDate, BadFilterRole) as error:
                return CommandResult(
                    "search", ExitCode.USAGE, message=str(error), error_code="bad_filter"
                )
            except UnknownFilterTerm as error:
                return CommandResult(
                    "search", ExitCode.USAGE, message=str(error), error_code="unknown_term"
                )
            added = sync_index(session, index)
            workspaces = list(session.scalars(select(WorkspaceRow.workspace_id)))
            mode = SearchMode(args.mode)
            hits = [
                {
                    "conversation_id": hit.conversation_id,
                    "native_node_id": hit.native_node_id,
                    "revision_id": hit.revision_id,
                    "role": hit.role,
                    "snippet": hit.snippet,
                }
                for workspace_id in workspaces
                for hit in index.search(
                    args.query,
                    workspace_id=workspace_id,
                    mode=mode,
                    limit=args.limit,
                    conversation_id=args.conversation,
                    filters=filters,
                )
            ][: args.limit]
            undated = sum(
                index.undated(
                    args.query,
                    workspace_id=workspace_id,
                    mode=mode,
                    conversation_id=args.conversation,
                    filters=filters,
                )
                for workspace_id in workspaces
            )
    finally:
        engine.dispose()
    data: dict[str, object] = {"mode": args.mode, "hits": hits, "newly_indexed": added}
    message = f"{len(hits)} matching message(s)"
    if filters is not None and filters.dated:
        data["undated_left_out"] = undated
        if undated:
            message += f"; {undated} more match but have no date, so a date filter leaves them out"
    return CommandResult(
        "search",
        data=data,
        message=message,
    )


def _similar(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """Find messages close in meaning (RET-003), with the local embedder; syncs first."""
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
    from knowledge_engine.infrastructure.workspace import WorkspaceRow
    from knowledge_engine.retrieval.embeddings import LocalHashEmbedder
    from knowledge_engine.retrieval.semantic import (
        SemanticIndex,
        StaleIndexError,
        semantic_index_path,
        sync_semantic,
    )

    db = database_path(settings)
    if not db.exists():
        return CommandResult(
            "similar", ExitCode.ERROR, message="no imports yet", error_code="no_imports"
        )
    embedder = LocalHashEmbedder()
    engine = create_sqlite_engine(db)
    try:
        try:
            index = SemanticIndex(semantic_index_path(settings), embedder, rebuild=args.rebuild)
        except StaleIndexError as error:
            return CommandResult(
                "similar", ExitCode.ERROR, message=f"{error} (use --rebuild)", error_code="stale"
            )
        with Session(engine) as session, index:
            synced = sync_semantic(session, index, settings.egress)
            hits = [
                {
                    "conversation_id": hit.conversation_id,
                    "native_node_id": hit.native_node_id,
                    "revision_id": hit.revision_id,
                    "role": hit.role,
                    "score": round(hit.score, 4),
                }
                for workspace_id in session.scalars(select(WorkspaceRow.workspace_id))
                for hit in index.search(
                    args.query,
                    workspace_id=workspace_id,
                    egress=settings.egress,
                    limit=args.limit,
                    conversation_ids=[args.conversation] if args.conversation else None,
                )
            ]
    finally:
        engine.dispose()
    hits.sort(key=lambda h: (-float(h["score"]), str(h["revision_id"])))  # type: ignore[arg-type]
    return CommandResult(
        "similar",
        data={
            "embedder": embedder.identity.model,
            "hits": hits[: args.limit],
            "newly_embedded": synced.embedded,
        },
        message=f"{len(hits[: args.limit])} close message(s) (local embedder: no synonyms)",
    )


def _find(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """Answer a question with the right search (RET-005 route, RET-004 fusion); syncs first."""
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
    from knowledge_engine.infrastructure.workspace import WorkspaceRow
    from knowledge_engine.relationships.view import related_by_conversation
    from knowledge_engine.retrieval.embeddings import LocalHashEmbedder
    from knowledge_engine.retrieval.hybrid import HybridRetriever
    from knowledge_engine.retrieval.lexical import LexicalIndex, search_index_path, sync_index
    from knowledge_engine.retrieval.planner import plan, run_plan
    from knowledge_engine.retrieval.semantic import (
        SemanticIndex,
        StaleIndexError,
        semantic_index_path,
        sync_semantic,
    )

    db = database_path(settings)
    if not db.exists():
        return CommandResult(
            "find", ExitCode.ERROR, message="no imports yet", error_code="no_imports"
        )
    question = plan(args.question)
    engine = create_sqlite_engine(db)
    related: dict[str, list[dict[str, object]]] = {}
    records: list[dict[str, object]] = []
    hits: list[dict[str, object]] = []
    fallback = False
    try:
        try:
            semantic = SemanticIndex(
                semantic_index_path(settings), LocalHashEmbedder(), rebuild=args.rebuild
            )
        except StaleIndexError as error:
            return CommandResult(
                "find", ExitCode.ERROR, message=f"{error} (use --rebuild)", error_code="stale"
            )
        with (
            Session(engine) as session,
            semantic,
            LexicalIndex(search_index_path(settings)) as lexical,
        ):
            sync_index(session, lexical)
            sync_semantic(session, semantic, settings.egress)
            retriever = HybridRetriever(session, lexical, semantic, settings.egress)
            for workspace_id in session.scalars(select(WorkspaceRow.workspace_id)):
                result = run_plan(
                    session,
                    question,
                    retriever,
                    lexical,
                    workspace_id=workspace_id,
                    limit=args.limit,
                    as_of=args.as_of,
                )
                fallback = fallback or result.fallback
                records += [
                    {
                        "record_id": r.record_id,
                        "record_type": r.record_type,
                        "status": r.status.value,
                        "assertion": r.assertion,
                        "conversation_id": r.conversation_id,
                        "revisions": list(r.revisions),
                        "because": list(r.because),
                        "superseded_by": list(r.superseded_by),
                        "conflicts_with": list(r.conflicts_with),
                    }
                    for r in result.records
                ]
                hits += [
                    {
                        "kind": h.kind,
                        "key": h.key,
                        "conversation_id": h.conversation_id,
                        "revision_id": h.revision_id,
                        "pinned": h.pinned,
                        "ranks": dict(h.ranks),
                        "score": round(h.score, 6),
                        "role": h.role,
                        "snippet": h.snippet,
                        "record_type": h.record_type,
                    }
                    for h in result.hits
                ]
            # Links between the chats found (REL-004): IDs, kind, direction, reasons.
            shown = records[: args.limit] + hits[: args.limit]
            related = {
                conversation: [link.as_dict(conversation) for link in links]
                for conversation, links in sorted(
                    related_by_conversation(
                        session, {str(h["conversation_id"]) for h in shown if h["conversation_id"]}
                    ).items()
                )
            }
    finally:
        engine.dispose()
    found = len(records) + len(hits)
    return CommandResult(
        "find",
        data={
            "route": question.route.value,
            "reasons": list(question.reasons),
            "exact_terms": list(question.exact_terms),
            "fallback": fallback,
            "records": records[: args.limit],
            "hits": hits[: args.limit],
            "related": related,
        },
        message=f"{question.route.value} route{' (fell back to hybrid)' if fallback else ''}: "
        f"{found} result(s)",
    )


def _ask(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """Answer from the chats with a citation on every sentence, or abstain (RET-007)."""
    import json

    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
    from knowledge_engine.infrastructure.workspace import WorkspaceRow
    from knowledge_engine.retrieval.answers import answer, to_json
    from knowledge_engine.retrieval.embeddings import LocalHashEmbedder
    from knowledge_engine.retrieval.hybrid import HybridRetriever
    from knowledge_engine.retrieval.lexical import LexicalIndex, search_index_path, sync_index
    from knowledge_engine.retrieval.semantic import (
        SemanticIndex,
        StaleIndexError,
        semantic_index_path,
        sync_semantic,
    )

    db = database_path(settings)
    if not db.exists():
        return CommandResult(
            "ask", ExitCode.ERROR, message="no imports yet", error_code="no_imports"
        )
    engine = create_sqlite_engine(db)
    answers: list[dict[str, object]] = []
    try:
        try:
            semantic = SemanticIndex(
                semantic_index_path(settings), LocalHashEmbedder(), rebuild=args.rebuild
            )
        except StaleIndexError as error:
            return CommandResult(
                "ask", ExitCode.ERROR, message=f"{error} (use --rebuild)", error_code="stale"
            )
        with (
            Session(engine) as session,
            semantic,
            LexicalIndex(search_index_path(settings)) as lexical,
        ):
            sync_index(session, lexical)
            sync_semantic(session, semantic, settings.egress)
            retriever = HybridRetriever(session, lexical, semantic, settings.egress)
            for workspace_id in session.scalars(select(WorkspaceRow.workspace_id)):
                found = answer(
                    session,
                    args.question,
                    retriever,
                    lexical,
                    workspace_id=workspace_id,
                    limit=args.limit,
                    as_of=args.as_of,
                )
                answers.append(json.loads(to_json(found)))
    finally:
        engine.dispose()
    answered = [a for a in answers if a["status"] != "unknown"]
    shown = (answered or answers or [{"answer": "no workspaces"}])[0]
    return CommandResult("ask", data={"answers": answers}, message=str(shown["answer"]))


def _eval_retrieval(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """Run the pinned retrieval benchmark (RET-008) in a scratch folder; fail below a floor."""
    import tempfile

    from knowledge_engine.evaluation.retrieval_bench import check, run_benchmark, to_markdown

    with tempfile.TemporaryDirectory(prefix="ke-bench-") as scratch:
        report = run_benchmark(Path(scratch))
    text = to_markdown(report)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    failures = check(report)
    data = {
        "scores": {
            m: {"recall": s.recall, "mrr": s.mrr, "exact_term_hit": s.exact_term_hit}
            for m, s in report.scores.items()
        },
        "answered_with_right_citation": report.answered_with_right_citation,
        "abstained_when_unanswerable": report.abstained_when_unanswerable,
        "model_requests": report.model_requests,
        "seconds": round(report.seconds, 2),
        "failures": failures,
    }
    if failures:
        return CommandResult(
            "eval retrieval",
            ExitCode.ERROR,
            data=data,
            message="below a pinned floor: " + "; ".join(failures),
            error_code="regression",
        )
    hybrid = report.scores["hybrid"]
    return CommandResult(
        "eval retrieval",
        data=data,
        message=f"PASS: hybrid recall@5 {hybrid.recall[5]:.3f}, MRR {hybrid.mrr:.3f}",
    )


def _eval_fidelity(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """Check every fixture export's nodes all land, in scratch workspaces (EVAL-002)."""
    import tempfile

    from knowledge_engine.evaluation.import_fidelity import (
        evaluate_fixtures,
        to_dict,
        to_markdown,
    )

    if not args.fixtures.is_dir():
        return CommandResult(
            "eval fidelity",
            ExitCode.USAGE,
            message="fixtures folder not found (run from the repository, or pass --fixtures)",
            error_code="no_fixtures",
        )
    with tempfile.TemporaryDirectory(prefix="ke-fidelity-") as scratch:
        report = evaluate_fixtures(args.fixtures, Path(scratch))
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(to_markdown(report), encoding="utf-8")
    data = to_dict(report)
    if not report.passed:
        silent = [e.name for e in report.exports if e.verdict == "silent_drop"]
        return CommandResult(
            "eval fidelity",
            ExitCode.ERROR,
            data=data,
            message="nodes lost without a warning in: " + ", ".join(silent),
            error_code="silent_drop",
        )
    return CommandResult(
        "eval fidelity",
        data=data,
        message=f"PASS: {len(report.exports)} export(s), no node lost without a warning",
    )


def _eval_temporal(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """Run the temporal/current-state benchmark (EVAL-005) in a scratch folder."""
    import tempfile

    from knowledge_engine.evaluation.temporal_bench import run_benchmark, to_dict, to_markdown

    fixture = args.fixtures / "engine_switch" / "export"
    if not fixture.is_dir():
        return CommandResult(
            "eval temporal",
            ExitCode.USAGE,
            message="fixtures folder not found (run from the repository, or pass --fixtures)",
            error_code="no_fixtures",
        )
    with tempfile.TemporaryDirectory(prefix="ke-temporal-") as scratch:
        report = run_benchmark(fixture, Path(scratch))
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(to_markdown(report), encoding="utf-8")
    data = to_dict(report)
    if not report.passed:
        return CommandResult(
            "eval temporal",
            ExitCode.ERROR,
            data=data,
            message="false supersession or lost history: "
            + (", ".join(report.false_supersessions) or "pipeline"),
            error_code="regression",
        )
    return CommandResult(
        "eval temporal",
        data=data,
        message=f"PASS: {data['right']} of {data['pairs']} pairs as expected, "
        "0 false supersessions, history kept",
    )


def _eval_e2e(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """Run ZIP to vault end to end, check every link and compare the golden (EVAL-006)."""
    import json
    import tempfile

    from knowledge_engine.evaluation.end_to_end import (
        E2E_QUERY,
        golden_diff,
        run_end_to_end,
        to_dict,
        vault_golden,
    )

    if not args.fixture.is_file():
        return CommandResult(
            "eval e2e",
            ExitCode.USAGE,
            message="fixture ZIP not found (run from the repository, or pass --fixture)",
            error_code="no_fixtures",
        )
    with tempfile.TemporaryDirectory(prefix="ke-e2e-") as scratch:
        report = run_end_to_end(args.fixture, Path(scratch), query=E2E_QUERY)
    golden = vault_golden(report.check)
    if args.update_golden:
        args.golden.parent.mkdir(parents=True, exist_ok=True)
        args.golden.write_text(json.dumps(golden, indent=1) + "\n", encoding="utf-8")
    diffs = (
        golden_diff(golden, json.loads(args.golden.read_text(encoding="utf-8")))
        if args.golden.is_file()
        else ["no golden file"]
    )
    data = {**to_dict(report), "golden_differences": diffs}
    problems = diffs[:3]
    broken = len(report.check.broken_links) + len(report.check.broken_embeds)
    if broken or report.check.bad_frontmatter:
        problems.append(
            f"{broken} broken link(s), {len(report.check.bad_frontmatter)} bad header(s)"
        )
    if not report.sources_first:
        problems.append("a chat is missing its source note or link")
    if not report.search_hit_in_vault:
        problems.append("search did not land on a note")
    if problems:
        return CommandResult(
            "eval e2e",
            ExitCode.ERROR,
            data=data,
            message="FAIL: " + "; ".join(problems),
            error_code="regression",
        )
    return CommandResult(
        "eval e2e",
        data=data,
        message=f"PASS: {report.check.notes} notes, {report.check.links} links and "
        f"{report.check.embeds} embeds all resolve; matches the golden",
    )


def _eval_gate(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """Run every evaluation once and label each PASS/FAIL/REVIEW/BLOCKED (EVAL-007)."""
    import tempfile

    from knowledge_engine.evaluation.gate import GateInputs, run_gate, to_dict, to_markdown

    if not (args.fixtures / "chatgpt").is_dir():
        return CommandResult(
            "eval gate",
            ExitCode.USAGE,
            message="fixtures folder not found (run from the repository, or pass --fixtures)",
            error_code="no_fixtures",
        )
    with tempfile.TemporaryDirectory(prefix="ke-gate-") as scratch:
        report = run_gate(GateInputs(args.fixtures, Path(scratch)))
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(to_markdown(report, commit=args.commit), encoding="utf-8")
    data = to_dict(report)
    summary = ", ".join(f"{n} {s}" for s, n in report.counts().items() if n)
    if not report.passed:
        failed = [c["check"] for c in data["checks"] if c["status"] == "FAIL"]
        return CommandResult(
            "eval gate",
            ExitCode.ERROR,
            data=data,
            message=f"FAIL ({summary}): " + ", ".join(failed),
            error_code="gate_failed",
        )
    return CommandResult("eval gate", data=data, message=f"{report.overall.value}: {summary}")


def _eval_variance(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """Run the synthetic exports in 3 shuffled orders plus pinned repeats (EVAL-008)."""
    import tempfile

    from knowledge_engine.evaluation.variance import SOURCES, run_variance, to_dict

    sources = [args.fixtures / s for s in SOURCES]
    if not all(s.exists() for s in sources):
        return CommandResult(
            "eval variance",
            ExitCode.USAGE,
            message="fixtures folder not found (run from the repository, or pass --fixtures)",
            error_code="no_fixtures",
        )
    with tempfile.TemporaryDirectory(prefix="ke-variance-") as scratch:
        report = run_variance(sources, Path(scratch))
    data = to_dict(report)
    if report.silent_drift or report.repeat_new_requests or not report.repeat_identical:
        return CommandResult(
            "eval variance",
            ExitCode.ERROR,
            data=data,
            message="FAIL: repeats changed or asked the model again, or drift went unlisted",
            error_code="regression",
        )
    if report.items:
        return CommandResult(
            "eval variance",
            data=data,
            message=f"REVIEW: {len(report.items)} answer(s) changed with the order; "
            "each is listed for review",
        )
    return CommandResult(
        "eval variance",
        data=data,
        message=f"PASS: {data['segments']} segments and {data['records']} records gave the "
        f"same answers in {len(report.runs)} orders; repeats made 0 new requests",
    )


def _docs_check(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """Check every link, embed and frontmatter block in a vault, as Obsidian reads them."""
    from knowledge_engine.evaluation.end_to_end import check_vault

    if not args.vault.is_dir():
        return CommandResult(
            "docs check",
            ExitCode.USAGE,
            message="vault folder not found",
            error_code="no_vault",
        )
    check = check_vault(args.vault)
    data = {
        "notes": check.notes,
        "links": check.links,
        "embeds": check.embeds,
        "broken_links": [list(b) for b in check.broken_links],
        "broken_embeds": [list(b) for b in check.broken_embeds],
        "bad_frontmatter": check.bad_frontmatter,
        # NOTE-010: notes written to the rich-note layout, and what's wrong with any note.
        "readable_notes": check.readable,
        "readability": [
            {"note": p.note, "check": p.check, "detail": p.detail} for p in check.readability
        ],
    }
    if not check.clean:
        broken = len(check.broken_links) + len(check.broken_embeds) + len(check.bad_frontmatter)
        problems = broken + len(check.readability)
        return CommandResult(
            "docs check",
            ExitCode.ERROR,
            data=data,
            message=(
                f"{problems} problem(s) in {check.notes} notes "
                f"({broken} link or header, {len(check.readability)} readability)"
            ),
            error_code="broken_links" if broken else "readability",
        )
    return CommandResult(
        "docs check",
        data=data,
        message=(
            f"{check.notes} notes: {check.links} links and {check.embeds} embeds all resolve; "
            f"{check.readable} rich note(s) within budget"
        ),
    )


def _docs_rubric(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """Run the NOTE-011 code checks on chats' rich notes, built in memory (writes nothing)."""
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from knowledge_engine.digest.stage import stored_digest
    from knowledge_engine.documents.rich_note import rich_conversation_note
    from knowledge_engine.evaluation.note_checks import (
        NOTE_CHECKS_VERSION,
        CheckStatus,
        check_note,
        summarise,
    )
    from knowledge_engine.importer.records import ConversationRow
    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
    from knowledge_engine.rendering.markdown import render_note
    from knowledge_engine.rendering.transcript import find_conversation, load_conversation

    name = "docs rubric"
    db = database_path(settings)
    if not db.exists():
        return CommandResult(
            name, ExitCode.ERROR, message="no imports yet", error_code="no_imports"
        )
    engine = create_sqlite_engine(db)
    try:
        with Session(engine) as session:
            if args.all:
                ids = list(
                    session.scalars(
                        select(ConversationRow.conversation_id).order_by(
                            ConversationRow.conversation_id
                        )
                    )
                )
            else:
                found = [find_conversation(session, ref) for ref in args.conversations]
                if None in found or not found:
                    return CommandResult(
                        name, ExitCode.USAGE, message="no such conversation", error_code="not_found"
                    )
                ids = [cid for cid in found if cid is not None]
            reports = []
            for conversation_id in ids:
                digest = stored_digest(session, load_conversation(session, conversation_id))
                note = rich_conversation_note(session, conversation_id, digest=digest)
                reports.append(check_note(session, conversation_id, render_note(note.model)))
    finally:
        engine.dispose()
    failed = [r for r in reports if not r.passed]
    data = {
        "version": NOTE_CHECKS_VERSION,
        "notes": len(reports),
        "passed": len(reports) - len(failed),
        "checks": summarise(reports),
        "problems": [
            {
                "conversation_id": r.conversation_id,
                "check": f.check,
                "status": f.status.value,
                "problems": list(f.problems),
            }
            for r in reports
            for f in r.findings
            if f.status is not CheckStatus.PASS
        ],
    }
    if failed:
        return CommandResult(
            name,
            ExitCode.ERROR,
            data=data,
            message=f"{len(failed)} of {len(reports)} note(s) failed a check",
            error_code="rubric_failed",
        )
    return CommandResult(name, data=data, message=f"{len(reports)} note(s) passed every check")


def _corrections(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """List human corrections and whether they still stand after re-imports (IMP-006)."""
    from sqlalchemy.orm import Session

    from knowledge_engine.importer.corrections import OverrideState, check_overrides
    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path

    db = database_path(settings)
    if not db.exists():
        return CommandResult(
            "corrections", ExitCode.ERROR, message="no imports yet", error_code="no_imports"
        )
    engine = create_sqlite_engine(db)
    try:
        with Session(engine) as session:
            checks = check_overrides(session)
    finally:
        engine.dispose()
    counts: dict[str, int] = {}
    for check in checks:
        counts[check.state.value] = counts.get(check.state.value, 0) + 1
    # IDs only: both revisions are named so a reviewer can open them side by side.
    flagged = [
        {
            "kind": c.kind.value,
            "override": c.override_ref,
            "changes": [
                {"node_key": x.node_key, "decided_on": x.decided_on, "now": x.now}
                for x in c.changes
            ],
        }
        for c in checks
        if c.state is OverrideState.REVIEW_REQUIRED
    ]
    return CommandResult(
        "corrections",
        data={"counts": dict(sorted(counts.items())), "review_required": flagged},
        message=f"{counts.get('kept', 0)} kept, {len(flagged)} need another look "
        "(their messages changed)",
    )


def _docs_note(settings: Settings, session: Any, args: argparse.Namespace) -> CommandResult:
    """Write one chat's knowledge note (DOC-003) or one topic's master note (DOC-005)."""
    from knowledge_engine.documents.notes import (
        TopicNotFound,
        write_conversation_note,
        write_topic_master,
    )
    from knowledge_engine.documents.render import Mode
    from knowledge_engine.documents.rich_note import write_rich_note
    from knowledge_engine.rendering.transcript import find_conversation
    from knowledge_engine.taxonomy.registry import TaxonomyRegistry

    command = f"docs {args.docs_command}"
    snapshot = None
    if args.taxonomy:
        try:
            snapshot = TaxonomyRegistry(session).snapshot(args.taxonomy)
        except KeyError:
            return CommandResult(
                command,
                ExitCode.USAGE,
                message="no such taxonomy version",
                error_code="no_taxonomy",
            )
    if args.docs_command == "vault":
        from knowledge_engine.documents.vault import sync_vault

        report = sync_vault(
            session, args.vault, settings.workspace_root / "archive", taxonomy=snapshot
        )
        counts = report.counts()
        # Counts only: note paths hold private chat titles.
        return CommandResult(
            command,
            data=counts,
            message=(
                f"{counts['created']} created, {counts['written']} updated, "
                f"{counts['unchanged']} unchanged, {counts['conflicts']} kept (edited by hand), "
                f"{counts['occupied']} skipped (not the engine's), {counts['broken_embeds']} "
                "broken image link(s)"
            ),
        )
    if args.docs_command == "chat":
        conversation_id = find_conversation(session, args.conversation)
        if conversation_id is None:
            return CommandResult(
                command, ExitCode.USAGE, message="no such conversation", error_code="not_found"
            )
        # v2 is the rich-note layout (NOTE-001); v1 (DOC-003) stays the default for now.
        if args.template == "v2":
            from knowledge_engine.digest.stage import stored_digest
            from knowledge_engine.documents.keywords import workspace_keywords
            from knowledge_engine.rendering.transcript import load_conversation

            # A digest already collected (NOTE-004) fills the summary; none is asked for here.
            digest = stored_digest(session, load_conversation(session, conversation_id))
            # Keywords are worked out across every chat: rarity means rare among all of them.
            topics = {conversation_id: [t.text for t in digest.topics]} if digest else {}
            keywords = workspace_keywords(session, taxonomy=snapshot, topics=topics)
            path = write_rich_note(
                session,
                conversation_id,
                args.vault,
                settings.workspace_root / "archive",
                taxonomy=snapshot,
                digest=digest,
                keywords=keywords.get(conversation_id),
            )
        else:
            path = write_conversation_note(
                session,
                conversation_id,
                args.vault,
                settings.workspace_root / "archive",
                taxonomy=snapshot,
            )
        # The file name holds the (private) chat title, so only its ID part is printed.
        # Plain "..." because a Windows console can't print the ellipsis character.
        shown = f"{path.parent.as_posix()}/... ({path.stem.rsplit('(', 1)[-1]}.md"
        return CommandResult(command, data={"note": shown}, message=f"wrote {shown}")
    else:
        if snapshot is None:
            return CommandResult(
                command,
                ExitCode.USAGE,
                message="a topic needs --taxonomy",
                error_code="no_taxonomy",
            )
        try:
            if args.template == "v2":
                # The readable layout (NOTE-010); v1 (DOC-005) stays the default.
                from knowledge_engine.documents.readable_master import (
                    write_readable_topic_master,
                )

                path = write_readable_topic_master(
                    session, args.topic, snapshot, args.vault, mode=Mode(args.mode)
                )
            else:
                path = write_topic_master(
                    session, args.topic, snapshot, args.vault, mode=Mode(args.mode)
                )
        except TopicNotFound as error:
            return CommandResult(command, ExitCode.USAGE, message=str(error), error_code="no_topic")
    return CommandResult(
        command, data={"note": path.as_posix()}, message=f"wrote {path.as_posix()}"
    )


def _docs(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """Build document contents and track dependencies, or list what a change affects (DOC-001)."""
    from sqlalchemy.orm import Session

    from knowledge_engine.documents.dependencies import affected_documents, register
    from knowledge_engine.documents.model import build_all
    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path

    db = database_path(settings)
    if not db.exists():
        return CommandResult(
            "docs", ExitCode.ERROR, message="no imports yet", error_code="no_imports"
        )
    engine = create_sqlite_engine(db)
    try:
        with Session(engine) as session:
            if args.docs_command == "project":
                from knowledge_engine.documents.render import Mode, write_project_master

                if args.template == "v2":
                    # The readable layout (NOTE-010); v1 (DOC-004) stays the default.
                    from knowledge_engine.documents.readable_master import (
                        write_readable_project_master,
                    )

                    path = write_readable_project_master(
                        session, args.project, args.vault, mode=Mode(args.mode)
                    )
                else:
                    path = write_project_master(
                        session, args.project, args.vault, mode=Mode(args.mode)
                    )
                return CommandResult(
                    "docs project",
                    data={"note": path.as_posix(), "mode": args.mode},
                    message=f"wrote {path.as_posix()}",
                )
            if args.docs_command in ("chat", "topic", "vault"):
                return _docs_note(settings, session, args)
            if args.docs_command == "affected":
                found = affected_documents(session, args.ids)
                return CommandResult(
                    "docs affected",
                    data={
                        "documents": [
                            {
                                "document_id": a.document_id,
                                "kind": a.kind.value,
                                "subject_id": a.subject_id,
                                "reasons": list(a.reasons),
                            }
                            for a in found
                        ]
                    },
                    message=f"{len(found)} document(s) to rebuild",
                )
            built = build_all(session)
            changed = [d for d in built if register(session, d).changed]
            session.commit()
    finally:
        engine.dispose()
    by_kind: dict[str, int] = {}
    for document in built:
        by_kind[document.kind.value] = by_kind.get(document.kind.value, 0) + 1
    return CommandResult(
        "docs build",
        data={
            "documents": len(built),
            "by_kind": by_kind,
            "changed": [d.document_id for d in changed],
            "unchanged": len(built) - len(changed),
        },
        message=f"{len(built)} document(s); {len(changed)} changed",
    )


def _state(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """What holds now or on a date, with the events behind it (REC-006); no text."""
    from datetime import UTC, datetime

    from sqlalchemy.orm import Session

    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
    from knowledge_engine.reconciliation.projection import project

    db = database_path(settings)
    if not db.exists():
        return CommandResult(
            "state", ExitCode.ERROR, message="no imports yet", error_code="no_imports"
        )

    def moment(text: str | None) -> datetime | None:
        if text is None:
            return None
        parsed = datetime.fromisoformat(text)
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)

    try:
        as_of_moment, known_at = moment(args.as_of), moment(args.known_at)
    except ValueError:
        return CommandResult(
            "state",
            ExitCode.USAGE,
            message="dates are ISO 8601, e.g. 2026-03-01",
            error_code="bad_date",
        )
    engine = create_sqlite_engine(db)
    try:
        with Session(engine) as session:
            found = project(
                session,
                as_of=as_of_moment.timestamp() if as_of_moment else None,
                known_at=known_at,
                project_id=args.project,
                conversation_id=args.conversation,
            )
    finally:
        engine.dispose()
    return CommandResult(
        "state",
        data={
            "entries": [{**asdict(e), "status": e.status.value} for e in found.entries],
            "proposals": [asdict(p) for p in found.proposals],
            "unresolved_conflicts": list(found.unresolved_conflicts),
        },
        message=f"{len(found.entries)} stated record(s); conflicts stay open, not decided by date",
    )


def _walk(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """Records connected to one record, each step with its origin (REC-007); no text."""
    from sqlalchemy.orm import Session

    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
    from knowledge_engine.reconciliation.graph import Direction, describe, walk

    db = database_path(settings)
    if not db.exists():
        return CommandResult(
            "walk", ExitCode.ERROR, message="no imports yet", error_code="no_imports"
        )
    engine = create_sqlite_engine(db)
    try:
        with Session(engine) as session:
            try:
                steps = walk(
                    session,
                    args.record,
                    kinds=args.kind or None,
                    depth=args.depth,
                    direction=Direction(args.direction),
                    include_closed=args.include_closed,
                )
            except KeyError:
                return CommandResult(
                    "walk", ExitCode.ERROR, message="no such record", error_code="unknown_record"
                )
    finally:
        engine.dispose()
    return CommandResult(
        "walk",
        data={"steps": [describe(s) for s in steps]},
        message=f"{len(steps) - 1} connected record(s)",
    )


def _timeline(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """Show decision events, oldest first; with --build, derive new ones first (REC-004/005)."""
    from sqlalchemy.orm import Session

    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
    from knowledge_engine.reconciliation.supersession import reconcile
    from knowledge_engine.reconciliation.timeline import build_events, timeline

    db = database_path(settings)
    if not db.exists():
        return CommandResult(
            "timeline", ExitCode.ERROR, message="no imports yet", error_code="no_imports"
        )
    engine = create_sqlite_engine(db)
    try:
        with Session(engine) as session:
            built: dict[str, object] = {}
            if args.build:
                replaced = reconcile(session)
                events = build_events(session)
                session.commit()
                built = {
                    "superseded": len(replaced.superseded),
                    "supersession_review_required": [
                        {"later": v.later, "earlier": v.earlier, "failed": list(v.failed)}
                        for v in replaced.review_required
                    ],
                    "events_added": events.added,
                }
            entries = timeline(session, [args.record] if args.record else None)
    finally:
        engine.dispose()
    return CommandResult(
        "timeline",
        data={**built, "events": [asdict(e) for e in entries]},
        message=f"{len(entries)} event(s); revoked events stay, marked",
    )


def _reconcile(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """Propose repeated claims, record links and conflicts in one go (REC-001..003); no text."""
    from sqlalchemy.orm import Session

    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
    from knowledge_engine.reconciliation.conflicts import conflicts, detect_conflicts
    from knowledge_engine.reconciliation.equivalence import propose_equivalences
    from knowledge_engine.reconciliation.relations import propose_links

    db = database_path(settings)
    if not db.exists():
        return CommandResult(
            "reconcile", ExitCode.ERROR, message="no imports yet", error_code="no_imports"
        )
    engine = create_sqlite_engine(db)
    try:
        with Session(engine) as session:
            same = propose_equivalences(session)
            links = propose_links(session)
            found = detect_conflicts(session)
            open_conflicts = len(conflicts(session))
            session.commit()
    finally:
        engine.dispose()
    return CommandResult(
        "reconcile",
        data={
            "duplicates_added": len(same.added),
            "links_added": links.by_predicate,
            "conflicts_added": len(found.added),
            "conflicts_unresolved": open_conflicts,
        },
        message="Proposals only: nothing merged, linked or resolved until a reviewer decides",
    )


def _duplicates(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """Propose, list and review records that may state the same claim (REC-001); no text."""
    from sqlalchemy.orm import Session

    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
    from knowledge_engine.reconciliation.equivalence import (
        EquivalenceError,
        State,
        equivalence_groups,
        pairs,
        propose_equivalences,
        review,
    )

    name = f"duplicates {args.duplicates_command}"
    db = database_path(settings)
    if not db.exists():
        return CommandResult(
            name, ExitCode.ERROR, message="no imports yet", error_code="no_imports"
        )
    engine = create_sqlite_engine(db)
    try:
        with Session(engine) as session:
            if args.duplicates_command == "detect":
                found = propose_equivalences(session)
                session.commit()
                return CommandResult(
                    name,
                    data={"added": list(found.added), "known": len(found.known)},
                    message=f"{len(found.added)} new pair(s) proposed; nothing merged",
                )
            if args.duplicates_command == "review":
                try:
                    review(
                        session,
                        args.pair,
                        State(args.decision),
                        reviewer=args.reviewer,
                        note=args.note,
                    )
                except KeyError:
                    return CommandResult(
                        name, ExitCode.ERROR, message="no such pair", error_code="unknown_pair"
                    )
                except EquivalenceError as error:
                    return CommandResult(
                        name, ExitCode.ERROR, message=str(error), error_code="refused"
                    )
                session.commit()
            states = [State(args.state)] if getattr(args, "state", None) else list(State)
            listed = [
                {
                    "pair_id": row.pair_id,
                    "records": [row.record_a, row.record_b],
                    "basis": row.basis,
                    "score": row.score,
                    "differences": json.loads(row.differences_json),
                    "state": row.state,
                }
                for row in pairs(session, states)
            ]
            groups = [list(group) for group in equivalence_groups(session)]
    finally:
        engine.dispose()
    return CommandResult(
        name,
        data={"pairs": listed, "groups": groups},
        message="Records that may state the same claim (confirmed pairs form groups)",
    )


def _conflicts(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """List and review records that cannot both hold (REC-008); IDs only, no text.

    ``ke reconcile`` finds conflicts and stores them unresolved; this is how a
    person works through them. A dismissed or resolved conflict stops making
    its records "conflicted" in ``ke state``, the timeline and answers.
    """
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
    from knowledge_engine.reconciliation.conflicts import (
        ConflictError,
        ConflictState,
        RecordConflictReviewRow,
        conflicts,
        review_conflict,
    )

    name = f"conflicts {args.conflicts_command}"
    db = database_path(settings)
    if not db.exists():
        return CommandResult(
            name, ExitCode.ERROR, message="no imports yet", error_code="no_imports"
        )
    engine = create_sqlite_engine(db)
    try:
        with Session(engine) as session:
            if args.conflicts_command == "review":
                # "reopen" is the person's word for going back to unresolved.
                to_state = {
                    "dismiss": ConflictState.DISMISSED,
                    "resolve": ConflictState.RESOLVED,
                    "reopen": ConflictState.UNRESOLVED,
                }[args.decision]
                try:
                    entry = review_conflict(
                        session, args.conflict, to_state, reviewer=args.reviewer, note=args.note
                    )
                except KeyError:
                    return CommandResult(
                        name,
                        ExitCode.USAGE,
                        message="no such conflict",
                        error_code="unknown_conflict",
                    )
                except ConflictError as error:
                    return CommandResult(
                        name, ExitCode.USAGE, message=str(error), error_code="refused"
                    )
                data = {
                    "conflict_id": args.conflict,
                    "from_state": entry.from_state,
                    "to_state": entry.to_state,
                }
                session.commit()
                return CommandResult(name, data=data, message="Review recorded")
            states = [ConflictState(args.state)] if args.state else list(ConflictState)
            listed = []
            for row in conflicts(session, states):
                reviews = session.scalars(
                    select(RecordConflictReviewRow)
                    .where(RecordConflictReviewRow.conflict_id == row.conflict_id)
                    .order_by(RecordConflictReviewRow.review_id)
                )
                listed.append(
                    {
                        "conflict_id": row.conflict_id,
                        "records": [row.record_a, row.record_b],
                        "kinds": json.loads(row.kinds_json),
                        "scope": json.loads(row.scope_json),
                        "evidence": json.loads(row.evidence_json),
                        "state": row.state,
                        # The note is the reviewer's own words, not chat text.
                        "history": [
                            {
                                "from_state": r.from_state,
                                "to_state": r.to_state,
                                "reviewer": r.reviewer,
                                "note": r.note,
                                "at": r.at.isoformat(),
                            }
                            for r in reviews
                        ],
                    }
                )
    finally:
        engine.dispose()
    return CommandResult(
        name,
        data={"conflicts": listed},
        message="Records that cannot both hold (review: dismiss, resolve or reopen)",
    )


def _record_links(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """List and review typed links between knowledge records (REC-008); IDs only, no text.

    ``ke reconcile`` proposes these links (creates, references, elaborates,
    same_project, depends_on) as candidates. A rejected link drops out of the
    notes and is only followed by ``ke walk --include-closed``.
    """
    from sqlalchemy import or_, select
    from sqlalchemy.orm import Session

    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
    from knowledge_engine.reconciliation.relations import (
        LinkError,
        LinkState,
        RecordLinkReviewRow,
        RecordLinkRow,
        review_link,
    )

    name = f"links {args.links_command}"
    db = database_path(settings)
    if not db.exists():
        return CommandResult(
            name, ExitCode.ERROR, message="no imports yet", error_code="no_imports"
        )
    engine = create_sqlite_engine(db)
    try:
        with Session(engine) as session:
            if args.links_command == "review":
                to_state = LinkState.ACCEPTED if args.decision == "accept" else LinkState.REJECTED
                try:
                    entry = review_link(
                        session, args.link, to_state, reviewer=args.reviewer, note=args.note
                    )
                except KeyError:
                    return CommandResult(
                        name, ExitCode.USAGE, message="no such link", error_code="unknown_link"
                    )
                except LinkError as error:
                    return CommandResult(
                        name, ExitCode.USAGE, message=str(error), error_code="refused"
                    )
                data = {
                    "link_id": args.link,
                    "from_state": entry.from_state,
                    "to_state": entry.to_state,
                }
                session.commit()
                return CommandResult(name, data=data, message="Review recorded")
            query = select(RecordLinkRow).order_by(RecordLinkRow.predicate, RecordLinkRow.link_id)
            if args.state:
                query = query.where(RecordLinkRow.state == args.state)
            if args.record:
                query = query.where(
                    or_(
                        RecordLinkRow.from_record == args.record,
                        RecordLinkRow.to_record == args.record,
                    )
                )
            listed = []
            for row in session.scalars(query):
                reviews = session.scalars(
                    select(RecordLinkReviewRow)
                    .where(RecordLinkReviewRow.link_id == row.link_id)
                    .order_by(RecordLinkReviewRow.review_id)
                )
                listed.append(
                    {
                        "link_id": row.link_id,
                        "from": row.from_record,
                        "predicate": row.predicate,
                        "to": row.to_record,
                        "detector": row.detector,
                        "evidence": json.loads(row.evidence_json),
                        "state": row.state,
                        "history": [
                            {
                                "from_state": r.from_state,
                                "to_state": r.to_state,
                                "reviewer": r.reviewer,
                                "note": r.note,
                                "at": r.at.isoformat(),
                            }
                            for r in reviews
                        ],
                    }
                )
    finally:
        engine.dispose()
    return CommandResult(
        name,
        data={"links": listed},
        message="Links between records (read as: from <predicate> to)",
    )


def _related_list(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """List conversation relationships with their evidence and history (REL-002)."""
    from sqlalchemy import or_, select
    from sqlalchemy.orm import Session

    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
    from knowledge_engine.relationships.store import ConversationRelationshipRow, history

    db = database_path(settings)
    if not db.exists():
        return CommandResult(
            "related list", ExitCode.ERROR, message="no imports yet", error_code="no_imports"
        )
    query = select(ConversationRelationshipRow).order_by(
        ConversationRelationshipRow.kind, ConversationRelationshipRow.relationship_id
    )
    if args.conversation:
        query = query.where(
            or_(
                ConversationRelationshipRow.from_conversation_id == args.conversation,
                ConversationRelationshipRow.to_conversation_id == args.conversation,
            )
        )
    if args.state:
        query = query.where(ConversationRelationshipRow.review_state == args.state)
    engine = create_sqlite_engine(db)
    try:
        with Session(engine) as session:
            items = [
                {
                    "relationship_id": row.relationship_id,
                    "from": row.from_conversation_id,
                    "kind": row.kind,
                    "to": row.to_conversation_id,
                    "evidence_class": row.evidence_class,
                    "confidence": row.confidence,
                    "review_state": row.review_state,
                    "detector": row.detector,
                    "evidence": json.loads(row.evidence_json),
                    "history": [
                        {
                            "action": h.action,
                            "from_state": h.from_state,
                            "to_state": h.to_state,
                            "reviewer": h.reviewer,
                            "note": h.note,
                            "at": h.at.isoformat(),
                        }
                        for h in history(session, row.relationship_id)
                    ],
                }
                for row in session.scalars(query)
            ]
    finally:
        engine.dispose()
    return CommandResult(
        "related list",
        data={"relationships": items},
        message="Links between conversations (read as: from <kind> to)",
    )


def _related_review(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """Record one review decision; the history is append-only."""
    from sqlalchemy.orm import Session

    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
    from knowledge_engine.relationships.store import (
        ConversationRelationshipRow,
        RelationKind,
        RelationshipError,
        ReviewAction,
        retype,
        review,
    )

    db = database_path(settings)
    if not db.exists():
        return CommandResult(
            "related review", ExitCode.ERROR, message="no imports yet", error_code="no_imports"
        )
    retyping = args.as_kind is not None or args.reverse
    if retyping and args.action != "accept":
        return CommandResult(
            "related review",
            ExitCode.USAGE,
            message="--as and --reverse only go with accept",
            error_code="usage",
        )
    engine = create_sqlite_engine(db)
    try:
        with Session(engine) as session, session.begin():
            try:
                if retyping:
                    old = session.get(ConversationRelationshipRow, args.relationship)
                    kind = RelationKind(args.as_kind or (old.kind if old else "related_to"))
                    new = retype(
                        session,
                        args.relationship,
                        kind,
                        reverse=args.reverse,
                        reviewer=args.reviewer,
                        note=args.note,
                    )
                    data = {
                        "relationship_id": args.relationship,
                        "to_state": "superseded",
                        "replaced_by": new.relationship_id,
                        "new": {
                            "from": new.from_conversation_id,
                            "kind": new.kind,
                            "to": new.to_conversation_id,
                        },
                    }
                else:
                    entry = review(
                        session,
                        args.relationship,
                        ReviewAction(args.action),
                        reviewer=args.reviewer,
                        note=args.note,
                    )
                    data = {
                        "relationship_id": args.relationship,
                        "from_state": entry.from_state,
                        "to_state": entry.to_state,
                    }
            except KeyError:
                return CommandResult(
                    "related review",
                    ExitCode.ERROR,
                    message="no such relationship",
                    error_code="unknown_relationship",
                )
            except RelationshipError as error:
                # Refused before anything was written, so leaving the block is safe.
                return CommandResult(
                    "related review", ExitCode.USAGE, message=str(error), error_code="refused"
                )
    finally:
        engine.dispose()
    return CommandResult("related review", data=data, message="Review recorded")


def _related_add(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """Store a link a person states by hand, already accepted (REL-006); IDs only."""
    from sqlalchemy.orm import Session

    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
    from knowledge_engine.relationships.store import RelationKind, RelationshipError, add_human

    db = database_path(settings)
    if not db.exists():
        return CommandResult(
            "related add", ExitCode.ERROR, message="no imports yet", error_code="no_imports"
        )
    engine = create_sqlite_engine(db)
    try:
        with Session(engine) as session:
            try:
                row = add_human(
                    session,
                    from_conversation_id=args.from_conversation,
                    kind=RelationKind(args.kind),
                    to_conversation_id=args.to_conversation,
                    reviewer=args.reviewer,
                    note=args.note,
                )
            except KeyError:
                return CommandResult(
                    "related add",
                    ExitCode.ERROR,
                    message="no such conversation",
                    error_code="unknown_conversation",
                )
            except RelationshipError as error:
                return CommandResult(
                    "related add", ExitCode.USAGE, message=str(error), error_code="refused"
                )
            data = {
                "relationship_id": row.relationship_id,
                "from": row.from_conversation_id,
                "kind": row.kind,
                "to": row.to_conversation_id,
                "evidence_class": row.evidence_class,
                "review_state": row.review_state,
            }
            session.commit()
    finally:
        engine.dispose()
    return CommandResult(
        "related add", data=data, message="Link recorded as accepted (read as: from <kind> to)"
    )


def _related_detect(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """Run the deterministic relationship detectors over the whole workspace."""
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
    from knowledge_engine.infrastructure.workspace import WorkspaceRow
    from knowledge_engine.relationships.detect import detect_relationships

    db = database_path(settings)
    if not db.exists():
        return CommandResult(
            "related detect", ExitCode.ERROR, message="no imports yet", error_code="no_imports"
        )
    engine = create_sqlite_engine(db)
    counts: dict[str, int] = {}
    try:
        with Session(engine) as session, session.begin():
            for workspace_id in session.scalars(select(WorkspaceRow.workspace_id)):
                found = detect_relationships(session, workspace_id=workspace_id, import_id=None)
                for key, value in found.items():
                    counts[key] = counts.get(key, 0) + value
    finally:
        engine.dispose()
    return CommandResult(
        "related detect", data={"new": dict(sorted(counts.items()))}, message="Detectors run"
    )


def _related_suggest(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """Propose related_to and same_project candidates from subjects and meaning (REL-003)."""
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
    from knowledge_engine.infrastructure.workspace import WorkspaceRow
    from knowledge_engine.relationships.related import suggest_related
    from knowledge_engine.taxonomy.registry import TaxonomyRegistry

    db = database_path(settings)
    if not db.exists():
        return CommandResult(
            "related suggest", ExitCode.ERROR, message="no imports yet", error_code="no_imports"
        )
    engine = create_sqlite_engine(db)
    counts: dict[str, int] = {}
    try:
        with Session(engine) as session, session.begin():
            snapshot = None
            if args.taxonomy:
                try:
                    snapshot = TaxonomyRegistry(session).snapshot(args.taxonomy)
                except KeyError:
                    return CommandResult(
                        "related suggest",
                        ExitCode.USAGE,
                        message="no such taxonomy version",
                        error_code="no_taxonomy",
                    )
            for workspace_id in session.scalars(select(WorkspaceRow.workspace_id)):
                found = suggest_related(
                    session, workspace_id=workspace_id, taxonomy=snapshot, egress=settings.egress
                )
                for key, value in found.items():
                    counts[key] = counts.get(key, 0) + value
    finally:
        engine.dispose()
    return CommandResult(
        "related suggest",
        data={"new": dict(sorted(counts.items()))},
        message=f"{sum(counts.values())} new suggestion(s); review them with ke related list",
    )


def _ui(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """Run the local web interface until Ctrl+C. Listens on 127.0.0.1 only."""
    import webbrowser

    from knowledge_engine.evaluation.report_labels import ReviewerKind
    from knowledge_engine.ui.app import serve
    from knowledge_engine.ui.evaluation import KeySource

    # The answer key is private and stays where it is; the evaluation pages
    # only read it. Who reviewed it must be said out loud (UI-006, LEG-002).
    key = None
    if args.gold is not None:
        if args.reviewer is None:
            return CommandResult(
                "ui",
                ExitCode.ERROR,
                message="--gold needs --reviewer (who checked the answer key)",
                error_code="reviewer_required",
            )
        if args.reviewer != "none" and args.review is None:
            return CommandResult(
                "ui",
                ExitCode.ERROR,
                message="a reviewed answer key needs --review (the review record)",
                error_code="review_required",
            )
        key = KeySource(args.gold, ReviewerKind(args.reviewer), args.review)
    try:
        server = serve(settings, port=args.port, answer_key=key)
    except OSError:
        return CommandResult(
            "ui",
            ExitCode.ERROR,
            message=f"port {args.port} is busy; try --port",
            error_code="port_busy",
        )
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"Knowledge Engine is open at {url} (Ctrl+C to stop)", flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return CommandResult("ui", data={"url": url}, message="Stopped the web interface")


def _api(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """Serve the JSON API until Ctrl+C. Listens on 127.0.0.1 only (API-001)."""
    try:
        import uvicorn

        from knowledge_engine.api.app import PREFIX, create_app
    except ImportError:
        return CommandResult(
            "api",
            ExitCode.ERROR,
            message='the API needs its extra: pip install -e ".[server]"',
            error_code="missing_dependency",
        )
    url = f"http://127.0.0.1:{args.port}{PREFIX}/docs"
    print(f"Knowledge Engine API at {url} (Ctrl+C to stop)", flush=True)
    # The host is fixed: the API never listens on the network.
    uvicorn.run(create_app(settings), host="127.0.0.1", port=args.port, log_level="warning")
    return CommandResult("api", data={"url": url}, message="Stopped the API")


def _inspect(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """Show stored conversations as counts only; optionally write a transcript note."""
    from sqlalchemy import func, select
    from sqlalchemy.orm import Session

    from knowledge_engine.importer.records import ConversationRow, MessageNodeRow
    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
    from knowledge_engine.rendering.transcript import (
        find_conversation,
        inspect_summary,
        load_conversation,
        write_transcript,
    )

    db = database_path(settings)
    if not db.exists():
        return CommandResult(
            "inspect", ExitCode.ERROR, message="no imports yet", error_code="no_imports"
        )
    engine = create_sqlite_engine(db)
    try:
        with Session(engine) as session:
            if args.conversation is None:
                rows = session.execute(
                    select(
                        ConversationRow.conversation_id,
                        ConversationRow.presence,
                        func.count(MessageNodeRow.node_key),
                    )
                    .outerjoin(
                        MessageNodeRow,
                        MessageNodeRow.conversation_id == ConversationRow.conversation_id,
                    )
                    .group_by(ConversationRow.conversation_id)
                    .order_by(ConversationRow.conversation_id)
                ).all()
                # IDs and counts only: titles are private.
                listing = [
                    {"conversation_id": cid, "presence": presence, "nodes": nodes}
                    for cid, presence, nodes in rows
                ]
                return CommandResult(
                    "inspect",
                    data={"conversations": listing, "count": len(listing)},
                    message="Stored conversations (IDs and counts only)",
                )
            conversation_id = find_conversation(session, args.conversation)
            if conversation_id is None:
                return CommandResult(
                    "inspect",
                    ExitCode.ERROR,
                    message="no such conversation",
                    error_code="not_found",
                )
            conversation = load_conversation(session, conversation_id)
            data = inspect_summary(conversation)
            if args.redact and data.get("native_conversation_id"):
                # Reports and gate checklists quote 8-character prefixes of
                # the export's own IDs, never the full ID (OPS-009).
                data["native_conversation_id"] = str(data["native_conversation_id"])[:8]
            if args.note is not None:
                path, broken = write_transcript(
                    session, conversation, args.note, settings.workspace_root / "archive"
                )
                # The file name holds the (private) title, so it isn't printed.
                data["note"] = f"{path.parent.as_posix()}/… ({path.stem.rsplit('(', 1)[-1]}.md"
                data["broken_embeds"] = len(broken)
    finally:
        engine.dispose()
    return CommandResult("inspect", data=data, message="Conversation structure (counts only)")


def _eval_smoke(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """Run the EVAL-010 batch smoke test in a fresh scratch workspace."""
    from datetime import UTC, datetime

    from knowledge_engine.evaluation.smoke import run_smoke
    from knowledge_engine.evaluation.synthetic import write_generated

    if (args.root is None) == (args.synthetic is None):
        return CommandResult(
            "eval smoke",
            ExitCode.USAGE,
            message="give a source folder or --synthetic N, not both",
            error_code="usage",
        )
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    base = settings.workspace_root / "smoke"
    if args.synthetic is not None:
        label = f"synthetic-{args.synthetic}-seed{args.seed}"
        root = write_generated(base / label, args.synthetic, args.seed) / "export"
        limit = None
    else:
        label = f"source-{args.limit or 'all'}"
        root, limit = args.root, args.limit
    scratch = settings.model_copy(update={"workspace_root": base / f"{label}-{stamp}"})
    report = run_smoke(root, scratch, limit=limit)
    report_path = base / f"{label}-{stamp}.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    data = {
        "conversations": report["conversations"],
        "timings_s": report["timings_s"],
        "peak_memory_mb": report["peak_memory_mb"],
        "checks": report["checks"],
        "warnings": report["first_import"]["warnings"],
        "report": report_path.name,
    }
    if not report["passed"]:
        return CommandResult(
            "eval smoke",
            ExitCode.ERROR,
            data=data,
            message="smoke test FAILED",
            error_code="failed",
        )
    return CommandResult("eval smoke", data=data, message="Smoke test passed")


def _eval_relationships(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """Score the workspace's relationship proposals against an answer key (EVAL-012).

    The key's quotes are checked against the archive first; a key that
    cites something the archive doesn't hold is not used to score.
    Nothing is written to the workspace.
    """
    from pydantic import ValidationError
    from sqlalchemy.orm import Session

    from knowledge_engine.evaluation.relationship_key import (
        check_evidence,
        load_key,
        proposals_from_db,
        score,
        to_dict,
        to_markdown,
    )
    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path

    name = "eval relationships"
    try:
        key = load_key(args.key)
    except (OSError, ValidationError) as error:
        return CommandResult(
            name,
            ExitCode.USAGE,
            message=f"answer key not usable: {type(error).__name__}",
            error_code="bad_key",
        )
    db = database_path(settings)
    if not db.exists():
        return CommandResult(
            name, ExitCode.ERROR, message="no imports yet", error_code="no_imports"
        )
    engine = create_sqlite_engine(db)
    try:
        with Session(engine) as session:
            problems = check_evidence(session, key)
            proposals = proposals_from_db(session)
    finally:
        engine.dispose()
    if problems:
        return CommandResult(
            name,
            ExitCode.ERROR,
            data={"problems": problems},
            message=f"{len(problems)} key evidence problem(s); fix the key before scoring",
            error_code="key_evidence_invalid",
        )
    result = score(key, proposals)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(to_markdown(key, result), encoding="utf-8")
    data = to_dict(key, result)
    measured = "n/a" if result.precision is None else f"{result.precision:.3f}"
    if not result.passed:
        return CommandResult(
            name,
            ExitCode.ERROR,
            data=data,
            message=f"FAIL: precision {measured}, below 0.90 (or nothing to score)",
            error_code="below_threshold",
        )
    return CommandResult(name, data=data, message=f"PASS: precision {measured}")


def _eval_links(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """Link, video and account counts for the first N chats (EVAL-010c); reads only."""
    from sqlalchemy.orm import Session

    from knowledge_engine.evaluation.link_counts import link_counts
    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path

    name = "eval links"
    db = database_path(settings)
    if not db.exists():
        return CommandResult(
            name, ExitCode.ERROR, message="no imports yet", error_code="no_imports"
        )
    engine = create_sqlite_engine(db)
    try:
        with Session(engine) as session:
            data = link_counts(session, args.limit)
    finally:
        engine.dispose()
    links, youtube, social = data["links"], data["youtube"], data["social"]
    return CommandResult(
        name,
        data=data,
        message=(
            f"{data['conversations']} chats: {links['occurrences']} links to "
            f"{links['distinct_targets']} targets, {youtube['distinct_videos']} videos "
            f"({youtube['mentions']} mentions), {social['distinct_accounts']} accounts, "
            f"{social['ambiguous_handles']} ambiguous @names"
        ),
    )


def _eval_review_reasons(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """Why a smoke run's answers went to review, by kind (#255); no model calls.

    Point ``KE_WORKSPACE_ROOT`` at the run's scratch folder
    (``<workspace>/smoke/semantic-...``). Nothing is written.
    """
    from sqlalchemy.orm import Session

    from knowledge_engine.evaluation.semantic_smoke import replay_review_reasons
    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path

    name = "eval review-reasons"
    db = database_path(settings)
    if not db.exists():
        return CommandResult(
            name, ExitCode.ERROR, message="no imports yet", error_code="no_imports"
        )
    engine = create_sqlite_engine(db)
    try:
        with Session(engine) as session:
            data = replay_review_reasons(session, args.limit)
            session.rollback()  # reading only: the replay's bookkeeping is thrown away
    finally:
        engine.dispose()
    summary = ", ".join(f"{k} {n}" for k, n in data["review_reasons"].items()) or "none"
    return CommandResult(
        name,
        data=data,
        message=f"{data['review_required']} of {data['segments']} in review; reasons: {summary}",
    )


def _eval_tokens(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """Estimated tokens per stage from the model ledger (OPS-010); counts only, no calls."""
    from sqlalchemy.orm import Session

    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
    from knowledge_engine.providers.ledger import token_estimates

    name = "eval tokens"
    db = database_path(settings)
    if not db.exists():
        return CommandResult(
            name, ExitCode.ERROR, message="no imports yet", error_code="no_imports"
        )
    engine = create_sqlite_engine(db)
    try:
        with Session(engine) as session:
            data = token_estimates(session)
    finally:
        engine.dispose()
    lines = [
        f"{family}: {n['requests']} requests ({n['cached']} answered, so re-runs are free), "
        f"~{n['input_tokens']} input and ~{n['output_tokens']} output tokens"
        for family, n in data.items()
        if n["requests"] or family != "other"
    ]
    return CommandResult(
        name,
        data=data,
        message="Estimated tokens (characters / 4, not a bill):\n" + "\n".join(lines),
    )


def _eval_semantic(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """Run the EVAL-011 semantic smoke test on a scratch copy, never the real database."""
    import sqlite3
    from contextlib import closing
    from datetime import UTC, datetime

    from sqlalchemy.orm import Session

    from knowledge_engine.evaluation.semantic_smoke import Faults, run_semantic_smoke
    from knowledge_engine.evaluation.synthetic import write_generated
    from knowledge_engine.importer import import_source
    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
    from knowledge_engine.infrastructure.logs import event_log

    provider = None
    if args.provider == "anthropic":
        # The paid path: synthetic chats only, a cap above zero, egress on.
        refusal = None
        if not args.synthetic:
            refusal = "the paid provider only runs on --synthetic conversations"
        elif args.max_cost_usd <= 0:
            refusal = "the paid provider needs --max-cost-usd above zero"
        elif not settings.egress.text_llm:
            refusal = "the paid provider needs [egress] text_llm = true in ke.toml"
        elif settings.limits.max_cost_usd_per_run <= 0:
            refusal = "the paid provider needs [limits] max_cost_usd_per_run above zero"
        if refusal:
            return CommandResult(
                "eval semantic", ExitCode.USAGE, message=refusal, error_code="refused"
            )
        from knowledge_engine.providers.anthropic_api import DEFAULT_MODEL, AnthropicProvider

        # Both caps hold: the one on the command line and the one in settings.
        cap = min(args.max_cost_usd, settings.limits.max_cost_usd_per_run)
        provider = AnthropicProvider(cap, model=args.model or DEFAULT_MODEL)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    base = settings.workspace_root / "smoke"
    label = f"semantic-synthetic-{args.synthetic}" if args.synthetic else f"semantic-{args.limit}"
    scratch = settings.model_copy(update={"workspace_root": base / f"{label}-{stamp}"})
    if args.synthetic:
        source = write_generated(base / f"{label}-src-{stamp}", args.synthetic, args.seed)
        import_source(source / "export", "smoke", settings=scratch)
        limit = args.synthetic
    else:
        real = database_path(settings)
        if not real.exists():
            return CommandResult(
                "eval semantic", ExitCode.ERROR, message="no imports yet", error_code="no_imports"
            )
        # Work on a copy: the smoke run writes fake answers and records.
        # SQLite's backup API copies a consistent snapshot, including
        # anything still in the write-ahead log; the source opens read-only.
        target = database_path(scratch)
        target.parent.mkdir(parents=True, exist_ok=True)
        with (
            closing(sqlite3.connect(real.resolve().as_uri() + "?mode=ro", uri=True)) as src,
            closing(sqlite3.connect(target)) as dst,
        ):
            src.backup(dst)
        limit = args.limit
    limits = settings.limits.model_copy(update={"max_model_calls_per_run": args.max_calls})
    engine = create_sqlite_engine(database_path(scratch))
    try:
        with Session(engine) as session:
            report = run_semantic_smoke(
                session,
                limit=limit,
                limits=limits,
                faults=Faults(invalid_every=args.invalid_every, silent_every=args.silent_every),
                log=event_log(scratch),
                provider=provider,
                egress=settings.egress,
            )
            session.commit()
    finally:
        engine.dispose()
    report_path = base / f"{label}-{stamp}.json"
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    data = {**report, "report": report_path.name}
    if not report["passed"]:
        return CommandResult(
            "eval semantic",
            ExitCode.ERROR,
            data=data,
            message="semantic smoke test FAILED",
            error_code="failed",
        )
    return CommandResult("eval semantic", data=data, message="Semantic smoke test passed")


def _not_built(name: str, ticket: str) -> Callable[[Settings, argparse.Namespace], CommandResult]:
    def handler(_settings: Settings, _args: argparse.Namespace) -> CommandResult:
        return CommandResult(
            name,
            ExitCode.NOT_IMPLEMENTED,
            data={"ticket": ticket},
            message=f"`ke {name}` is not built yet ({ticket}).",
            error_code="not_implemented",
        )

    return handler


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for every ``ke`` command.

    Returns:
        The configured parser (it raises instead of exiting on errors).
    """
    parser = _Parser(
        prog="ke", description="Knowledge Engine: local, provenance-first chat archive."
    )
    parser.add_argument("--version", action="version", version=f"ke {__version__}")
    parser.add_argument("--config", type=Path, help="TOML config file (default: none)")
    parser.add_argument("--json", action="store_true", help="print one JSON object instead of text")
    commands = parser.add_subparsers(dest="command", metavar="COMMAND", parser_class=_Parser)

    status = commands.add_parser("status", help="show settings and database state")
    status.set_defaults(handler=_status)

    db = commands.add_parser("db", help="database maintenance")
    db_commands = db.add_subparsers(dest="db_command", metavar="ACTION", parser_class=_Parser)
    upgrade = db_commands.add_parser(
        "upgrade", help="apply pending migrations (backs up first when there are any)"
    )
    upgrade.add_argument(
        "--backup-to", type=Path, help="backup folder (default: <workspace>-backups next to it)"
    )
    upgrade.add_argument("--no-backup", action="store_true", help="migrate without a backup")
    upgrade.set_defaults(handler=_db_upgrade)

    raw = commands.add_parser("raw", help="read-only views of raw source folders")
    raw_commands = raw.add_subparsers(dest="raw_command", metavar="ACTION", parser_class=_Parser)
    inv = raw_commands.add_parser("inventory", help="list a raw folder or ZIP, metadata only")
    inv.add_argument("root", type=Path, help="raw folder or export ZIP (never modified)")
    inv.add_argument(
        "--show-names", action="store_true", help="show real file names (local use only)"
    )
    inv.set_defaults(handler=_inventory)

    imports = commands.add_parser("imports", help="past imports and their reports")
    imports_commands = imports.add_subparsers(
        dest="imports_command", metavar="ACTION", parser_class=_Parser
    )
    report = imports_commands.add_parser("report", help="show a stored import report")
    report.add_argument(
        "which", nargs="?", default="latest", help="`latest` (default) or an import ID"
    )
    report.set_defaults(handler=_imports_report)
    candidates = imports_commands.add_parser(
        "candidates", help="chats whose ID is missing or taken, waiting for a decision"
    )
    candidates.add_argument(
        "--status", choices=["review_required", "accepted", "rejected"], help="only this status"
    )
    candidates.set_defaults(handler=_imports_candidates)
    candidates_commands = candidates.add_subparsers(
        dest="candidates_command", metavar="ACTION", parser_class=_Parser
    )
    cand_review = candidates_commands.add_parser(
        "review", help="accept (import under an ID made from its content) or reject"
    )
    cand_review.add_argument("candidate", help="the candidate ID")
    cand_review.add_argument("decision", choices=["accept", "reject"])
    cand_review.add_argument("--reviewer", required=True, help="who decided")
    cand_review.set_defaults(handler=_imports_candidates)

    inspect = commands.add_parser(
        "inspect",
        help="browse stored conversations (read-only)",
        description=(
            "Counts only, never text or titles. The export's own conversation ID is printed "
            "in full, because this is a local debugging tool; use --redact for anything "
            "that goes into a report, issue or checklist."
        ),
    )
    inspect.add_argument(
        "conversation", nargs="?", help="a conv_ ID or the export's conversation ID"
    )
    inspect.add_argument(
        "--redact",
        action="store_true",
        help="print only the first 8 characters of the export's conversation ID",
    )
    inspect.add_argument(
        "--note", type=Path, metavar="VAULT", help="also write a source transcript note here"
    )
    inspect.set_defaults(handler=_inspect)

    evaluation = commands.add_parser("eval", help="evaluation runs")
    eval_commands = evaluation.add_subparsers(
        dest="eval_command", metavar="ACTION", parser_class=_Parser
    )
    smoke = eval_commands.add_parser(
        "smoke", help="import, re-import and render a batch in a scratch workspace"
    )
    smoke.add_argument("root", nargs="?", type=Path, help="export folder or ZIP (only read)")
    smoke.add_argument("--synthetic", type=int, metavar="N", help="generate N fake conversations")
    smoke.add_argument("--seed", type=int, default=1, help="seed for --synthetic (default 1)")
    smoke.add_argument("--limit", type=int, metavar="N", help="import only the first N")
    smoke.set_defaults(handler=_eval_smoke)
    semantic = eval_commands.add_parser(
        "semantic",
        help="segment, classify and extract a batch with a local fake model, on a scratch copy",
    )
    semantic.add_argument("--limit", type=int, default=50, help="first N imported conversations")
    semantic.add_argument("--synthetic", type=int, metavar="N", help="use N fake conversations")
    semantic.add_argument("--seed", type=int, default=1, help="seed for --synthetic (default 1)")
    semantic.add_argument("--max-calls", type=int, default=10_000, help="model call budget")
    semantic.add_argument("--invalid-every", type=int, default=7, help="every Nth answer is broken")
    semantic.add_argument("--silent-every", type=int, default=13, help="every Nth never answers")
    semantic.add_argument(
        "--provider",
        choices=("fake", "anthropic"),
        default="fake",
        help=(
            "anthropic = the paid API (needs --synthetic, --max-cost-usd, "
            "[egress] text_llm and [limits] max_cost_usd_per_run)"
        ),
    )
    semantic.add_argument("--model", help="pinned model for --provider anthropic")
    semantic.add_argument(
        "--max-cost-usd", type=float, default=0.0, help="hard cost cap for --provider anthropic"
    )
    semantic.set_defaults(handler=_eval_semantic)
    links_eval = eval_commands.add_parser(
        "links",
        help="link, YouTube and social-account counts for the first N chats (no text, no calls)",
    )
    links_eval.add_argument("--limit", type=int, default=100, help="first N chats (default 100)")
    links_eval.set_defaults(handler=_eval_links)
    reasons = eval_commands.add_parser(
        "review-reasons",
        help="why classifications went to review, counted by kind (no text, no model calls)",
    )
    reasons.add_argument("--limit", type=int, help="the run's conversation count (default all)")
    reasons.set_defaults(handler=_eval_review_reasons)
    eval_commands.add_parser(
        "tokens", help="estimated tokens per stage from the model ledger (no calls)"
    ).set_defaults(handler=_eval_tokens)
    relationships_eval = eval_commands.add_parser(
        "relationships",
        help="score proposed links between chats against an independent answer key",
    )
    relationships_eval.add_argument(
        "--key", type=Path, required=True, help="relationship answer key (JSON, relkey-v1)"
    )
    relationships_eval.add_argument("--out", type=Path, help="write the Markdown report here")
    relationships_eval.set_defaults(handler=_eval_relationships)

    retrieval_bench = eval_commands.add_parser(
        "retrieval", help="the pinned retrieval benchmark: words vs meaning vs combined"
    )
    retrieval_bench.add_argument("--out", type=Path, help="write the Markdown report here")
    retrieval_bench.set_defaults(handler=_eval_retrieval)
    fidelity = eval_commands.add_parser(
        "fidelity", help="import every fixture and check no node is lost without a warning"
    )
    fidelity.add_argument(
        "--fixtures",
        type=Path,
        default=Path("tests/fixtures/chatgpt"),
        help="folder of fixture cases (default: the repository's synthetic fixtures)",
    )
    fidelity.add_argument("--out", type=Path, help="write the Markdown report here")
    fidelity.set_defaults(handler=_eval_fidelity)
    temporal = eval_commands.add_parser(
        "temporal", help="check later statements never wrongly replace earlier decisions"
    )
    temporal.add_argument(
        "--fixtures",
        type=Path,
        default=Path("tests/fixtures/chatgpt"),
        help="folder of fixture cases (default: the repository's synthetic fixtures)",
    )
    temporal.add_argument("--out", type=Path, help="write the Markdown report here")
    temporal.set_defaults(handler=_eval_temporal)
    e2e = eval_commands.add_parser(
        "e2e", help="run a ZIP all the way to a vault and check every link in it"
    )
    e2e.add_argument(
        "--fixture",
        type=Path,
        default=Path("tests/fixtures/e2e/export.zip"),
        help="the export ZIP (default: the repository's synthetic one)",
    )
    e2e.add_argument(
        "--golden",
        type=Path,
        default=Path("tests/fixtures/e2e/vault_golden.json"),
        help="the expected vault shape to compare with",
    )
    e2e.add_argument(
        "--update-golden",
        action="store_true",
        help="write the vault shape as the new golden (review the diff before committing)",
    )
    e2e.set_defaults(handler=_eval_e2e)
    variance = eval_commands.add_parser(
        "variance", help="check the same chats give the same answers in any order"
    )
    variance.add_argument(
        "--fixtures",
        type=Path,
        default=Path("tests/fixtures"),
        help="the fixtures folder (default: the repository's)",
    )
    variance.set_defaults(handler=_eval_variance)
    gate = eval_commands.add_parser(
        "gate", help="run every evaluation once: PASS, FAIL, REVIEW or BLOCKED for each"
    )
    gate.add_argument(
        "--fixtures",
        type=Path,
        default=Path("tests/fixtures"),
        help="the fixtures folder (default: the repository's)",
    )
    gate.add_argument("--out", type=Path, help="write the Markdown report here")
    gate.add_argument("--commit", help="the commit the report describes (for the record)")
    gate.set_defaults(handler=_eval_gate)

    transcript = commands.add_parser("transcript", help="YouTube video transcripts")
    transcript_commands = transcript.add_subparsers(
        dest="transcript_command", metavar="ACTION", parser_class=_Parser
    )
    attach = transcript_commands.add_parser(
        "add", help="attach a transcript file you have (VTT, SRT or text) to a linked video"
    )
    attach.add_argument("video", help="the 11-character YouTube video ID")
    attach.add_argument("file", type=Path, help="the transcript file (only read)")
    attach.add_argument("--format", choices=["auto", "vtt", "srt", "text"], default="auto")
    attach.add_argument("--language", help="language tag, e.g. en")
    attach.add_argument("--source-url", help="where the file came from")
    attach.add_argument("--note", help="a short note on where it came from")
    attach.set_defaults(handler=_transcript_add)
    fetch_cmd = transcript_commands.add_parser(
        "fetch",
        help="ask the YouTube Data API for captions (transcript_fetch on, your own token)",
    )
    fetch_cmd.add_argument("video", help="the 11-character YouTube video ID")
    fetch_cmd.add_argument("--language", help="preferred language tag, e.g. en")
    fetch_cmd.set_defaults(handler=_transcript_fetch)
    status_cmd = transcript_commands.add_parser("status", help="a video's transcript status")
    status_cmd.add_argument("video", help="the 11-character YouTube video ID")
    status_cmd.set_defaults(handler=_transcript_status)
    cue_find = transcript_commands.add_parser(
        "find", help="find words in attached transcripts (with the chats citing each video)"
    )
    cue_find.add_argument("words", help="every word must appear in the line")
    cue_find.add_argument("--limit", type=int, default=20, help="at most this many lines")
    cue_find.set_defaults(handler=_transcript_find)

    accounts = commands.add_parser("accounts", help="social accounts mentioned in your chats")
    accounts.add_argument("--platform", help="only this platform, e.g. github")
    accounts.add_argument(
        "--ambiguous", action="store_true", help="list bare @handles with no platform instead"
    )
    accounts.add_argument("--all", action="store_true", help="include rejected accounts")
    accounts.set_defaults(handler=_accounts)
    accounts_commands = accounts.add_subparsers(
        dest="accounts_command", metavar="ACTION", parser_class=_Parser
    )
    acct_review = accounts_commands.add_parser(
        "review", help="confirm or reject who an account is (kept in its history)"
    )
    acct_review.add_argument("account", help="the acct_ ID")
    acct_review.add_argument("decision", choices=["confirm", "reject"])
    acct_review.add_argument("--reviewer", required=True, help="who decided")
    acct_review.add_argument("--note", help="why")
    acct_review.set_defaults(handler=_accounts)
    acct_link = accounts_commands.add_parser(
        "link", help="file an ambiguous @handle mention under an account"
    )
    acct_link.add_argument("mention", help="the amen_ ID (from `ke accounts --ambiguous`)")
    acct_link.add_argument("account", help="the acct_ ID")
    acct_link.add_argument("--reviewer", required=True, help="who decided")
    acct_link.add_argument("--note", help="why")
    acct_link.set_defaults(handler=_accounts)

    segments = commands.add_parser("segments", help="a chat's topic segments (no text shown)")
    segments.add_argument("conversation", help="the conv_ ID")
    segments.add_argument("--split", metavar="MESSAGE", help="start a segment at this message")
    segments.add_argument("--merge", metavar="MESSAGE", help="join the segment starting here")
    segments.add_argument("--clear", metavar="MESSAGE", help="forget the decision at this message")
    segments.add_argument("--reviewer", help="who decided (required with a decision)")
    segments.add_argument("--note", help="why")
    segments.set_defaults(handler=_segments)
    corpus = commands.add_parser(
        "corpus", help="segment counts and a seeded sample of segment IDs (no text shown)"
    )
    corpus.add_argument("--sample", type=int, default=0, help="how many segments to sample")
    corpus.add_argument("--seed", default="nrm-006", help="same seed, same sample")
    corpus.set_defaults(handler=_corpus)
    gold = commands.add_parser("gold", help="golden answer keys for evaluation")
    gold_commands = gold.add_subparsers(dest="gold_command", required=True)
    template = gold_commands.add_parser(
        "template", help="start a private golden set (IDs only) in the workspace"
    )
    template.add_argument("--count", type=int, default=40, help="conversations (30 to 50)")
    template.add_argument("--seed", default="golden-v1", help="same seed, same choice")
    template.add_argument("--taxonomy", required=True, help="taxonomy version to label against")
    template.add_argument("--annotator", default="reviewer", help="who will annotate")
    template.set_defaults(handler=_gold_template)
    score = gold_commands.add_parser(
        "score", help="score this workspace's records against a private answer key (numbers only)"
    )
    score.add_argument("--gold", type=Path, required=True, help="the answer key JSON")
    score.add_argument(
        "--reviewer",
        choices=["owner", "ai_session", "same_model", "none"],
        required=True,
        help="who reviewed the key (printed on the report)",
    )
    score.add_argument("--review", type=Path, help="the review record (its hash is printed)")
    score.add_argument("--out", type=Path, help="write the Markdown report here")
    score.add_argument(
        "--no-rules", action="store_true", help="don't run the rule extractors first"
    )
    score.add_argument(
        "--count-as",
        action="append",
        metavar="KEY_TYPE=PRODUCED_TYPE",
        help="also count a produced type as the key's type, e.g. idea=proposal (repeatable)",
    )
    score.set_defaults(handler=_gold_score)
    convert = gold_commands.add_parser(
        "convert", help="turn a per-chat answer key folder into one golden set (reads it only)"
    )
    convert.add_argument("--key", type=Path, required=True, help="the per-chat key folder")
    convert.add_argument("--name", default="answer-key-v2", help="the golden set's name")
    convert.add_argument("--out", type=Path, help="where to write it (default: workspace gold/)")
    convert.add_argument("--taxonomy", default="none", help="recorded on the set (no labels)")
    convert.add_argument(
        "--annotator", default="answer-key", help="who wrote the key, as scores credit it"
    )
    convert.set_defaults(handler=_gold_convert)
    gold_commands.add_parser("schema", help="print the golden set JSON Schema").set_defaults(
        handler=_gold_schema
    )
    access = commands.add_parser("access", help="accounts, API tokens and workspace roles")
    access_commands = access.add_subparsers(dest="access_command", required=True)
    access_add = access_commands.add_parser("add", help="add an account (turns API checks on)")
    access_add.add_argument("name")
    access_add.add_argument(
        "--service", action="store_true", help="a program, not a person (viewer/editor only)"
    )
    for sub, text in (
        ("token", "make a new API token (shown once)"),
        ("revoke", "revoke all of an account's tokens"),
        ("disable", "stop an account logging in"),
        ("rotate", "revoke all tokens and make one new one"),
    ):
        access_commands.add_parser(sub, help=text).add_argument("name")
    access_delete = access_commands.add_parser(
        "delete", help="erase an account, its tokens and roles (the log keeps only an ID)"
    )
    access_delete.add_argument("name")
    access_delete.add_argument("--confirm", required=True, help="the account name again")
    access_grant = access_commands.add_parser("grant", help="give an account a role")
    access_grant.add_argument("name")
    access_grant.add_argument("role", choices=["viewer", "editor", "reviewer", "owner"])
    access_remove = access_commands.add_parser("remove", help="take an account out of a workspace")
    access_remove.add_argument("name")
    for scoped in (access_grant, access_remove):
        scoped.add_argument(
            "--workspace", default="default", help="workspace name (default: default)"
        )
    access_commands.add_parser("list", help="accounts and their roles (no tokens)")
    access_log = access_commands.add_parser("log", help="the authorisation log, newest first")
    access_log.add_argument("--limit", type=int, default=50)
    access.set_defaults(handler=_access)

    tenant = commands.add_parser(
        "tenant", help="separate workspaces served by `ke api` (needs tenants_root)"
    )
    tenant_commands = tenant.add_subparsers(dest="tenant_command", required=True)
    tenant_add = tenant_commands.add_parser("add", help="create a workspace and its owner")
    tenant_add.add_argument("name", help="letters, digits, '-' and '_'")
    tenant_add.add_argument("--owner", required=True, help="the owner's account name")
    tenant_commands.add_parser("list", help="created workspaces")
    tenant_delete = tenant_commands.add_parser(
        "delete", help="erase a whole workspace and its inbox (cannot be undone)"
    )
    tenant_delete.add_argument("name")
    tenant_delete.add_argument("--confirm", required=True, help="the workspace name again")
    tenant.set_defaults(handler=_tenant)

    purge = commands.add_parser(
        "purge", help="delete whole conversations and everything made from them"
    )
    purge_commands = purge.add_subparsers(dest="purge_command", required=True)
    purge_plan = purge_commands.add_parser(
        "plan", help="list what a purge would delete, and its token (reads only)"
    )
    purge_plan.add_argument("conversations", nargs="+", help="conv_ IDs or native IDs")
    purge_plan.set_defaults(handler=_purge)
    purge_run = purge_commands.add_parser(
        "run", help="purge, leave tombstones and check nothing is left"
    )
    purge_run.add_argument("conversations", nargs="+", help="the same IDs as the plan")
    purge_run.add_argument("--confirm", required=True, help="the token `ke purge plan` printed")
    purge_run.add_argument("--reason", required=True, help="why, for the audit log")
    purge_run.add_argument("--vault", type=Path, help="a vault to re-sync afterwards")
    purge_run.add_argument("--taxonomy", help="the taxonomy version that vault uses")
    purge_run.set_defaults(handler=_purge)
    purge_commands.add_parser("log", help="every purge so far (counts only)").set_defaults(
        handler=_purge
    )
    backup = commands.add_parser("backup", help="back up, verify and restore the workspace")
    backup_commands = backup.add_subparsers(dest="backup_command", required=True)
    backup_create = backup_commands.add_parser(
        "create", help="write a new backup folder (database and original files)"
    )
    backup_create.add_argument("--to", type=Path, required=True, help="where backups are kept")
    backup_create.set_defaults(handler=_backup)
    backup_verify = backup_commands.add_parser(
        "verify", help="re-check every file and row count in a backup"
    )
    backup_verify.add_argument("folder", type=Path, help="the backup folder")
    backup_verify.set_defaults(handler=_backup)
    backup_restore = backup_commands.add_parser(
        "restore", help="restore a backup into an empty folder and check it"
    )
    backup_restore.add_argument("folder", type=Path, help="the backup folder")
    backup_restore.add_argument("--to", type=Path, required=True, help="an empty folder")
    backup_restore.set_defaults(handler=_backup)
    bundle = commands.add_parser("bundle", help="export one project as a ZIP, or check one")
    bundle_commands = bundle.add_subparsers(dest="bundle_command", required=True)
    bundle_export = bundle_commands.add_parser(
        "export", help="write a project's notes, records and evidence to one ZIP"
    )
    bundle_export.add_argument("project", help="an approved project ID")
    bundle_export.add_argument("--to", type=Path, required=True, help="the .zip file to write")
    bundle_export.add_argument(
        "--with-transcripts", action="store_true", help="also include the chats' full text"
    )
    bundle_export.set_defaults(handler=_bundle)
    for action, text in (
        ("verify", "check every member and quote hash and the member names"),
        ("show", "count a bundle's records by type and status (no text)"),
    ):
        bundle_action = bundle_commands.add_parser(action, help=text)
        bundle_action.add_argument("file", type=Path, help="the bundle .zip")
        bundle_action.set_defaults(handler=_bundle)
    digest = commands.add_parser(
        "digest", help="summarise chats through request files a Claude session answers"
    )
    digest_commands = digest.add_subparsers(dest="digest_command", required=True)
    digest_run = digest_commands.add_parser(
        "run", help="write digest requests, or collect answers and write notes (run again)"
    )
    digest_run.add_argument("conversations", nargs="*", help="conv_ or export conversation IDs")
    digest_run.add_argument("--all", action="store_true", help="every imported chat")
    digest_run.add_argument("--run-id", required=True, help="the batch folder name, e.g. gold-40")
    digest_run.add_argument("--vault", type=Path, help="write each finished chat's rich note here")
    digest_run.add_argument(
        "--taxonomy", help="label notes under this published version (default: the newest)"
    )
    digest.set_defaults(handler=_digest)
    classify = commands.add_parser(
        "classify", help="label chats under a published taxonomy through request files"
    )
    classify_commands = classify.add_subparsers(dest="classify_command", required=True)
    classify_run = classify_commands.add_parser(
        "run", help="write classification requests, or collect answers (run again)"
    )
    classify_run.add_argument("conversations", nargs="*", help="conv_ or export conversation IDs")
    classify_run.add_argument("--ids-file", type=Path, help="a file with one chat ID per line")
    classify_run.add_argument("--all", action="store_true", help="every imported chat")
    classify_run.add_argument("--taxonomy", required=True, help="the published version, e.g. tax-1")
    classify_run.add_argument("--run-id", required=True, help="the batch folder name, e.g. gold-40")
    classify_review = classify_commands.add_parser(
        "review", help="send segments waiting for review to a reviewer session"
    )
    classify_review.add_argument(
        "--taxonomy", required=True, help="the published version, e.g. tax-1"
    )
    classify_review.add_argument(
        "--run-id", required=True, help="the batch folder name, e.g. review-1"
    )
    classify.set_defaults(handler=_classify)
    extract = commands.add_parser(
        "extract", help="find decisions, suggestions and questions through request files"
    )
    extract_commands = extract.add_subparsers(dest="extract_command", required=True)
    extract_run = extract_commands.add_parser(
        "run", help="write extraction requests, or collect answers and store records (run again)"
    )
    extract_run.add_argument("conversations", nargs="*", help="conv_ or export conversation IDs")
    extract_run.add_argument("--ids-file", type=Path, help="a file with one chat ID per line")
    extract_run.add_argument("--all", action="store_true", help="every imported chat")
    extract_run.add_argument("--run-id", required=True, help="the batch folder name, e.g. gold-40")
    extract.set_defaults(handler=_extract)
    web = commands.add_parser("web", help="fetch web pages (allowlisted, network_fetch on)")
    web_commands = web.add_subparsers(dest="web_command", required=True)
    web_fetch = web_commands.add_parser("fetch", help="fetch one page into located blocks")
    web_fetch.add_argument("url")
    web_fetch.add_argument("--save", action="store_true", help="keep the page's bytes by hash")
    web.set_defaults(handler=_web)
    file_parser = commands.add_parser("file", help="read a note, text, Word or PDF file")
    file_commands = file_parser.add_subparsers(dest="file_command", required=True)
    file_read = file_commands.add_parser(
        "read", help="show a file's blocks, headings and warnings (reads only)"
    )
    file_read.add_argument("path", type=Path, help="a .md, .markdown, .txt, .docx or .pdf file")
    file_read.add_argument("--blocks", action="store_true", help="list every block's location")
    file_read.set_defaults(handler=_file_read)
    logs = commands.add_parser("logs", help="search the run log by ID (no private text)")
    logs.add_argument("--stage-key", help="one stage key's whole lineage")
    logs.add_argument("--job-id", help="one job's events")
    logs.add_argument("--segment-id", help="one segment's events")
    logs.add_argument("--event", help="one event name, e.g. model.repair")
    logs.add_argument("--limit", type=int, default=200, help="newest events to show")
    logs.set_defaults(handler=_logs)
    taxonomy = commands.add_parser("taxonomy", help="the shared vocabulary")
    taxonomy_commands = taxonomy.add_subparsers(dest="taxonomy_command", required=True)
    tax_report = taxonomy_commands.add_parser(
        "report", help="duplicates, parent loops, orphans and review activity (read-only)"
    )
    tax_report.set_defaults(handler=_taxonomy_report)
    # NOTE-006: bootstrap the first taxonomy (proposer and reviewer are separate sessions).
    tax_pack = taxonomy_commands.add_parser(
        "pack", help="write a private sample pack for the proposer session"
    )
    tax_pack.add_argument("--out", type=Path, required=True, help="inside a private folder")
    tax_pack.add_argument("--sample", type=int, default=300, help="segments to sample")
    tax_pack.add_argument("--seed", default="tax-v1", help="same seed, same sample")
    tax_pack.set_defaults(handler=_taxonomy_bootstrap)
    tax_propose = taxonomy_commands.add_parser(
        "propose", help="file a proposer's plan as proposals (run again after each review)"
    )
    tax_propose.add_argument("plan", type=Path, help="the plan JSON")
    tax_propose.add_argument("--pack", type=Path, required=True, help="the pack it was written for")
    tax_propose.set_defaults(handler=_taxonomy_bootstrap)
    tax_sheet = taxonomy_commands.add_parser(
        "sheet", help="write the open proposals for a reviewer"
    )
    tax_sheet.add_argument("--out", type=Path, required=True, help="inside a private folder")
    tax_sheet.set_defaults(handler=_taxonomy_bootstrap)
    tax_review = taxonomy_commands.add_parser(
        "review", help="apply a reviewer's decisions (never the proposer's own)"
    )
    tax_review.add_argument("review", type=Path, help="the review JSON")
    tax_review.set_defaults(handler=_taxonomy_bootstrap)
    tax_summary = taxonomy_commands.add_parser(
        "summary", help="write a one-page summary of the vocabulary for the owner"
    )
    tax_summary.add_argument("--out", type=Path, required=True, help="inside a private folder")
    tax_summary.set_defaults(handler=_taxonomy_bootstrap)
    tax_publish = taxonomy_commands.add_parser(
        "publish", help="freeze the approved vocabulary as a version (the owner's decision)"
    )
    tax_publish.add_argument("version", help="e.g. tax-1")
    tax_publish.add_argument("--author", required=True, help="who decided to publish")
    tax_publish.add_argument("--note", help="why")
    tax_publish.set_defaults(handler=_taxonomy_bootstrap)
    # NOTE-014: keep the vocabulary up to date as new chats arrive.
    tax_refresh = taxonomy_commands.add_parser(
        "refresh",
        help="file new topic candidates and count uncovered chats; --out writes a pack of them",
    )
    tax_refresh.add_argument("--out", type=Path, help="write a refresh pack (private folder)")
    tax_refresh.add_argument("--taxonomy", help="the version to refresh (default: newest)")
    tax_refresh.add_argument("--sample", type=int, default=150, help="segments to sample")
    tax_refresh.add_argument("--seed", default="refresh", help="same seed, same sample")
    tax_refresh.set_defaults(handler=_taxonomy_refresh)
    tax_relabel = taxonomy_commands.add_parser(
        "relabel", help="after a publish: relabel only what the new version changes"
    )
    tax_relabel.add_argument("old", help="the version the labels came from, e.g. tax-1")
    tax_relabel.add_argument("new", help="the version just published, e.g. tax-2")
    tax_relabel.add_argument("--run-id", help="ask a Claude session through request files")
    tax_relabel.add_argument("--vault", type=Path, help="then update the notes in this vault")
    tax_relabel.set_defaults(handler=_taxonomy_relabel)

    search = commands.add_parser("search", help="find messages by words, phrase or exact text")
    search.add_argument("query", help="what to look for")
    search.add_argument(
        "--mode",
        choices=["tokens", "phrase", "exact"],
        default="tokens",
        help="tokens: all words, any order (default); phrase: words in order; "
        "exact: character for character, case included",
    )
    search.add_argument("--limit", type=int, default=20, help="at most this many hits")
    search.add_argument("--conversation", help="only this conv_ ID")
    search.add_argument("--since", help="only messages on or after this day (YYYY-MM-DD, UTC)")
    search.add_argument("--until", help="only messages on or before this day (YYYY-MM-DD, UTC)")
    search.add_argument(
        "--role", choices=["user", "assistant", "tool", "system"], help="only this speaker"
    )
    search.add_argument(
        "--term", help="only messages in segments labelled with this term_ or project ID"
    )
    search.add_argument(
        "--taxonomy", help="the published version --term is checked in (default: the newest)"
    )
    search.set_defaults(handler=_search)

    similar = commands.add_parser("similar", help="find messages close in meaning (local)")
    similar.add_argument("query", help="what to look for")
    similar.add_argument("--limit", type=int, default=20, help="at most this many hits")
    similar.add_argument("--conversation", help="only this conv_ ID")
    similar.add_argument(
        "--rebuild", action="store_true", help="rebuild an index made by another embedder"
    )
    similar.set_defaults(handler=_similar)

    find = commands.add_parser(
        "find", help="ask a question; picks decision records, exact or combined search"
    )
    find.add_argument("question", help="the question or text to look for")
    find.add_argument("--limit", type=int, default=20, help="at most this many results")
    find.add_argument(
        "--as-of", type=float, help="decision questions: the state at this time (epoch seconds)"
    )
    find.add_argument(
        "--rebuild", action="store_true", help="rebuild a meaning index made by another embedder"
    )
    find.set_defaults(handler=_find)

    ask = commands.add_parser(
        "ask", help="answer from your chats, citing every sentence (or say it doesn't know)"
    )
    ask.add_argument("question", help="the question")
    ask.add_argument("--limit", type=int, default=8, help="at most this many pieces of evidence")
    ask.add_argument(
        "--as-of", type=float, help="decision questions: the state at this time (epoch seconds)"
    )
    ask.add_argument(
        "--rebuild", action="store_true", help="rebuild a meaning index made by another embedder"
    )
    ask.set_defaults(handler=_ask)

    corrections = commands.add_parser(
        "corrections", help="which human corrections still stand after re-imports"
    )
    corrections.set_defaults(handler=_corrections)

    docs = commands.add_parser("docs", help="knowledge documents and what a change affects")
    docs_commands = docs.add_subparsers(dest="docs_command", metavar="ACTION", parser_class=_Parser)
    docs_build = docs_commands.add_parser(
        "build", help="build every document's content and record what it depends on"
    )
    docs_build.set_defaults(handler=_docs)
    docs_affected = docs_commands.add_parser(
        "affected", help="the documents to rebuild after these records or revisions changed"
    )
    docs_affected.add_argument("ids", nargs="+", help="krec_ or rev_ IDs")
    docs_affected.set_defaults(handler=_docs)
    docs_project = docs_commands.add_parser(
        "project", help="write a project's master note (current, history or all) into a vault"
    )
    docs_project.add_argument("project", help="the project ID")
    docs_project.add_argument("--vault", type=Path, required=True, help="the vault folder")
    docs_project.add_argument(
        "--mode", choices=["current", "history", "all"], default="all", help="default: all"
    )
    docs_project.add_argument(
        "--template",
        choices=("v1", "v2"),
        default="v1",
        help="v1: the DOC-004 master; v2: the readable layout (summary first, one line per item)",
    )
    docs_project.set_defaults(handler=_docs)
    docs_chat = docs_commands.add_parser(
        "chat", help="write a chat's knowledge note (labels, quotes, branches, images, links)"
    )
    docs_chat.add_argument("conversation", help="conv_ ID or the export's conversation ID")
    docs_chat.add_argument("--vault", type=Path, required=True, help="the vault folder")
    docs_chat.add_argument("--taxonomy", help="taxonomy version to show labels under")
    docs_chat.add_argument(
        "--template",
        choices=("v1", "v2"),
        default="v1",
        help="v1: the DOC-003 note; v2: the rich-note layout (summary and card first)",
    )
    docs_chat.set_defaults(handler=_docs)
    docs_topic = docs_commands.add_parser(
        "topic", help="write a topic's master note from every chat (by term ID, label or alias)"
    )
    docs_topic.add_argument("topic", help="term ID, label or alias")
    docs_topic.add_argument("--vault", type=Path, required=True, help="the vault folder")
    docs_topic.add_argument("--taxonomy", help="taxonomy version (required)")
    docs_topic.add_argument(
        "--mode", choices=["current", "history", "all"], default="all", help="default: all"
    )
    docs_topic.add_argument(
        "--template",
        choices=("v1", "v2"),
        default="v1",
        help="v1: the DOC-005 master; v2: the readable layout (summary first, one line per item)",
    )
    docs_topic.set_defaults(handler=_docs)
    docs_vault = docs_commands.add_parser(
        "vault",
        help="write or update every managed note and image in a vault (keeps your edits)",
    )
    docs_vault.add_argument("--vault", type=Path, required=True, help="the vault folder")
    docs_vault.add_argument("--taxonomy", help="taxonomy version for labels and topic notes")
    docs_vault.set_defaults(handler=_docs)
    docs_check = docs_commands.add_parser(
        "check",
        help="check every link, embed and note header, and each note's length and empty "
        "sections, in a vault (changes nothing)",
    )
    docs_check.add_argument("--vault", type=Path, required=True, help="the vault folder")
    docs_check.set_defaults(handler=_docs_check)
    docs_rubric = docs_commands.add_parser(
        "rubric", help="check chats' rich notes: real citations, cited claims, budget (NOTE-011)"
    )
    docs_rubric.add_argument("conversations", nargs="*", help="conv_ or export conversation IDs")
    docs_rubric.add_argument("--all", action="store_true", help="every imported chat")
    docs_rubric.set_defaults(handler=_docs_rubric)

    related = commands.add_parser("related", help="links between conversations (forks, quotes)")
    related_commands = related.add_subparsers(
        dest="related_command", metavar="ACTION", parser_class=_Parser
    )
    listing = related_commands.add_parser("list", help="list proposed and reviewed links")
    listing.add_argument("--conversation", help="only links to or from this conv_ ID")
    listing.add_argument(
        "--state",
        choices=["candidate", "accepted", "rejected", "superseded"],
        help="only this state",
    )
    listing.set_defaults(handler=_related_list)
    decide = related_commands.add_parser("review", help="accept, reject or supersede a link")
    decide.add_argument("relationship", help="the rel_ ID")
    decide.add_argument("action", choices=["accept", "reject", "supersede"])
    decide.add_argument("--note", help="why (kept in the history)")
    decide.add_argument("--reviewer", default="owner", help="who decided (default: owner)")
    decide.add_argument(
        "--as",
        dest="as_kind",
        choices=["continues", "forked_from", "related_to"],
        help="with accept: accept it as this kind instead (the old link is superseded)",
    )
    decide.add_argument(
        "--reverse",
        action="store_true",
        help="with accept: the link points the other way (the old link is superseded)",
    )
    decide.set_defaults(handler=_related_review)
    add_link = related_commands.add_parser(
        "add", help="state a link yourself, e.g. 'B continues A' (stored as accepted)"
    )
    add_link.add_argument("from_conversation", metavar="FROM", help="the conv_ ID it starts from")
    add_link.add_argument("kind", choices=["continues", "forked_from", "related_to"])
    add_link.add_argument("to_conversation", metavar="TO", help="the conv_ ID it points to")
    add_link.add_argument("--reviewer", default="owner", help="who said so (default: owner)")
    add_link.add_argument("--note", help="why (kept in the history)")
    add_link.set_defaults(handler=_related_add)
    rerun = related_commands.add_parser(
        "detect", help="run the link detectors again (imports already do this)"
    )
    rerun.set_defaults(handler=_related_detect)
    suggest = related_commands.add_parser(
        "suggest", help="suggest related chats from shared projects, topics and wording"
    )
    suggest.add_argument("--taxonomy", help="taxonomy version whose labels count")
    suggest.set_defaults(handler=_related_suggest)

    commands.add_parser(
        "reconcile", help="propose repeated claims, record links and conflicts"
    ).set_defaults(handler=_reconcile)
    conflicts_cmd = commands.add_parser(
        "conflicts", help="records that cannot both hold: list and review (no text shown)"
    )
    conflicts_commands = conflicts_cmd.add_subparsers(
        dest="conflicts_command", metavar="ACTION", parser_class=_Parser
    )
    conflicts_list = conflicts_commands.add_parser("list", help="stored conflicts and reviews")
    conflicts_list.add_argument(
        "--state", choices=["unresolved", "dismissed", "resolved"], help="only this state"
    )
    conflicts_list.set_defaults(handler=_conflicts)
    conflicts_review = conflicts_commands.add_parser(
        "review", help="dismiss (not a real conflict), resolve, or reopen a conflict"
    )
    conflicts_review.add_argument("conflict", help="the kcf_ ID")
    conflicts_review.add_argument("decision", choices=["dismiss", "resolve", "reopen"])
    conflicts_review.add_argument("--reviewer", required=True, help="who decided")
    conflicts_review.add_argument("--note", required=True, help="why (kept in the history)")
    conflicts_review.set_defaults(handler=_conflicts)
    links_cmd = commands.add_parser(
        "links", help="links between records (creates, references...): list and review"
    )
    links_commands = links_cmd.add_subparsers(
        dest="links_command", metavar="ACTION", parser_class=_Parser
    )
    links_list = links_commands.add_parser("list", help="proposed and reviewed record links")
    links_list.add_argument(
        "--state", choices=["candidate", "accepted", "rejected"], help="only this state"
    )
    links_list.add_argument("--record", help="only links to or from this krec_ ID")
    links_list.set_defaults(handler=_record_links)
    links_review = links_commands.add_parser("review", help="accept or reject a record link")
    links_review.add_argument("link", help="the krl_ ID")
    links_review.add_argument("decision", choices=["accept", "reject"])
    links_review.add_argument("--reviewer", required=True, help="who decided")
    links_review.add_argument("--note", help="why, optionally (kept in the history)")
    links_review.set_defaults(handler=_record_links)
    state = commands.add_parser("state", help="what holds now or on a date (no text shown)")
    state.add_argument("--as-of", help="only what the chats said by this date (ISO 8601)")
    state.add_argument("--known-at", help="as it was understood at this date (ISO 8601)")
    state.add_argument("--project", help="only this project ID")
    state.add_argument("--conversation", help="only this conv_ ID")
    state.set_defaults(handler=_state)
    walk_cmd = commands.add_parser("walk", help="records connected to one record (no text shown)")
    walk_cmd.add_argument("record", help="the krec_ ID to start from")
    walk_cmd.add_argument("--kind", action="append", help="edge kind to follow (repeatable)")
    walk_cmd.add_argument("--depth", type=int, default=2, help="most steps away (default 2)")
    walk_cmd.add_argument("--direction", choices=["out", "in", "both"], default="both")
    walk_cmd.add_argument(
        "--include-closed", action="store_true", help="also follow rejected or closed edges"
    )
    walk_cmd.set_defaults(handler=_walk)
    timeline_cmd = commands.add_parser("timeline", help="how decisions moved (no text shown)")
    timeline_cmd.add_argument("--record", help="only events touching this krec_ ID")
    timeline_cmd.add_argument(
        "--build",
        action="store_true",
        help="first derive proposals, acceptances, conflicts and clear replacements",
    )
    timeline_cmd.set_defaults(handler=_timeline)
    duplicates = commands.add_parser(
        "duplicates", help="records that may state the same claim (never merged automatically)"
    )
    duplicates_commands = duplicates.add_subparsers(
        dest="duplicates_command", metavar="ACTION", parser_class=_Parser
    )
    dup_list = duplicates_commands.add_parser("list", help="list proposed and reviewed pairs")
    dup_list.add_argument("--state", choices=["proposed", "confirmed", "rejected"])
    dup_list.set_defaults(handler=_duplicates)
    duplicates_commands.add_parser("detect", help="propose new pairs").set_defaults(
        handler=_duplicates
    )
    dup_review = duplicates_commands.add_parser("review", help="confirm or reject a pair")
    dup_review.add_argument("pair", help="the req_ ID")
    dup_review.add_argument("decision", choices=["confirmed", "rejected"])
    dup_review.add_argument("--reviewer", required=True, help="who decided")
    dup_review.add_argument("--note", help="why (required to confirm a near miss)")
    dup_review.set_defaults(handler=_duplicates)

    ui = commands.add_parser("ui", help="open the local web interface (this computer only)")
    ui.add_argument("--port", type=int, default=8765, help="port on 127.0.0.1 (default 8765)")
    ui.add_argument("--no-browser", action="store_true", help="don't open a browser window")
    ui.add_argument("--gold", type=Path, help="private answer key for the Evaluation pages")
    ui.add_argument(
        "--reviewer",
        choices=["owner", "ai_session", "same_model", "none"],
        help="who reviewed the answer key (needed with --gold)",
    )
    ui.add_argument("--review", type=Path, help="the answer key's review record")
    ui.set_defaults(handler=_ui)

    api = commands.add_parser("api", help="serve the JSON API (this computer only)")
    api.add_argument("--port", type=int, default=8766, help="port on 127.0.0.1 (default 8766)")
    api.set_defaults(handler=_api)

    watch = commands.add_parser(
        "watch", help="import exports as they land in a folder (once each; only read)"
    )
    watch.add_argument("folder", type=Path, help="the folder to watch (e.g. your downloads)")
    watch.add_argument("--account", metavar="LABEL", help="account label for these exports")
    watch.add_argument("--partial", action="store_true", help="exports hold only some chats")
    watch.add_argument("--vault", type=Path, help="also keep this vault up to date")
    watch.add_argument("--interval", type=float, default=5.0, help="seconds between looks")
    watch.add_argument(
        "--settle", type=float, default=3.0, help="seconds an export must stay unchanged"
    )
    watch.add_argument("--once", action="store_true", help="look twice, act, then stop")
    watch.set_defaults(handler=_watch)
    importer = commands.add_parser("import", help="import an export (folder or ZIP; only read)")
    importer.add_argument("source", type=Path, help="export ZIP or folder")
    importer.add_argument(
        "--format", choices=["auto", "chatgpt-export-v1", "chatgpt-split-v1"], default="auto"
    )
    importer.add_argument(
        "--account",
        metavar="LABEL",
        help="account label (default: the matching raw root's, or 'default')",
    )
    importer.add_argument(
        "--partial",
        action="store_true",
        help="the source is only some chats: don't mark the others 'not seen'",
    )
    importer.set_defaults(handler=_import)
    return parser


# ---------------------------------------------------------------- entry points


def main(argv: Sequence[str] | None = None) -> int:
    """Run one ``ke`` command and print its result.

    Args:
        argv: Arguments without the program name (defaults to ``sys.argv[1:]``).

    Returns:
        The exit code (an ``ExitCode`` value).
    """
    args_list = list(sys.argv[1:] if argv is None else argv)
    want_json = "--json" in args_list
    parser = build_parser()
    try:
        args = parser.parse_args(args_list)
    except _UsageError as error:
        return _emit(
            CommandResult("usage", ExitCode.USAGE, message=str(error), error_code="usage"),
            want_json,
            usage=parser.format_usage(),
        )
    handler = getattr(args, "handler", None)
    if handler is None:
        name = args.command or "ke"
        return _emit(
            CommandResult(
                name, ExitCode.USAGE, message="a command is required", error_code="usage"
            ),
            args.json,
            usage=parser.format_usage(),
        )
    try:
        settings = load_settings(config_file=args.config)
    except (ValidationError, ValueError, FileNotFoundError, OSError) as error:
        return _emit(
            CommandResult(
                args.command, ExitCode.CONFIG, message=_config_message(error), error_code="config"
            ),
            args.json,
        )
    try:
        result = handler(settings, args)
    except Exception as error:  # noqa: BLE001 - last-resort guard for a clean exit code
        result = CommandResult(
            args.command, ExitCode.ERROR, message=type(error).__name__, error_code="internal"
        )
    return _emit(result, args.json)


def _config_message(error: Exception) -> str:
    # Field names and reasons only. Pydantic's full text can include input
    # values, so it is summarised rather than printed.
    if isinstance(error, ValidationError):
        problems = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in error.errors()]
        return "invalid settings: " + "; ".join(problems)
    if isinstance(error, FileNotFoundError):
        return f"config file not found: {Path(str(error.filename)).name}"
    return f"invalid settings: {error}"


def _emit(result: CommandResult, as_json: bool, usage: str = "") -> int:
    if as_json:
        print(result.as_json())
    else:
        stream = sys.stdout if result.exit_code is ExitCode.OK else sys.stderr
        if usage:
            print(usage.rstrip(), file=stream)
        print(result.as_text(), file=stream)
    return int(result.exit_code)


def run() -> None:
    """Console-script entry point used by the installed ``ke`` command."""
    raise SystemExit(main())


if __name__ == "__main__":
    run()
