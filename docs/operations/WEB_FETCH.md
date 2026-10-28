# Fetching web pages (INT-001)

`ke web fetch URL [--save]` reads one web page into located blocks, the same shape as a note or a Word file (ING-008). It is off by default and refuses rather than guesses.

## Turning it on

Both are needed, in `ke.toml`:

```toml
web_allowlist = ["docs.python.org", "example.org"]   # a subdomain of an entry counts

[egress]
network_fetch = true
```

## What it refuses (error codes)

| Code | When |
|---|---|
| `egress_off` | `network_fetch` is off. |
| `host_not_allowed` | The host (or any host a redirect leads to) isn't on `web_allowlist`. |
| `private_address` | The host resolves to a loopback, private, link-local, shared (100.64/10), reserved, multicast or unspecified address. If any one of several answers is private, the fetch is refused. |
| `bad_url` | Not http(s), a user name or password in the URL, or a port other than 80/443. |
| `too_many_redirects` | More than 5. |
| `bad_redirect` | A redirect without a `Location`. |
| `too_large` | More than 5 MB, as declared or as read. |
| `unsupported_type` | Not HTML or plain text. |
| `http_status` | Anything but 200 at the end. |
| `dns_failed`, `connection_failed` | The name didn't resolve or the connection failed (the error type only). |

**Why redirects can't reach your network.** Each hop is checked from scratch: allowlist, then DNS, then every address. The connection goes to the address that was checked, with the host name used only for the `Host` header and the TLS certificate check. A DNS answer that changes between the check and the connection (rebinding) therefore can't send the request somewhere private.

## What a fetched page records

- the URL asked for, every redirect, and the final URL;
- the canonical URL (lower-case host, default port and fragment removed, `utm_*`, `fbclid`, `gclid` and similar dropped);
- the page's own `<link rel="canonical">`, only if it names an allowed host;
- the SHA-256 of the exact bytes and the fetch time;
- blocks (headings, paragraphs, list items, quotes, code, table cells), each with offsets into the extracted text and its heading path. Scripts, styles, `<template>`, `<noscript>` and `<svg>` are dropped.

`--save` keeps the exact bytes and the metadata in `<workspace>/web/<sha256>/` (`page`, `meta.json`). The same bytes are stored once and never overwritten.

Page text is data, never instructions: anything that passes it to a model quotes it as untrusted (`docs/operations/SOURCE_AS_DATA.md`).

**Tested without the network.** `tests/integration/test_web_fetch.py` swaps the resolver and the connection for fakes. The real pinned connection (`pinned_connector`) is plain `http.client` with standard certificate checks. It has no automated test, because CI makes no outbound calls.
