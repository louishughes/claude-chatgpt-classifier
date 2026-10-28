"""The API's app factory, its swappable parts, and its one error shape (API-001).

``create_app(settings)`` builds a FastAPI app for one workspace. Everything
an endpoint needs from outside (the settings, the database, the model
provider) arrives through a *dependency*: a small function FastAPI calls
for each request. Tests replace those functions with
``app.dependency_overrides`` so an endpoint runs against a temporary
database and a fake model, with no network and no real workspace.

Rules every endpoint gets for free:

* **One error shape.** Every failure is ``{"error": {"code", "message"}}``
  with a stable ``code`` a program can branch on. Validation errors name the
  bad fields but never echo the values sent (they could be private text),
  and an unexpected crash says ``internal_error`` without a traceback.
* **Versioned paths.** Everything is under ``/api/v1``; the OpenAPI
  document at ``/api/v1/openapi.json`` carries the package version.
* **This computer only.** Requests must name a loopback host
  (``127.0.0.1``, ``localhost``, ``[::1]``), which stops a web page
  elsewhere reaching the API through a DNS trick. ``ke api`` refuses to
  listen on anything but a loopback address. No CORS headers are sent, so
  another site's scripts can't read the answers.
* **Schema check.** An endpoint that opens the database refuses
  (``schema_mismatch``, 503) when the database is older or newer than the
  code, exactly as imports do (OPS-007).

Talking points:
    - "The API is one factory with swappable parts: in tests the database
      and the model are fakes, in real use they're my workspace."
    - "Every error has the same shape and a stable code, and it never
      repeats what was sent, so private text can't leak through an error."
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException

from knowledge_engine import __version__
from knowledge_engine.api import imports, knowledge, retrieval
from knowledge_engine.api.deps import (
    ApiError,
    ErrorBody,
    ErrorDetail,
    ProviderDep,
    SessionsDep,
    SettingsDep,
    get_jobs,
    get_provider,
    get_sessions,
    get_settings,
)
from knowledge_engine.infrastructure.db import SessionFactory, database_path
from knowledge_engine.infrastructure.migrations import current_revision, head_revision
from knowledge_engine.settings import Capability, Settings
from knowledge_engine.ui.app import is_loopback
from knowledge_engine.ui.data import workspace_status

API_VERSION = "v1"
PREFIX = f"/api/{API_VERSION}"
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
# Re-exported so tests and later endpoints have one place to import from.
__all__ = ["ApiError", "create_app", "get_jobs", "get_provider", "get_sessions", "get_settings"]


class Health(BaseModel):
    """``GET /health``: the process is up. Touches nothing else."""

    status: str
    version: str
    api_version: str


class DatabaseStatus(BaseModel):
    """The workspace database's schema, as ``ke status`` shows it."""

    exists: bool
    revision: str
    latest: str


class ProviderStatus(BaseModel):
    """Which model provider the API would use, and whether egress allows it."""

    name: str
    capability: str
    version: str
    allowed: bool


class Status(BaseModel):
    """``GET /status``: version, database schema, egress switches, provider.

    No folder paths: they can name private things, and a program using the
    API doesn't need them.
    """

    version: str
    api_version: str
    database: DatabaseStatus
    egress_enabled: list[str]
    provider: ProviderStatus


def _error(status: int, code: str, message: str) -> JSONResponse:
    body = ErrorBody(error=ErrorDetail(code=code, message=message))
    return JSONResponse(body.model_dump(), status_code=status)


# ------------------------------------------------------------------ the app


