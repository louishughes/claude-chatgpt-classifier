"""The web app behind ``ke ui``: routes, pages and the local-only server (UI-001).

It is a plain WSGI app (the standard Python web interface), so it needs no
web framework and the tests can call it directly without a network.

Safety rules, all enforced here:

* the server binds to a loopback address (127.0.0.1 / ::1) and refuses
  anything else, so nobody else on the network can open it;
* every request's ``Host`` header must name this machine, which stops a
  web page elsewhere from reaching the app through a DNS trick;
* every page is rendered with auto-escaping, and pages are sent with a
  strict Content-Security-Policy (no scripts from anywhere);
* a form (the Import button) must carry this run's secret token and come
  from this app's own address, so another website can't submit it.

Talking points:
    - "It's a tiny website on my own machine: it refuses to listen on the
      network, and every page is escaped so chat text can't become code."
"""

from __future__ import annotations

import ipaddress
import re
import secrets
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from socketserver import ThreadingMixIn
from typing import Any
from urllib.parse import parse_qs, urlsplit
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from jinja2 import Environment, PackageLoader, select_autoescape
from sqlalchemy.orm import Session

from knowledge_engine import __version__
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.settings import Settings
from knowledge_engine.ui import data
from knowledge_engine.ui.jobs import ImportJobs

StartResponse = Callable[[str, list[tuple[str, str]]], Any]
WSGIApp = Callable[[dict[str, Any], StartResponse], Iterable[bytes]]

_IMPORT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_ACCOUNT_RE = re.compile(r"^[A-Za-z0-9_-]{1,63}$")
_MAX_FORM_BYTES = 64 * 1024
_HEADERS = [
    ("Content-Type", "text/html; charset=utf-8"),
    # No scripts at all, styles only from the page itself, no framing.
    ("Content-Security-Policy", "default-src 'none'; style-src 'self'; frame-ancestors 'none'"),
    ("X-Content-Type-Options", "nosniff"),
    ("Referrer-Policy", "no-referrer"),
    ("Cache-Control", "no-store"),
]


class NotLocalError(ValueError):
    """Raised when asked to serve on an address other than this machine."""


@dataclass(frozen=True)
class Page:
    """A response: HTTP status, template name and its values."""

    status: str
    template: str
    values: dict[str, Any]
    location: str | None = None  # set for a redirect (303 See Other)


@dataclass(frozen=True)
class _Context:
    settings: Settings
    jobs: ImportJobs
    # A random token in every form. A web page elsewhere can make the
    # browser POST here, but can't read this token, so its POST is refused.
    form_token: str


