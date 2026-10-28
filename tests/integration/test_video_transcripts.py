"""YTB-002: transcript status, the network policy gate and user-supplied transcripts."""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from knowledge_engine.cli.main import ExitCode, main
from knowledge_engine.domain.enums import TranscriptStatus
from knowledge_engine.importer.run import run_import
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.links.video_transcripts import (
    ProviderAnswer,
    TranscriptCueRow,
    TranscriptSnapshotRow,
    UnknownVideoError,
    attach_user_transcript,
    request_transcript,
    video_status,
)
from knowledge_engine.settings import EgressPolicy, Settings

VID = "aBcDeFgHiJk"
VTT = b"WEBVTT\n\n00:00:01.000 --> 00:00:02.000\n<v Host>Synthetic hello\n\nuntimed? no\n"
SRT = b"1\n00:00:01,000 --> 00:00:02,500\nSynthetic line\n"


class FakeProvider:
    """Records every call; answers from a script."""

    name = "fake"

    def __init__(self, *answers: ProviderAnswer) -> None:
        self.answers = list(answers)
        self.calls = 0

    def fetch(self, video_id: str) -> ProviderAnswer:
        self.calls += 1
        return self.answers[min(self.calls, len(self.answers)) - 1]


def _export(root: Path) -> Path:
    mapping: dict[str, Any] = {
        "root": {"id": "root", "parent": None, "children": ["u0"], "message": None},
        "u0": {
            "id": "u0",
            "parent": "root",
            "children": [],
            "message": {
                "id": "u0",
                "author": {"role": "user"},
                "create_time": 1704067200.0,
                "content": {"content_type": "text", "parts": [f"https://youtu.be/{VID}"]},
                "metadata": {},
            },
        },
    }
    root.mkdir(parents=True)
    conversation = {"id": "c-t-1", "title": "Synthetic", "mapping": mapping, "current_node": "u0"}
    (root / "conversations.json").write_text(json.dumps([conversation]), encoding="utf-8")
    return root


def _settings(tmp_path: Path, *, fetch: bool = False) -> Settings:
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


def test_with_the_switch_off_no_provider_is_called(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    provider = FakeProvider(ProviderAnswer(TranscriptStatus.SUCCEEDED, data=VTT))
    for session in _session(settings):
        row = request_transcript(session, settings, VID, provider)
        assert row.status == "permission_required"
        assert row.last_error == "transcript_fetch switched off"
        assert video_status(session, VID) == TranscriptStatus.PERMISSION_REQUIRED
    assert provider.calls == 0


def test_with_the_switch_on_a_success_is_stored_once(tmp_path: Path) -> None:
    settings = _settings(tmp_path, fetch=True)
    provider = FakeProvider(
        ProviderAnswer(
            TranscriptStatus.SUCCEEDED, data=VTT, language="en", source_url="https://x.invalid/t"
        )
    )
    for session in _session(settings):
        row = request_transcript(session, settings, VID, provider)
        assert (row.status, row.attempts) == ("succeeded", 1)
        again = request_transcript(session, settings, VID, provider)
        assert again.status == "succeeded"
        snapshot = session.get(TranscriptSnapshotRow, row.transcript_id)
        assert snapshot is not None and snapshot.language == "en"
        assert json.loads(snapshot.provenance_json)["method"] == "provider:fake"
        cues = session.scalars(select(TranscriptCueRow).order_by(TranscriptCueRow.ordinal)).all()
        assert [(c.start_ms, c.speaker, c.text) for c in cues][0] == (
            1000,
            "Host",
            "Synthetic hello",
        )
        assert video_status(session, VID) == TranscriptStatus.SUCCEEDED
    assert provider.calls == 1  # never fetched twice


def test_temporary_problems_are_retried_a_bounded_number_of_times(tmp_path: Path) -> None:
    settings = _settings(tmp_path, fetch=True)
    provider = FakeProvider(ProviderAnswer(TranscriptStatus.RATE_LIMITED, reason="429"))
    for session in _session(settings):
        row = request_transcript(session, settings, VID, provider)
        assert row.status == "failed"
        assert row.attempts == 3
        assert "429" in (row.last_error or "")
    assert provider.calls == 3


def test_unavailable_is_a_final_answer_with_its_reason(tmp_path: Path) -> None:
    settings = _settings(tmp_path, fetch=True)
    provider = FakeProvider(ProviderAnswer(TranscriptStatus.UNAVAILABLE, reason="private video"))
    for session in _session(settings):
        row = request_transcript(session, settings, VID, provider)
        assert (row.status, row.last_error) == ("unavailable", "private video")
        assert video_status(session, VID) == TranscriptStatus.UNAVAILABLE
    assert provider.calls == 1


def test_user_supplied_transcript_attaches_with_provenance(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    for session in _session(settings):
        first = attach_user_transcript(
            session, settings, VID, SRT, language="en", note="synthetic captions"
        )
        second = attach_user_transcript(session, settings, VID, SRT)
        assert first.transcript_id == second.transcript_id
        assert session.scalar(select(func.count()).select_from(TranscriptSnapshotRow)) == 1
        provenance = json.loads(first.provenance_json)
        assert provenance["method"] == "user_supplied"
        assert provenance["note"] == "synthetic captions"
        assert video_status(session, VID) == TranscriptStatus.SUCCEEDED
        # A later refused fetch never undoes a transcript we already have.
        request_transcript(session, settings, VID, FakeProvider())
        assert video_status(session, VID) == TranscriptStatus.SUCCEEDED
        with pytest.raises(UnknownVideoError):
            attach_user_transcript(session, settings, "zzzzzzzzzzz", SRT)
    archive = settings.workspace_root / "archive"
    import hashlib

    sha = hashlib.sha256(SRT).hexdigest()
    assert (archive / sha[:2] / sha).read_bytes() == SRT


def test_cli_add_and_status(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = _settings(tmp_path)
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(settings.workspace_root))
    transcript = tmp_path / "captions.txt"
    transcript.write_text("0:05\nSynthetic words\n", encoding="utf-8")
    assert main(["--json", "transcript", "add", VID, str(transcript), "--language", "en"]) == 0
    added = json.loads(capsys.readouterr().out)["data"]
    assert (added["format"], added["cues"], added["timed_cues"]) == ("text", 1, 1)

    assert main(["--json", "transcript", "status", VID]) == 0
    status = json.loads(capsys.readouterr().out)["data"]
    assert status["transcript_status"] == "succeeded"
    assert status["acquisitions"][0]["method"] == "user_supplied"

    code = main(["--json", "transcript", "status", "zzzzzzzzzzz"])
    assert code == ExitCode.ERROR
    assert json.loads(capsys.readouterr().out)["error"] == {"code": "unknown_video"}
