"""NOTE-018: an all-review chat shows a suggested category; a reviewer session settles it.

Synthetic chat: four messages about a raised bed, a seven-hour pause (a new
segment), then two about soup. A fake classifier answers both segments but
says it is unsure, so both go to review and nothing is settled. Then
``ke classify review`` writes request files, this test answers them as the
"reviewer session", and the next run stores the answers as reviews.
"""

from __future__ import annotations

import io
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.classification.classifier import REVIEW_REQUIRED, SegmentClassifier
from knowledge_engine.classification.store import ClassificationReviewRow, save
from knowledge_engine.cli.main import main
from knowledge_engine.documents.rich_note import chat_labels, rich_conversation_note
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.importer.run import run_import
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.providers.base import FakeProvider, ModelRequest
from knowledge_engine.providers.ledger import ModelStageRunner
from knowledge_engine.rendering.markdown import render_note
from knowledge_engine.rendering.transcript import load_conversation
from knowledge_engine.segmentation.overrides import load_segments
from knowledge_engine.settings import EgressPolicy, load_settings
from knowledge_engine.taxonomy.registry import Dimension, TaxonomyRegistry, TermStatus
from knowledge_engine.ui.app import make_app

T0 = 1704067200.0
HOUR = 3600.0
_TAG = re.compile(r"^\[m:([^\]]+)\] (\w+):\n(.+)$", re.M)


def _export(root: Path) -> Path:
    nodes = [
        ("u1", "user", "How deep should a raised bed be for vegetables?", T0),
        ("a1", "assistant", "A raised bed works well at 30 cm deep.", T0 + 60),
        ("u2", "user", "Should the raised bed have a liner underneath it?", T0 + 120),
        ("a2", "assistant", "Yes, line the raised bed with fabric.", T0 + 180),
        ("u3", "user", "Different thing: what is a good soup for a cold winter?", T0 + 7 * HOUR),
        ("a3", "assistant", "Try a lentil soup with cumin.", T0 + 7 * HOUR + 60),
    ]
    mapping: dict[str, Any] = {
        "root": {"id": "root", "parent": None, "children": [], "message": None}
    }
    parent = "root"
    for node, role, text, t in nodes:
        mapping[node] = {
            "id": node,
            "parent": parent,
            "children": [],
            "message": {
                "id": node,
                "author": {"role": role},
                "create_time": t,
                "content": {"content_type": "text", "parts": [text]},
                "metadata": {},
            },
        }
        mapping[parent]["children"].append(node)
        parent = node
    chat = {
        "id": "c-unsure",
        "title": "Synthetic unsure chat",
        "create_time": T0,
        "mapping": mapping,
        "current_node": parent,
    }
    root.mkdir(parents=True)
    (root / "conversations.json").write_text(json.dumps([chat]), encoding="utf-8")
    return root


def _answer(terms: dict[str, str], *, unsure: bool) -> Callable[[str], dict[str, Any]]:
    """Label the bed segment Raised beds and the soup one Cooking, citing its first message."""

    def answer(input_text: str) -> dict[str, Any]:
        first = _TAG.findall(input_text)[0][0]
        term = terms["beds"] if "raised bed" in input_text else terms["food"]
        item = {"term_id": term, "rank": "primary", "confidence": 0.6, "evidence": [first]}
        return {
            "domain": [item],
            "needs_review": unsure,
            "review_reason": "near tie" if unsure else None,
        }

    return answer


def _cli(capsys: pytest.CaptureFixture[str], *args: str) -> dict[str, Any]:
    capsys.readouterr()
    assert main(["--json", *args]) == 0
    return dict(json.loads(capsys.readouterr().out)["data"])


