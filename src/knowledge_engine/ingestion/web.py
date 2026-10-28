"""Reading a web page safely: allowlist, no private addresses, bounded size (INT-001).

``fetch_page(url, ...)`` downloads one page and reads it into located
blocks, the same shape as a note or a Word file (ING-008). The rules:

* **Off unless switched on.** ``[egress] network_fetch`` must be on, and
  the host must be on ``web_allowlist`` (empty by default, so nothing is
  allowed). Only ``http``/``https`` on the default ports; no user names
  or passwords in the URL.
* **No private addresses (SSRF).** Every hop's host name is resolved first,
  and if *any* address is loopback, private, link-local, multicast,
  reserved or unspecified the fetch stops. The connection then goes to the
  address that was checked, never to a second lookup, so a DNS answer that
  changes between check and use (rebinding) can't slip a private address
  in. Redirects are followed by hand, at most five, and each new URL is
  checked again from the start: a redirect to ``http://127.0.0.1/`` or to
  a name that resolves to ``10.0.0.5`` is refused.
* **Bounded.** At most ``max_bytes`` are read (5 MB by default); a page
  that says or turns out to be larger is refused. Only HTML and plain text.
* **Anchored.** The result records the URL asked for, the URL finally
  read, the canonical URL (cleaned of tracking parameters and fragments),
  the page's own ``<link rel="canonical">`` if it names an allowed host,
  the SHA-256 of the exact bytes, and blocks with character offsets into
  the extracted text. ``save_snapshot`` stores the bytes once, by hash, and
  never overwrites.
* **Data, not instructions.** Page text is only ever data (OPS-006);
  scripts, styles and hidden templates are dropped.

Tests swap the resolver and the connection for fakes, so no test touches
the network.

Talking points:
    - "The fetcher checks the address it actually connects to, on every
      redirect, so a public link can't bounce it into my own network."
    - "Every block of a fetched page keeps its offsets, plus the hash of
      the exact bytes and the canonical URL, so a quote traces back."
"""

from __future__ import annotations

import hashlib
import http.client
import ipaddress
import json
import socket
import ssl
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from html.parser import HTMLParser
from pathlib import Path
from typing import Protocol
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from knowledge_engine.ingestion.documents import (
    Block,
    BlockKind,
    ParsedDocument,
    TextBuilder,
    decode_text,
)
from knowledge_engine.settings import Capability, EgressPolicy

WEB_PARSER_VERSION = "int-001-v1"
MAX_REDIRECTS = 5
DEFAULT_MAX_BYTES = 5 * 1024 * 1024
TIMEOUT_S = 15.0
_TYPES = ("text/html", "application/xhtml+xml", "text/plain")
_TRACKING = ("utm_", "fbclid", "gclid", "mc_cid", "mc_eid", "igshid", "ref_src")
_USER_AGENT = "knowledge-engine/1 (personal archive; one page at a time)"


class WebFetchError(RuntimeError):
    """A page that wasn't fetched, with a stable ``code`` (never page content)."""

    def __init__(self, code: str, message: str) -> None:
        """Say why (``code`` is short and stable, e.g. ``private_address``)."""
        super().__init__(message)
        self.code = code


# ------------------------------------------------------------------ URLs


def canonical_url(url: str) -> str:
    """The URL with case, default ports, fragments and tracking parameters normalised.

    Raises:
        WebFetchError: ``bad_url`` for anything but a plain http(s) URL.
    """
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https") or not parts.hostname:
        raise WebFetchError("bad_url", "only http and https URLs with a host can be fetched")
    if parts.username is not None or parts.password is not None:
        raise WebFetchError("bad_url", "URLs with a user name or password are refused")
    try:
        port = parts.port
    except ValueError as error:
        raise WebFetchError("bad_url", "the port isn't a number") from error
    if port is not None and port != {"http": 80, "https": 443}[scheme]:
        raise WebFetchError("bad_url", "only the default ports are fetched")
    host = parts.hostname.lower().rstrip(".")
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith(_TRACKING)
    ]
    return urlunsplit((scheme, host, parts.path or "/", urlencode(query), ""))


