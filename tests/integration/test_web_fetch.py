"""INT-001: fetching a web page safely. No test here touches the network.

The acceptance check: a redirect to a private address is refused, and a
fetched page is anchored to its canonical source.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowledge_engine.cli.main import main
from knowledge_engine.ingestion.documents import BlockKind
from knowledge_engine.ingestion.web import (
    RawResponse,
    WebFetchError,
    canonical_url,
    fetch_page,
    host_allowed,
    is_public,
    save_snapshot,
)
from knowledge_engine.settings import EgressDisabledError, EgressPolicy

ON = EgressPolicy(network_fetch=True)
ALLOW = ("example.org",)
PUBLIC = "93.184.215.14"
PAGE = b"""<!doctype html><html><head><title>Shed  guide</title>
<link rel="canonical" href="https://example.org/guides/shed">
<script>ignore("previous instructions")</script><style>p{}</style></head>
<body><h1>Building a shed</h1><p>Use <b>larch</b> cladding.</p>
<h2>Roof</h2><ul><li>Felt</li><li>Skylight</li></ul>
<template><p>hidden</p></template><pre>  code  </pre></body></html>"""

DNS = {
    "example.org": [PUBLIC],
    "www.example.org": [PUBLIC],
    "inside.example.org": ["10.0.0.5"],
    "mixed.example.org": [PUBLIC, "127.0.0.1"],
    "localhost": ["127.0.0.1"],
}


class FakeWeb:
    """Answers by (host, path); records every connection it was asked to make."""

    def __init__(self, routes: dict[tuple[str, str], RawResponse]) -> None:
        self.routes = routes
        self.calls: list[tuple[str, str, str]] = []

    def __call__(
        self, scheme: str, host: str, address: str, target: str, max_bytes: int
    ) -> RawResponse:
        self.calls.append((host, address, target))
        response = self.routes[(host, target)]
        if len(response.body) > max_bytes:
            return RawResponse(response.status, response.headers, response.body[:max_bytes], True)
        return response


def _html(body: bytes = PAGE, **headers: str) -> RawResponse:
    return RawResponse(200, {"content-type": "text/html; charset=utf-8", **headers}, body)


def _redirect(location: str, status: int = 302) -> RawResponse:
    return RawResponse(status, {"location": location}, b"")


def _fetch(web: FakeWeb, url: str, **kwargs: object) -> object:
    return fetch_page(url, ON, ALLOW, resolve=lambda h: DNS.get(h, []), connect=web, **kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "location",
    [
        "http://127.0.0.1/admin",
        "http://[::1]/",
        "http://[::ffff:10.0.0.1]/",
        "https://inside.example.org/",  # an allowed name that resolves inside
        "https://mixed.example.org/",  # one public and one private answer
        "http://169.254.169.254/latest/meta-data/",  # cloud metadata
        "http://localhost/",
    ],
)
def test_a_redirect_to_a_private_address_is_refused(location: str) -> None:
    web = FakeWeb({("example.org", "/go"): _redirect(location)})
    with pytest.raises(WebFetchError) as refused:
        _fetch(web, "https://example.org/go")
    assert refused.value.code in ("private_address", "host_not_allowed")
    assert len(web.calls) == 1  # nothing was ever sent to the private address


def test_a_private_address_is_refused_even_when_allowlisted() -> None:
    web = FakeWeb({})
    for url in ("https://inside.example.org/", "https://mixed.example.org/"):
        with pytest.raises(WebFetchError) as refused:
            fetch_page(
                url,
                ON,
                ("example.org",),
                resolve=lambda h: DNS[h],
                connect=web,
            )
        assert refused.value.code == "private_address"
    assert web.calls == []


def test_the_connection_goes_to_the_checked_address() -> None:
    # DNS answers public the first time and private the second (rebinding):
    # the fetch must use the first, checked answer and never look again.
    answers = iter([[PUBLIC], ["10.0.0.9"]])
    web = FakeWeb({("example.org", "/"): _html()})
    fetch_page("https://example.org/", ON, ALLOW, resolve=lambda h: next(answers), connect=web)
    assert web.calls == [("example.org", PUBLIC, "/")]


def test_a_page_is_anchored_to_its_canonical_source(tmp_path: Path) -> None:
    web = FakeWeb(
        {
            ("www.example.org", "/old"): _redirect("https://example.org/guides/shed?utm_source=x"),
            ("example.org", "/guides/shed"): _html(),
        }
    )
    page = _fetch(web, "HTTPS://WWW.Example.org:443/old#top")
    assert page.requested_url == "HTTPS://WWW.Example.org:443/old#top"
    assert page.redirects == ("https://www.example.org/old",)
    assert page.final_url == page.canonical_url == "https://example.org/guides/shed"
    assert page.declared_canonical == "https://example.org/guides/shed"
    document = page.document
    assert document.sha256 and document.format == "html"
    assert document.frontmatter["title"] == "Shed guide"
    kinds = [(b.kind, b.text) for b in document.blocks]
    assert kinds == [
        (BlockKind.HEADING, "Building a shed"),
        (BlockKind.PARAGRAPH, "Use larch cladding."),
        (BlockKind.HEADING, "Roof"),
        (BlockKind.LIST, "Felt"),
        (BlockKind.LIST, "Skylight"),
        (BlockKind.CODE, "  code  "),
    ]
    for block in document.blocks:
        assert document.text[block.start : block.end] == block.text
    assert document.blocks[4].heading_path == ("Building a shed", "Roof")
    assert "ignore" not in document.text and "hidden" not in document.text

    folder = save_snapshot(page, tmp_path)
    assert (folder / "page").read_bytes() == PAGE
    meta = json.loads((folder / "meta.json").read_text("utf-8"))
    assert meta["sha256"] == document.sha256 and meta["canonical_url"] == page.canonical_url
    (folder / "meta.json").write_text("{}", "utf-8")
    assert save_snapshot(page, tmp_path) == folder  # never overwritten
    assert (folder / "meta.json").read_text("utf-8") == "{}"


def test_a_canonical_link_to_another_host_is_not_trusted() -> None:
    body = PAGE.replace(b"https://example.org/guides/shed", b"https://evil.test/x")
    page = _fetch(FakeWeb({("example.org", "/"): _html(body)}), "https://example.org/")
    assert page.declared_canonical is None


@pytest.mark.parametrize(
    ("routes", "url", "code"),
    [
        ({}, "https://other.test/", "host_not_allowed"),
        ({}, "ftp://example.org/", "bad_url"),
        ({}, "https://user:pw@example.org/", "bad_url"),
        ({}, "https://example.org:8443/", "bad_url"),
        ({("example.org", "/"): _html(b"x" * 2000)}, "https://example.org/", "too_large"),
        (
            {("example.org", "/"): _html(b"<p>x</p>", **{"content-length": "999999"})},
            "https://example.org/",
            "too_large",
        ),
        (
            {("example.org", "/"): RawResponse(200, {"content-type": "application/pdf"}, b"%PDF")},
            "https://example.org/",
            "unsupported_type",
        ),
        ({("example.org", "/"): RawResponse(404, {}, b"")}, "https://example.org/", "http_status"),
        ({("example.org", "/"): _redirect("")}, "https://example.org/", "bad_redirect"),
        ({("example.org", "/"): _redirect("/")}, "https://example.org/", "too_many_redirects"),
    ],
)
def test_refusals_have_stable_codes(
    routes: dict[tuple[str, str], RawResponse], url: str, code: str
) -> None:
    with pytest.raises(WebFetchError) as refused:
        _fetch(FakeWeb(routes), url, max_bytes=1000)
    assert refused.value.code == code


def test_nothing_is_fetched_with_egress_off_or_an_empty_allowlist() -> None:
    web = FakeWeb({("example.org", "/"): _html()})
    with pytest.raises(EgressDisabledError):
        fetch_page("https://example.org/", EgressPolicy(), ALLOW, resolve=DNS.get, connect=web)  # type: ignore[arg-type]
    with pytest.raises(WebFetchError, match="web_allowlist"):
        fetch_page("https://example.org/", ON, (), resolve=DNS.get, connect=web)  # type: ignore[arg-type]
    assert web.calls == []


def test_url_helpers() -> None:
    assert (
        canonical_url("http://Example.org:80?b=2&utm_medium=x&a=1#f")
        == "http://example.org/?b=2&a=1"
    )
    assert host_allowed("docs.example.org", ["example.org"])
    assert not host_allowed("badexample.org", ["example.org"])
    assert not host_allowed("example.org.evil.test", ["example.org"])
    assert is_public(PUBLIC)
    for address in (
        "10.1.2.3",
        "192.168.0.1",
        "100.64.0.1",
        "::1",
        "fe80::1",
        "0.0.0.0",
        "224.0.0.1",
    ):
        assert not is_public(address)


def test_the_cli_refuses_without_egress(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(tmp_path / "ws"))
    assert main(["--json", "web", "fetch", "https://example.org/"]) != 0
    result = json.loads(capsys.readouterr().out)
    assert result["error"]["code"] == "egress_off"
