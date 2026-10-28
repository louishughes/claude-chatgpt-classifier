"""NOTE-012: the chat page shows the knowledge note beside the transcript; /notes lists them.

The chat is synthetic; its records come from the real rule extractors and
its digest from ``FakeProvider`` through the NOTE-003 stage, so the page
shows what the engine really writes.
"""

from __future__ import annotations

import io
import json
import re
from collections.abc import Iterable
from functools import partial
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.digest.stage import DigestStage
from knowledge_engine.extraction import actions, decisions, preferences
from knowledge_engine.extraction.runner import RuleExtractor, run
from knowledge_engine.extraction.text import segment_extraction_messages
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.importer.run import run_import
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.providers.base import FakeProvider, ModelRequest
from knowledge_engine.providers.ledger import ModelStageRunner
from knowledge_engine.rendering.transcript import load_conversation, message_anchor
from knowledge_engine.segmentation.overrides import load_segments
from knowledge_engine.settings import EgressPolicy, Settings
from knowledge_engine.ui.app import make_app
from knowledge_engine.ui.notes import note_html

_TAG = re.compile(r"^\[m:([^\]]+)\] (\w+):\n(.+)$", re.M)
# Chat text that would be markup if it were not escaped.
SNEAKY = "Which wood should the raised bed use, cedar or pine? <script>alert(1)</script>"


def _export(root: Path) -> Path:
    nodes = [
        ("u1", "user", SNEAKY),
        ("a1", "assistant", "I suggest cedar boards because they resist rot."),
        ("u2", "user", "Yes, let's do that. I'll order the cedar boards tomorrow."),
        ("a2", "assistant", "Good. Line the bed with landscape fabric first."),
    ]
    mapping: dict[str, Any] = {"root": {"id": "root", "parent": None, "children": []}}
    parent = "root"
    for i, (node, role, text) in enumerate(nodes):
        mapping[node] = {
            "id": node,
            "parent": parent,
            "children": [],
            "message": {
                "id": node,
                "author": {"role": role},
                "create_time": 1704067200.0 + 60 * i,
                "content": {"content_type": "text", "parts": [text]},
                "metadata": {},
            },
        }
        mapping[parent]["children"].append(node)
        parent = node
    chat = {
        "id": "c-garden",
        "title": "Synthetic garden",
        "create_time": 1704067200.0,
        "mapping": mapping,
        "current_node": parent,
    }
    root.mkdir(parents=True)
    (root / "conversations.json").write_text(json.dumps([chat]), encoding="utf-8")
    return root


def _digest_answer(request: ModelRequest) -> dict[str, Any]:
    tags = _TAG.findall(request.input_text)
    first_id, _, first_text = tags[0]
    last_id, _, last_text = tags[-1]
    start = [{"message_id": first_id, "text": " ".join(first_text.split()[:3])}]
    end = [{"message_id": last_id, "text": " ".join(last_text.split()[:3])}]
    return {
        "summary": [
            {"text": "The user asked which wood to use.", "quotes": start},
            {"text": "They chose cedar.", "quotes": end},
        ],
        "purpose": {"text": "Pick a wood for a raised bed.", "quotes": start},
        "status": {"value": "settled", "quotes": end},
        "intent": {"value": "decide", "text": "Choose a wood.", "quotes": start},
        "open_questions": [{"text": "How thick should the boards be?", "quotes": start}],
    }


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    settings = Settings(workspace_root=tmp_path / "ws")
    run_import(_export(tmp_path / "export"), "acct", format_id=None, settings=settings)
    with Session(create_sqlite_engine(database_path(settings))) as session:
        [cid] = session.scalars(select(ConversationRow.conversation_id)).all()
        chat = load_conversation(session, cid)
        segments = [
            (s.segment_id, segment_extraction_messages(chat, s))
            for s in load_segments(session, chat)
        ]
        occurrences = actions.load_occurrences(session, list(chat.revisions.values()))
        run(
            session,
            segments,
            [
                RuleExtractor(
                    "decisions", decisions.EXTRACTOR_VERSION, decisions.extract_decisions
                ),
                RuleExtractor(
                    "preferences", preferences.EXTRACTOR_VERSION, preferences.extract_preferences
                ),
                RuleExtractor(
                    "actions",
                    actions.EXTRACTOR_VERSION,
                    partial(actions.extract_actions, occurrences=occurrences),
                ),
            ],
        )
        runner = ModelStageRunner(
            session, FakeProvider(_digest_answer), EgressPolicy(text_llm=True)
        )
        assert DigestStage(runner).run(chat).state == "done"
        session.commit()
    return settings


