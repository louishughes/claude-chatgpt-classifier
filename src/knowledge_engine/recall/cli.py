"""The ``recall`` command: answers from your chat history, read-only (RCL-001).

Usage::

    recall history find "wasted space mechanics"
    recall history find "status effects" --meaning
    recall --json history find "port 8080" --mode exact
    recall history repeats
    recall projects show "Haggis game"
    recall decisions history "Haggis game"
    recall decisions conflicts "Haggis game"

**Why it reuses ``ke``'s search instead of its own.** ``recall history
find`` calls the very same functions as ``ke search`` (word search,
RET-001) and ``ke similar`` (meaning search, RET-003), then adds what a
person or an agent needs to *use* a hit: the chat's title and the
message's date. So both commands always agree on what matches, and a fix
to search fixes both.

**What "read-only" means here.** ``recall`` never changes a stored record.
The one thing it may write is the search index, a rebuildable cache that
``ke search`` also brings up to date before searching.

**Output.** Plain text for a person by default. ``--json`` (anywhere on the
line) prints one JSON object in the same envelope as ``ke --json``, for
AI agents: ``{"command", "ok", "exit_code", "data", "message", "error"}``.

Talking points:
    - "recall and ke share one search engine, so they can't disagree; recall
      only adds the context a person needs: chat title and date."
    - "Every hit carries its chat and message ID, so you can always go back
      to the original message rather than trust a summary."
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, NoReturn

from pydantic import ValidationError

from knowledge_engine import __version__

# CommandResult and ExitCode are the CLI's shared result contract (FND-008),
# so recall's JSON looks exactly like ke's. The two private handlers are
# reused on purpose: see the module docstring.
from knowledge_engine.cli.main import CommandResult, ExitCode, _search, _similar
from knowledge_engine.settings import Settings, load_settings

# How much of a message to show when a hit has no highlighted snippet
# (meaning search scores whole messages, so there is nothing to highlight).
SNIPPET_CHARS = 160


class _UsageError(Exception):
    """Raised by the parser instead of exiting, so ``--json`` can report it."""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise _UsageError(message)


def build_parser() -> argparse.ArgumentParser:
    """Build the ``recall`` command line: groups of read-only subcommands.

    Returns:
        The parser. It raises ``_UsageError`` instead of exiting on bad input.
    """
    parser = _Parser(
        prog="recall",
        description="Answers from your own chat history. Read-only; every answer cites "
        "its chat and message.",
        epilog="Add --json anywhere for one JSON object (for scripts and AI agents).",
    )
    parser.add_argument("--version", action="version", version=f"recall {__version__}")
    parser.add_argument("--config", type=Path, help="TOML config file (default: none)")
    # --json is taken out of the arguments before parsing (see main), so it
    # works before or after a subcommand. It's listed here only for --help.
    parser.add_argument("--json", action="store_true", help="print one JSON object")
    groups = parser.add_subparsers(dest="group", metavar="GROUP", parser_class=_Parser)

    history = groups.add_parser("history", help="search your conversations")
    history_commands = history.add_subparsers(dest="action", metavar="ACTION", parser_class=_Parser)
    find = history_commands.add_parser(
        "find",
        help="find messages by words or by meaning",
        description="Find messages by their words (default) or by meaning (--meaning). "
        "Each hit shows the date, who wrote it, the chat title, and the chat and "
        "message IDs to open the original.",
    )
    find.add_argument("query", help="what to look for")
    find.add_argument(
        "--mode",
        choices=("tokens", "phrase", "exact"),
        default="tokens",
        help="tokens: all the words, any order (default); phrase: the words in order; "
        "exact: the exact text",
    )
    find.add_argument(
        "--meaning",
        action="store_true",
        help="match by meaning with the local embedder (catches rewording, not synonyms)",
    )
    find.add_argument("--limit", type=int, default=10, help="at most this many hits (10)")
    find.add_argument("--since", help="only messages on or after this date (YYYY-MM-DD)")
    find.add_argument("--until", help="only messages on or before this date (YYYY-MM-DD)")
    find.add_argument("--role", help="only messages by this speaker, e.g. user or assistant")
    find.add_argument("--chat", help="only this chat (a conv_ ID)")
    find.set_defaults(handler=_history_find)

    repeats = history_commands.add_parser(
        "repeats",
        help="requests you made again, reworded, in other chats (no AI)",
        description="Group your own messages that ask much the same thing in two or more "
        "chats, most chats first. Local word matching, no model: rewording is found, "
        "synonyms are not. Each member shows its date, chat title and IDs.",
    )
    repeats.add_argument(
        "--min-chats", type=int, default=2, help="only groups spanning this many chats (2)"
    )
    repeats.add_argument("--since", help="only messages on or after this date (YYYY-MM-DD)")
    repeats.add_argument("--until", help="only messages on or before this date (YYYY-MM-DD)")
    repeats.add_argument(
        "--project", help="only messages in chats labelled with this approved project or term ID"
    )
    repeats.add_argument(
        "--taxonomy", help="the published vocabulary version for --project (default newest)"
    )
    repeats.add_argument("--limit", type=int, default=20, help="at most this many groups (20)")
    repeats.set_defaults(handler=_history_repeats)

    projects = groups.add_parser("projects", help="what your chats settled about a project")
    project_commands = projects.add_subparsers(
        dest="action", metavar="ACTION", parser_class=_Parser
    )
    show = project_commands.add_parser(
        "show",
        help="one project: what holds now, what changed, what is in conflict",
        description="Show one approved project: its current decisions, requirements and "
        "preferences, what is in conflict or was replaced, open questions, how many "
        "assistant suggestions were accepted, rejected or never answered, and its chats. "
        "Every item quotes the message it comes from.",
    )
    show.add_argument("name", help="the project's name, an alias, or its proj_ ID")
    show.set_defaults(handler=_projects_show)

    decisions = groups.add_parser("decisions", help="how a project's decisions moved")
    decision_commands = decisions.add_subparsers(
        dest="action", metavar="ACTION", parser_class=_Parser
    )
    history_cmd = decision_commands.add_parser(
        "history",
        help="a project's decisions by subject, each step oldest first",
        description="Group a project's decisions by subject and show each step oldest "
        "first: suggested, accepted, rejected, clarified, revised, replaced, contradicted. "
        "Every step quotes its message. Withdrawn steps stay, marked revoked. Nothing is "
        "called replaced unless the chats said so explicitly.",
    )
    history_cmd.add_argument("name", help="the project's name, an alias, or its proj_ ID")
    history_cmd.set_defaults(handler=_decisions_history)
    conflicts_cmd = decision_commands.add_parser(
        "conflicts",
        help="a project's decisions that still disagree",
        description="List pairs of a project's records that disagree and that nobody has "
        "settled yet, both sides quoted. A conflict is never shown as a replacement.",
    )
    conflicts_cmd.add_argument("name", help="the project's name, an alias, or its proj_ ID")
    conflicts_cmd.add_argument(
        "--all", action="store_true", help="also show conflicts already dismissed or resolved"
    )
    conflicts_cmd.set_defaults(handler=_decisions_conflicts)
    return parser


# ---------------------------------------------------------------- commands


def _history_find(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """Run word or meaning search, then add each hit's chat title and date."""
    name = "history find"
    if args.limit <= 0:
        return CommandResult(
            name, ExitCode.USAGE, message="--limit must be 1 or more", error_code="usage"
        )
    if args.meaning:
        # Meaning search has no date or speaker filters (RET-003). Refusing is
        # clearer than quietly ignoring a filter the user asked for.
        if args.since or args.until or args.role:
            return CommandResult(
                name,
                ExitCode.USAGE,
                message="--since, --until and --role work with word search only",
                error_code="usage",
            )
        result = _similar(
            settings,
            argparse.Namespace(
                query=args.query, limit=args.limit, conversation=args.chat, rebuild=False
            ),
        )
    else:
        result = _search(
            settings,
            argparse.Namespace(
                query=args.query,
                mode=args.mode,
                limit=args.limit,
                conversation=args.chat,
                since=args.since,
                until=args.until,
                role=args.role,
                term=None,
                taxonomy=None,
            ),
        )
    if result.exit_code is not ExitCode.OK:
        return CommandResult(name, result.exit_code, result.data, result.message, result.error_code)

    hits: list[dict[str, Any]] = list(result.data["hits"])
    details = _hit_details(settings, [str(hit["revision_id"]) for hit in hits])
    for hit in hits:
        title, created, text = details.get(str(hit["revision_id"]), (None, None, ""))
        hit["title"] = title
        hit["date"] = _date(created)
        if "snippet" not in hit:
            hit["snippet"] = _shorten(text)
    data: dict[str, Any] = {
        "query": args.query,
        "how": "meaning" if args.meaning else args.mode,
        "hits": hits,
    }
    # Imported notes (ING-012) and the "undated left out" count only come
    # from word search; pass them through unchanged when present.
    for key in ("document_hits", "undated_left_out"):
        if key in result.data:
            data[key] = result.data[key]
    return CommandResult(name, data=data, message=result.message)


