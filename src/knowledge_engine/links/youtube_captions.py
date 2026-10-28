"""Captions from the official YouTube Data API, with your own permission (INT-002).

The only network transcript source the engine uses. It plugs into YTB-002's
``request_transcript``, so the ``transcript_fetch`` switch, the bounded
retries and the recorded statuses all apply unchanged.

How it asks, and why it often can't:

1. ``captions.list`` names a video's caption tracks. No tracks: the answer
   is ``unavailable`` ("no caption tracks").
2. ``captions.download`` fetches one track as WebVTT. YouTube only allows
   this for videos the signed-in account may edit (usually its owner's own
   videos). Anything else comes back 403, which is recorded as
   ``permission_required``. It is **never** worked around: no scraping of
   the watch page, no unofficial "timedtext" endpoints, no third-party
   downloaders.

A human-made track is preferred to an automatic one. An automatic (ASR)
track is accepted but marked ``machine_generated`` in the snapshot's
provenance, so nobody mistakes it for what the speaker wrote. Quota and
rate-limit answers come back as ``rate_limited`` (temporary, retried a
bounded number of times by ``request_transcript``), and calls are spaced
at least ``min_interval_s`` apart.

The OAuth access token is read from ``KE_YOUTUBE_ACCESS_TOKEN`` (the
environment only, like the model key) and is never stored or logged.

Talking points:
    - "Transcripts come only from the official API with my own sign-in;
      if YouTube says no, the engine records 'permission required' and
      stops. It never scrapes."
    - "An automatic caption track is labelled machine-generated in its
      provenance."
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import SecretStr

from knowledge_engine.domain.enums import TranscriptStatus
from knowledge_engine.ingestion.transcripts import TranscriptFormat
from knowledge_engine.links.video_transcripts import ProviderAnswer

API = "https://www.googleapis.com/youtube/v3"
TIMEOUT_S = 20.0
_RATE_REASONS = {"quotaExceeded", "rateLimitExceeded", "userRateLimitExceeded"}


@dataclass(frozen=True)
class HttpAnswer:
    """One API answer: status code and body bytes."""

    status: int
    body: bytes


# GET url with headers -> answer. Tests pass a fake; the real one is urllib.
Http = Callable[[str, dict[str, str]], HttpAnswer]


def urllib_get(url: str, headers: dict[str, str]) -> HttpAnswer:
    """A plain HTTPS GET with certificate checks (the default context)."""
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:  # noqa: S310 - fixed https host
            return HttpAnswer(response.status, response.read())
    except urllib.error.HTTPError as error:
        return HttpAnswer(error.code, error.read())
    except (OSError, urllib.error.URLError):
        return HttpAnswer(0, b"")


def _reason(body: bytes) -> str:
    # The API's own error reason (e.g. "forbidden", "quotaExceeded"); never page text.
    try:
        errors = json.loads(body)["error"]["errors"]
        return str(errors[0].get("reason", ""))
    except (ValueError, KeyError, IndexError, TypeError):
        return ""


class YouTubeCaptionsProvider:
    """The YouTube Data API v3 captions provider (see the module docstring)."""

    name = "youtube_data_api"

    def __init__(
        self,
        access_token: SecretStr,
        *,
        language: str | None = None,
        http: Http = urllib_get,
        min_interval_s: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Set up with a token; ``language`` (e.g. ``en``) picks among tracks."""
        self._token = access_token
        self._language = language
        self._http = http
        self._min_interval = min_interval_s
        self._clock = clock
        self._sleep = sleep
        self._last: float | None = None

    def _get(self, path: str, query: dict[str, str]) -> HttpAnswer:
        if self._last is not None:
            wait = self._min_interval - (self._clock() - self._last)
            if wait > 0:
                self._sleep(wait)
        self._last = self._clock()
        url = f"{API}/{path}?{urllib.parse.urlencode(query)}"
        headers = {"Authorization": f"Bearer {self._token.get_secret_value()}"}
        return self._http(url, headers)

    def _refused(self, answer: HttpAnswer, what: str) -> ProviderAnswer:
        reason = _reason(answer.body)
        if answer.status == 429 or reason in _RATE_REASONS:
            return ProviderAnswer(TranscriptStatus.RATE_LIMITED, reason=f"{what}: {reason or 429}")
        if answer.status in (401, 403):
            return ProviderAnswer(
                TranscriptStatus.PERMISSION_REQUIRED,
                reason=f"{what}: YouTube refused ({reason or answer.status}); captions can "
                "only be downloaded for videos your account may edit",
            )
        if answer.status == 404:
            return ProviderAnswer(TranscriptStatus.UNAVAILABLE, reason=f"{what}: not found")
        return ProviderAnswer(TranscriptStatus.FAILED, reason=f"{what}: HTTP {answer.status}")

    def fetch(self, video_id: str) -> ProviderAnswer:
        """Find the best caption track and download it, or say exactly why not."""
        listed = self._get("captions", {"part": "snippet", "videoId": video_id})
        if listed.status != 200:
            return self._refused(listed, "captions.list")
        try:
            tracks: list[dict[str, Any]] = json.loads(listed.body).get("items", [])
        except ValueError:
            return ProviderAnswer(TranscriptStatus.FAILED, reason="captions.list: not JSON")
        if not tracks:
            return ProviderAnswer(TranscriptStatus.UNAVAILABLE, reason="no caption tracks")
        track = _choose(tracks, self._language)
        snippet = track.get("snippet", {})
        downloaded = self._get(f"captions/{track['id']}", {"tfmt": "vtt"})
        if downloaded.status != 200:
            return self._refused(downloaded, "captions.download")
        machine = str(snippet.get("trackKind", "")).lower() == "asr"
        return ProviderAnswer(
            TranscriptStatus.SUCCEEDED,
            data=downloaded.body,
            format=TranscriptFormat.VTT,
            language=snippet.get("language") or None,
            source_url=f"https://www.youtube.com/watch?v={video_id}",
            detail={
                "caption_track": str(track["id"]),
                "track_kind": str(snippet.get("trackKind", "")),
                "machine_generated": "yes" if machine else "no",
                "api": "youtube.captions.download v3",
            },
        )


def _choose(tracks: list[dict[str, Any]], language: str | None) -> dict[str, Any]:
    """Prefer the asked language, then a human-made track, then the first listed."""

    def rank(track: dict[str, Any]) -> tuple[int, int]:
        info = track.get("snippet") or {}
        same = language is not None and str(info.get("language", "")).lower().startswith(
            language.lower()
        )
        human = str(info.get("trackKind", "")).lower() != "asr"
        return (0 if same else 1, 0 if human else 1)

    return sorted(tracks, key=rank)[0]
