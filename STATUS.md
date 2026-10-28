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
| EVAL-010 Batch smoke test (50/100) | IN_PROGRESS (synthetic 50/100 pass, `ke eval smoke`, docs/evaluation/EVAL-010_SMOKE.md; real-data half waits for a session on Louis's PC, REV-009) | SESSION_LOG 2026-10-28 EVAL-010 |

**Next unblocked:** Milestone 2 in plan order: ING-010 + NRM-003 (transcript adapter and offsets), then LNK-001, YTB-001/002, SOC-001/002, REL-002, RET-001, UI-004. The M1 gate still needs the real-data runs and a Windows test run on Louis's PC (one session).

**Needs Louis (logged, skipped, not waited on):**
- Real-data checkpoint: REV-009 (#143) and the real half of EVAL-010 (#39) need a read-only session on your PC: `ke inspect` on a few conversations and `ke eval smoke raw --limit 50` / `--limit 100`. Synthetic runs pass.
- AGENTS.md guardrail 1 still says the owner approves the gold set. Since 00:13 you asked to stay out of tagging, and ADR-0009 and OPEN_DECISIONS now say an independent blind Claude session reviews it. Agents can't edit AGENTS.md themselves, so that one line needs your edit (or your OK in a session that can).
