"""Find URLs in message text and citation metadata (LNK-001).

Two kinds of mention:

* **message_text:** a URL written in the message. Its span is the exact
  half-open range of code points it covers in the canonical text
  (NRM-003), after trimming what surrounds it in normal writing: a
  sentence's full stop, a closing bracket that isn't part of the URL,
  Markdown ``[label](url)`` and ``<url>`` wrappers;
* **citation_metadata:** a URL in the message's structured citations (the
  sources a web-browsing answer cites). The export's own character
  positions for these don't reliably match the canonical text, so the
  span here is the citation's position in the list, ``[i, i + 1)``.

Each mention keeps the original string. ``canonical_url`` gives the
destination used to group mentions: lower-case scheme and host, no
default port, ``/`` for an empty path, no ``#fragment``. The query is kept
exactly: changing it could point at a different page.

Only ``http`` and ``https`` URLs with a scheme are recognised; a bare
``example.com`` is not guessed at. Everything here is pure text handling:
URLs are untrusted data and are never fetched.

Talking points:
    - "A link mentioned 12 times is one destination with 12 mentions, each
      pinned to the exact characters in the exact message."
    - "Trimming a URL out of a sentence has rules, and the tests cover the
      awkward cases: Markdown, angle brackets and full stops."
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from knowledge_engine.graph.offsets import Span

MESSAGE_TEXT = "message_text"
CITATION_METADATA = "citation_metadata"
CONTEXT_CHARS = 80

# A URL runs until whitespace or a character that can't appear unescaped in
# one and usually wraps it in prose (quotes, angle brackets, backticks).
_URL_RE = re.compile(r"https?://[^\s<>\"'` 　]+", re.IGNORECASE)
_TRAILING = ".,;:!?*"
_PAIRS = {")": "(", "]": "[", "}": "{"}
_DEFAULT_PORTS = {"http": 80, "https": 443}


@dataclass(frozen=True)
class FoundLink:
    """One URL mention.

    Attributes:
        origin: ``message_text`` or ``citation_metadata``.
        span: Code-point range in the canonical text (message_text), or
            the citation's list position (citation_metadata).
        original: The URL exactly as written.
        canonical_url: The destination it groups under.
        host: The canonical host.
    """

    origin: str
    span: Span
    original: str
    canonical_url: str
    host: str


def canonical_url(url: str) -> tuple[str, str] | None:
    """Return ``(canonical_url, host)`` for an http(s) URL, or None if it isn't one.

    Args:
        url: The URL as written.

    Returns:
        The canonical form and its host, or None for anything that doesn't
        parse as an http(s) URL with a host.
    """
    try:
        parts = urlsplit(url.strip())
        port = parts.port
    except ValueError:
        return None
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").rstrip(".")
    if scheme not in _DEFAULT_PORTS or not host:
        return None
    try:
        host = host.encode("idna").decode("ascii").lower()
    except UnicodeError:
        host = host.lower()
    netloc = host if port in (None, _DEFAULT_PORTS[scheme]) else f"{host}:{port}"
    if ":" in host:  # IPv6 literal
        netloc = f"[{host}]" if port in (None, _DEFAULT_PORTS[scheme]) else f"[{host}]:{port}"
    return urlunsplit((scheme, netloc, parts.path or "/", parts.query, "")), host


def find_in_text(text: str, *, markdown_links: bool = False) -> list[FoundLink]:
    """Find every http(s) URL in a message's canonical text.

    Args:
        text: ``CanonicalNode.text``.
        markdown_links: Also end a URL where a Markdown link's target starts,
            so ``[https://x](https://x)`` gives two mentions, not one long
            wrong URL, and where a second target follows a first
            (``(https://a)(https://b)``). The cost: a URL with a literal
            ``](`` or ``)(`` in it is cut there (ING-013). Notes use it. Chat messages don't yet:
            changing their mentions would add new rows on every re-import
            of an old chat, so that needs its own repair plan.

    Returns:
        Mentions in order of position; each span selects exactly
        ``original`` from ``text``.
    """
    found: list[FoundLink] = []
    position = 0
    while (match := _URL_RE.search(text, position)) is not None:
        start, end = match.start(), match.end()
        position = end
        if markdown_links:
            cuts = [
                c for c in (text.find("](", start, end), text.find(")(", start, end)) if c != -1
            ]
            if cuts:
                end = position = min(cuts)  # the next search finds the link's own target
        end = _trim(text, start, end)
        original = text[start:end]
        canonical = canonical_url(original)
        if canonical is None:
            continue
        found.append(FoundLink(MESSAGE_TEXT, Span(start, end), original, *canonical))
    return found


def find_in_metadata(message: Mapping[str, Any] | None) -> list[FoundLink]:
    """Find URLs in a native message's citation metadata.

    Looks at ``metadata.citations[].metadata.url`` and
    ``metadata.content_references[]`` (``url`` and ``items[].url``). Shapes
    it doesn't know are ignored, never guessed at.

    Args:
        message: The native message object.

    Returns:
        Mentions in list order, spans ``[i, i + 1)``.
    """
    metadata = (message or {}).get("metadata")
    if not isinstance(metadata, Mapping):
        return []
    urls: list[str] = []
    citations = metadata.get("citations")
    if isinstance(citations, list):
        for citation in citations:
            inner = citation.get("metadata") if isinstance(citation, Mapping) else None
            if isinstance(inner, Mapping) and isinstance(inner.get("url"), str):
                urls.append(inner["url"])
    references = metadata.get("content_references")
    if isinstance(references, list):
        for reference in references:
            if not isinstance(reference, Mapping):
                continue
            if isinstance(reference.get("url"), str):
                urls.append(reference["url"])
            items = reference.get("items")
            if isinstance(items, list):
                urls.extend(
                    item["url"]
                    for item in items
                    if isinstance(item, Mapping) and isinstance(item.get("url"), str)
                )
    found = []
    for position, url in enumerate(urls):
        canonical = canonical_url(url)
        if canonical is not None:
            found.append(
                FoundLink(CITATION_METADATA, Span(position, position + 1), url, *canonical)
            )
    return found


def context(text: str, span: Span, width: int = CONTEXT_CHARS) -> tuple[str, str]:
    """Return up to ``width`` characters before and after a text span."""
    return text[max(0, span.start - width) : span.start], text[span.end : span.end + width]


def _trim(text: str, start: int, end: int) -> int:
    # Drop trailing characters that belong to the sentence, not the URL: a
    # full stop, a comma, Markdown emphasis, or a closing bracket that has no
    # partner inside the URL (as in "(see https://x.org/a)" or "[t](url)").
    while end > start:
        last = text[end - 1]
        if last in _TRAILING:
            end -= 1
        elif last in _PAIRS:
            url = text[start:end]
            if url.count(_PAIRS[last]) < url.count(last):
                end -= 1
            else:
                break
        else:
            break
    return end


def iter_links(text: str, message: Mapping[str, Any] | None) -> Iterator[FoundLink]:
    """Yield every mention in a message: text first, then citation metadata."""
    yield from find_in_text(text)
    yield from find_in_metadata(message)
