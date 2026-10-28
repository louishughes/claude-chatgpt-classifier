"""UI-001: the local web interface shows imports and plain-words reports.

The app is called directly as a WSGI function, so no network is used,
except one test that starts the real server on a free loopback port.
"""

from __future__ import annotations

import io
import re
import shutil
import threading
import time
import urllib.request
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import pytest

from knowledge_engine.importer.run import run_import
from knowledge_engine.settings import Settings
from knowledge_engine.ui.app import NotLocalError, WSGIApp, is_loopback, make_app, serve
from knowledge_engine.ui.data import plain_words

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _call(
    app: WSGIApp,
    target: str,
    *,
    host: str = "127.0.0.1:8765",
    method: str = "GET",
    form: dict[str, str] | None = None,
    origin: str | None = None,
) -> tuple[str, dict[str, str], str]:
    captured: dict[str, Any] = {}

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        captured["status"], captured["headers"] = status, dict(headers)

    payload = urlencode(form or {}).encode("utf-8")
    path, _, query = target.partition("?")
    environ: dict[str, Any] = {
        "REQUEST_METHOD": method,
        "PATH_INFO": path,
        "QUERY_STRING": query,
        "HTTP_HOST": host,
        "CONTENT_LENGTH": str(len(payload)),
        "wsgi.input": io.BytesIO(payload),
    }
    if origin is not None:
        environ["HTTP_ORIGIN"] = origin
    body: Iterable[bytes] = app(environ, start_response)
    return captured["status"], captured["headers"], b"".join(body).decode("utf-8", errors="replace")


def _get(
    settings: Settings, path: str, *, host: str = "127.0.0.1:8765", method: str = "GET"
) -> tuple[str, dict[str, str], str]:
    return _call(make_app(settings), path, host=host, method=method)


def _token(app: WSGIApp) -> str:
    _, _, page = _call(app, "/import")
    match = re.search(r'name="token" value="([^"]+)"', page)
    assert match is not None
    return match.group(1)


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
    assert _get(settings, "/jobs/unknown")[0].startswith("404")


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


# ---------------------------------------------------------------- UI-002


def test_import_from_the_browser_runs_and_shows_the_report(
    settings: Settings, export: Path
) -> None:
    app = make_app(settings)
    status, headers, _ = _call(
        app,
        "/import",
        method="POST",
        form={"token": _token(app), "source": str(export)},
        origin="http://127.0.0.1:8765",
    )
    assert status.startswith("303")
    job_page = headers["Location"]
    assert job_page.startswith("/jobs/")

    deadline = time.monotonic() + 30
    while True:
        status, headers, body = _call(app, job_page)
        if status.startswith("303") or time.monotonic() > deadline:
            break
        assert "Importing" in body
        assert 'http-equiv="refresh"' in body
        time.sleep(0.05)
    assert status.startswith("303")
    report_page = headers["Location"]
    assert report_page.startswith("/imports/")
    _, _, report = _call(app, report_page)
    assert "Your original files were not changed." in report

    _, _, home = _call(app, "/")
    assert home.count('href="/imports/') == 1


class _FinishesWhileRead:
    """A job that finishes the moment its state is first looked at (#288).

    The real job runs on another thread, so it can finish between the page's
    "is it done?" check and the template drawing the page. This stand-in
    makes that unlucky timing happen every time instead of once in a while.
    """

    import_id = "imp_0123456789abcdef"
    status = "succeeded"
    error = None

    def __init__(self) -> None:
        self._reads = 0

    @property
    def state(self) -> str:
        self._reads += 1
        return "running" if self._reads == 1 else "done"


