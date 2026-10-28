"""What every API endpoint can ask for, and the API's error type (API-001).

Endpoints never build their own database connection or model provider:
they declare a dependency from here, and FastAPI supplies it per request.
Tests replace any of them with ``app.dependency_overrides``.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends, Request
from pydantic import BaseModel

from knowledge_engine.infrastructure.db import SessionFactory, database_path
from knowledge_engine.infrastructure.upgrade import SchemaMismatchError, require_current
from knowledge_engine.providers.base import StructuredModelProvider
from knowledge_engine.providers.file_batch import FileBatchProvider
from knowledge_engine.settings import Settings
from knowledge_engine.ui.jobs import ImportJobs


class ApiError(Exception):
    """A failure an endpoint reports on purpose, with a stable code.

    Attributes:
        status: The HTTP status, e.g. 404.
        code: A short machine-readable name, e.g. ``not_found``.
        message: One sentence for a person. Never private text.
    """

    def __init__(self, status: int, code: str, message: str) -> None:
        """Describe the failure (see the class attributes)."""
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


class ErrorDetail(BaseModel):
    """The inside of every error answer."""

    code: str
    message: str


class ErrorBody(BaseModel):
    """What every failed request gets back."""

    error: ErrorDetail


# --------------------------------------------------------------- dependencies
# Each of these is what an endpoint asks for. Tests swap them out with
# app.dependency_overrides[get_settings] = lambda: test_settings, and so on.


WORKSPACE_HEADER = "X-KE-Workspace"
_tenants_guard = threading.Lock()


def get_settings(request: Request) -> Settings:
    """The settings of the workspace this request is about.

    One person's engine: the settings the app was created with. With
    ``tenants_root`` set (PROD-003), the ``X-KE-Workspace`` header names a
    tenant and the request gets that tenant's own folder; every other
    dependency (database, indexes, jobs, exports) is built from it.

    Raises:
        ApiError: 400 ``workspace_required`` without the header; 401
            ``unauthenticated`` for a name that isn't a created workspace
            (the same answer as a bad token, so names can't be probed).
    """
    from knowledge_engine.access.tenants import tenant_exists, tenant_settings

    base: Settings = request.app.state.settings
    if base.tenants_root is None:
        return base
    name = request.headers.get(WORKSPACE_HEADER, "").strip()
    if not name:
        raise ApiError(400, "workspace_required", f"send the {WORKSPACE_HEADER} header")
    if not tenant_exists(base, name):
        raise ApiError(401, "unauthenticated", "unknown workspace or token")
    # One Settings object per tenant, so per-workspace job lists stay put.
    with _tenants_guard:
        known: dict[str, Settings] = request.app.state.tenants
        if name not in known:
            known[name] = tenant_settings(base, name)
        return known[name]


def get_sessions(settings: Annotated[Settings, Depends(get_settings)]) -> Iterator[SessionFactory]:
    """A database session factory, only if the schema matches this code.

    Raises:
        ApiError: ``no_database`` (503) before the first import, or
            ``schema_mismatch`` (503) when ``ke db upgrade`` is needed or
            the database is from a newer version.
    """
    if not database_path(settings).exists():
        raise ApiError(503, "no_database", "nothing has been imported into this workspace yet")
    sessions = SessionFactory.from_settings(settings)
    try:
        try:
            require_current(sessions.engine)
        except SchemaMismatchError as error:
            raise ApiError(503, "schema_mismatch", str(error)) from error
        yield sessions
    finally:
        sessions.dispose()


def get_provider(settings: Annotated[Settings, Depends(get_settings)]) -> StructuredModelProvider:
    """The model provider: by default the file-batch one (ADR-0009).

    It writes request files for a Claude Code session to answer; it refuses
    to write any while ``[egress] text_llm`` is off. Tests swap in a fake.
    """
    return FileBatchProvider(settings.model_batch_root, "api", settings.egress)


_jobs_guard = threading.Lock()


def get_jobs(request: Request, settings: Annotated[Settings, Depends(get_settings)]) -> ImportJobs:
    """The app's background imports for this workspace (one list per workspace).

    It is kept on the app, so ``GET /jobs/{id}`` finds a job that an earlier
    ``POST /imports`` started. A new list is made for new settings (another
    tenant, or a test overriding them).
    """
    with _jobs_guard:
        if request.app.state.settings.tenants_root is not None:
            # One list per tenant: a job started in one workspace can't be
            # looked up from another.
            lists: dict[str, ImportJobs] = request.app.state.tenant_jobs
            key = str(settings.workspace_root)
            if key not in lists:
                lists[key] = ImportJobs(settings)
            return lists[key]
        current = getattr(request.app.state, "jobs", None)
        if current is None or current[0] is not settings:
            current = (settings, ImportJobs(settings))
            request.app.state.jobs = current
        jobs: ImportJobs = current[1]
        return jobs


SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionsDep = Annotated[SessionFactory, Depends(get_sessions)]
ProviderDep = Annotated[StructuredModelProvider, Depends(get_provider)]
JobsDep = Annotated[ImportJobs, Depends(get_jobs)]
