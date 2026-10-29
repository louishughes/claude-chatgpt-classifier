"""UI-009: the chats list and the search page narrow by category and date."""

from __future__ import annotations

import io
import json
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.classification.store import record_review
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.importer.run import run_import
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.rendering.transcript import load_conversation
from knowledge_engine.segmentation.overrides import load_segments
from knowledge_engine.settings import Settings
from knowledge_engine.taxonomy.registry import Dimension, TaxonomyRegistry, TermStatus
from knowledge_engine.ui.app import make_app

JAN_1 = 1704067200.0  # 2024-01-01 00:00 UTC
FEB_1 = 1706745600.0  # 2024-02-01 00:00 UTC


def _chat(cid: str, title: str, start: float | None, texts: list[str]) -> dict[str, Any]:
    mapping: dict[str, Any] = {"root": {"id": "root", "parent": None, "children": []}}
    parent = "root"
    for i, text in enumerate(texts):
        node = f"{cid}-m{i}"
        mapping[node] = {
            "id": node,
            "parent": parent,
            "children": [],
            "message": {
                "id": node,
                "author": {"role": "user" if i % 2 == 0 else "assistant"},
                "create_time": None if start is None else start + 60 * i,
                "content": {"content_type": "text", "parts": [text]},
                "metadata": {},
            },
        }
        mapping[parent]["children"].append(node)
        parent = node
    return {
        "id": cid,
        "title": title,
        "create_time": start,
        "mapping": mapping,
        "current_node": parent,
    }


@pytest.fixture
def world(tmp_path: Path) -> Iterator[tuple[Settings, dict[str, str]]]:
    chats = [
        _chat("c-jan", "Synthetic January garden", JAN_1, ["Garden compost?", "Compost works."]),
        _chat("c-feb", "Synthetic February soup", FEB_1, ["Garden herbs soup?", "Yes, soup."]),
        _chat("c-none", "Synthetic undated", None, ["A garden note."]),
    ]
    root = tmp_path / "export"
    root.mkdir()
    (root / "conversations.json").write_text(json.dumps(chats), encoding="utf-8")
    settings = Settings(workspace_root=tmp_path / "ws")
    run_import(root, "acct", format_id=None, settings=settings)
    engine = create_sqlite_engine(database_path(settings))
    with Session(engine) as session:
        ids = dict(
            session.execute(
                select(ConversationRow.native_conversation_id, ConversationRow.conversation_id)
            )
            .tuples()
            .all()
        )
        registry = TaxonomyRegistry(session)
        gardening = registry.add_term(Dimension.TOPIC, "Gardening", status=TermStatus.APPROVED)
        unused = registry.add_term(Dimension.TOPIC, "Unused", status=TermStatus.APPROVED)
        taxonomy = registry.publish("tax-1", author="test")
        chat = load_conversation(session, ids["c-jan"])
        for segment in load_segments(session, chat):
            record_review(
                session,
                taxonomy,
                segment.segment_id,
                "topic",
                primary=gardening.term_id,
                reviewer="test",
            )
        found = {"Gardening": gardening.term_id, "Unused": unused.term_id}
        session.commit()
    engine.dispose()
    yield settings, {**ids, **found}


def _get(settings: Settings, target: str) -> str:
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
    assert captured["status"] == "200 OK"
    return b"".join(body).decode("utf-8")


def _titles(page: str) -> set[str]:
    return {t for t in ("January garden", "February soup", "Synthetic undated") if t in page}


def test_category_list_offers_only_labelled_terms_with_counts(
    world: tuple[Settings, dict[str, str]],
) -> None:
    settings, ids = world
    page = _get(settings, "/chats")
    assert f'<option value="{ids["Gardening"]}">topic: Gardening (1)</option>' in page
    assert "Unused" not in page  # approved but labels no chat
    assert _titles(page) == {"January garden", "February soup", "Synthetic undated"}


def test_chats_filter_by_category_and_dates(world: tuple[Settings, dict[str, str]]) -> None:
    settings, ids = world
    assert _titles(_get(settings, f"/chats?category={ids['Gardening']}")) == {"January garden"}
    page = _get(settings, "/chats?since=2024-01-15")
    assert _titles(page) == {"February soup"}
    assert "chats with no start date are left out" in page
    assert _titles(_get(settings, "/chats?until=2024-01-01")) == {"January garden"}
    # Filters combine.
    both = _get(settings, f"/chats?category={ids['Gardening']}&since=2024-01-15")
    assert _titles(both) == set() and "No chats yet" not in both


def test_bad_chat_filters_say_so_and_are_not_applied(
    world: tuple[Settings, dict[str, str]],
) -> None:
    settings, _ = world
    page = _get(settings, "/chats?category=term_nope%3Cb%3E")
    assert "isn&#39;t in the published vocabulary" in page and "<b>" not in page
    assert len(_titles(page)) == 3
    page = _get(settings, "/chats?since=yesterday")
    assert "dates must be YYYY-MM-DD" in page and len(_titles(page)) == 3


def test_search_page_filters(world: tuple[Settings, dict[str, str]]) -> None:
    settings, ids = world
    page = _get(settings, f"/search?q=garden&term={ids['Gardening']}")
    assert "1 message." in page and f'value="{ids["Gardening"]}" selected' in page
    page = _get(settings, "/search?q=garden&since=2024-01-15")
    assert "1 message." in page and "1 more match but have no date" in page
    page = _get(settings, "/search?q=soup&role=assistant")
    assert "1 message." in page and 'value="assistant" selected' in page
    refused = _get(settings, "/search?q=garden&term=term_nope")
    assert "Nothing was searched." in refused and "message." not in refused.split("</form>")[1]


def test_approved_category_on_no_chat_is_empty_not_unknown(
    world: tuple[Settings, dict[str, str]],
) -> None:
    settings, ids = world
    page = _get(settings, f"/chats?category={ids['Unused']}")
    assert "0 chats, filtered." in page and "isn&#39;t in the published vocabulary" not in page
    # The search page offers every approved term without reading the chats.
    search = _get(settings, "/search")
    assert f'value="{ids["Unused"]}">topic: Unused</option>' in search


def test_refused_filters_are_not_reported_as_applied(
    world: tuple[Settings, dict[str, str]],
) -> None:
    settings, _ = world
    page = _get(settings, "/chats?q=Synthetic&category=term_nope&since=bad")
    assert '3 chats with "Synthetic" in the title.</p>' in page  # not "filtered"
    assert "dates must be YYYY-MM-DD" in page and "isn&#39;t in the published" in page
