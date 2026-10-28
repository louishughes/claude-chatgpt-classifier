"""YTB-001: table of YouTube URL forms, lookalikes and invalid IDs."""

from __future__ import annotations

import pytest

from knowledge_engine.links.youtube import YouTubeRef, parse_youtube

VID = "dQw4w9WgXcQ"  # synthetic-looking 11-character ID; never fetched


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (f"https://www.youtube.com/watch?v={VID}", YouTubeRef(VID)),
        (f"http://youtube.com/watch?v={VID}&t=90", YouTubeRef(VID, t_seconds=90)),
        (f"https://m.youtube.com/watch?v={VID}&t=1m30s", YouTubeRef(VID, t_seconds=90)),
        (
            f"https://music.youtube.com/watch?v={VID}&list=PLabc_123",
            YouTubeRef(VID, playlist_id="PLabc_123"),
        ),
        (f"https://youtu.be/{VID}?t=1h2m3s", YouTubeRef(VID, t_seconds=3723)),
        (f"https://youtu.be/{VID}", YouTubeRef(VID)),
        (f"https://www.youtube.com/shorts/{VID}", YouTubeRef(VID)),
        (f"https://www.youtube.com/live/{VID}?feature=share", YouTubeRef(VID)),
        (f"https://www.youtube.com/embed/{VID}?start=30", YouTubeRef(VID, t_seconds=30)),
        (f"https://www.youtube-nocookie.com/embed/{VID}", YouTubeRef(VID)),
        (f"https://www.youtube.com/watch?v={VID}#t=45", YouTubeRef(VID, t_seconds=45)),
        (
            f"https://www.youtube.com/watch?v={VID}&ab_channel=SomeChannel",
            YouTubeRef(VID, channel_hint="SomeChannel"),
        ),
        (f"HTTPS://WWW.YOUTUBE.COM/watch?v={VID}", YouTubeRef(VID)),
        # A time that can't be read is dropped, never guessed.
        (f"https://youtu.be/{VID}?t=soon", YouTubeRef(VID)),
    ],
)
def test_video_forms(url: str, expected: YouTubeRef) -> None:
    assert parse_youtube(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        f"https://youtube.com.example.net/watch?v={VID}",  # lookalike
        f"https://notyoutube.com/watch?v={VID}",
        f"https://youtu.be.example.org/{VID}",
        f"https://www.youtube.com/watch?v={VID[:10]}",  # too short
        f"https://www.youtube.com/watch?v={VID}x",  # too long
        "https://www.youtube.com/watch?v=dQw4w9WgX!Q",  # bad character
        "https://www.youtube.com/@SomeChannel",  # a channel, not a video
        "https://www.youtube.com/playlist?list=PLabc",
        "https://www.youtube.com/",
        f"ftp://youtube.com/watch?v={VID}",
        "not a url",
    ],
)
def test_not_videos(url: str) -> None:
    assert parse_youtube(url) is None
