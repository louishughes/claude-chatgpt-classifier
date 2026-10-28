"""Document list, preview and export endpoints (API-005).

``GET /documents`` lists every note the engine would write (transcripts,
knowledge notes, project, topic, video and account notes) and
``GET /documents/preview`` shows one note's Markdown, both without writing
anything. ``POST /exports`` writes them all into an Obsidian vault in the
background (DOC-006's ``sync_vault``) and answers at once with a job.

Where an export may go is deliberately narrow: a **name**, not a path.
``{"destination": "main"}`` means ``<workspace>/exports/main``. A name is
letters, digits, ``-`` and ``_``, so ``../x``, ``/etc``, a drive path or
``a/b`` are refused before anything is touched (``invalid_destination``),
and a destination that is a link pointing somewhere else is refused too.
Inside the destination, ``sync_vault``'s own promises hold: it never
overwrites a file it didn't make, keeps hand edits and anything written
below the marker line, and reports each case. (To write into a vault
elsewhere on the computer, use ``ke docs vault --vault <folder>``.)

Talking points:
    - "Over the API you can only export into a named folder inside the
      workspace, so a request can't make the engine write anywhere else."
    - "Even there it never overwrites a file I made or a note I edited."
"""

from __future__ import annotations

import re
import secrets
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from knowledge_engine.api.deps import ApiError, SessionsDep, SettingsDep, get_settings
from knowledge_engine.documents.vault import plan_vault, sync_vault
from knowledge_engine.infrastructure.db import SessionFactory
from knowledge_engine.settings import Settings
from knowledge_engine.taxonomy.registry import TaxonomyRegistry, TaxonomySnapshot

router = APIRouter()

_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_KINDS = ("transcript", "knowledge", "project", "topic", "video", "accounts", "account")


def exports_root(settings: Settings) -> Path:
    """Where API exports go: ``<workspace>/exports``."""
    return settings.workspace_root / "exports"


def destination_folder(settings: Settings, name: str) -> Path:
    """The folder for an export name, or ``invalid_destination``.

    Raises:
        ApiError: The name isn't a plain name, or the folder (or the exports
            folder) is a link that leads outside the workspace's exports.
    """
    if not _NAME_RE.fullmatch(name):
        raise ApiError(
            400,
            "invalid_destination",
            "a destination is a name (letters, digits, '-' and '_'), not a path",
        )
    root = exports_root(settings)
    folder = root / name
    # resolve() follows links: a planted link to elsewhere is caught here.
    if folder.exists() or root.exists():
        base = settings.workspace_root.resolve() / "exports"
        if root.resolve() != base or not folder.resolve().is_relative_to(base):
            raise ApiError(400, "invalid_destination", "that destination leads outside exports")
    return folder


@dataclass
class ExportJob:
    """One background export and how it went (counts only: paths hold titles)."""

    job_id: str
    destination: str
    state: str = "running"
    counts: dict[str, int] | None = None
    error: str | None = None
    done: threading.Event = field(default_factory=threading.Event, repr=False)


class ExportJobs:
    """Background exports; one at a time per destination."""

    def __init__(self, settings: Settings) -> None:
        """Create the job list for one workspace."""
        self._settings = settings
        self._jobs: dict[str, ExportJob] = {}
        self._guard = threading.Lock()

    def start(self, folder: Path, name: str, taxonomy: TaxonomySnapshot | None) -> ExportJob:
        """Start an export, unless one to the same destination is still running."""
        with self._guard:
            if any(j.destination == name and j.state == "running" for j in self._jobs.values()):
                raise ApiError(409, "export_running", "an export to that destination is running")
            job = ExportJob(job_id=secrets.token_hex(8), destination=name)
            self._jobs[job.job_id] = job
        threading.Thread(target=self._run, args=(job, folder, taxonomy), daemon=True).start()
        return job

    def get(self, job_id: str) -> ExportJob | None:
        """A job by ID, or None."""
        with self._guard:
            return self._jobs.get(job_id)

    def _run(self, job: ExportJob, folder: Path, taxonomy: TaxonomySnapshot | None) -> None:
        sessions = SessionFactory.from_settings(self._settings)
        try:
            with sessions.transaction(write=False) as session:
                report = sync_vault(
                    session, folder, self._settings.workspace_root / "archive", taxonomy=taxonomy
                )
            job.counts = report.counts()
            job.state = "done"
        except Exception as error:  # noqa: BLE001 - a failed job must still finish
            # The type only: the message could name a private path or title.
            job.error = f"the export stopped with an unexpected error ({type(error).__name__})"
            job.state = "failed"
        finally:
            sessions.dispose()
            job.done.set()


