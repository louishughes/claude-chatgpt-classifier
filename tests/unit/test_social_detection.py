"""SOC-001: platform URL forms, qualified handles, and what isn't an account."""

from __future__ import annotations

import pytest

from knowledge_engine.links.extract import find_in_text
from knowledge_engine.links.social import AMBIGUOUS, RESOLVED, account_from_url, find_accounts


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://x.com/SynthUser", ("x", "SynthUser", None)),
        ("https://twitter.com/synth_user/", ("x", "synth_user", None)),
        ("https://www.instagram.com/synth.user/", ("instagram", "synth.user", None)),
        ("https://www.tiktok.com/@synthuser", ("tiktok", "synthuser", None)),
        ("https://www.linkedin.com/in/synth-user-123/", ("linkedin", "synth-user-123", None)),
        ("https://www.youtube.com/@SynthChannel", ("youtube", "SynthChannel", None)),
        (
            "https://www.youtube.com/channel/UCabcdefghijklmnopqrstuv",
            ("youtube", None, "UCabcdefghijklmnopqrstuv"),
        ),
        ("https://github.com/synth-octo", ("github", "synth-octo", None)),
        ("https://www.reddit.com/user/synth_user/", ("reddit", "synth_user", None)),
        ("https://bsky.app/profile/synth.bsky.social", ("bluesky", "synth.bsky.social", None)),
        ("https://www.threads.net/@synth.user", ("threads", "synth.user", None)),
        ("https://www.facebook.com/synth.user", ("facebook", "synth.user", None)),
        ("https://www.facebook.com/profile.php?id=1000123", ("facebook", None, "1000123")),
        ("https://www.twitch.tv/synthstreamer", ("twitch", "synthstreamer", None)),
    ],
)
def test_profile_urls(url: str, expected: tuple[str, str | None, str | None]) -> None:
    found = account_from_url(url)
    assert found is not None
    assert found[:3] == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://x.com/SynthUser/status/123",  # a post, not a profile
        "https://x.com/home",
        "https://github.com/synth-octo/repo",  # a repository
        "https://github.com/features",
        "https://www.instagram.com/p/AbC123/",
        "https://www.youtube.com/watch?v=aBcDeFgHiJk",  # a video
        "https://x.com.example.net/SynthUser",  # lookalike
        "https://example.org/@synth",
    ],
)
def test_not_profiles(url: str) -> None:
    assert account_from_url(url) is None


def _accounts(text: str) -> list[tuple[str, str | None, str | None, str]]:
    return [
        (a.span.of(text), a.platform, a.handle, a.resolution)
        for a in find_accounts(text, find_in_text(text))
    ]


def test_qualified_handles_resolve_and_bare_ones_stay_ambiguous() -> None:
    text = (
        "GitHub: @synth-octo, @SynthUser on Twitter, and ask @someone. "
        "Mastodon @synth@example.social"
    )
    assert _accounts(text) == [
        ("GitHub: @synth-octo", "github", "synth-octo", RESOLVED),
        ("@SynthUser on Twitter", "x", "SynthUser", RESOLVED),
        ("@someone", None, "someone", AMBIGUOUS),
        ("@synth@example.social", "mastodon", "synth@example.social", RESOLVED),
    ]


def test_emails_decorators_and_code_are_not_accounts() -> None:
    text = (
        "Mail synth@example.org please.\n"
        "@property\n"
        "    @app.route('/x')\n"
        "Use `@decorator` here, and\n"
        "```\n@synth_in_code\n```\n"
        "see https://medium.com/@synthwriter/post"
    )
    assert _accounts(text) == []


def test_profile_url_in_text_is_one_mention_not_two() -> None:
    text = "Follow https://x.com/SynthUser now"
    assert _accounts(text) == [("https://x.com/SynthUser", "x", "SynthUser", RESOLVED)]