def _hit_details(
    settings: Settings, revision_ids: list[str]
) -> dict[str, tuple[str | None, float | None, str]]:
    """Chat title, message time and message text for each revision, in one query."""
    if not revision_ids:
        return {}
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from knowledge_engine.graph.nodes import canonical_node
    from knowledge_engine.importer.records import (
        ConversationRow,
        MessageNodeRow,
        MessageRevisionRow,
    )
    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path

    engine = create_sqlite_engine(database_path(settings))
    try:
        with Session(engine) as session:
            rows = session.execute(
                select(
                    MessageRevisionRow.revision_id,
                    ConversationRow.title,
                    MessageRevisionRow.create_time,
                    MessageRevisionRow.role,
                    MessageRevisionRow.content_json,
                    MessageNodeRow.native_node_id,
                )
                .join(MessageNodeRow, MessageNodeRow.node_key == MessageRevisionRow.node_key)
                .join(
                    ConversationRow,
                    ConversationRow.conversation_id == MessageNodeRow.conversation_id,
                )
                .where(MessageRevisionRow.revision_id.in_(revision_ids))
            ).all()
    finally:
        engine.dispose()
    details: dict[str, tuple[str | None, float | None, str]] = {}
    for revision, title, created, role, content, native in rows:
        # The same canonical text the search indexes see (lexical._passages),
        # so a snippet never shows words the index didn't search.
        message = {
            "id": native,
            "author": {"role": role},
            "content": json.loads(content),
            "create_time": created,
        }
        node = canonical_node(native, {"id": native, "message": message})
        details[revision] = (title, created, node.text if node is not None else "")
    return details