def _answer_files(run_dir: Path, answer: Callable[[str], dict[str, Any]]) -> int:
    """Answer every unanswered request, as the reviewer session; return how many exist."""
    asked = 0
    for request_file in sorted(run_dir.glob("*.request.jsonl")):
        lines = [json.loads(x) for x in request_file.read_text("utf-8").splitlines() if x.strip()]
        requests = [x for x in lines if "request_id" in x]
        asked += len(requests)
        response = request_file.with_name(request_file.name.replace(".request.", ".response."))
        done = set()
        if response.exists():
            done = {json.loads(x)["request_id"] for x in response.read_text("utf-8").splitlines()}
        with response.open("a", encoding="utf-8") as out:
            for line in requests:
                if line["request_id"] not in done:
                    reply = {
                        "request_id": line["request_id"],
                        "output": answer(line["input_text"]),
                        "served_model": "dry-run",
                        "session_ref": "reviewer-1",
                    }
                    out.write(json.dumps(reply) + "\n")
    return asked


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """An imported chat whose two segments are both waiting for review."""
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(tmp_path / "ws"))
    monkeypatch.setenv("KE_MODEL_BATCH_ROOT", str(tmp_path / "private" / "model-batches"))
    settings = load_settings()
    run_import(_export(tmp_path / "export"), "acct", format_id=None, settings=settings)
    engine = create_sqlite_engine(database_path(settings))
    with Session(engine) as session:
        [cid] = session.scalars(select(ConversationRow.conversation_id)).all()
        registry = TaxonomyRegistry(session)
        home = registry.add_term(Dimension.DOMAIN, "Home and garden", status=TermStatus.APPROVED)
        beds = registry.add_term(
            Dimension.DOMAIN, "Raised beds", status=TermStatus.APPROVED, parent_id=home.term_id
        )
        food = registry.add_term(Dimension.DOMAIN, "Cooking", status=TermStatus.APPROVED)
        snapshot = registry.publish("tax-1", author="test")
        terms = {"beds": beds.term_id, "food": food.term_id}
        chat = load_conversation(session, cid)
        segments = load_segments(session, chat)
        assert len(segments) == 2, "the pause should start a second segment"
        unsure = _answer(terms, unsure=True)

        def classify(request: ModelRequest) -> dict[str, Any]:
            return unsure(request.input_text)

        runner = ModelStageRunner(session, FakeProvider(classify), EgressPolicy(text_llm=True))
        results = SegmentClassifier(snapshot, runner=runner).classify([(chat, s) for s in segments])
        assert {r.state for r in results} == {REVIEW_REQUIRED}
        save(session, results, provider_id="fake")
        session.commit()
    engine.dispose()
    monkeypatch.setenv("KE_EGRESS__TEXT_LLM", "true")
    return {"cid": cid, "run_dir": str(tmp_path / "private" / "model-batches" / "rev"), **terms}


def _note(cid: str) -> tuple[str, str | None]:
    """The rendered note and the chat-level category label."""
    engine = create_sqlite_engine(database_path(load_settings()))
    with Session(engine) as session:
        snapshot = TaxonomyRegistry(session).snapshot("tax-1")
        note = rich_conversation_note(session, cid, taxonomy=snapshot, digest=None)
        category = chat_labels(session, load_conversation(session, cid), snapshot).category
    engine.dispose()
    return render_note(note.model), category


def test_all_review_chat_shows_a_suggestion_and_its_label_stays_unset(
    world: dict[str, str],
) -> None:
    text, category = _note(world["cid"])

    assert category is None
    assert "\ncategory: unclassified\n" in text  # front matter: no label yet
    # The bed segment holds four of the six messages, so it is the suggestion.
    assert "unclassified; suggested: Home and garden › Raised beds (waiting for review)" in text
    assert "Suggested, waiting for review (not a label): **Home and garden › Raised beds**" in text
    assert "segment(s) 1." in text


def test_a_reviewer_answer_file_settles_the_category(
    world: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    args = ("classify", "review", "--taxonomy", "tax-1", "--run-id", "rev")
    first = _cli(capsys, *args)
    assert (first["queued"], first["pending"], first["reviewed"]) == (2, 2, 0)

    asked = _answer_files(Path(world["run_dir"]), _answer(world, unsure=False))
    assert asked == 2
    second = _cli(capsys, *args)
    assert (second["reviewed"], second["pending"], second["unsure"]) == (2, 0, 0)

    text, category = _note(world["cid"])
    assert category == "Home and garden"
    assert "\ncategory: Home and garden\n" in text
    assert "suggested" not in text.casefold()
    engine = create_sqlite_engine(database_path(load_settings()))
    with Session(engine) as session:
        reviewers = set(session.scalars(select(ClassificationReviewRow.reviewer)))
    engine.dispose()
    assert reviewers == {"session:reviewer-1"}

    # Reviewed segments leave the queue: no new request, nothing recorded twice.
    third = _cli(capsys, *args)
    assert third["queued"] == third["reviewed"] == 0
    assert _answer_files(Path(world["run_dir"]), _answer(world, unsure=False)) == asked


def test_an_unsure_reviewer_records_nothing(
    world: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    args = ("classify", "review", "--taxonomy", "tax-1", "--run-id", "rev")
    _cli(capsys, *args)
    _answer_files(Path(world["run_dir"]), _answer(world, unsure=True))

    second = _cli(capsys, *args)
    assert (second["reviewed"], second["unsure"], second["queued"]) == (0, 2, 2)
    text, category = _note(world["cid"])
    assert category is None and "suggested: Home and garden › Raised beds" in text


def test_notes_page_shows_the_suggestion_under_unclassified(world: dict[str, str]) -> None:
    captured: dict[str, str] = {}

    def start_response(status: str, headers: list[tuple[str, str]]) -> None:
        captured["status"] = status

    environ = {
        "REQUEST_METHOD": "GET",
        "PATH_INFO": "/notes",
        "QUERY_STRING": "",
        "HTTP_HOST": "127.0.0.1:8765",
        "CONTENT_LENGTH": "0",
        "wsgi.input": io.BytesIO(b""),
    }
    page = b"".join(make_app(load_settings())(environ, start_response)).decode("utf-8")

    assert captured["status"].startswith("200")
    assert "<h2>unclassified" in page
    row = page.split(f'href="/chats/{world["cid"]}"', 1)[1].split("</tr>", 1)[0]
    assert "suggested: Home and garden › Raised beds (waiting for review)" in row
