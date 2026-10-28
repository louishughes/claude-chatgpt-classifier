"""``ke``: the command-line entry point, with fixed output and exit-code contracts.

Every command returns a ``CommandResult``. The same result is printed either
as readable text or, with ``--json``, as one JSON object with sorted keys, so
scripts and tests can rely on its exact shape. Exit codes are a closed list
(``ExitCode``), so a script can tell "you typed it wrong" from "the config is
invalid" from "not built yet" without reading messages.

Commands that aren't built yet (``import``) exist as placeholders that exit
with ``NOT_IMPLEMENTED``, so the interface can be tried and tested now.
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
from dataclasses import dataclass, field
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
        return ", ".join(_text_value(v) for v in value) or "-"
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

    importer = commands.add_parser("import", help="import an export (not built yet)")
    importer.add_argument("source", type=Path, help="export ZIP or folder")
    importer.add_argument(
        "--format", choices=["auto", "chatgpt-export", "chatgpt-split-v1"], default="auto"
    )
    importer.set_defaults(handler=_not_built("import", "ING-003"))
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
