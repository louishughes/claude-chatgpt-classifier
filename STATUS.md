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

**Next unblocked:** slice G3 (ING-006 + NRM-001), slice I1 (ING-001 + IMP-001). Order and module layout follow docs/plans/M1_CONSOLIDATION.md (adopted).
