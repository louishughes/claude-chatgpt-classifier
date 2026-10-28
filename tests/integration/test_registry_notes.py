"""YTB-003 + SOC-003: video notes, transcript cue search and account registry notes."""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.documents.registries import (
    account_note,
    account_registry_note,
    find_cues,
    registry_path,
    video_note,
    video_path,
)
from knowledge_engine.documents.vault import sync_vault
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.importer.run import run_import
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.links.social_store import SocialAccountRow
from knowledge_engine.links.video_transcripts import attach_user_transcript
from knowledge_engine.rendering.markdown import render_note
from knowledge_engine.settings import Settings

VID = "aBcDeFgHiJk"
BARE = "zYxWvUtSrQp"  # linked, but never given a transcript
CHATS = {
    "c-reg-a": [
        f"Synthetic: watch https://www.youtube.com/watch?v={VID}&t=75 about sheds",
        "Synthetic: see https://github.com/Synth-Octo and ask @someone",
    ],
    "c-reg-b": [f"Synthetic: again https://youtu.be/{VID} and https://youtu.be/{BARE}"],
}
VTT = (
    b"WEBVTT\n\n"
    b"00:00:05.000 --> 00:00:07.000\n<v Host>Synthetic: the garden shed needs a level base\n\n"
    b"00:01:15.000 --> 00:01:18.000\n"
    b"Synthetic: felt goes on the shed roof [[not a link]] #notatag\n"
)


def _export(root: Path) -> Path:
    chats = []
    for cid, texts in CHATS.items():
        nodes: list[tuple[str, str | None]] = [("root", None)]
        nodes += [(f"{cid}-m{i}", text) for i, text in enumerate(texts)]
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
        chats.append(
            {
                "id": cid,
                "title": f"Synthetic {cid}",
                "mapping": mapping,
                "current_node": nodes[-1][0],
            }
        )
    root.mkdir(parents=True)
    (root / "conversations.json").write_text(json.dumps(chats), encoding="utf-8")
    return root


@pytest.fixture
def world(tmp_path: Path) -> Iterator[tuple[Settings, Session, dict[str, str]]]:
    settings = Settings(workspace_root=tmp_path / "ws")
    run_import(_export(tmp_path / "export"), "acct", format_id=None, settings=settings)
    session = Session(create_sqlite_engine(database_path(settings)))
    attach_user_transcript(session, settings, VID, VTT, language="en", note="synthetic")
    session.commit()
    chats = dict(
        session.execute(
            select(ConversationRow.native_conversation_id, ConversationRow.conversation_id)
        )
        .tuples()
        .all()
    )
    yield settings, session, chats
    session.close()


def test_cue_hit_resolves_to_the_moment_and_every_citing_chat(
    world: tuple[Settings, Session, dict[str, str]],
) -> None:
    _, session, chats = world
    [hit] = find_cues(session, "SHED roof")  # every word, any case
    assert hit.video_id == VID and hit.ordinal == 1  # ordinals count from 0
    assert hit.start_seconds == 75
    assert hit.url == f"https://www.youtube.com/watch?v={VID}&t=75s"
    assert set(hit.conversations) == {chats["c-reg-a"], chats["c-reg-b"]}
    assert len(hit.revisions) == 2  # both messages linking to the video
    assert {h.ordinal for h in find_cues(session, "shed")} == {0, 1}
    assert find_cues(session, "shed bicycle") == []
    assert find_cues(session, "%") == []  # no words, no hits (and no SQL wildcards)


def test_video_notes_state_their_transcript_and_link_back(
    world: tuple[Settings, Session, dict[str, str]],
) -> None:
    _, session, chats = world
    note = render_note(video_note(session, VID))
    assert "A transcript is attached." in note
    assert "transcript_status: succeeded" in note
    assert f"[1:15](https://www.youtube.com/watch?v={VID}&t=75s)" in note  # mention and cue
    assert note.count("#^") == 2  # each mention links to its message
    assert re.search(r"Host: Synthetic: the garden shed needs a level base \^cue-0$", note, re.M)
    assert "\\[\\[not a link\\]\\]" in note and "\\#notatag" in note  # cue text is escaped
    for native in ("c-reg-a", "c-reg-b"):
        assert f"(`{chats[native]}`)" in note.split("## Conversations", 1)[1]
    bare = render_note(video_note(session, BARE))
    assert "No transcript: none attached and none requested." in bare
    assert "## Cues" not in bare
    with pytest.raises(KeyError):
        video_note(session, "missingvide")


def test_registry_lists_accounts_and_keeps_bare_names_for_review(
    world: tuple[Settings, Session, dict[str, str]],
) -> None:
    _, session, chats = world
    [account] = session.scalars(select(SocialAccountRow)).all()
    registry = render_note(account_registry_note(session))
    accounts, review = registry.split("## Needs review", 1)
    assert "### github" in accounts and "`synth-octo`" in accounts.lower()
    assert f"Account ({account.account_id.replace('_', '-', 1)[:16]})" in accounts
    assert "@someone" not in accounts  # a bare name is never filed under an account
    assert "`@someone`: 1 mention(s) in 1 chat(s)" in review
    detail = render_note(account_note(session, account.account_id))
    assert "[[Account registry]]" in detail
    assert "https://github.com/Synth-Octo" in detail
    assert "#^" in detail  # the mention links to its message
    assert f"(`{chats['c-reg-a']}`)" in detail.split("## Conversations", 1)[1]


def test_vault_gets_video_and_account_notes_whose_links_resolve(
    world: tuple[Settings, Session, dict[str, str]], tmp_path: Path
) -> None:
    settings, session, _ = world
    vault = tmp_path / "vault"
    report = sync_vault(session, vault, settings.workspace_root / "archive")
    made = set(report.created)
    assert video_path(VID).as_posix() in made and video_path(BARE).as_posix() in made
    assert registry_path().as_posix() in made
    stems = {Path(p).stem for p in made}
    registry = (vault / registry_path().as_posix()).read_text(encoding="utf-8")
    for target in re.findall(r"\[\[(Account \([^)]+\))\]\]", registry):
        assert target in stems  # every account link in the registry has its note
    assert sync_vault(session, vault, settings.workspace_root / "archive").counts()["written"] == 0


def test_cli_transcript_find(
    world: tuple[Settings, Session, dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from knowledge_engine.cli.main import main

    settings, session, chats = world
    session.close()
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(settings.workspace_root))
    assert main(["--json", "transcript", "find", "level base"]) == 0
    [hit] = json.loads(capsys.readouterr().out)["data"]["hits"]
    assert (hit["video_id"], hit["cue"], hit["start_seconds"]) == (VID, 0, 5)
    assert set(hit["conversations"]) == {chats["c-reg-a"], chats["c-reg-b"]}