_export_guard = threading.Lock()


def get_export_jobs(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
) -> ExportJobs:
    """The app's export jobs for this workspace (one list per app)."""
    with _export_guard:
        current = getattr(request.app.state, "export_jobs", None)
        if current is None or current[0] is not settings:
            current = (settings, ExportJobs(settings))
            request.app.state.export_jobs = current
        jobs: ExportJobs = current[1]
        return jobs


ExportJobsDep = Annotated[ExportJobs, Depends(get_export_jobs)]


class ExportRequest(BaseModel):
    """``POST /exports``."""

    destination: str = Field(min_length=1, max_length=200)
    taxonomy: str | None = Field(default=None, max_length=100)


def _job(job: ExportJob) -> dict[str, Any]:
    return {
        "job_id": job.job_id,
        "destination": job.destination,
        "state": job.state,
        "counts": job.counts,
        "error": job.error,
    }


def _snapshot(session: Session, version: str | None) -> TaxonomySnapshot | None:
    if version is None:
        return None
    try:
        return TaxonomyRegistry(session).snapshot(version)
    except KeyError as error:
        raise ApiError(404, "not_found", "no such taxonomy version") from error


@router.get("/documents", tags=["documents"])
def list_documents(
    sessions: SessionsDep,
    kind: Annotated[str | None, Query(pattern="^(" + "|".join(_KINDS) + ")$")] = None,
    taxonomy: Annotated[str | None, Query(max_length=100)] = None,
) -> dict[str, Any]:
    """Every note an export would write: its vault path, kind and size. Writes nothing."""
    with sessions.transaction(write=False) as session:
        planned = plan_vault(session, taxonomy=_snapshot(session, taxonomy))
    items = [
        {
            "path": note.path.as_posix(),
            "kind": note.kind,
            "characters": len(note.text),
            "media": len(note.media),
        }
        for note in planned
        if kind is None or note.kind == kind
    ]
    return {"items": items, "total": len(items)}


@router.get("/documents/preview", tags=["documents"])
def preview(
    sessions: SessionsDep,
    path: Annotated[str, Query(min_length=1, max_length=1000)],
    taxonomy: Annotated[str | None, Query(max_length=100)] = None,
) -> dict[str, Any]:
    """One note's Markdown as an export would write it (before the marker line)."""
    with sessions.transaction(write=False) as session:
        planned = plan_vault(session, taxonomy=_snapshot(session, taxonomy))
    # A lookup, never a file read: any path that isn't a planned note is just "not found".
    found = [note for note in planned if note.path.as_posix() == path]
    if not found:
        raise ApiError(404, "not_found", "no such document")
    return {"path": path, "kind": found[0].kind, "markdown": found[0].text}


@router.get("/exports", tags=["documents"])
def list_destinations(settings: SettingsDep) -> dict[str, Any]:
    """Existing export destinations (names only)."""
    root = exports_root(settings)
    names = sorted(p.name for p in root.iterdir() if p.is_dir()) if root.is_dir() else []
    return {"destinations": [n for n in names if _NAME_RE.fullmatch(n)]}


@router.post("/exports", status_code=202, tags=["documents"])
def start_export(
    body: ExportRequest, settings: SettingsDep, sessions: SessionsDep, jobs: ExportJobsDep
) -> dict[str, Any]:
    """Export every note into ``<workspace>/exports/<destination>`` in the background."""
    folder = destination_folder(settings, body.destination)
    with sessions.transaction(write=False) as session:
        snapshot = _snapshot(session, body.taxonomy)
    return _job(jobs.start(folder, body.destination, snapshot))


@router.get("/exports/jobs/{job_id}", tags=["documents"])
def get_export(job_id: str, jobs: ExportJobsDep) -> dict[str, Any]:
    """How a background export is going; counts when done."""
    job = jobs.get(job_id)
    if job is None:
        raise ApiError(404, "not_found", "no such export job")
    return _job(job)