def create_app(settings: Settings) -> FastAPI:
    """Build the API for one workspace.

    Args:
        settings: The workspace's settings.

    Returns:
        The app. Serve it with ``ke api`` or call it with a test client.
    """
    app = FastAPI(
        title="Knowledge Engine API",
        version=__version__,
        openapi_url=f"{PREFIX}/openapi.json",
        docs_url=f"{PREFIX}/docs",
        redoc_url=None,
        responses={503: {"model": ErrorBody}},
    )
    app.state.settings = settings
    _add_error_handlers(app)
    app.include_router(imports.router, prefix=PREFIX)
    app.include_router(knowledge.router, prefix=PREFIX)
    app.include_router(retrieval.router, prefix=PREFIX)

    @app.middleware("http")
    async def local_only(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # A DNS-rebinding page sends its own domain as Host: refuse it
        # before any endpoint runs.
        if not host_is_local(request.headers.get("host", "")):
            return _error(400, "host_not_local", "this API only answers requests to this computer")
        if request.method not in _SAFE_METHODS:
            # A web page elsewhere can make the browser POST here (the Host is
            # then 127.0.0.1), but only as a form or plain text, and with its
            # own Origin. JSON bodies need a CORS preflight, which this API
            # never grants, so requiring JSON plus a local Origin stops it.
            origin = request.headers.get("origin")
            if origin is not None and not host_is_local(urlsplit(origin).netloc):
                return _error(403, "origin_not_local", "requests from other sites are refused")
            if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
                return _error(415, "json_required", "send the request body as application/json")
        return await call_next(request)

    @app.get(f"{PREFIX}/health", response_model=Health, tags=["system"])
    def health() -> Health:
        return Health(status="ok", version=__version__, api_version=API_VERSION)

    @app.get(f"{PREFIX}/status", response_model=Status, tags=["system"])
    def status(settings: SettingsDep, provider: ProviderDep) -> Status:
        return Status(
            version=__version__,
            api_version=API_VERSION,
            database=_database_status(settings),
            egress_enabled=[c.value for c in Capability if settings.egress.allows(c)],
            provider=ProviderStatus(
                name=provider.identity.provider_id,
                capability=provider.identity.capability.value,
                version=provider.identity.version,
                allowed=not provider.identity.sends_data
                or settings.egress.allows(provider.identity.capability),
            ),
        )

    @app.get(f"{PREFIX}/counts", response_model=dict[str, int], tags=["system"])
    def counts(sessions: SessionsDep) -> dict[str, int]:
        """How many conversations, messages, imports... are stored (numbers only)."""
        with sessions.transaction(write=False) as session:
            return workspace_status(session)

    return app


def _database_status(settings: Settings) -> DatabaseStatus:
    # Status must work on a database of any version, so this reads the
    # revision directly instead of going through get_sessions' check.
    path = database_path(settings)
    revision = None
    if path.exists():
        sessions = SessionFactory.from_settings(settings)
        try:
            revision = current_revision(sessions.engine)
        finally:
            sessions.dispose()
    return DatabaseStatus(exists=path.exists(), revision=revision or "none", latest=head_revision())


def _add_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def api_error(_request: Request, error: ApiError) -> JSONResponse:
        return _error(error.status, error.code, error.message)

    @app.exception_handler(RequestValidationError)
    async def invalid(_request: Request, error: RequestValidationError) -> JSONResponse:
        # Field locations only: the values sent may be private text.
        fields = sorted({".".join(str(p) for p in e["loc"]) for e in error.errors()})
        return _error(422, "invalid_request", "invalid fields: " + ", ".join(fields))

    @app.exception_handler(HTTPException)
    async def http_error(_request: Request, error: HTTPException) -> JSONResponse:
        codes = {404: "not_found", 405: "method_not_allowed"}
        code = codes.get(error.status_code, f"http_{error.status_code}")
        message = error.detail if isinstance(error.detail, str) else code
        return _error(error.status_code, code, message)

    @app.exception_handler(Exception)
    async def crash(_request: Request, _exc: Exception) -> JSONResponse:
        # No traceback: it could quote private text from a failed query.
        return _error(500, "internal_error", "the server hit an unexpected error")


def host_is_local(host_header: str) -> bool:
    """True if a ``Host`` header names this machine (``[::1]:8766`` -> ``::1``)."""
    try:
        host = urlsplit("//" + host_header).hostname
    except ValueError:
        return False
    return host is not None and is_loopback(host)
