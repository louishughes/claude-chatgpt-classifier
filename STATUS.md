# Status

Live ticket status for the build. The full ticket list is `docs/TICKETS.csv` (kept in sync with `docs/ROADMAP_AND_TICKETS.md`); execution order is `docs/plans/DEPENDENCY_MAP.md` §4. A ticket is `VERIFIED` only with real command output recorded in `.agent-history/SESSION_LOG.md`.

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
| ING-003 ImportCoordinator → import_source | VERIFIED (slice I2; `ke import` CLI wiring waits for Louis, see below) | SESSION_LOG 2026-10-27 ING-003 |
| IMP-002 Logical identity resolver | VERIFIED (slice I4: ID collisions and missing IDs become review_required candidates, never merged) | SESSION_LOG 2026-10-27 IMP-002 |
| IMP-004 Transactional idempotent commit, resume and import locking | VERIFIED (repeat + crash rerun in I2; single-writer import lock in I5; checkpoint resume deferred per M1_CONSOLIDATION) | SESSION_LOG 2026-10-27 IMP-004 |
| IMP-003 Message revision and graph delta engine | VERIFIED (slice I3) | SESSION_LOG 2026-10-27 IMP-003 |
| MED-001 Media blob / asset / occurrence model | VERIFIED (slice M1: tables + derived-artefact table, nothing writes it yet) | SESSION_LOG 2026-10-27 MED-001 |
| MED-003 Media dedup and header facts | VERIFIED (slice M1: one blob per byte content, occurrences per revision part, reference/copy modes) | SESSION_LOG 2026-10-27 MED-003 |
| MED-002 Asset pointer resolver | VERIFIED (slice M2: unresolved/missing/ambiguous with evidence; manifest-listed-absent, conversation folders, identical bytes, attachments; real manifest shape to confirm at REV-009) | SESSION_LOG 2026-10-27 MED-002 |
| ING-007 Source integrity reconciliation | VERIFIED (slice I6: raw-JSON counts vs stored counts, fidelity summary, integrity_mismatch warning) | SESSION_LOG 2026-10-27 ING-007 |
| IMP-005 Import audit report | VERIFIED (slice I6: summary block, stored in the ledger, `ke imports report [latest|ID]` JSON and text) | SESSION_LOG 2026-10-27 IMP-005 |

**Next unblocked:** slice R2 (MED-004 image embeds in notes), then R3 (BRW-001 browsing, `ke inspect`), E (EVAL-010). `ke import` itself still waits on Louis (retiring the placeholder test). Order and module layout follow docs/plans/M1_CONSOLIDATION.md (adopted).

**Needs Louis (logged, skipped, not waited on):**
- Wiring `ke import` to `import_source` means retiring `tests/unit/test_cli.py::test_import_is_an_honest_placeholder`, which asserts the placeholder. Changing an existing test needs your OK (guardrail). Until then, imports run through `import_source(...)` in Python.
