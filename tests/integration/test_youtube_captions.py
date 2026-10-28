"""INT-002: captions from the official YouTube Data API. No test touches the network.

A fake ``Http`` plays YouTube's part. The acceptance checks: a refused or
missing transcript gets a concrete status and never invented cues, nothing
is asked with the switch off, retries are bounded, and an automatic track
is labelled machine-generated.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from knowledge_engine.cli.main import ExitCode, main
from knowledge_engine.importer.run import run_import
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.links.video_transcripts import (
    TranscriptCueRow,
    TranscriptSnapshotRow,
    request_transcript,
)
from knowledge_engine.links.youtube_captions import HttpAnswer, YouTubeCaptionsProvider
from knowledge_engine.settings import EgressPolicy, Settings

VID = "aBcDeFgHiJk"
TOKEN = SecretStr("synthetic-oauth-token")
VTT = b"WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nSynthetic caption\n"
OK_VTT = HttpAnswer(200, VTT)


def _tracks(*tracks: tuple[str, str, str]) -> HttpAnswer:
    items = [
        {"id": i, "snippet": {"language": lang, "trackKind": kind}} for i, lang, kind in tracks
    ]
    return HttpAnswer(200, json.dumps({"items": items}).encode())


def _error(status: int, reason: str) -> HttpAnswer:
    return HttpAnswer(status, json.dumps({"error": {"errors": [{"reason": reason}]}}).encode())


class FakeYouTube:
    """Answers captions.list and captions.download from a script; records each call."""

    def __init__(self, listed: HttpAnswer, download: HttpAnswer = OK_VTT) -> None:
        self.listed = listed
        self.download = download
        self.calls: list[tuple[str, dict[str, str]]] = []

    def __call__(self, url: str, headers: dict[str, str]) -> HttpAnswer:
        self.calls.append((url, headers))
        return self.listed if "/captions?" in url else self.download


class Clock:
    """A fake clock: ``sleep`` moves time on and is recorded."""

    def __init__(self) -> None:
        self.now = 100.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def _provider(
    web: FakeYouTube, clock: Clock | None = None, **kwargs: Any
) -> YouTubeCaptionsProvider:
    clock = clock or Clock()
    return YouTubeCaptionsProvider(TOKEN, http=web, clock=clock, sleep=clock.sleep, **kwargs)


def _export(root: Path) -> Path:
    message = {
        "id": "u0",
        "author": {"role": "user"},
        "create_time": 1704067200.0,
        "content": {"content_type": "text", "parts": [f"https://youtu.be/{VID}"]},
        "metadata": {},
    }
    mapping = {
        "root": {"id": "root", "parent": None, "children": ["u0"], "message": None},
        "u0": {"id": "u0", "parent": "root", "children": [], "message": message},
    }
    root.mkdir(parents=True)
    conversation = {"id": "c-y-1", "title": "Synthetic", "mapping": mapping, "current_node": "u0"}
    (root / "conversations.json").write_text(json.dumps([conversation]), encoding="utf-8")
    return root


def _settings(tmp_path: Path, *, fetch: bool = True) -> Settings:
    settings = Settings(workspace_root=tmp_path / "ws", egress=EgressPolicy(transcript_fetch=fetch))
    run_import(_export(tmp_path / "export"), "acct", format_id=None, settings=settings)
    return settings


def _session(settings: Settings) -> Iterator[Session]:
    engine = create_sqlite_engine(database_path(settings))
    try:
        with Session(engine) as session, session.begin():
            yield session
    finally:
        engine.dispose()


def _stored(session: Session) -> tuple[int, int]:
    snapshots = session.scalar(select(func.count()).select_from(TranscriptSnapshotRow)) or 0
    cues = session.scalar(select(func.count()).select_from(TranscriptCueRow)) or 0
    return snapshots, cues


def test_a_human_track_is_stored_with_its_provenance(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    web = FakeYouTube(_tracks(("t-asr", "en", "asr"), ("t-std", "en", "standard")))
    for session in _session(settings):
        row = request_transcript(session, settings, VID, _provider(web))
        assert row.status == "succeeded"
        snapshot = session.get(TranscriptSnapshotRow, row.transcript_id)
        assert snapshot is not None and snapshot.language == "en"
        provenance = json.loads(snapshot.provenance_json)
        assert provenance["method"] == "provider:youtube_data_api"
        assert (provenance["caption_track"], provenance["machine_generated"]) == ("t-std", "no")
        cue = session.scalars(select(TranscriptCueRow)).one()
        assert (cue.start_ms, cue.text) == (1000, "Synthetic caption")
    assert "/captions/t-std?tfmt=vtt" in web.calls[1][0]
    assert all(h == {"Authorization": "Bearer synthetic-oauth-token"} for _u, h in web.calls)


def test_an_automatic_track_is_marked_machine_generated(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    web = FakeYouTube(_tracks(("t-std", "fr", "standard"), ("t-asr", "en", "asr")))
    for session in _session(settings):
        # The asked language beats a human track in another language.
        row = request_transcript(session, settings, VID, _provider(web, language="en"))
        snapshot = session.get(TranscriptSnapshotRow, row.transcript_id)
        assert snapshot is not None
        provenance = json.loads(snapshot.provenance_json)
        assert (provenance["caption_track"], provenance["track_kind"]) == ("t-asr", "asr")
        assert provenance["machine_generated"] == "yes"


def test_no_tracks_is_unavailable_and_nothing_is_invented(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    web = FakeYouTube(_tracks())
    for session in _session(settings):
        row = request_transcript(session, settings, VID, _provider(web))
        assert (row.status, row.last_error) == ("unavailable", "no caption tracks")
        assert _stored(session) == (0, 0)
    assert len(web.calls) == 1  # no download was tried


@pytest.mark.parametrize(
    ("listed", "download", "status"),
    [
        (_error(403, "forbidden"), None, "permission_required"),
        (_error(401, "authError"), None, "permission_required"),
        (_tracks(("t1", "en", "standard")), _error(403, "forbidden"), "permission_required"),
        (_error(404, "videoNotFound"), None, "unavailable"),
        (_error(500, "backendError"), None, "failed"),
    ],
)
def test_refusals_get_a_concrete_status(
    tmp_path: Path, listed: HttpAnswer, download: HttpAnswer | None, status: str
) -> None:
    settings = _settings(tmp_path)
    web = FakeYouTube(listed, download or OK_VTT)
    for session in _session(settings):
        row = request_transcript(session, settings, VID, _provider(web))
        assert row.status == status
        assert row.last_error  # always says why
        assert "synthetic-oauth-token" not in row.last_error
        assert _stored(session) == (0, 0)


def test_quota_is_retried_a_bounded_number_of_times_with_spacing(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    web = FakeYouTube(_error(403, "quotaExceeded"))
    clock = Clock()
    for session in _session(settings):
        row = request_transcript(session, settings, VID, _provider(web, clock, min_interval_s=2.0))
        assert (row.status, row.attempts) == ("failed", 3)
        assert "quotaExceeded" in (row.last_error or "")
    assert len(web.calls) == 3
    assert clock.slept == [2.0, 2.0]  # calls never closer than the minimum gap


def test_with_the_switch_off_youtube_is_never_asked(tmp_path: Path) -> None:
    settings = _settings(tmp_path, fetch=False)
    web = FakeYouTube(_tracks(("t1", "en", "standard")))
    for session in _session(settings):
        row = request_transcript(session, settings, VID, _provider(web))
        assert row.status == "permission_required"
    assert web.calls == []


def test_the_cli_needs_a_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = _settings(tmp_path)
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(settings.workspace_root))
    monkeypatch.delenv("KE_YOUTUBE_ACCESS_TOKEN", raising=False)
    assert main(["--json", "transcript", "fetch", VID]) == ExitCode.USAGE
    assert json.loads(capsys.readouterr().out)["error"]["code"] == "no_token"
