"""Social accounts mentioned in chats: detection rules (SOC-001).

Three kinds of mention, from most to least certain:

* **a profile URL** on a known platform, like ``https://github.com/octo``
  or ``https://www.youtube.com/channel/UC...``: the platform and the handle
  (or the platform's own permanent ID) come from the URL;
* **a platform-qualified handle** in the text, like ``GitHub: @octo``,
  ``@octo on Instagram`` or a Mastodon address ``@octo@mastodon.social``;
* **a bare @handle**, like ``ask @octo``: no platform, so it is recorded
  as an *ambiguous* candidate and never linked to any account.

Not accounts: email addresses (``me@example.org``), code decorators
(``@property`` on its own line), anything inside Markdown code, and post
or video pages (a tweet isn't a profile).

Rules only read text. Nothing is fetched, followed or contacted.

Talking points:
    - "A profile link or 'GitHub: @name' is a real account mention; a bare
      @name could be anyone, so it's kept as an ambiguous candidate and
      never guessed into an identity."
    - "Emails and Python decorators look like handles; the rules and tests
      make sure they aren't counted."
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit

from knowledge_engine.graph.offsets import Span
from knowledge_engine.links.extract import MESSAGE_TEXT, FoundLink

RESOLVED = "resolved"
AMBIGUOUS = "ambiguous"


@dataclass(frozen=True)
class FoundAccount:
    """One social account mention.

    Attributes:
        origin: ``message_text`` or ``citation_metadata`` (as for links).
        span: Where it is (code points, or the citation position).
        raw: The mention exactly as written.
        platform: e.g. ``github``; None for a bare @handle.
        handle: The handle as written, without ``@``; None if only an ID.
        stable_id: The platform's permanent account ID, when the URL has one.
        profile_url: The canonical profile URL, when known.
        resolution: ``resolved`` (platform known) or ``ambiguous``.
    """

    origin: str
    span: Span
    raw: str
    platform: str | None
    handle: str | None
    stable_id: str | None = None
    profile_url: str | None = None
    resolution: str = RESOLVED


@dataclass(frozen=True)
class _Rule:
    platform: str
    hosts: frozenset[str]
    pattern: re.Pattern[str]  # matched against the URL path
    profile: str  # profile URL template, {handle}
    reserved: frozenset[str] = frozenset()
    id_group: str | None = None  # a named group holding a permanent ID


def _rule(
    platform: str,
    hosts: Iterable[str],
    pattern: str,
    profile: str,
    reserved: Iterable[str] = (),
    id_group: str | None = None,
) -> _Rule:
    return _Rule(
        platform,
        frozenset(hosts),
        re.compile(pattern),
        profile,
        frozenset(reserved),
        id_group,
    )


# One rule per profile URL form (TR-14's platform list). A path must match
# the whole pattern, so post and video pages don't count as profiles.
_RULES = (
    _rule(
        "x",
        ("x.com", "twitter.com", "mobile.twitter.com"),
        r"/(?P<handle>[A-Za-z0-9_]{1,15})/?",
        "https://x.com/{handle}",
        (
            "home",
            "i",
            "intent",
            "search",
            "explore",
            "settings",
            "login",
            "share",
            "hashtag",
            "messages",
            "notifications",
            "compose",
            "tos",
            "privacy",
        ),
    ),
    _rule(
        "instagram",
        ("instagram.com",),
        r"/(?P<handle>[A-Za-z0-9._]{1,30})/?",
        "https://www.instagram.com/{handle}/",
        ("p", "reel", "reels", "explore", "stories", "accounts", "direct", "tv"),
    ),
    _rule(
        "tiktok",
        ("tiktok.com",),
        r"/@(?P<handle>[A-Za-z0-9._]{2,24})/?",
        "https://www.tiktok.com/@{handle}",
    ),
    _rule(
        "linkedin",
        ("linkedin.com",),
        r"/in/(?P<handle>[A-Za-z0-9-]{3,100})/?",
        "https://www.linkedin.com/in/{handle}/",
    ),
    _rule(
        "youtube",
        ("youtube.com", "m.youtube.com"),
        r"/@(?P<handle>[A-Za-z0-9._-]{3,30})/?",
        "https://www.youtube.com/@{handle}",
    ),
    _rule(
        "youtube",
        ("youtube.com", "m.youtube.com"),
        r"/channel/(?P<id>UC[A-Za-z0-9_-]{22})/?",
        "https://www.youtube.com/channel/{handle}",
        id_group="id",
    ),
    _rule(
        "github",
        ("github.com",),
        r"/(?P<handle>[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?)/?",
        "https://github.com/{handle}",
        (
            "features",
            "topics",
            "about",
            "pricing",
            "login",
            "settings",
            "marketplace",
            "explore",
            "sponsors",
            "issues",
            "pulls",
            "notifications",
            "new",
            "apps",
            "orgs",
            "search",
            "trending",
            "collections",
            "events",
            "security",
            "enterprise",
            "join",
            "signup",
            "contact",
            "site",
            "readme",
            "codespaces",
        ),
    ),
    _rule(
        "reddit",
        ("reddit.com", "old.reddit.com"),
        r"/(?:user|u)/(?P<handle>[A-Za-z0-9_-]{3,20})/?",
        "https://www.reddit.com/user/{handle}/",
    ),
    _rule(
        "bluesky",
        ("bsky.app",),
        r"/profile/(?P<handle>[A-Za-z0-9.-]{3,253})/?",
        "https://bsky.app/profile/{handle}",
    ),
    _rule(
        "threads",
        ("threads.net", "threads.com"),
        r"/@(?P<handle>[A-Za-z0-9._]{1,30})/?",
        "https://www.threads.net/@{handle}",
    ),
    _rule(
        "facebook",
        ("facebook.com", "m.facebook.com"),
        r"/(?P<handle>[A-Za-z0-9.]{5,50})/?",
        "https://www.facebook.com/{handle}",
        (
            "pages",
            "groups",
            "events",
            "watch",
            "marketplace",
            "photo",
            "photos",
            "story.php",
            "sharer",
            "share",
            "login",
            "help",
            "policies",
            "gaming",
            "profile.php",
        ),
    ),
    _rule(
        "twitch",
        ("twitch.tv", "m.twitch.tv"),
        r"/(?P<handle>[A-Za-z0-9_]{4,25})/?",
        "https://www.twitch.tv/{handle}",
        ("directory", "videos", "settings", "subscriptions", "downloads", "jobs", "p"),
    ),
)

# Words that name a platform next to an @handle in text.
_PLATFORM_WORDS = {
    "twitter": "x",
    "x": "x",
    "instagram": "instagram",
    "insta": "instagram",
    "ig": "instagram",
    "tiktok": "tiktok",
    "github": "github",
    "threads": "threads",
    "twitch": "twitch",
    "bluesky": "bluesky",
    "bsky": "bluesky",
    "reddit": "reddit",
    "youtube": "youtube",
    "linkedin": "linkedin",
    "mastodon": "mastodon",
    "facebook": "facebook",
}
_WORDS = "|".join(sorted(_PLATFORM_WORDS, key=len, reverse=True))
_HANDLE = r"@(?P<handle>[A-Za-z0-9_](?:[A-Za-z0-9_.-]{0,48}[A-Za-z0-9_])?)"
# "GitHub: @octo", "Twitter @octo", "(Instagram) @octo".
_BEFORE_RE = re.compile(rf"\b(?P<word>{_WORDS})\)?\s*[:\-]?\s*{_HANDLE}", re.IGNORECASE)
# "@octo on GitHub", "@octo (Instagram)", "@octo on twitter".
_AFTER_RE = re.compile(rf"{_HANDLE}\s*(?:on|\(|at)\s*(?P<word>{_WORDS})\b", re.IGNORECASE)
# "@octo@mastodon.social": a Fediverse address carries its own server.
_FEDI_RE = re.compile(
    r"(?<![\w.@])@(?P<handle>[A-Za-z0-9_]{1,30})@(?P<server>[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)"
)
# Any @word not glued to a preceding word character (which would be an email).
_BARE_RE = re.compile(rf"(?<![\w.@/]){_HANDLE}(?![\w@])")
# A whole line that's just a decorator: "@property", "@app.route('/x')".
_DECORATOR_LINE_RE = re.compile(r"^[ \t]*@[\w.]+(?:\(.*\))?[ \t]*$", re.MULTILINE)
_CODE_RE = re.compile(r"```.*?(?:```|\Z)|`[^`\n]*`", re.DOTALL)


def account_from_url(url: str) -> tuple[str, str | None, str | None, str] | None:
    """Return ``(platform, handle, stable_id, profile_url)`` for a profile URL.

    Args:
        url: A URL as written.

    Returns:
        The account, or None if it isn't a profile URL on a known platform.
    """
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return None
    if parts.scheme.lower() not in {"http", "https"}:
        return None
    host = (parts.hostname or "").rstrip(".").lower().removeprefix("www.")
    if host in {"facebook.com", "m.facebook.com"} and parts.path == "/profile.php":
        number = parse_qs(parts.query).get("id", [""])[0]
        if number.isdigit():
            return "facebook", None, number, f"https://www.facebook.com/profile.php?id={number}"
        return None
    for rule in _RULES:
        if host not in rule.hosts:
            continue
        match = rule.pattern.fullmatch(parts.path)
        if not match:
            continue
        if rule.id_group:
            stable = match.group(rule.id_group)
            return rule.platform, None, stable, rule.profile.format(handle=stable)
        handle = match.group("handle")
        if handle.lower() in rule.reserved:
            return None
        return rule.platform, handle, None, rule.profile.format(handle=handle)
    return None


def find_accounts(text: str, links: Iterable[FoundLink]) -> list[FoundAccount]:
    """Find every social account mention in one message.

    Args:
        text: The canonical text.
        links: The message's URL mentions (LNK-001), for profile URLs.

    Returns:
        Mentions ordered by origin then position. A text range claimed by a
        qualified handle or a profile URL isn't counted again as a bare one.
    """
    found: list[FoundAccount] = []
    for link in links:
        account = account_from_url(link.original)
        if account is not None:
            platform, handle, stable, profile = account
            found.append(
                FoundAccount(
                    link.origin, link.span, link.original, platform, handle, stable, profile
                )
            )
    blocked = _code_ranges(text)
    taken = [link.span for link in links if link.origin == MESSAGE_TEXT]

    def free(start: int, end: int) -> bool:
        return not any(s < end and start < e for s, e in blocked) and not any(
            span.start < end and start < span.end for span in taken
        )

    for match in _FEDI_RE.finditer(text):
        if free(match.start(), match.end()):
            handle = f"{match.group('handle')}@{match.group('server').lower()}"
            found.append(_text_mention(text, match.start(), match.end(), "mastodon", handle))
            taken.append(Span(match.start(), match.end()))
    for regex in (_BEFORE_RE, _AFTER_RE):
        for match in regex.finditer(text):
            if free(match.start(), match.end()):
                platform = _PLATFORM_WORDS[match.group("word").lower()]
                found.append(
                    _text_mention(text, match.start(), match.end(), platform, match.group("handle"))
                )
                taken.append(Span(match.start(), match.end()))
    for match in _BARE_RE.finditer(text):
        if free(match.start(), match.end()):
            found.append(
                FoundAccount(
                    MESSAGE_TEXT,
                    Span(match.start(), match.end()),
                    match.group(0),
                    None,
                    match.group("handle"),
                    resolution=AMBIGUOUS,
                )
            )
    return sorted(found, key=lambda a: (a.origin, a.span.start, a.span.end))


def _text_mention(text: str, start: int, end: int, platform: str, handle: str) -> FoundAccount:
    profile = None
    for rule in _RULES:
        if rule.platform == platform and not rule.id_group:
            profile = rule.profile.format(handle=handle)
            break
    return FoundAccount(
        MESSAGE_TEXT, Span(start, end), text[start:end], platform, handle, None, profile
    )


def _code_ranges(text: str) -> list[tuple[int, int]]:
    # Markdown code and decorator-only lines: "@" there is code, not a person.
    ranges = [(m.start(), m.end()) for m in _CODE_RE.finditer(text)]
    ranges += [(m.start(), m.end()) for m in _DECORATOR_LINE_RE.finditer(text)]
    return ranges


def iter_accounts(text: str, links: Iterable[FoundLink]) -> Iterator[FoundAccount]:
    """Yield every account mention in a message (see ``find_accounts``)."""
    yield from find_accounts(text, list(links))