def host_allowed(host: str, allowlist: Sequence[str]) -> bool:
    """Whether ``host`` is on the allowlist, exactly or as a subdomain of an entry."""
    host = host.lower().rstrip(".")
    for entry in allowlist:
        entry = entry.lower().strip().rstrip(".")
        if entry and (host == entry or host.endswith("." + entry)):
            return True
    return False


def is_public(address: str) -> bool:
    """True only for globally routable unicast addresses.

    ``is_global`` already excludes loopback, private, link-local, shared
    (100.64/10), documentation, reserved and unspecified ranges; multicast
    is excluded on top. An IPv4 address written as IPv6 (``::ffff:10.0.0.1``)
    is judged as the IPv4 address it is.
    """
    ip = ipaddress.ip_address(address)
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


# ------------------------------------------------------------- transport

Resolver = Callable[[str], list[str]]


def system_resolver(host: str) -> list[str]:
    """Every address the system resolves ``host`` to."""
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as error:
        raise WebFetchError("dns_failed", "the host name didn't resolve") from error
    return sorted({str(info[4][0]) for info in infos})


@dataclass(frozen=True)
class RawResponse:
    """One HTTP answer: status, lower-cased headers and at most the allowed bytes."""

    status: int
    headers: dict[str, str]
    body: bytes
    truncated: bool = False


class Connector(Protocol):
    """Sends one GET to a checked address (tests use a fake)."""

    def __call__(
        self, scheme: str, host: str, address: str, target: str, max_bytes: int
    ) -> RawResponse:
        """GET ``target`` from ``host`` by connecting to ``address``."""
        ...


class _PinnedHTTPS(http.client.HTTPSConnection):
    # Connects to the checked address, but verifies the certificate (and
    # sends SNI) for the host name, so pinning doesn't weaken TLS.
    def __init__(self, host: str, address: str) -> None:
        super().__init__(host, timeout=TIMEOUT_S, context=ssl.create_default_context())
        self._address = address

    def connect(self) -> None:
        sock = socket.create_connection((self._address, 443), TIMEOUT_S)
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)  # type: ignore[attr-defined]


class _PinnedHTTP(http.client.HTTPConnection):
    def __init__(self, host: str, address: str) -> None:
        super().__init__(host, timeout=TIMEOUT_S)
        self._address = address

    def connect(self) -> None:
        self.sock = socket.create_connection((self._address, 80), TIMEOUT_S)


def pinned_connector(
    scheme: str, host: str, address: str, target: str, max_bytes: int
) -> RawResponse:
    """The real connection: to ``address``, with ``host`` as Host header and TLS name."""
    connection: http.client.HTTPConnection = (
        _PinnedHTTPS(host, address) if scheme == "https" else _PinnedHTTP(host, address)
    )
    try:
        connection.request(
            "GET", target, headers={"User-Agent": _USER_AGENT, "Accept": "text/html"}
        )
        response = connection.getresponse()
        body = response.read(max_bytes + 1)
        headers = {k.lower(): v for k, v in response.getheaders()}
        return RawResponse(response.status, headers, body[:max_bytes], len(body) > max_bytes)
    except (OSError, http.client.HTTPException) as error:
        raise WebFetchError("connection_failed", type(error).__name__) from error
    finally:
        connection.close()


# ------------------------------------------------------------------ fetch


@dataclass(frozen=True)
class WebPage:
    """A fetched page and where exactly it came from.

    Attributes:
        requested_url: What was asked for.
        final_url: The URL actually read (after redirects).
        canonical_url: ``final_url`` normalised (``canonical_url()``).
        declared_canonical: The page's ``<link rel="canonical">``, cleaned,
            if it names an allowed host; else None.
        redirects: Every URL followed on the way, in order.
        fetched_at: When (UTC, ISO).
        status: The final HTTP status.
        content_type: Its media type.
        document: The page as located blocks (``format`` is ``html`` or
            ``text``); ``document.sha256`` is the hash of the exact bytes.
    """

    requested_url: str
    final_url: str
    canonical_url: str
    declared_canonical: str | None
    redirects: tuple[str, ...]
    fetched_at: str
    status: int
    content_type: str
    document: ParsedDocument
    raw: bytes = field(repr=False, default=b"")


