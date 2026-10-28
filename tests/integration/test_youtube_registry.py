"""YTB-001: 12 mentions of one video give 1 video and 12 mention records."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from knowledge_engine.importer.run import run_import
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.links.store import LinkOccurrenceRow, LinkTargetRow
from knowledge_engine.links.youtube import YouTubeMentionRow, YouTubeVideoRow
from knowledge_engine.settings import Settings

VID = "aBcDeFgHiJk"
FORMS = [
    f"https://www.youtube.com/watch?v={VID}",
    f"https://youtu.be/{VID}",
    f"https://youtu.be/{VID}?t=30",
    f"https://m.youtube.com/watch?v={VID}&t=1m",
    f"https://www.youtube.com/shorts/{VID}",
    f"https://www.youtube.com/live/{VID}",
    f"https://www.youtube.com/embed/{VID}",
    f"https://music.youtube.com/watch?v={VID}&list=PLsynthetic",
    f"https://www.youtube.com/watch?v={VID}&ab_channel=Synthetic",
    f"https://youtube.com/watch?v={VID}",
    f"https://www.youtube.com/watch?v={VID}#t=5",
    f"https://www.youtube-nocookie.com/embed/{VID}",
]


def _export(root: Path) -> Path:
    # One user message per URL form, in a single chain.
    nodes: list[tuple[str, str | None]] = [("root", None)]
    nodes += [(f"m{i}", f"Watch {url} please") for i, url in enumerate(FORMS)]
    nodes.append(("lookalike", f"Not this: https://youtube.com.example.net/watch?v={VID}"))
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
                "create_time": 1704067200.0 + i,
                "content": {"content_type": "text", "parts": [text]},
                "metadata": {},
            },
        }
    root.mkdir(parents=True)
    conversation = {
        "id": "c-yt-1",
        "title": "Synthetic videos",
        "create_time": 1704067200.0,
        "mapping": mapping,
        "current_node": nodes[-1][0],
    }
    (root / "conversations.json").write_text(json.dumps([conversation]), encoding="utf-8")
    return root


def test_one_video_twelve_mentions_and_reimport_is_stable(tmp_path: Path) -> None:
    settings = Settings(workspace_root=tmp_path / "ws")
    export = _export(tmp_path / "export")
    report = run_import(export, "acct", format_id=None, settings=settings)
    assert report.links["new_youtube_mentions"] == 12

    engine = create_sqlite_engine(database_path(settings))
    try:
        with Session(engine) as session:
            videos = session.scalars(select(YouTubeVideoRow)).all()
            assert [v.video_id for v in videos] == [VID]
            assert videos[0].transcript_status == "not_requested"
            mentions = session.scalars(select(YouTubeMentionRow)).all()
            assert len(mentions) == 12
            assert sorted(m.t_seconds for m in mentions if m.t_seconds is not None) == [5, 30, 60]
            assert {m.playlist_id for m in mentions} == {None, "PLsynthetic"}
            # Each mention is a real link occurrence pointing at a youtube_video target.
            for mention in mentions:
                occurrence = session.get(LinkOccurrenceRow, mention.mention_id)
                assert occurrence is not None
                target = session.get(LinkTargetRow, occurrence.target_id)
                assert target is not None and target.kind == "youtube_video"
            lookalike = session.scalars(
                select(LinkTargetRow).where(LinkTargetRow.host == "youtube.com.example.net")
            ).one()
            assert lookalike.kind == "web"
    finally:
        engine.dispose()

    again = run_import(export, "acct", format_id=None, settings=settings)
    assert again.links.get("new_youtube_mentions", 0) == 0
    engine = create_sqlite_engine(database_path(settings))
    try:
        with Session(engine) as session:
            assert session.scalar(select(func.count()).select_from(YouTubeMentionRow)) == 12
            assert session.scalar(select(func.count()).select_from(YouTubeVideoRow)) == 1
    finally:
        engine.dispose()
