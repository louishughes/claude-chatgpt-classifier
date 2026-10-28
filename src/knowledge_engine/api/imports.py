"""Import, job and source endpoints (API-002).

``POST /imports`` starts an import in the background and answers at once
with ``202 Accepted`` and a job ID, never with a finished report: a full
export takes minutes. A program then asks ``GET /jobs/{id}`` until the job
is ``done`` or ``failed``, and reads the report at ``GET /imports/{id}``.
The job runs the same importer as ``ke import`` and the Import button, so
the workspace lock still allows one import at a time.

Sources are the stored conversations. ``GET /sources`` pages through them,
``GET /sources/{id}`` gives one conversation's facts (branch points, graph
issues, related chats), and ``GET /sources/{id}/nodes`` pages through its
messages in transcript order: the active path first, then each alternate
branch, each message once, with its parent so the tree can be rebuilt.

Lists are paged with ``offset`` and ``limit``; every page says ``total``
and ``next_offset`` (null on the last page).

Talking points:
    - "Starting an import over the API gives back a ticket number straight
      away; the report only appears once the import has really finished."
    - "Every message comes with its parent, so a program can rebuild the
      branches exactly, not a flattened transcript."
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from knowledge_engine.api.deps import ApiError, JobsDep, SessionsDep, SettingsDep
from knowledge_engine.importer.ledger import ImportBatchRow
from knowledge_engine.rendering.transcript import (
    StoredConversation,
    load_conversation,
    transcript_sections,
)
from knowledge_engine.ui.data import (
    list_conversations,
    list_imports,
    load_report,
    related_view,
)
from knowledge_engine.ui.jobs import ImportJob

router = APIRouter()

_ACCOUNT_RE = re.compile(r"^[A-Za-z0-9_-]{1,63}$")
MAX_LIMIT = 500
Offset = Annotated[int, Query(ge=0)]
Limit = Annotated[int, Query(ge=1, le=MAX_LIMIT)]


class ImportRequest(BaseModel):
    """``POST /imports``: what to import.

    Attributes:
        source: The export folder or ZIP on this computer. It is only read.
        account: The account label; default: the matching raw root's, or
            ``default``.
        partial: True if this export is not the whole history (chats it
            lacks are then not marked "not seen").
    """

    source: str = Field(min_length=1, max_length=4096)
    account: str | None = None
    partial: bool = False


class Job(BaseModel):
    """A background import and how it's going."""

    job_id: str
    state: str  # running, done or failed
    import_id: str | None
    status: str | None  # the import's own status once done (succeeded, partial...)
    error: str | None  # a plain reason when failed; never a path


class Page(BaseModel):
    """The paging part of every list answer."""

    total: int
    offset: int
    limit: int
    next_offset: int | None


def _page(total: int, offset: int, limit: int) -> dict[str, Any]:
    following = offset + limit
    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "next_offset": following if following < total else None,
    }


def _job(job: ImportJob) -> Job:
    return Job(
        job_id=job.job_id,
        state=job.state,
        import_id=job.import_id,
        status=job.status,
        error=job.error,
    )


@router.post("/imports", status_code=202, response_model=Job, tags=["imports"])
def start_import(
    body: ImportRequest, settings: SettingsDep, jobs: JobsDep, request: Request
) -> Job:
    """Start importing an export in the background; answer with its job at once.

    With several workspaces (PROD-003) ``source`` is a name inside that
    workspace's inbox folder, and anything resolving outside it (``..``, an
    absolute path, a link out) is refused before the disk is even checked:
    otherwise one tenant could import another's files.
    """
    source = Path(body.source.strip().strip('"')).expanduser()
    base = request.app.state.settings
    if base.tenants_root is not None:
        inbox = (base.tenants_root / "inbox" / settings.workspace_root.name).resolve()
        source = (inbox / source).resolve()
        if not source.is_relative_to(inbox):
            raise ApiError(403, "source_outside_inbox", "import only from your workspace's inbox")
    # Messages never repeat the path: it can name private things.
    if not source.exists():
        raise ApiError(400, "source_not_found", "that file or folder doesn't exist")
    if source.resolve().is_relative_to(settings.workspace_root.resolve()):
        raise ApiError(400, "source_in_workspace", "that's inside the workspace, not an export")
    account = (body.account or "").strip() or settings.account_for(source)
    if not _ACCOUNT_RE.fullmatch(account):
        raise ApiError(
            400, "invalid_account", "account labels use letters, numbers, '-' and '_' only"
        )
    return _job(jobs.start(source, account, partial=body.partial))


@router.get("/jobs/{job_id}", response_model=Job, tags=["imports"])
def get_job(job_id: str, jobs: JobsDep) -> Job:
    """How a background import is going."""
    job = jobs.get(job_id)
    if job is None:
        raise ApiError(404, "not_found", "no such job (jobs are forgotten when the API restarts)")
    return _job(job)


