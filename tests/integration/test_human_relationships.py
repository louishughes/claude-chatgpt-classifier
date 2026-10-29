"""REL-006: a person states or retypes a link between two chats, in its direction."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.cli.main import main
from knowledge_engine.documents.notes import conversation_note
from knowledge_engine.importer import import_source
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.relationships.store import ConversationRelationshipRow, history
from knowledge_engine.rendering.markdown import render_note
from knowledge_engine.settings import Settings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt"
NATIVE = "c0000008-0000-4000-8000-00000000000"  # + 1..5, the copied_prefix chats


@pytest.fixture
def world(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[Settings, dict[int, str]]]:
    """copied_prefix imported; yields settings and chat number -> conv_ ID."""
    settings = Settings(workspace_root=tmp_path / "ws")
    import_source(FIXTURES / "copied_prefix" / "export", "fixture", settings=settings)
    engine = create_sqlite_engine(database_path(settings))
    with Session(engine) as session:
        chats = {
            int(native[-1]): conv
            for native, conv in session.execute(
                select(ConversationRow.native_conversation_id, ConversationRow.conversation_id)
            )
        }
    engine.dispose()
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(settings.workspace_root))
    yield settings, chats


def _run(capsys: pytest.CaptureFixture[str], *argv: str) -> tuple[int, dict[str, Any], str]:
    code = main(["--json", *argv])
    out = capsys.readouterr().out
    return code, json.loads(out), out


def _related(settings: Settings, conversation_id: str) -> str:
    """The "Related conversations" part of a chat's knowledge note."""
    engine = create_sqlite_engine(database_path(settings))
    with Session(engine) as session:
        text = render_note(conversation_note(session, conversation_id).model)
    engine.dispose()
    return text.split("## Related conversations", 1)[1].split("\n## ", 1)[0]


def _row(settings: Settings, relationship_id: str) -> tuple[str, str, str, str, list[str]]:
    engine = create_sqlite_engine(database_path(settings))
    with Session(engine) as session:
        row = session.get(ConversationRelationshipRow, relationship_id)
        assert row is not None
        found = (
            row.from_conversation_id,
            row.kind,
            row.to_conversation_id,
            row.review_state,
            [h.action for h in history(session, relationship_id)],
        )
    engine.dispose()
    return found


def test_a_person_adds_continues_and_both_notes_read_it_the_right_way(
    world: tuple[Settings, dict[int, str]], capsys: pytest.CaptureFixture[str]
) -> None:
    settings, chats = world
    later, earlier = chats[4], chats[3]
    code, body, _ = _run(
        capsys, "related", "add", later, "continues", earlier, "--reviewer", "louis"
    )
    assert code == 0
    data = body["data"]
    assert (data["evidence_class"], data["review_state"]) == ("human", "accepted")
    link = data["relationship_id"]
    assert _row(settings, link) == (later, "continues", earlier, "accepted", ["accept"])

    # "B continues A": in B's note B is "this chat"; in A's note A is.
    later_line = next(line for line in _related(settings, later).splitlines() if link in line)
    assert "this chat **continues** [[" in later_line
    earlier_line = next(line for line in _related(settings, earlier).splitlines() if link in line)
    assert "]] **continues** this chat" in earlier_line

    # Rejecting it hides it from both notes; the history keeps both steps.
    assert _run(capsys, "related", "review", link, "reject", "--note", "no")[0] == 0
    assert link not in _related(settings, later) and link not in _related(settings, earlier)
    assert _row(settings, link)[3:] == ("rejected", ["accept", "reject"])