def _checked_address(url: str, allowlist: Sequence[str], resolve: Resolver) -> str:
    host = urlsplit(url).hostname or ""
    if not host_allowed(host, allowlist):
        raise WebFetchError("host_not_allowed", "that host isn't on web_allowlist")
    try:
        addresses = [str(ipaddress.ip_address(host))]  # a literal IP: no lookup
    except ValueError:
        addresses = resolve(host)
    if not addresses:
        raise WebFetchError("dns_failed", "the host name didn't resolve")
    if not all(is_public(a) for a in addresses):
        raise WebFetchError("private_address", "the host resolves to a private or local address")
    return addresses[0]


def fetch_page(
    url: str,
    egress: EgressPolicy,
    allowlist: Sequence[str],
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    resolve: Resolver = system_resolver,
    connect: Connector = pinned_connector,
) -> WebPage:
    """Fetch one page under every rule in the module docstring.

    Raises:
        EgressDisabledError: ``network_fetch`` is off.
        WebFetchError: Any refusal, with a stable ``code``.
    """
    egress.require(Capability.NETWORK_FETCH)
    current = canonical_url(url)
    followed: list[str] = []
    for _ in range(MAX_REDIRECTS + 1):
        parts = urlsplit(current)
        address = _checked_address(current, allowlist, resolve)
        target = parts.path + (f"?{parts.query}" if parts.query else "")
        response = connect(parts.scheme, parts.hostname or "", address, target, max_bytes)
        if response.status in (301, 302, 303, 307, 308):
            location = response.headers.get("location")
            if not location:
                raise WebFetchError("bad_redirect", "a redirect without a Location")
            followed.append(current)
            current = canonical_url(urljoin(current, location))
            continue
        break
    else:
        raise WebFetchError("too_many_redirects", f"more than {MAX_REDIRECTS} redirects")
    if response.status != 200:
        raise WebFetchError("http_status", f"the server answered {response.status}")
    declared = response.headers.get("content-length", "")
    if response.truncated or (declared.isdigit() and int(declared) > max_bytes):
        raise WebFetchError("too_large", f"the page is larger than {max_bytes} bytes")
    content_type = response.headers.get("content-type", "").split(";")[0].strip().lower()
    if content_type not in _TYPES:
        raise WebFetchError("unsupported_type", "only HTML and plain text pages are read")
    document = parse_html(response.body) if content_type != "text/plain" else _plain(response.body)
    declared_canonical = None
    if document.frontmatter and isinstance(document.frontmatter.get("canonical"), str):
        try:
            candidate = canonical_url(urljoin(current, document.frontmatter["canonical"]))
            if host_allowed(urlsplit(candidate).hostname or "", allowlist):
                declared_canonical = candidate
        except WebFetchError:
            pass  # a broken canonical link is ignored, not followed
    return WebPage(
        requested_url=url,
        final_url=current,
        canonical_url=current,
        declared_canonical=declared_canonical,
        redirects=tuple(followed),
        fetched_at=datetime.now(UTC).isoformat(),
        status=response.status,
        content_type=content_type,
        document=document,
        raw=response.body,
    )


# ------------------------------------------------------------------- HTML

_BLOCK_TAGS = {
    "h1": BlockKind.HEADING,
    "h2": BlockKind.HEADING,
    "h3": BlockKind.HEADING,
    "h4": BlockKind.HEADING,
    "h5": BlockKind.HEADING,
    "h6": BlockKind.HEADING,
    "p": BlockKind.PARAGRAPH,
    "li": BlockKind.LIST,
    "blockquote": BlockKind.QUOTE,
    "pre": BlockKind.CODE,
    "td": BlockKind.TABLE,
    "th": BlockKind.TABLE,
}
_SKIP = {"script", "style", "template", "noscript", "svg", "head"}


