# YouTube captions (INT-002)

The engine gets a video's words in one of two ways:

1. **You supply them** (YTB-002): `ke transcript add VIDEO FILE [--language en]` with a `.vtt`, `.srt` or timed text file. Always allowed, no network.
2. **The official YouTube Data API v3**, signed in as you: `ke transcript fetch VIDEO [--language en]`.

There is no third way. The engine never scrapes the watch page, never calls the unofficial `timedtext` endpoint and never uses a third-party downloader.

## Switching it on

Both are needed, and both are off by default:

- `transcript_fetch = true` under `[egress]` in `ke.toml` (or `KE_EGRESS__TRANSCRIPT_FETCH=true`);
- `KE_YOUTUBE_ACCESS_TOKEN`: an OAuth access token for your Google account with a YouTube scope (for example `youtube.force-ssl`). Environment only. It is never written to `ke.toml`, the database, a log or an error message.

## Why it often says "permission required"

YouTube lets `captions.download` fetch a track only for videos the signed-in account may edit, which usually means your own uploads. For anyone else's video the answer is 403, recorded as `permission_required` with the reason. Use `ke transcript add` with captions you are allowed to use instead.

## What gets recorded

| YouTube's answer | Status | Retried? |
|---|---|---|
| a track downloaded | `succeeded`, cues stored | no |
| no caption tracks | `unavailable` | no |
| 404 | `unavailable` | no |
| 401 / 403 | `permission_required` | no |
| 429, `quotaExceeded`, `rateLimitExceeded`, `userRateLimitExceeded` | `rate_limited`, then `failed` after 3 tries | yes, at most 3 tries in all |
| anything else | `failed` with the HTTP status | no |

Calls are at least 1 second apart. A failed or refused fetch never removes a transcript you already have, and nothing is invented: without a downloaded track there are no cues.

**Which track.** The language you asked for first, then a human-made track over an automatic one. An automatic (ASR) track is accepted, but its snapshot's provenance says `machine_generated: yes` and `track_kind: asr`, next to the caption track ID and the API used.

**Tested without the network.** `tests/integration/test_youtube_captions.py` replaces the HTTP call with a fake YouTube. The real call is plain `urllib` with default certificate checks and has no automated test, because CI makes no outbound calls.