def test_hand_made_links_are_refused_when_they_make_no_sense(
    world: tuple[Settings, dict[int, str]], capsys: pytest.CaptureFixture[str]
) -> None:
    _, chats = world
    a, b = chats[3], chats[4]
    assert _run(capsys, "related", "add", b, "related_to", a)[0] == 0
    code, body, _ = _run(capsys, "related", "add", b, "related_to", a)  # the same again
    assert (code, body["error"]["code"]) == (2, "refused")
    code, body, _ = _run(capsys, "related", "add", a, "continues", a)
    assert (code, body["error"]["code"]) == (2, "refused")
    code, body, out = _run(capsys, "related", "add", a, "continues", "conv_secret-words")
    assert (code, body["error"]["code"]) == (1, "unknown_conversation")
    assert "secret-words" not in out
    # Only judgements can be stated by hand; "quotes" is a fact a detector checks.
    assert main(["related", "add", a, "quotes", b]) == 2
    capsys.readouterr()


def test_retype_and_reverse_a_candidate(
    world: tuple[Settings, dict[int, str]], capsys: pytest.CaptureFixture[str]
) -> None:
    settings, chats = world
    _, body, _ = _run(capsys, "related", "list", "--state", "candidate")
    links = {
        (r["from"], r["kind"], r["to"]): r["relationship_id"] for r in body["data"]["relationships"]
    }
    fork = links[(chats[2], "forked_from", chats[1])]
    ref = links[(chats[3], "references", chats[1])]

    # The person says chat 2 really continues chat 1.
    code, body, _ = _run(
        capsys, "related", "review", fork, "accept", "--as", "continues", "--note", "same work"
    )
    assert code == 0
    new = body["data"]["replaced_by"]
    assert _row(settings, fork)[3:] == ("superseded", ["supersede"])
    assert _row(settings, new) == (chats[2], "continues", chats[1], "accepted", ["accept"])
    note = _related(settings, chats[1])
    assert new in note and fork not in note  # shown once, as the person said

    # ...and that chat 1 is related to chat 3, not the other way round.
    code, body, _ = _run(
        capsys, "related", "review", ref, "accept", "--as", "related_to", "--reverse"
    )
    assert code == 0
    assert _row(settings, body["data"]["replaced_by"])[:3] == (chats[1], "related_to", chats[3])

    # --as only makes sense with accept, and an unchanged retype is refused.
    code, body, _ = _run(capsys, "related", "review", new, "reject", "--as", "related_to")
    assert (code, body["error"]["code"]) == (2, "usage")
    code, body, _ = _run(capsys, "related", "review", new, "accept", "--as", "continues")
    assert (code, body["error"]["code"]) == (2, "refused")
    assert _row(settings, new)[3] == "accepted"  # the refusal changed nothing


def test_overruled_links_stay_overruled(
    world: tuple[Settings, dict[int, str]], capsys: pytest.CaptureFixture[str]
) -> None:
    settings, chats = world
    _, body, _ = _run(capsys, "related", "list", "--state", "candidate")
    links = {
        (r["from"], r["kind"], r["to"]): r["relationship_id"] for r in body["data"]["relationships"]
    }
    fork = links[(chats[2], "forked_from", chats[1])]
    ref = links[(chats[3], "references", chats[1])]
    _, body, _ = _run(capsys, "related", "review", fork, "accept", "--as", "continues")
    new = body["data"]["replaced_by"]

    # Rejecting the replacement doesn't bring back the link it replaced.
    assert _run(capsys, "related", "review", new, "reject")[0] == 0
    note = _related(settings, chats[1])
    assert fork not in note and new not in note

    # A superseded or rejected link can't be retyped again.
    for gone in (fork, new):
        code, body, _ = _run(capsys, "related", "review", gone, "accept", "--as", "related_to")
        assert (code, body["error"]["code"]) == (2, "refused")
    assert _row(settings, new)[3:] == ("rejected", ["accept", "reject"])

    # Reversing keeps the old link's own history: one supersede.
    _, body, _ = _run(capsys, "related", "review", ref, "accept", "--reverse", "--as", "continues")
    assert _row(settings, ref)[3:] == ("superseded", ["supersede"])
    code, body, out = _run(capsys, "related", "review", "rel_secret-words", "accept")
    assert body["error"]["code"] == "unknown_relationship" and "secret-words" not in out
