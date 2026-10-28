"""The web app behind ``ke ui``: routes, pages and the local-only server (UI-001).

It is a plain WSGI app (the standard Python web interface), so it needs no
web framework and the tests can call it directly without a network.

Safety rules, all enforced here:

* the server binds to a loopback address (127.0.0.1 / ::1) and refuses
  anything else, so nobody else on the network can open it;
* every request's ``Host`` header must name this machine, which stops a
  web page elsewhere from reaching the app through a DNS trick;
* every page is rendered with auto-escaping, and pages are sent with a
  strict Content-Security-Policy (no scripts from anywhere).

Talking points:
    - "It's a tiny website on my own machine: it refuses to listen on the
      network, and every page is escaped so chat text can't become code."
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from socketserver import ThreadingMixIn
from typing import Any
from urllib.parse import urlsplit
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

from jinja2 import Environment, PackageLoader, select_autoescape
from sqlalchemy.orm import Session

from knowledge_engine import __version__
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.settings import Settings
from knowledge_engine.ui import data

StartResponse = Callable[[str, list[tuple[str, str]]], Any]
WSGIApp = Callable[[dict[str, Any], StartResponse], Iterable[bytes]]

_IMPORT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
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

    def app(environ: dict[str, Any], start_response: StartResponse) -> Iterable[bytes]:
        if not _host_is_local(environ.get("HTTP_HOST", "")):
            start_response("400 Bad Request", [("Content-Type", "text/plain")])
            return [b"This app only answers requests addressed to localhost."]
        method = environ.get("REQUEST_METHOD", "GET")
        path = environ.get("PATH_INFO", "/")
        if path == "/style.css" and method == "GET":
            start_response("200 OK", [("Content-Type", "text/css"), ("Cache-Control", "no-store")])
            return [style]
        page = _route(settings, method, path)
        body = env.get_template(page.template).render(
            version=__version__, workspace=str(settings.workspace_root), **page.values
        )
        start_response(page.status, list(_HEADERS))
        return [body.encode("utf-8")]

    return app


def _route(settings: Settings, method: str, path: str) -> Page:
    if method != "GET":
        return Page("405 Method Not Allowed", "error.html", {"message": "Not allowed."})
    if path == "/":
        return _home(settings)
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