def _date(created: float | None) -> str | None:
    if created is None:
        return None
    return datetime.fromtimestamp(created, tz=UTC).date().isoformat()


def _shorten(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= SNIPPET_CHARS else flat[: SNIPPET_CHARS - 1] + "…"


def _history_repeats(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """Group the requests you made again in other chats (RCL-002)."""
    from sqlalchemy.orm import Session

    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
    from knowledge_engine.recall.repeats import (
        MATCH_THRESHOLD,
        REPEATS_VERSION,
        find_repeats,
        load_requests,
    )
    from knowledge_engine.retrieval.filters import (
        BadFilterDate,
        UnknownFilterTerm,
        build_filters,
    )

    name = "history repeats"
    if args.min_chats < 2:
        return CommandResult(
            name, ExitCode.USAGE, message="--min-chats must be 2 or more", error_code="usage"
        )
    if args.limit <= 0:
        return CommandResult(
            name, ExitCode.USAGE, message="--limit must be 1 or more", error_code="usage"
        )
    db = database_path(settings)
    if not db.exists():
        return CommandResult(
            name, ExitCode.ERROR, message="no imports yet", error_code="no_imports"
        )
    engine = create_sqlite_engine(db)
    try:
        with Session(engine) as session:
            try:
                filters = build_filters(
                    session,
                    since=args.since,
                    until=args.until,
                    term=args.project,
                    taxonomy=args.taxonomy,
                )
            except BadFilterDate as error:
                return CommandResult(
                    name, ExitCode.USAGE, message=str(error), error_code="bad_filter"
                )
            except UnknownFilterTerm as error:
                return CommandResult(
                    name, ExitCode.USAGE, message=str(error), error_code="unknown_term"
                )
            requests = load_requests(session, filters)
    finally:
        engine.dispose()
    report = find_repeats(requests, min_chats=args.min_chats)
    shown = report.groups[: args.limit]
    groups = [
        {
            "chats": group.chats,
            "weakest_match": group.weakest,
            "first_date": _date(group.members[0].created),
            "last_date": _date(group.members[-1].created),
            "members": [
                {
                    "conversation_id": m.conversation_id,
                    "title": m.title,
                    "native_node_id": m.native_node_id,
                    "revision_id": m.revision_id,
                    "date": _date(m.created),
                    "snippet": _shorten(m.text),
                }
                for m in group.members
            ],
        }
        for group in shown
    ]
    chats = len({m.conversation_id for g in shown for m in g.members})
    message = (
        f"{len(report.groups)} repeated request(s)"
        + (f", showing {len(shown)}" if len(shown) < len(report.groups) else "")
        + f"; compared {report.checked} of your messages, {report.too_short} too short"
    )
    return CommandResult(
        name,
        data={
            "version": REPEATS_VERSION,
            "threshold": MATCH_THRESHOLD,
            "checked": report.checked,
            "too_short": report.too_short,
            "groups_found": len(report.groups),
            "chats_in_shown_groups": chats,
            "groups": groups,
        },
        message=message,
    )


def _projects_show(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """Show one project's knowledge with re-checked quotes (RCL-003)."""
    from sqlalchemy.orm import Session

    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
    from knowledge_engine.recall.projects import (
        PROJECTS_VERSION,
        ProjectLookupError,
        find_project,
        show_project,
    )

    name = "projects show"
    db = database_path(settings)
    if not db.exists():
        return CommandResult(
            name, ExitCode.ERROR, message="no imports yet", error_code="no_imports"
        )
    engine = create_sqlite_engine(db)
    try:
        with Session(engine) as session:
            try:
                view = show_project(session, find_project(session, args.name))
            except ProjectLookupError as error:
                data: dict[str, Any] = {}
                if error.matches:
                    data["matches"] = [
                        {"project_id": pid, "name": label} for pid, label in error.matches
                    ]
                return CommandResult(
                    name, ExitCode.USAGE, data=data, message=str(error), error_code=error.code
                )
    finally:
        engine.dispose()

    def item(entry: Any) -> dict[str, Any]:
        return {
            "record_id": entry.record_id,
            "record_type": entry.record_type,
            "status": entry.status,
            "assertion": entry.assertion,
            "superseded_by": list(entry.superseded_by),
            "conflicts_with": list(entry.conflicts_with),
            "more_quotes": entry.more_quotes,
            "quotes": [
                {
                    "conversation_id": q.conversation_id,
                    "native_node_id": q.native_node_id,
                    "date": _date(q.created),
                    "actor": q.actor,
                    "text": q.text,
                    "problem": q.problem,
                }
                for q in entry.quotes
            ],
        }

    dated = [c.created for c in view.chats if c.created is not None]
    data = {
        "version": PROJECTS_VERSION,
        "project_id": view.project_id,
        "name": view.name,
        "aliases": list(view.aliases),
        "first_date": _date(min(dated)) if dated else None,
        "last_date": _date(max(dated)) if dated else None,
        "sections": {key: [item(e) for e in items] for key, items in view.sections.items()},
        "suggestions": view.suggestions,
        "questions": [item(e) for e in view.questions],
        "chats": [
            {"conversation_id": c.conversation_id, "title": c.title, "date": _date(c.created)}
            for c in view.chats
        ],
        "related": [
            {
                "relationship_id": link.relationship_id,
                "kind": link.kind,
                "from_conversation_id": link.from_conversation_id,
                "to_conversation_id": link.to_conversation_id,
                "evidence_class": link.evidence_class,
                "review_state": link.review_state,
                "because": list(link.because),
            }
            for link in view.related
        ],
    }
    counts = {key: len(items) for key, items in view.sections.items()}
    message = (
        f"{view.name}: {counts.get('current', 0)} current, "
        f"{counts.get('conflicted', 0)} in conflict, {counts.get('superseded', 0)} replaced; "
        f"{len(view.chats)} chat(s)"
    )
    return CommandResult(name, data=data, message=message)


def _on_project(
    settings: Settings, command: str, name: str, work: Callable[[Any, Any], CommandResult]
) -> CommandResult:
    """Open the archive, find the one project ``name`` means, and run ``work`` on it."""
    from sqlalchemy.orm import Session

    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
    from knowledge_engine.recall.projects import ProjectLookupError, find_project

    db = database_path(settings)
    if not db.exists():
        return CommandResult(
            command, ExitCode.ERROR, message="no imports yet", error_code="no_imports"
        )
    engine = create_sqlite_engine(db)
    try:
        with Session(engine) as session:
            try:
                project = find_project(session, name)
            except ProjectLookupError as error:
                data: dict[str, Any] = {}
                if error.matches:
                    data["matches"] = [
                        {"project_id": pid, "name": label} for pid, label in error.matches
                    ]
                return CommandResult(
                    command, ExitCode.USAGE, data=data, message=str(error), error_code=error.code
                )
            return work(session, project)
    finally:
        engine.dispose()


def _record_json(record: Any) -> dict[str, Any]:
    return {
        "record_id": record.record_id,
        "record_type": record.record_type,
        "status": record.status,
        "assertion": record.assertion,
        "date": _date(record.first_time),
        "quotes": [
            {
                "conversation_id": q.conversation_id,
                "native_node_id": q.native_node_id,
                "date": _date(q.created),
                "actor": q.actor,
                "text": q.text,
                "problem": q.problem,
            }
            for q in record.quotes
        ],
    }


def _decisions_history(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """A project's decisions by subject, steps oldest first (RCL-004)."""
    from knowledge_engine.recall.decisions import DECISIONS_VERSION, decision_history

    def work(session: Any, project: Any) -> CommandResult:
        subjects = decision_history(session, project)
        data = {
            "version": DECISIONS_VERSION,
            "project_id": project.project_id,
            "name": project.name,
            "subjects": [
                {
                    "records": [_record_json(r) for r in subject.records],
                    "steps": [
                        {
                            "event_id": step.event_id,
                            "label": step.label,
                            "date": _date(step.happened_at),
                            "from_record": step.from_record,
                            "to_record": step.to_record,
                            "actor": step.actor,
                            "revoked": step.revoked_by is not None,
                            "revoked_by": step.revoked_by,
                            "revoked_note": step.revoked_note,
                        }
                        for step in subject.steps
                    ],
                }
                for subject in subjects
            ],
        }
        steps = sum(len(s.steps) for s in subjects)
        message = f"{project.name}: {len(subjects)} subject(s), {steps} step(s), oldest first"
        return CommandResult("decisions history", data=data, message=message)

    return _on_project(settings, "decisions history", args.name, work)


def _decisions_conflicts(settings: Settings, args: argparse.Namespace) -> CommandResult:
    """A project's records that still disagree (RCL-004)."""
    from knowledge_engine.recall.decisions import DECISIONS_VERSION, decision_conflicts

    def work(session: Any, project: Any) -> CommandResult:
        found = decision_conflicts(session, project, include_settled=args.all)
        data = {
            "version": DECISIONS_VERSION,
            "project_id": project.project_id,
            "name": project.name,
            "conflicts": [
                {
                    "conflict_id": c.conflict_id,
                    "state": c.state,
                    "kinds": list(c.kinds),
                    "records": [_record_json(r) for r in c.records],
                }
                for c in found
            ],
        }
        open_count = sum(c.state == "unresolved" for c in found)
        message = f"{project.name}: {open_count} unresolved conflict(s)"
        if args.all:
            message += f", {len(found) - open_count} settled"
        return CommandResult("decisions conflicts", data=data, message=message)

    return _on_project(settings, "decisions conflicts", args.name, work)


# ---------------------------------------------------------------- output

# Section headings for `recall projects show`, in the order they print.
_PROJECT_SECTIONS = (
    ("current", "What holds now"),
    ("conflicted", "In conflict (needs your call)"),
    ("pending", "Waiting for a check"),
    ("unknown", "Date unknown"),
    ("superseded", "Replaced"),
)


def as_text(result: CommandResult) -> str:
    """Render a result for a person: one line per hit, then its snippet.

    Args:
        result: What a command returned.

    Returns:
        The text to print.
    """
    if result.exit_code is ExitCode.OK and "groups" in result.data:
        return _repeats_text(result)
    if result.exit_code is ExitCode.OK and "sections" in result.data:
        return _project_text(result)
    if result.exit_code is ExitCode.OK and "subjects" in result.data:
        return _history_text(result)
    if result.exit_code is ExitCode.OK and "conflicts" in result.data:
        return _conflicts_text(result)
    if result.data.get("matches"):
        lines = [result.as_text()]
        lines += [f"    {m['project_id']}  {m['name']}" for m in result.data["matches"]]
        return "\n".join(lines)
    if result.exit_code is not ExitCode.OK or "hits" not in result.data:
        return result.as_text()
    lines = [result.message]
    for hit in result.data["hits"]:
        date = hit.get("date") or "no date"
        title = hit.get("title") or "(untitled chat)"
        lines.append(f"{date}  {hit.get('role') or '?'}  {title}")
        lines.append(f"    {hit['conversation_id']}  message {hit['native_node_id']}")
        lines.append(f"    {hit['snippet']}")
    for doc in result.data.get("document_hits", []):
        lines.append(f"note  {doc['name']}  {doc['locator']}")
        lines.append(f"    {doc['snippet']}")
    return "\n".join(lines)


def _repeats_text(result: CommandResult) -> str:
    lines = [result.message]
    for number, group in enumerate(result.data["groups"], start=1):
        span = group["first_date"] or "no date"
        if group["last_date"] and group["last_date"] != group["first_date"]:
            span += f" to {group['last_date']}"
        lines.append(f"{number}. asked in {group['chats']} chats, {span}")
        for member in group["members"]:
            date = member["date"] or "no date"
            title = member["title"] or "(untitled chat)"
            lines.append(f"    {date}  {title}  {member['conversation_id']}")
            lines.append(f"        {member['snippet']}")
    return "\n".join(lines)


def _project_text(result: CommandResult) -> str:
    data = result.data
    span = data["first_date"] or "no date"
    if data["last_date"] and data["last_date"] != data["first_date"]:
        span += f" to {data['last_date']}"
    lines = [f"{data['name']}  ({data['project_id']})"]
    if data["aliases"]:
        lines.append("also called: " + ", ".join(data["aliases"]))
    lines.append(f"{len(data['chats'])} chat(s), {span}")
    # Short labels so a "replaced by" or "conflicts with" line can point at
    # another item on the same screen instead of printing a krec_ ID.
    labels: dict[str, str] = {}
    for key, _ in _PROJECT_SECTIONS:
        for entry in data["sections"].get(key, []):
            labels[entry["record_id"]] = f"#{len(labels) + 1}"
    for key, heading in _PROJECT_SECTIONS:
        entries = data["sections"].get(key, [])
        if not entries:
            continue
        lines += ["", f"{heading} ({len(entries)})"]
        for entry in entries:
            lines += _entry_lines(entry, labels)
    suggestions = data["suggestions"]
    lines += [
        "",
        f"Assistant suggestions (counted, not decisions): {suggestions['accepted']} accepted, "
        f"{suggestions['rejected']} rejected, {suggestions['open']} never answered",
    ]
    if data["questions"]:
        lines += ["", f"Open questions ({len(data['questions'])})"]
        for entry in data["questions"]:
            lines += _entry_lines(entry, labels)
    lines += ["", "Chats"]
    for chat in data["chats"]:
        title = chat["title"] or "(untitled chat)"
        lines.append(f"    {chat['date'] or 'no date'}  {title}  {chat['conversation_id']}")
    if data["related"]:
        lines += ["", "Related chats"]
        for link in data["related"]:
            line = (
                f"    {link['from_conversation_id']} {link['kind'].replace('_', ' ')} "
                f"{link['to_conversation_id']} ({link['evidence_class']}, {link['review_state']})"
            )
            lines.append(line)
    return "\n".join(lines)


def _entry_lines(entry: dict[str, Any], labels: dict[str, str]) -> list[str]:
    label = labels.get(entry["record_id"], "-")
    lines = [f"  {label} {entry['record_type']}: {_shorten(entry['assertion'])}"]
    if entry["superseded_by"]:
        lines.append(
            "      replaced by " + ", ".join(labels.get(r, r) for r in entry["superseded_by"])
        )
    if entry["conflicts_with"]:
        lines.append(
            "      conflicts with " + ", ".join(labels.get(r, r) for r in entry["conflicts_with"])
        )
    for q in entry["quotes"]:
        where = f"{q['date'] or 'no date'}  {q['conversation_id']}  message {q['native_node_id']}"
        if q["text"] is None:
            lines.append(f"      {where}: quote not shown ({q['problem']})")
        else:
            lines.append(f'      {where} ({q["actor"]}): "{_shorten(q["text"])}"')
    if entry["more_quotes"]:
        lines.append(f"      and {entry['more_quotes']} more quote(s)")
    return lines


def _record_lines(record: dict[str, Any], label: str, indent: str = "    ") -> list[str]:
    lines = [
        f"{indent}{label} {record['status']} {record['record_type']}: "
        f"{_shorten(record['assertion'])}"
    ]
    for q in record["quotes"]:
        where = f"{q['date'] or 'no date'}  {q['conversation_id']}  message {q['native_node_id']}"
        if q["text"] is None:
            lines.append(f"{indent}    {where}: quote not shown ({q['problem']})")
        else:
            lines.append(f'{indent}    {where} ({q["actor"]}): "{_shorten(q["text"])}"')
    return lines


def _history_text(result: CommandResult) -> str:
    lines = [result.message]
    for number, subject in enumerate(result.data["subjects"], start=1):
        # Records are named by letter within their subject, so a step can
        # say "B replaced A" instead of printing two krec_ IDs.
        letters = {
            r["record_id"]: chr(ord("A") + i) if i < 26 else str(i + 1)
            for i, r in enumerate(subject["records"])
        }
        lines += ["", f"{number}. {_shorten(subject['records'][0]['assertion'])}"]
        for record in subject["records"]:
            lines += _record_lines(record, letters[record["record_id"]] + ".")
        for step in subject["steps"]:
            source = letters.get(step["from_record"] or "", "elsewhere")
            target = letters.get(step["to_record"] or "", "")
            if step["label"] == "suggested":
                what = f"{source} suggested"
            elif target:
                what = f"{source} {step['label']} {target}"
            else:
                what = f"{source} {step['label']}"
            line = f"    {step['date'] or 'no date'}  {what}"
            if step["revoked"]:
                line += f"  [revoked by {step['revoked_by']}: {step['revoked_note'] or ''}]"
            lines.append(line)
    return "\n".join(lines)


def _conflicts_text(result: CommandResult) -> str:
    lines = [result.message]
    for number, conflict in enumerate(result.data["conflicts"], start=1):
        kinds = ", ".join(conflict["kinds"]) or "conflict"
        settled = (
            "unresolved: nothing says which holds"
            if conflict["state"] == "unresolved"
            else conflict["state"]
        )
        lines += ["", f"{number}. {kinds} ({settled})"]
        for letter, record in zip("AB", conflict["records"], strict=True):
            lines += _record_lines(record, letter + ".")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """Run one ``recall`` command and print its result.

    Args:
        argv: Arguments without the program name (defaults to ``sys.argv[1:]``).

    Returns:
        The exit code (an ``ExitCode`` value, the same contract as ``ke``).
    """
    args_list = list(sys.argv[1:] if argv is None else argv)
    # Agents tend to put --json at the end; accept it anywhere.
    want_json = "--json" in args_list
    args_list = [arg for arg in args_list if arg != "--json"]
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
        return _emit(
            CommandResult(
                args.group or "recall",
                ExitCode.USAGE,
                message="a command is required (try recall --help)",
                error_code="usage",
            ),
            want_json,
            usage=parser.format_usage(),
        )
    try:
        settings = load_settings(config_file=args.config)
    except (ValidationError, ValueError, FileNotFoundError, OSError):
        # Field names in pydantic's errors can echo input values, so only
        # the fact is reported; `ke status` explains config problems in detail.
        return _emit(
            CommandResult(
                "config",
                ExitCode.CONFIG,
                message="invalid settings (run ke status)",
                error_code="config",
            ),
            want_json,
        )
    try:
        result = handler(settings, args)
    except Exception as error:  # noqa: BLE001 - last-resort guard for a clean exit code
        result = CommandResult(
            f"{args.group} {args.action}",
            ExitCode.ERROR,
            message=type(error).__name__,
            error_code="internal",
        )
    return _emit(result, want_json)


def _emit(result: CommandResult, as_json: bool, usage: str = "") -> int:
    if as_json:
        print(result.as_json())
    else:
        stream = sys.stdout if result.exit_code is ExitCode.OK else sys.stderr
        if usage:
            print(usage.rstrip(), file=stream)
        print(as_text(result), file=stream)
    return int(result.exit_code)


def run() -> None:
    """Console-script entry point used by the installed ``recall`` command."""
    raise SystemExit(main())


if __name__ == "__main__":
    run()