def is_loopback(host: str) -> bool:
    """Return True if ``host`` is this machine only (127.x.x.x, ::1, localhost)."""
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def make_app(settings: Settings) -> WSGIApp:
    """Return the WSGI app for one workspace.

    Args:
        settings: The workspace's settings.

    Returns:
        A WSGI callable.
    """
    env = Environment(
        loader=PackageLoader("knowledge_engine.ui", "templates"),
        autoescape=select_autoescape(default=True, default_for_string=True),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["when"] = _when
    style = (env.loader.get_source(env, "style.css")[0]).encode("utf-8")  # type: ignore[union-attr]
    ctx = _Context(settings, ImportJobs(settings), secrets.token_urlsafe(24))

    def app(environ: dict[str, Any], start_response: StartResponse) -> Iterable[bytes]:
        if not _host_is_local(environ.get("HTTP_HOST", "")):
            start_response("400 Bad Request", [("Content-Type", "text/plain")])
            return [b"This app only answers requests addressed to localhost."]
        method = environ.get("REQUEST_METHOD", "GET")
        path = environ.get("PATH_INFO", "/")
        if path == "/style.css" and method == "GET":
            start_response("200 OK", [("Content-Type", "text/css"), ("Cache-Control", "no-store")])
            return [style]
        if method == "POST" and not _origin_is_local(environ.get("HTTP_ORIGIN")):
            page = Page("403 Forbidden", "error.html", {"message": "Refused: not from this app."})
        else:
            page = _route(ctx, method, path, environ)
        if page.location is not None:
            start_response("303 See Other", [("Location", page.location), *_HEADERS])
            return [b""]
        body = env.get_template(page.template).render(
            version=__version__,
            workspace=str(settings.workspace_root),
            form_token=ctx.form_token,
            **page.values,
        )
        start_response(page.status, list(_HEADERS))
        return [body.encode("utf-8")]

    return app


def _route(ctx: _Context, method: str, path: str, environ: dict[str, Any]) -> Page:
    settings = ctx.settings
    if path == "/import":
        if method == "POST":
            return _start_import(ctx, _read_form(environ))
        if method == "GET":
            return _import_form(settings, {}, None)
    if method != "GET":
        return Page("405 Method Not Allowed", "error.html", {"message": "Not allowed."})
    if path == "/":
        return _home(settings)
    if path.startswith("/jobs/"):
        job = ctx.jobs.get(path.removeprefix("/jobs/"))
        if job is not None:
            if job.state == "done" and job.import_id:
                return Page("303 See Other", "", {}, location=f"/imports/{job.import_id}")
            return Page("200 OK", "job.html", {"job": job})
    if path.startswith("/imports/"):
        import_id = path.removeprefix("/imports/")
        if _IMPORT_ID_RE.fullmatch(import_id):
            return _report(settings, import_id)
    return Page("404 Not Found", "error.html", {"message": "There's no page here."})


def _home(settings: Settings) -> Page:
    db = database_path(settings)
    if not db.exists():
        return Page("200 OK", "home.html", {"status": None, "imports": []})
    engine = create_sqlite_engine(db)
    try:
        with Session(engine) as session:
            values = {
                "status": data.workspace_status(session),
                "imports": data.list_imports(session),
            }
    finally:
        engine.dispose()
    return Page("200 OK", "home.html", values)


def _report(settings: Settings, import_id: str) -> Page:
    db = database_path(settings)
    report = None
    if db.exists():
        engine = create_sqlite_engine(db)
        try:
            with Session(engine) as session:
                report = data.load_report(session, import_id)
        finally:
            engine.dispose()
    if report is None:
        return Page("404 Not Found", "error.html", {"message": "No import with that ID."})
    return Page("200 OK", "report.html", {"report": report, "lines": data.plain_words(report)})


def _import_form(settings: Settings, form: dict[str, str], error: str | None) -> Page:
    roots = [(str(root.path), root.account_namespace) for root in settings.raw_roots]
    status = "400 Bad Request" if error else "200 OK"
    return Page(status, "import.html", {"roots": roots, "form": form, "error": error})


def _start_import(ctx: _Context, form: dict[str, str]) -> Page:
    if not secrets.compare_digest(form.get("token", ""), ctx.form_token):
        return Page("403 Forbidden", "error.html", {"message": "Refused: not from this app."})
    raw = form.get("source", "").strip().strip('"')
    if not raw:
        return _import_form(ctx.settings, form, "Choose the export folder or ZIP to import.")
    source = Path(raw).expanduser()
    if not source.exists():
        return _import_form(ctx.settings, form, "That file or folder doesn't exist.")
    if source.resolve().is_relative_to(ctx.settings.workspace_root.resolve()):
        return _import_form(ctx.settings, form, "That's inside the workspace, not an export.")
    account = form.get("account", "").strip() or ctx.settings.account_for(source)
    if not _ACCOUNT_RE.fullmatch(account):
        return _import_form(
            ctx.settings, form, "Account labels use letters, numbers, '-' and '_' only."
        )
    job = ctx.jobs.start(source, account, partial=form.get("partial") == "on")
    return Page("303 See Other", "", {}, location=f"/jobs/{job.job_id}")


def _read_form(environ: dict[str, Any]) -> dict[str, str]:
    try:
        length = int(environ.get("CONTENT_LENGTH") or 0)
    except ValueError:
        length = 0
    if length <= 0 or length > _MAX_FORM_BYTES:
        return {}
    body = environ["wsgi.input"].read(length).decode("utf-8", errors="replace")
    return {key: values[0] for key, values in parse_qs(body).items()}


def _origin_is_local(origin: str | None) -> bool:
    # Browsers send Origin on POSTs; a missing one (old clients, tests) is
    # covered by the form token.
    if origin is None:
        return True
    return _host_is_local(urlsplit(origin).netloc)


def _host_is_local(host_header: str) -> bool:
    # "localhost:8765" -> "localhost"; "[::1]:8765" -> "::1".
    try:
        host = urlsplit("//" + host_header).hostname
    except ValueError:
        return False
    return host is not None and is_loopback(host)


def _when(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M") if value else "-"


class _ThreadingServer(ThreadingMixIn, WSGIServer):
    daemon_threads = True


class _QuietHandler(WSGIRequestHandler):
    # The default handler prints every request line; URLs can carry IDs,
    # so the server stays quiet and the terminal shows only what we print.
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        return


def serve(settings: Settings, host: str = "127.0.0.1", port: int = 8765) -> WSGIServer:
    """Create (but don't start) the local server for a workspace.

    Args:
        settings: The workspace's settings.
        host: Must be a loopback address.
        port: TCP port; 0 picks a free one.

    Returns:
        The server; call ``serve_forever()`` on it.

    Raises:
        NotLocalError: If ``host`` isn't this machine.
    """
    if not is_loopback(host):
        raise NotLocalError("the interface only listens on this computer (127.0.0.1)")
    return make_server(
        host, port, make_app(settings), server_class=_ThreadingServer, handler_class=_QuietHandler
    )
