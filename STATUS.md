# Status

Live ticket status for the build. The original ticket list is `docs/TICKETS.csv` with `docs/ROADMAP_AND_TICKETS.md` (both frozen reference since REV-006; new tickets are GitHub Issues); execution order is `docs/plans/DEPENDENCY_MAP.md` §4. A ticket is `VERIFIED` only with real command output recorded in `.agent-history/SESSION_LOG.md`.

**Milestone:** M1 source-fidelity slice (no AI, no network). **Branches:** one small PR per slice from `main` (two tickets at most, REV-005); module layout per `docs/plans/M1_CONSOLIDATION.md`. `docs/TICKETS.csv` is frozen reference; status lives here and in GitHub Issues.

| Ticket | Status | Evidence |
|---|---|---|
| FND-001 Bootstrap Python repository and tool configuration | VERIFIED | SESSION_LOG 2026-10-27 FND-001 |
| FND-002 Environment and settings manager | VERIFIED | SESSION_LOG 2026-10-27 FND-002 |
| FND-003 Relational persistence interface and SQLite engine | VERIFIED | SESSION_LOG 2026-10-27 FND-003 |
| FND-004 Alembic migration baseline | VERIFIED | SESSION_LOG 2026-10-27 FND-004 |
| FND-005 Domain models and stable identifiers | VERIFIED (scope note: Segment/KnowledgeRecord deferred to M3) | SESSION_LOG 2026-10-27 FND-005 |
| EVAL-009 Synthetic source-fidelity fixture suite and scale generator | VERIFIED (M2 link/YouTube/social cases deferred to their tickets) | SESSION_LOG 2026-10-27 EVAL-009 |
| FND-006 Processing jobs and fingerprint keys | VERIFIED | SESSION_LOG 2026-10-27 FND-006 |
| FND-008 CLI skeleton and error/exit contracts | VERIFIED | SESSION_LOG 2026-10-27 FND-008 |
| OPS-008 Raw/private data Git guard and fixture redaction check | VERIFIED | SESSION_LOG 2026-10-27 OPS-008 |
| SRC-001 Read-only raw source inventory and guard | VERIFIED | SESSION_LOG 2026-10-27 SRC-001 |
| DOC-002 Deterministic Markdown/YAML renderer | VERIFIED | SESSION_LOG 2026-10-27 DOC-002 |
| ING-005 ChatGPT message-graph parsing | VERIFIED (slice G1: pure ConversationGraph; branch kinds and integrity issues come in G2) | SESSION_LOG 2026-10-27 ING-005 |
| REL-001 Native branch classification and path enumeration | VERIFIED (slice G2) | SESSION_LOG 2026-10-27 REL-001 |
| NRM-002 Conversation graph integrity checker | VERIFIED (slice G2) | SESSION_LOG 2026-10-27 NRM-002 |
| ING-006 ChatGPT content and attachment parser | VERIFIED (slice G3) | SESSION_LOG 2026-10-27 ING-006 |
| NRM-001 Canonical node normalization contract | VERIFIED (slice G3) | SESSION_LOG 2026-10-27 NRM-001 |
| ING-002 SourceAdapter protocol and import manifests | VERIFIED (slice A1; the stored ImportManifest is part of IMP-001/IMP-005) | SESSION_LOG 2026-10-27 ING-002 |
| ING-004 ChatGPT ZIP layout discovery | VERIFIED (slice A1; JSON is loaded per file within the size limit, not streamed) | SESSION_LOG 2026-10-27 ING-004 |
| ING-011 ChatGPT split-wrapper directory adapter | VERIFIED (slice A2) | SESSION_LOG 2026-10-27 ING-011 |
| ING-001 Secure archive storage and checksums | VERIFIED (slice I1) | SESSION_LOG 2026-10-27 ING-001 |
| IMP-001 ImportBatch and source-file snapshot ledger | VERIFIED (slice I1) | SESSION_LOG 2026-10-27 IMP-001 |
| ING-003 ImportCoordinator → import_source | VERIFIED (slice I2; `ke import` wired in UI-002) | SESSION_LOG 2026-10-27 ING-003 |
| IMP-002 Logical identity resolver | VERIFIED (slice I4: ID collisions and missing IDs become review_required candidates, never merged) | SESSION_LOG 2026-10-27 IMP-002 |
| IMP-004 Transactional idempotent commit, resume and import locking | VERIFIED (repeat + crash rerun in I2; single-writer import lock in I5; checkpoint resume deferred per M1_CONSOLIDATION) | SESSION_LOG 2026-10-27 IMP-004 |
| IMP-003 Message revision and graph delta engine | VERIFIED (slice I3) | SESSION_LOG 2026-10-27 IMP-003 |
| MED-001 Media blob / asset / occurrence model | VERIFIED (slice M1: tables + derived-artefact table, nothing writes it yet) | SESSION_LOG 2026-10-27 MED-001 |
| MED-003 Media dedup and header facts | VERIFIED (slice M1: one blob per byte content, occurrences per revision part, reference/copy modes) | SESSION_LOG 2026-10-27 MED-003 |
| MED-002 Asset pointer resolver | VERIFIED (slice M2: unresolved/missing/ambiguous with evidence; manifest-listed-absent, conversation folders, identical bytes, attachments; real manifest shape to confirm at REV-009) | SESSION_LOG 2026-10-27 MED-002 |
| ING-007 Source integrity reconciliation | VERIFIED (slice I6: raw-JSON counts vs stored counts, fidelity summary, integrity_mismatch warning) | SESSION_LOG 2026-10-27 ING-007 |
| IMP-005 Import audit report | VERIFIED (slice I6: summary block, stored in the ledger, `ke imports report [latest|ID]` JSON and text) | SESSION_LOG 2026-10-27 IMP-005 |
| MED-004 Vault media embeds and missing markers | VERIFIED (slice R2: verified copies at _attachments/<2hex>/<sha>.<ext>, warning markers with pointer + reason, check_embeds link checker) | SESSION_LOG 2026-10-28 MED-004 |
| BRW-001 Source browser and transcript notes | VERIFIED (slice R3: transcript from stored records, labelled branches, per-message anchors, image embeds; `ke inspect [ID] [--note VAULT]` counts only) | SESSION_LOG 2026-10-28 BRW-001 |
| UI-001 `ke ui` local web interface: home and import reports | VERIFIED (loopback-only server, Host check, CSP, autoescaped Jinja2 pages, plain-words report) | SESSION_LOG 2026-10-28 UI-001 |
| UI-002 Import from the browser (and `ke import`) | VERIFIED (Import page with form token + Origin check, background job with self-refreshing progress page, plain failure reasons; `ke import SOURCE [--account] [--format] [--partial]`; placeholder test replaced by real tests) | SESSION_LOG 2026-10-28 UI-002 |
| UI-003 Chat, branch and image browser | VERIFIED (/chats list with title search and paging; /chats/<id> active path, labelled branches with links to where they leave, outside-tree messages, images inline or missing markers with reasons; /media/<sha> re-hashes before serving; shares transcript_sections with the notes, output byte-identical on all fixtures) | SESSION_LOG 2026-10-28 UI-003 |
| NRM-003 Canonical source offset and quote hashing | VERIFIED (slice T1: half-open code-point spans, ke-quote-v1 hash, cite/verify, UTF-16/UTF-8 converters; Hypothesis round trip) | SESSION_LOG 2026-10-28 NRM-003 |
| ING-010 Transcript adapter with timestamps | VERIFIED (slice T1: VTT/SRT/text cues, exact ms or None, <v> speakers only, out-of-order/reversed/unreadable timing kept and warned, sha256 + source_url + language; nothing fetched) | SESSION_LOG 2026-10-28 ING-010 |
| LNK-001 URL occurrence extraction and link registry | VERIFIED (slice L1: link_targets + link_occurrences, migration 0009; exact code-point spans after trimming prose/Markdown/angle brackets; citation metadata by list position; canonical URL keeps the query, drops the fragment; never fetched; reimport adds 0) | SESSION_LOG 2026-10-28 LNK-001 |
| YTB-001 YouTube canonicaliser and video registry | VERIFIED (slice Y1: watch/youtu.be/shorts/live/embed/v/mobile/music/nocookie forms, exact-host check against lookalikes, t/start/#t, list, ab_channel; youtube_videos + youtube_mentions keyed by link occurrence, migration 0010; transcript_status starts not_requested) | SESSION_LOG 2026-10-28 YTB-001 |
| YTB-002 Transcript acquisition jobs, status and user-supplied transcripts | VERIFIED (slice Y2: transcript_acquisitions/snapshots/cues, migration 0011; transcript_fetch switch gates every provider call; bounded retries for rate_limited/failed, unavailable/permission_required final; user-supplied VTT/SRT/text attach with provenance, archived bytes, idempotent; `ke transcript add|status`; no provider built in, needs INT-002) | SESSION_LOG 2026-10-28 YTB-002 |
| LEG-001 Old-failure regression fixtures for the importer | VERIFIED (fixture legacy_regressions: interleaved edit+regen timestamps, same-title chats, short replies, code + execution_output numbering, image occurrence, unreferenced image file; 7 tests citing previous-attempts-review §2a) | SESSION_LOG 2026-10-28 LEG-001 |
| SOC-001 Social account mention detection | VERIFIED (links/social.py: profile URLs for 13 platforms incl. stable IDs, platform-qualified handles, Fediverse addresses; bare @handle stays ambiguous; emails, decorators, code and non-profile URLs excluded) | SESSION_LOG 2026-10-28 SOC |
| SOC-002 Social account registry, aliases and review | VERIFIED (social_accounts/account_aliases/account_mentions, migration 0012; one account across URL + handle; ambiguous never auto-links; reimport adds 0 mentions; `ke accounts [--platform] [--ambiguous]`) | SESSION_LOG 2026-10-28 SOC |
| REL-002 Cross-conversation relationship model and structural detectors | VERIFIED (relationships/store.py + detect.py, migration 0013 with append-only triggers; shared node IDs, copied prefix, chatgpt.com links, verbatim quotes; all candidates; fixtures copied_prefix + similar_unrelated; `ke related list/review/detect`) | SESSION_LOG 2026-10-28 REL-002 |
| RET-001 SQLite FTS5 lexical index and search | VERIFIED (retrieval/lexical.py: separate rebuildable index file, one row per revision with workspace/conversation/node; tokens, phrase and exact modes; query words always quoted; fixture search_terms, 12 queries; `ke search`) | SESSION_LOG 2026-10-28 RET-001 |
| EVAL-010 Batch smoke test (50/100) | IN_PROGRESS (synthetic 50/100 pass, `ke eval smoke`, docs/evaluation/EVAL-010_SMOKE.md; real-data half waits for a session on Louis's PC, REV-009) | SESSION_LOG 2026-10-28 EVAL-010 |

**Next unblocked:** Milestone 2 in plan order: UI-004. The M1 gate still needs the real-data runs and a Windows test run on Louis's PC (one session).

**Needs Louis (logged, skipped, not waited on):**
- Real-data checkpoint: REV-009 (#143) and the real half of EVAL-010 (#39) need a read-only session on your PC: `ke inspect` on a few conversations and `ke eval smoke raw --limit 50` / `--limit 100`. Synthetic runs pass.
- AGENTS.md guardrail 1 still says the owner approves the gold set. Since 00:13 you asked to stay out of tagging, and ADR-0009 and OPEN_DECISIONS now say an independent blind Claude session reviews it. Agents can't edit AGENTS.md themselves, so that one line needs your edit (or your OK in a session that can).