@router.get("/imports", tags=["imports"])
def get_imports(sessions: SessionsDep, offset: Offset = 0, limit: Limit = 50) -> dict[str, Any]:
    """Past imports, newest first, with their conversation counts."""
    with sessions.transaction(write=False) as session:
        rows = list_imports(session, limit=offset + limit)
        total = int(_count_imports(session))
    items = [
        {
            "import_id": row.import_id,
            "status": row.status,
            "started_at": row.started_at,
            "format_id": row.format_id,
            "conversations": row.conversations,
        }
        for row in rows[offset:]
    ]
    return {"items": items, **_page(total, offset, limit)}


@router.get("/imports/{import_id}", tags=["imports"])
def get_import(import_id: str, sessions: SessionsDep) -> dict[str, Any]:
    """One import's stored report: status, counts and warnings.

    A ``partial`` status means some chats failed or were set aside; the
    ``warnings`` and ``summary`` say which kinds and how many.
    """
    with sessions.transaction(write=False) as session:
        report = load_report(session, import_id)
    if report is None:
        raise ApiError(404, "not_found", "no such import")
    return report


@router.get("/sources", tags=["sources"])
def get_sources(
    sessions: SessionsDep,
    q: Annotated[str, Query(max_length=200)] = "",
    offset: Offset = 0,
    limit: Limit = 100,
) -> dict[str, Any]:
    """Stored conversations, newest first; ``q`` filters by title words."""
    with sessions.transaction(write=False) as session:
        rows, total = list_conversations(session, q, offset, limit)
    items = [
        {
            "conversation_id": row.conversation_id,
            "title": row.title,
            "created": row.created,
            "presence": row.presence,
            "messages": row.messages,
        }
        for row in rows
    ]
    return {"items": items, **_page(total, offset, limit)}


@router.get("/sources/{conversation_id}", tags=["sources"])
def get_source(conversation_id: str, sessions: SessionsDep) -> dict[str, Any]:
    """One conversation: facts, branch points, graph issues and related chats."""
    with sessions.transaction(write=False) as session:
        conversation = _load(session, conversation_id)
        related = related_view(session, [conversation.conversation_id]).get(
            conversation.conversation_id, []
        )
    graph = conversation.graph
    return {
        "conversation_id": conversation.conversation_id,
        "native_conversation_id": conversation.native_conversation_id,
        "title": conversation.title,
        "created": _time(conversation.create_time),
        "presence": conversation.presence,
        "messages": len(conversation.messages),
        "current_node": graph.current_node,
        "branch_points": [
            {
                "parent_id": point.parent_id,
                "kind": point.kind.value,
                "children": list(point.children),
                "active_child": point.active_child,
            }
            for point in graph.branch_points
        ],
        "issues": [{"code": i.code.value, "node_id": i.node_id} for i in graph.issues],
        "media_uses": sum(len(uses) for uses in conversation.media.values()),
        "related": related,
    }


@router.get("/sources/{conversation_id}/nodes", tags=["sources"])
def get_nodes(
    conversation_id: str, sessions: SessionsDep, offset: Offset = 0, limit: Limit = 100
) -> dict[str, Any]:
    """A conversation's messages in transcript order, each with its parent."""
    with sessions.transaction(write=False) as session:
        conversation = _load(session, conversation_id)
    graph = conversation.graph
    ordered = [
        (node_id, section.kind, section.branch_kind)
        for section in transcript_sections(conversation)
        for node_id in section.messages
    ]
    items = []
    for node_id, kind, branch_kind in ordered[offset : offset + limit]:
        node = conversation.messages[node_id]
        shape = graph.nodes.get(node_id)
        revision = conversation.revisions.get(node_id, "")
        items.append(
            {
                "node_id": node_id,
                "node_key": conversation.node_keys.get(node_id),
                "revision_id": revision or None,
                "message_id": node.message_id,
                "parent_id": shape.parent_id if shape else None,
                "children": list(shape.children) if shape else [],
                "section": kind,  # active, alternate or outside (a damaged tree)
                "branch_kind": branch_kind,
                "message_number": graph.message_number(node_id),
                "role": node.role,
                "content_type": node.content_type,
                "created": _time(node.create_time),
                "text": node.text,
                "media": [
                    {
                        "pointer": ref.pointer,
                        "availability": ref.availability,
                        "blob_sha256": ref.blob_sha256,
                        "media_type": ref.media_type,
                    }
                    for ref in conversation.media.get(revision, [])
                ],
            }
        )
    return {"items": items, **_page(len(ordered), offset, limit)}


def _load(session: Session, conversation_id: str) -> StoredConversation:
    try:
        return load_conversation(session, conversation_id)
    except KeyError as error:
        raise ApiError(404, "not_found", "no such conversation") from error


def _count_imports(session: Session) -> int:
    return int(session.scalar(select(func.count()).select_from(ImportBatchRow)) or 0)


def _time(value: float | None) -> datetime | None:
    return datetime.fromtimestamp(value, UTC) if value is not None else None
