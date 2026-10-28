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


def _db_upgrade(settings: Settings, _args: argparse.Namespace) -> CommandResult:
    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
    from knowledge_engine.infrastructure.migrations import current_revision, upgrade_to_head

    engine = create_sqlite_engine(database_path(settings))
    try:
        before = current_revision(engine)
        upgrade_to_head(engine)
        after = current_revision(engine)
    finally:
        engine.dispose()
    return CommandResult(
        "db upgrade",
        data={"before": before or "none", "after": after or "none", "changed": before != after},
        message="Database is up to date" if before == after else "Database upgraded",
    )


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
    return CommandResult("imports report", data=data, message=f"Import report ({batch.status})")


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
    """List the social account registry (SOC-002): read-only."""
    from sqlalchemy.orm import Session

    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
    from knowledge_engine.links.social_store import account_summaries, ambiguous_handles

    db = database_path(settings)
    if not db.exists():
        return CommandResult(
            "accounts", ExitCode.ERROR, message="no imports yet", error_code="no_imports"
        )
    engine = create_sqlite_engine(db)
    try:
        with Session(engine) as session:
            if args.ambiguous:
                return CommandResult(
                    "accounts",
                    data={"ambiguous": ambiguous_handles(session)},
                    message="Bare @handles (no platform; never linked to an account)",
                )
            accounts_list = account_summaries(session, platform=args.platform)
    finally:
        engine.dispose()
    return CommandResult(
        "accounts", data={"accounts": accounts_list}, message="Social accounts (never contacted)"
    )


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


def _search(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """Search message text (RET-001). Brings the search index up to date first."""
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
    from knowledge_engine.infrastructure.workspace import WorkspaceRow
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
            added = sync_index(session, index)
            hits = [
                {
                    "conversation_id": hit.conversation_id,
                    "native_node_id": hit.native_node_id,
                    "revision_id": hit.revision_id,
                    "role": hit.role,
                    "snippet": hit.snippet,
                }
                for workspace_id in session.scalars(select(WorkspaceRow.workspace_id))
                for hit in index.search(
                    args.query,
                    workspace_id=workspace_id,
                    mode=SearchMode(args.mode),
                    limit=args.limit,
                    conversation_id=args.conversation,
                )
            ][: args.limit]
    finally:
        engine.dispose()
    return CommandResult(
        "search",
        data={"mode": args.mode, "hits": hits, "newly_indexed": added},
        message=f"{len(hits)} matching message(s)",
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
    from knowledge_engine.relationships.store import ReviewAction, review

    db = database_path(settings)
    if not db.exists():
        return CommandResult(
            "related review", ExitCode.ERROR, message="no imports yet", error_code="no_imports"
        )
    engine = create_sqlite_engine(db)
    try:
        with Session(engine) as session, session.begin():
            try:
                entry = review(
                    session,
                    args.relationship,
                    ReviewAction(args.action),
                    reviewer=args.reviewer,
                    note=args.note,
                )
            except KeyError:
                return CommandResult(
                    "related review",
                    ExitCode.ERROR,
                    message="no such relationship",
                    error_code="unknown_relationship",
                )
            data = {
                "relationship_id": args.relationship,
                "from_state": entry.from_state,
                "to_state": entry.to_state,
            }
    finally:
        engine.dispose()
    return CommandResult("related review", data=data, message="Review recorded")


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


def _ui(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """Run the local web interface until Ctrl+C. Listens on 127.0.0.1 only."""
    import webbrowser

    from knowledge_engine.ui.app import serve

    try:
        server = serve(settings, port=args.port)
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
    upgrade = db_commands.add_parser("upgrade", help="apply pending migrations")
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

    inspect = commands.add_parser("inspect", help="browse stored conversations (read-only)")
    inspect.add_argument(
        "conversation", nargs="?", help="a conv_ ID or the export's conversation ID"
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
    semantic.set_defaults(handler=_eval_semantic)

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
    status_cmd = transcript_commands.add_parser("status", help="a video's transcript status")
    status_cmd.add_argument("video", help="the 11-character YouTube video ID")
    status_cmd.set_defaults(handler=_transcript_status)

    accounts = commands.add_parser("accounts", help="social accounts mentioned in your chats")
    accounts.add_argument("--platform", help="only this platform, e.g. github")
    accounts.add_argument(
        "--ambiguous", action="store_true", help="list bare @handles with no platform instead"
    )
    accounts.set_defaults(handler=_accounts)

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
    gold_commands.add_parser("schema", help="print the golden set JSON Schema").set_defaults(
        handler=_gold_schema
    )
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
    search.set_defaults(handler=_search)

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
    decide.set_defaults(handler=_related_review)
    rerun = related_commands.add_parser(
        "detect", help="run the link detectors again (imports already do this)"
    )
    rerun.set_defaults(handler=_related_detect)

    commands.add_parser(
        "reconcile", help="propose repeated claims, record links and conflicts"
    ).set_defaults(handler=_reconcile)
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
    ui.set_defaults(handler=_ui)

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
