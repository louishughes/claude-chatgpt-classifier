"""UI-001: the local web interface shows imports and plain-words reports.

The app is called directly as a WSGI function, so no network is used,
except one test that starts the real server on a free loopback port.
"""

from __future__ import annotations

import io
import shutil
import threading
import urllib.request
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest

from knowledge_engine.importer.run import run_import
from knowledge_engine.settings import Settings
from knowledge_engine.ui.app import NotLocalError, is_loopback, make_app, serve
from knowledge_engine.ui.data import plain_words

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _get(
    settings: Settings, path: str, *, host: str = "127.0.0.1:8765", method: str = "GET"
) -> tuple[str, dict[str, str], str]:
    captured: dict[str, Any] = {}

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        captured["status"], captured["headers"] = status, dict(headers)

    environ = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "HTTP_HOST": host,
        "wsgi.input": io.BytesIO(),
    }
    body: Iterable[bytes] = make_app(settings)(environ, start_response)
    return captured["status"], captured["headers"], b"".join(body).decode("utf-8")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(workspace_root=tmp_path / "ws")


@pytest.fixture
def export(tmp_path: Path) -> Path:
    source = next(p for p in sorted(FIXTURES.rglob("conversations.json")))
    root = tmp_path / "export"
    shutil.copytree(source.parent, root)
    return root


def test_empty_workspace_home_says_no_imports(settings: Settings) -> None:
    status, headers, body = _get(settings, "/")
    assert status.startswith("200")
    assert "No imports yet" in body
    assert "script-src" not in headers["Content-Security-Policy"]  # default-src 'none' covers it
    assert "default-src 'none'" in headers["Content-Security-Policy"]


def test_home_lists_imports_and_report_explains_them(settings: Settings, export: Path) -> None:
    first = run_import(export, "acct", format_id=None, settings=settings)
    run_import(export, "acct", format_id=None, settings=settings)
    _, _, home = _get(settings, "/")
    assert home.count('href="/imports/') == 2
    assert f'href="/imports/{first.import_id}"' in home

    status, _, report = _get(settings, f"/imports/{first.import_id}")
    assert status.startswith("200")
    assert "Your original files were not changed." in report
    assert "<details>" in report


def test_repeat_import_report_says_nothing_new(settings: Settings, export: Path) -> None:
    run_import(export, "acct", format_id=None, settings=settings)
    second = run_import(export, "acct", format_id=None, settings=settings)
    _, _, report = _get(settings, f"/imports/{second.import_id}")
    assert "Nothing new: this export was already in the archive." in report


def test_unknown_and_malformed_pages_are_404(settings: Settings) -> None:
    assert _get(settings, "/imports/nope")[0].startswith("404")
    assert _get(settings, "/imports/../../etc/passwd")[0].startswith("404")
    assert _get(settings, "/elsewhere")[0].startswith("404")
    assert _get(settings, "/", method="POST")[0].startswith("405")


def test_requests_for_other_hosts_are_refused(settings: Settings) -> None:
    # A page elsewhere can point a name it controls at 127.0.0.1 (DNS
    # rebinding); the Host header still names that site, so it's refused.
    assert _get(settings, "/", host="evil.example:8765")[0].startswith("400")
    assert _get(settings, "/", host="localhost:8765")[0].startswith("200")
    assert _get(settings, "/", host="[::1]:8765")[0].startswith("200")


def test_text_from_the_archive_is_escaped(settings: Settings) -> None:
    report = {
        "status": "succeeded",
        "conversations": {},
        "integrity": {"reconciled": False, "mismatches": ["<script>alert(1)</script>"]},
    }
    sentences = [s for _, s in plain_words(report)]
    assert any("<script>" in s for s in sentences)  # plain_words returns raw text...
    from jinja2 import Environment, PackageLoader, select_autoescape

    env = Environment(
        loader=PackageLoader("knowledge_engine.ui", "templates"),
        autoescape=select_autoescape(default=True, default_for_string=True),
    )
    env.filters["when"] = lambda v: "-"
    html = env.get_template("report.html").render(
        version="x", workspace="w", report={"import_id": "i", **report}, lines=plain_words(report)
    )
    assert "<script>" not in html  # ...and the template escapes it
    assert "&lt;script&gt;" in html


def test_plain_words_flags_problems() -> None:
    report = {
        "status": "partial",
        "conversations": {"new": 1, "failed": 2, "not_seen": 3},
        "asset_occurrences": {"available": 4, "missing": 1},
        "summary": {"failed": 2, "candidate_duplicates": 1, "new_media": 1},
        "raw_tree_unchanged": True,
    }
    tones = dict((s, t) for t, s in plain_words(report))
    assert tones["Some images couldn't be found or matched: 1 missing."] == "look"
    assert tones["2 chats couldn't be imported."] == "look"
    assert any("3 chats weren't in this export" in s for s in tones)
    assert plain_words({"status": "running"})[0][0] == "info"


def test_server_refuses_non_loopback_hosts(settings: Settings) -> None:
    assert is_loopback("127.0.0.1") and is_loopback("::1") and is_loopback("localhost")
    assert not is_loopback("0.0.0.0") and not is_loopback("192.168.1.5")
    with pytest.raises(NotLocalError):
        serve(settings, host="0.0.0.0", port=0)


def test_real_server_answers_on_loopback(settings: Settings) -> None:
    server = serve(settings, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        url = f"http://127.0.0.1:{server.server_port}/"
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url, timeout=5) as response:
            assert response.status == 200
            assert "Your archive" in response.read().decode("utf-8")
        with opener.open(url + "style.css", timeout=5) as response:
            assert response.headers["Content-Type"] == "text/css"
    finally:
        server.shutdown()
        server.server_close()
