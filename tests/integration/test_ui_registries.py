"""UI-004: links, videos, accounts and search pages, each mention one click from its message."""

from __future__ import annotations

import io
import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import pytest

from knowledge_engine.importer.run import run_import
from knowledge_engine.settings import Settings
from knowledge_engine.ui.app import make_app

VID = "aBcDeFgHiJk"
MESSAGES = [
    f"Synthetic: watch https://www.youtube.com/watch?v={VID}&t=75 and https://example.org/synth",
    f"Synthetic: again https://youtu.be/{VID} plus https://github.com/Synth-Octo",
    "Synthetic: GitHub: @synth-octo, and ask @someone. Code SYN-UI-0042 <b>bold</b>",
]


def _export(root: Path) -> Path:
    nodes: list[tuple[str, str | None]] = [("root", None)]
    nodes += [(f"m{i}", text) for i, text in enumerate(MESSAGES)]
    mapping: dict[str, Any] = {}
    for i, (node, text) in enumerate(nodes):
        mapping[node] = {
            "id": node,
            "parent": nodes[i - 1][0] if i else None,
            "children": [nodes[i + 1][0]] if i + 1 < len(nodes) else [],
            "message": None
            if text is None
            else {
                "id": node,
                "author": {"role": "user"},
                "create_time": 1704067200.0 + 60 * i,
                "content": {"content_type": "text", "parts": [text]},
                "metadata": {},
            },
        }
    root.mkdir(parents=True)
    conversation = {
        "id": "c-ui4-1",
        "title": "Synthetic registry chat",
        "mapping": mapping,
        "current_node": nodes[-1][0],
    }
    (root / "conversations.json").write_text(json.dumps([conversation]), encoding="utf-8")
    return root


def _get(settings: Settings, target: str) -> tuple[str, str]:
    captured: dict[str, Any] = {}

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        captured["status"] = status

    path, _, query = target.partition("?")
    environ: dict[str, Any] = {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": path,
        "QUERY_STRING": query,
        "HTTP_HOST": "127.0.0.1:8765",
        "CONTENT_LENGTH": "0",
        "wsgi.input": io.BytesIO(b""),
    }
    body: Iterable[bytes] = make_app(settings)(environ, start_response)
    return captured["status"], b"".join(body).decode("utf-8")


@pytest.fixture(scope="module")
def settings(tmp_path_factory: pytest.TempPathFactory) -> Settings:
    root = tmp_path_factory.mktemp("ui4")
    settings = Settings(workspace_root=root / "ws")
    run_import(_export(root / "export"), "acct", format_id=None, settings=settings)
    return settings


def _follow(settings: Settings, page: str) -> list[str]:
    """Return every chat link on a page, after checking its anchor exists there."""
    links = re.findall(r'href="(/chats/[^"#]+)#([^"]+)"', page)
    assert links
    for chat, anchor in links:
        status, chat_page = _get(settings, chat)
        assert status == "200 OK"
        assert f'id="{anchor}"' in chat_page
    return [anchor for _, anchor in links]


def test_links_page_lists_each_address_once(settings: Settings) -> None:
    status, page = _get(settings, "/links")
    assert status == "200 OK"
    assert page.count(">https://example.org/synth<") == 1
    target = re.search(r'href="(/links/link_[0-9a-f]+)">https://example.org/synth<', page)
    assert target is not None
    status, detail = _get(settings, target.group(1))
    assert status == "200 OK" and 'rel="noreferrer noopener"' in detail
    assert len(_follow(settings, detail)) == 1

    _, filtered = _get(settings, "/links?q=github")
    assert "github.com" in filtered and "example.org" not in filtered


def test_video_page_has_both_mentions_and_the_timestamp(settings: Settings) -> None:
    _, page = _get(settings, "/videos")
    assert f'href="/videos/{VID}"' in page and "not requested" in page
    status, detail = _get(settings, f"/videos/{VID}")
    assert status == "200 OK"
    assert len(_follow(settings, detail)) == 2  # one video, two mentions
    assert f"watch?v={VID}&amp;t=75s" in detail and ">1:15<" in detail


def test_accounts_page_links_one_account_and_lists_bare_names(settings: Settings) -> None:
    _, page = _get(settings, "/accounts")
    assert page.count("@synth-octo</a>") == 1
    assert "@someone" in page and "Bare @names" in page
    account = re.search(r'href="(/accounts/acct_[0-9a-f]+)"', page)
    assert account is not None
    _, detail = _get(settings, account.group(1))
    assert len(_follow(settings, detail)) == 2  # the URL and the qualified handle
    assert "https://github.com/Synth-Octo" in detail


def test_search_page_finds_and_escapes(settings: Settings) -> None:
    _, page = _get(settings, "/search?q=SYN-UI-0042&mode=exact")
    assert "1 message." in page
    assert "[SYN-UI-0042]" in page
    _follow(settings, page)
    assert "<b>bold</b>" not in page  # message text is escaped, never markup

    _, injected = _get(settings, "/search?q=%3Cscript%3E&mode=nonsense")
    assert "<script>" not in injected
    assert 'value="tokens" checked' in injected  # unknown mode falls back


@pytest.mark.parametrize(
    "path", ["/links/link_nope", "/videos/short", "/videos/xxxxxxxxxxx", "/accounts/acct_nope"]
)
def test_unknown_ids_are_404(settings: Settings, path: str) -> None:
    status, _ = _get(settings, path)
    assert status == "404 Not Found"


def test_pages_work_before_any_import(tmp_path: Path) -> None:
    empty = Settings(workspace_root=tmp_path / "ws")
    for path in ("/links", "/videos", "/accounts", "/search?q=anything", "/search"):
        status, _ = _get(empty, path)
        assert status == "200 OK"
