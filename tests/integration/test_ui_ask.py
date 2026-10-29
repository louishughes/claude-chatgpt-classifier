"""UI-007: the Ask page gives a cited answer or says it can't find one."""

from __future__ import annotations

import io
import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pytest

from knowledge_engine.importer.run import run_import
from knowledge_engine.settings import Settings
from knowledge_engine.ui.app import make_app

TEXTS = [
    "Synthetic: we painted the garden shed bright red last weekend",
    "Synthetic: red is a bold choice for a shed <b>bold</b>",
    "Synthetic: the kubernetes cluster keeps restarting its pods",
]


def _export(root: Path) -> Path:
    nodes: list[tuple[str, str | None]] = [("root", None)]
    nodes += [(f"ask-m{i}", text) for i, text in enumerate(TEXTS)]
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
                "author": {"role": "user" if i % 2 else "assistant"},
                "create_time": 1704067200.0 + 60 * i,
                "content": {"content_type": "text", "parts": [text]},
                "metadata": {},
            },
        }
    chat = {"id": "c-ask", "title": "Synthetic shed", "mapping": mapping, "current_node": "ask-m2"}
    root.mkdir(parents=True)
    (root / "conversations.json").write_text(json.dumps([chat]), encoding="utf-8")
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
    root = tmp_path_factory.mktemp("ui7")
    settings = Settings(workspace_root=root / "ws")
    run_import(_export(root / "export"), "acct", format_id=None, settings=settings)
    return settings


def _ask(settings: Settings, question: str) -> str:
    status, page = _get(settings, "/ask?q=" + quote(question))
    assert status == "200 OK"
    return page


def test_empty_page_has_the_form_and_a_nav_link(settings: Settings) -> None:
    status, page = _get(settings, "/ask")
    assert status == "200 OK"
    assert 'action="/ask"' in page and 'href="/ask" aria-current="page"' in page
    assert "How it looked" not in page


def test_answer_chips_open_the_cited_message(settings: Settings) -> None:
    page = _ask(settings, "what colour did we paint the shed")
    assert "Answered from your chats." in page
    chips = re.findall(r'class="chip" href="(/chats/[^"#]+)#([^"]+)">\[(\d+)\]', page)
    assert chips
    for chat, anchor, _ in chips:
        status, chat_page = _get(settings, chat)
        assert status == "200 OK" and f'id="{anchor}"' in chat_page
    # Every chip number is listed under Sources, and the route is explained.
    for _, _, number in chips:
        assert f'<li value="{number}">' in page
    assert "Route: <strong>" in page and "no AI model called" in page
    assert "<b>bold</b>" not in page  # cited text is escaped, never markup


def test_unanswerable_question_abstains(settings: Settings) -> None:
    page = _ask(settings, "what is the capital of peru")
    assert "Not answered." in page and "can&#39;t find this in your chats" in page
    assert 'class="chip"' not in page and "Sources</h2>" not in page


def test_question_text_is_escaped_and_capped(settings: Settings) -> None:
    page = _ask(settings, "<script>alert(1)</script> shed")
    assert "<script>alert(1)</script>" not in page
    long = _ask(settings, "shed " * 400)
    value = re.search(r'id="q" name="q" type="text" value="([^"]*)"', long)
    assert value is not None and len(value.group(1)) <= 1000


def test_nothing_imported_says_so(tmp_path: Path) -> None:
    page = _ask(Settings(workspace_root=tmp_path / "empty"), "anything")
    assert "Nothing imported yet" in page