def test_job_page_is_consistent_when_the_import_finishes_mid_request(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    from knowledge_engine.ui.jobs import ImportJobs

    monkeypatch.setattr(ImportJobs, "get", lambda self, job_id: _FinishesWhileRead())
    status, headers, body = _call(make_app(settings), "/jobs/abc")
    # Either "still running, check again" or "done, here's the report":
    # never a failure page for an import that didn't fail.
    if status.startswith("303"):
        assert headers["Location"].startswith("/imports/")
    else:
        assert 'http-equiv="refresh"' in body
        assert "didn't finish" not in body


def test_import_form_rejects_forged_and_bad_requests(settings: Settings, tmp_path: Path) -> None:
    app = make_app(settings)
    token = _token(app)
    # No token, or a wrong one: another site can make the browser POST, but
    # can't read the token from this app's page.
    assert _call(app, "/import", method="POST", form={"source": "x"})[0].startswith("403")
    forged = {"token": "guess", "source": str(tmp_path)}
    assert _call(app, "/import", method="POST", form=forged)[0].startswith("403")
    # A POST whose Origin is another site is refused before anything else.
    foreign = _call(
        app,
        "/import",
        method="POST",
        form={"token": token, "source": str(tmp_path)},
        origin="https://evil.example",
    )
    assert foreign[0].startswith("403")

    status, _, page = _call(
        app, "/import", method="POST", form={"token": token, "source": str(tmp_path / "nope")}
    )
    assert status.startswith("400")
    assert "doesn&#39;t exist" in page or "doesn't exist" in page
    settings.workspace_root.mkdir(parents=True, exist_ok=True)
    inside = _call(
        app, "/import", method="POST", form={"token": token, "source": str(settings.workspace_root)}
    )
    assert inside[0].startswith("400")
    bad_account = _call(
        app,
        "/import",
        method="POST",
        form={"token": token, "source": str(tmp_path), "account": "../x"},
    )
    assert bad_account[0].startswith("400")


def test_failed_browser_import_says_why(settings: Settings, tmp_path: Path) -> None:
    app = make_app(settings)
    junk = tmp_path / "junk"
    junk.mkdir()
    (junk / "notes.txt").write_text("hello", encoding="utf-8")
    _, headers, _ = _call(
        app, "/import", method="POST", form={"token": _token(app), "source": str(junk)}
    )
    deadline = time.monotonic() + 30
    while True:
        _, _, body = _call(app, headers["Location"])
        if "didn" in body or time.monotonic() > deadline:
            break
        time.sleep(0.05)
    assert "isn&#39;t a ChatGPT export" in body or "isn't a ChatGPT export" in body
    assert str(junk) not in body


# ---------------------------------------------------------------- UI-003

CHATGPT = FIXTURES / "chatgpt"
CASES = sorted(p.name for p in CHATGPT.iterdir() if (p / "manifest.json").is_file())
_NOTE_ANCHOR_RE = re.compile(r" \^(node-[0-9a-f]{32})$", re.MULTILINE)


def _case_root(case: str) -> Path:
    export = CHATGPT / case / "export"
    zips = list(export.glob("*.zip"))
    return zips[0] if zips else export


def _chat_ids(settings: Settings) -> list[str]:
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from knowledge_engine.importer.records import ConversationRow
    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path

    engine = create_sqlite_engine(database_path(settings))
    try:
        with Session(engine) as session:
            return list(session.scalars(select(ConversationRow.conversation_id)).all())
    finally:
        engine.dispose()


def _note_anchors(settings: Settings, conversation_id: str) -> list[str]:
    from sqlalchemy.orm import Session

    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
    from knowledge_engine.rendering.markdown import render_note
    from knowledge_engine.rendering.transcript import load_conversation, transcript_model

    engine = create_sqlite_engine(database_path(settings))
    try:
        with Session(engine) as session:
            note = render_note(transcript_model(load_conversation(session, conversation_id)))
    finally:
        engine.dispose()
    return _NOTE_ANCHOR_RE.findall(note)


@pytest.mark.parametrize("case", CASES)
def test_chat_page_shows_every_message_once(case: str, settings: Settings) -> None:
    run_import(_case_root(case), "fixture", format_id=None, settings=settings)
    app = make_app(settings)
    _, _, listing = _call(app, "/chats")
    for conversation_id in _chat_ids(settings):
        assert f'href="/chats/{conversation_id}"' in listing
        status, _, page = _call(app, f"/chats/{conversation_id}")
        assert status.startswith("200")
        ids = re.findall(r'<article class="message [^"]*" id="(node-[0-9a-f]{32})"', page)
        # Same messages as the transcript note, each exactly once.
        assert sorted(ids) == sorted(_note_anchors(settings, conversation_id))
        assert len(ids) == len(set(ids))
        assert "<script" not in page.lower()


@pytest.mark.parametrize("case", ["branches_edit", "branches_regen"])
def test_branches_are_labelled_and_link_to_where_they_leave(case: str, settings: Settings) -> None:
    run_import(_case_root(case), "fixture", format_id=None, settings=settings)
    app = make_app(settings)
    pages = [_call(app, f"/chats/{cid}")[2] for cid in _chat_ids(settings)]
    branched = [page for page in pages if "Other branches" in page]
    assert branched
    for page in branched:
        assert re.search(r"<h3>Branch \([a-z_]+\)</h3>", page)
        for anchor in re.findall(r'<a href="#(node-[0-9a-f]{32})">Go there', page):
            assert f'id="{anchor}"' in page


def test_images_are_shown_and_served_only_if_unchanged(settings: Settings, tmp_path: Path) -> None:
    export = tmp_path / "repeated"
    shutil.copytree(_case_root("repeated_image"), export)
    run_import(export, "fixture", format_id=None, settings=settings)
    app = make_app(settings)
    urls: set[str] = set()
    for conversation_id in _chat_ids(settings):
        _, _, page = _call(app, f"/chats/{conversation_id}")
        urls.update(re.findall(r'<img src="(/media/[0-9a-f]{64})"', page))
    assert urls
    url = sorted(urls)[0]
    status, headers, _ = _call(app, url)
    assert status.startswith("200")
    assert headers["Content-Type"].startswith("image/")
    assert headers["X-Content-Type-Options"] == "nosniff"

    # Reference mode: the image still lives in the export. If it is edited
    # after the import, the app refuses to serve the changed bytes.
    for image in (export / "images").rglob("*"):
        if image.is_file():
            image.write_bytes(image.read_bytes() + b"changed")
    assert _call(app, url)[0].startswith("404")


def test_missing_images_are_marked_with_a_reason(settings: Settings) -> None:
    run_import(_case_root("asset_problems"), "fixture", format_id=None, settings=settings)
    app = make_app(settings)
    pages = " ".join(_call(app, f"/chats/{cid}")[2] for cid in _chat_ids(settings))
    assert re.search(r'<p class="error">Image (missing|unresolved|ambiguous)', pages)


def test_chat_list_search_and_bad_addresses(settings: Settings) -> None:
    assert "0 chats" in _call(make_app(settings), "/chats")[2]  # nothing imported yet
    run_import(
        _case_root("same_title_different_chat"), "fixture", format_id=None, settings=settings
    )
    app = make_app(settings)
    _, _, everything = _call(app, "/chats")
    total = len(re.findall(r'href="/chats/conv_', everything))
    assert total >= 2
    # "%" is a wildcard in SQL; here it is just a character, so nothing matches.
    _, _, none = _call(app, "/chats?q=%25")
    assert "0 chats" in none
    assert _call(app, "/chats/conv_nope")[0].startswith("404")
    assert _call(app, "/chats/../../x")[0].startswith("404")
    assert _call(app, "/media/" + "0" * 64)[0].startswith("404")
    assert _call(app, "/media/not-a-hash")[0].startswith("404")


def test_chat_list_counts_match_the_chat_page(settings: Settings) -> None:
    run_import(_case_root("branches_regen"), "fixture", format_id=None, settings=settings)
    app = make_app(settings)
    _, _, listing = _call(app, "/chats")
    for conversation_id in _chat_ids(settings):
        row = re.search(
            rf'href="/chats/{conversation_id}">.*?</td>\s*<td>.*?</td>\s*<td>(\d+)</td>',
            listing,
            re.S,
        )
        assert row is not None
        page = _call(app, f"/chats/{conversation_id}")[2]
        assert f"· {row.group(1)} messages ·" in page