def _get(settings: Settings, path: str) -> tuple[str, str]:
    captured: dict[str, Any] = {}

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        captured["status"] = status

    environ = {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": path,
        "QUERY_STRING": "",
        "HTTP_HOST": "127.0.0.1:8765",
        "CONTENT_LENGTH": "0",
        "wsgi.input": io.BytesIO(b""),
    }
    body: Iterable[bytes] = make_app(settings)(environ, start_response)
    return captured["status"], b"".join(body).decode("utf-8")


class _Page(HTMLParser):
    """Collects element IDs, links inside the note, and any script tags."""

    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.cites: list[tuple[str, str]] = []  # (href, label)
        self.scripts = 0
        self._href: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.add(str(values["id"]))
        if tag == "script":
            self.scripts += 1
        if tag == "a" and values.get("class") == "cite":
            self._href = values.get("href")

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self.cites.append((self._href, data))
            self._href = None


def _conversation_id(settings: Settings) -> str:
    with Session(create_sqlite_engine(database_path(settings))) as session:
        return str(session.scalars(select(ConversationRow.conversation_id)).one())


def test_chat_page_shows_summary_card_and_decisions_beside_the_transcript(
    settings: Settings,
) -> None:
    cid = _conversation_id(settings)
    status, page = _get(settings, f"/chats/{cid}")

    assert status.startswith("200")
    note = page.split('<div class="note">', 1)[1].split('<section class="transcript-pane"', 1)[0]
    assert "The user asked which wood to use." in note  # summary
    assert '<table class="note-card">' in note and "Pick a wood for a raised bed." in note  # card
    assert "<h3>Decisions</h3>" in note and "Decided." in note
    assert "How thick should the boards be?" in note  # open question from the digest
    assert '<section class="transcript-pane" id="transcript">' in page


def test_every_citation_opens_the_message_it_names(settings: Settings) -> None:
    cid = _conversation_id(settings)
    _, page = _get(settings, f"/chats/{cid}")
    parsed = _Page()
    parsed.feed(page)

    with Session(create_sqlite_engine(database_path(settings))) as session:
        chat = load_conversation(session, cid)
        expected = {
            f"m{chat.graph.message_number(native)}": f"#{message_anchor(key)}"
            for native, key in chat.node_keys.items()
            if chat.graph.message_number(native) is not None
        }
    assert parsed.cites, "the note should cite messages"
    for href, label in parsed.cites:
        assert href == expected[label], (href, label)  # m3 jumps to message 3, not another
        assert href[1:] in parsed.ids  # and that message is on the page


def test_chat_text_cannot_become_markup(settings: Settings) -> None:
    cid = _conversation_id(settings)
    _, page = _get(settings, f"/chats/{cid}")
    parsed = _Page()
    parsed.feed(page)

    assert parsed.scripts == 0
    assert "&lt;script&gt;" in page


def test_notes_page_lists_chats_by_category_with_status_and_questions(
    settings: Settings,
) -> None:
    cid = _conversation_id(settings)
    status, page = _get(settings, "/notes")

    assert status.startswith("200")
    assert "No taxonomy published yet" in page
    assert "<h2>unclassified" in page
    row = page.split(f'href="/chats/{cid}"', 1)[1].split("</tr>", 1)[0]
    assert "settled" in row
    assert re.search(r'<td class="num">1</td>', row)  # one open question


def test_converter_handles_the_notes_shapes() -> None:
    body = "\n".join(
        [
            "# Title",
            "> [!summary] Summary",
            "> One. [[t (conv-1)#^node-a|m1]]",
            "",
            "## Card",
            "",
            "| | |",
            "|---|---|",
            "| **Purpose** | Go. [[t (conv-1)#^node-a\\|m1]] |",
            "",
            "- **Bold** and *italic* \\*not italic\\* \\[\\[x\\]\\] &lt;b&gt;",
            "- See [[Other knowledge (conv-2)]] and [[Unknown]]",
        ]
    )
    out = note_html(body, "t (conv-1)", {"Other knowledge (conv-2)": "/chats/conv_2"})

    assert "<h1>" not in out and "Title" not in out
    assert '<aside class="callout summary">' in out
    assert out.count('<a class="cite" href="#node-a">m1</a>') == 2  # the table's \| too
    assert "<td><strong>Purpose</strong></td>" in out
    assert "<strong>Bold</strong> and <em>italic</em> *not italic* [[x]] &lt;b&gt;" in out
    assert '<a href="/chats/conv_2">Other knowledge (conv-2)</a>' in out
    assert "and Unknown</li>" in out  # an unknown link is plain words
