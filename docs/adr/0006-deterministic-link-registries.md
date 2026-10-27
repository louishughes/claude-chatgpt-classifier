# ADR-0006: Deterministic URL, YouTube and social registries; opt-in transcripts

```yaml
id: ADR-0006
kind: architecture_decision
status: proposed
recorded_at: 2026-10-27
scope: extraction/links
supersedes: []
related_tickets: [LNK-001, YTB-001, YTB-002, YTB-003, SOC-001, SOC-002, SOC-003, EXT-006, INT-002]
```

## Context
YouTube was only covered by `INT-002` (P1, after a web connector), and URL/social detection only by the LLM-based `EXT-006`. That would delay a simple, deterministic capability behind the whole semantic pipeline, and make it depend on a model that can miss or invent links.

## Decision (proposed)
- URL detection is deterministic, runs on canonical text (and structured citation metadata) during the source phase, and records every occurrence with an exact `[start,end)` span, actor and origin. No fetching.
- **YouTube:** a canonicaliser handles `watch`, `youtu.be`, `shorts`, `live`, `embed` and mobile forms, keeping the original URL, `t`/`start`, `list` and channel context. One `YouTubeVideo` per ID, one mention per occurrence. Each new video gets a `TranscriptAcquisition` record in `not_requested`.
- Transcript statuses: `not_requested`, `queued`, `succeeded`, `unavailable`, `permission_required`, `rate_limited`, `failed`. User-supplied transcripts come first (YTB-002). Network providers are a separate, opt-in, rate-limited P1 integration (INT-002) and must never bypass access controls. A transcript is never generated from a title, description or model.
- **Social accounts:** platform URL rules and explicit platform-qualified handles create account mentions. A bare `@name` stays an `ambiguous` candidate. The registry stores platform, stable ID if known, handle, URL, aliases, first/last seen, counts and citing conversations. Detection never authorises crawling, following or contacting anyone.
- EXT-006 consumes these registries instead of re-detecting URLs.

## Alternatives
- Leave everything to an LLM reference extractor: non-deterministic, costly, can't guarantee "every occurrence". Rejected.
- Fetch transcripts automatically on discovery: conflicts with privacy defaults and platform terms. Rejected.

## Consequences
Link registries ship in milestone M2, before any model call. Owner decision OD-07 covers which transcript sources are acceptable.