class _Extractor(HTMLParser):
    """Collects the text of block elements; skips scripts and hidden parts."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[tuple[BlockKind, int | None, str]] = []
        self.title = ""
        self.canonical: str | None = None
        self._skip = 0
        self._in_title = False
        self._open: tuple[BlockKind, int | None] | None = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "link" and (values.get("rel") or "").lower() == "canonical":
            self.canonical = values.get("href")
        if tag == "title":
            self._in_title = True
        if tag in _SKIP:
            self._skip += 1
        elif tag in _BLOCK_TAGS and self._skip == 0:
            self._close()
            level = int(tag[1]) if tag[0] == "h" and tag[1:].isdigit() else None
            self._open = (_BLOCK_TAGS[tag], level)
        elif tag == "br":
            self._text.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        if tag in _SKIP:
            self._skip = max(0, self._skip - 1)
        elif tag in _BLOCK_TAGS:
            self._close()

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        elif self._skip == 0 and self._open is not None:
            self._text.append(data)

    def _close(self) -> None:
        if self._open is not None:
            text = (
                " ".join("".join(self._text).split())
                if self._open[0] is not BlockKind.CODE
                else "".join(self._text).strip("\n")
            )
            if text:
                self.blocks.append((self._open[0], self._open[1], text))
        self._open, self._text = None, []

    def close(self) -> None:
        super().close()
        self._close()


def parse_html(data: bytes) -> ParsedDocument:
    """An HTML page as located blocks; the title and canonical link go in ``frontmatter``."""
    text, encoding, warnings = decode_text(data)
    extractor = _Extractor()
    extractor.feed(text)
    extractor.close()
    builder = TextBuilder()
    blocks: list[Block] = []
    path: list[tuple[int, str]] = []
    for kind, level, piece in extractor.blocks:
        start, end = builder.add(piece)
        if kind is BlockKind.HEADING and level is not None:
            path = [(lvl, t) for lvl, t in path if lvl < level] + [(level, piece)]
        blocks.append(
            Block(
                index=len(blocks),
                kind=kind,
                text=piece,
                start=start,
                end=end,
                line_start=None,
                line_end=None,
                heading_path=tuple(t for _, t in path),
                level=level,
                locator=f"B{len(blocks) + 1}",
            )
        )
    meta = {"title": " ".join(extractor.title.split())}
    if extractor.canonical:
        meta["canonical"] = extractor.canonical
    return ParsedDocument(
        format="html",
        sha256=hashlib.sha256(data).hexdigest(),
        size=len(data),
        encoding=encoding,
        text=builder.text(),
        frontmatter=meta,
        frontmatter_raw=None,
        blocks=tuple(blocks),
        warnings=warnings if blocks else (*warnings, "no_text_blocks"),
        parser=WEB_PARSER_VERSION,
    )


def _plain(data: bytes) -> ParsedDocument:
    from knowledge_engine.ingestion.documents import parse_text

    return parse_text(data)


# --------------------------------------------------------------- snapshot


def save_snapshot(page: WebPage, workspace_root: Path) -> Path:
    """Store the exact bytes once, by hash, with a metadata file; never overwrite.

    Returns:
        The folder ``<workspace>/web/<sha256>/`` holding ``page`` and
        ``meta.json``. A second save of the same bytes changes nothing.
    """
    folder = workspace_root / "web" / page.document.sha256
    if (folder / "meta.json").exists():
        return folder
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "page").write_bytes(page.raw)
    meta = {key: value for key, value in asdict(page).items() if key not in ("raw", "document")}
    meta["sha256"] = page.document.sha256
    meta["parser"] = page.document.parser
    (folder / "meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True), "utf-8")
    return folder
