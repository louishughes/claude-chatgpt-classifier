# Roadmap and Dependency-Ordered Engineering Backlog

> **FROZEN REFERENCE (2026-10-27, REV-006).** Live tickets are GitHub Issues: milestone maps #4–#9, tickets #10–#132. This file and `docs/TICKETS.csv` are no longer updated; status, scope and blockers live in the issues. See `docs/agents/issue-tracker.md`. (No banner row was added to the CSV because a comment row would break standard CSV readers.)
**Status:** planned; not implemented. **Ticket count:** 122 (93 original + 29 added by the 2026-10-27 specification audit). Tickets are ordered in this file so all blockers precede their dependents; this file order is **not** the execution order. Execution order, milestones and the first vertical slice are in `docs/plans/IMPLEMENTATION_PLAN.md` and `docs/plans/DEPENDENCY_MAP.md`.

> **Tracker note (audit 2026-10-27):** `docs/agents/issue-tracker.md` names GitHub Issues as the tracker of record and calls this file and `TICKETS.csv` legacy reference. The audit work order required them to be updated in sync, so they were. Which source is authoritative going forward is open decision OD-08 in `docs/reviews/OPEN_DECISIONS.md`.

## Phase gates
| Phase | Gate |
|---|---|
| Foundation | Packages, schema and stage contracts validated on a clean machine |
| Ingestion | Immutable source and full-fidelity branch-aware, idempotent import |
| Source identity, media and links *(added 2026-10-27)* | Gate G1: read-only raw import, logical identity, branch kinds, media occurrences, zero-duplicate reimport, delta report, source browsing and 50/100-conversation smoke (EVAL-010). Gate G2: URL/YouTube/social registries and structural relationship candidates, all LLM-free |
| Normalisation | Stable canonical nodes/segments/evidence anchors |
| Taxonomy | Published controlled vocabulary and review process |
| Classification | Approved labels only and order-independent identifiers |
| Extraction | Evidence backed typed records and actor validation |
| Reconciliation | Correct project history and current-state projection |
| Retrieval | Exact/semantic/structured citation-grounded search |
| Documents | Obsidian notes and living masters with safe regeneration |
| Relationships and registries (late) *(added 2026-10-27)* | Semantic relatedness, relationship review in notes/retrieval, transcript cue linking, account registry notes, correction survival |
| Evaluation | Golden baseline and bounded release gates |
| API | Typed endpoints and testable provider/storage overrides |
| Operations | Restore/security/release and deletion verification |
| Productisation | Hosted/multi-user rights isolation; deferred until trusted MVP |
| Integrations | Other documents/web/video and watched sources |

## Dependency map
Ticket dependency chains are defined per ticket below and in `TICKETS.csv`. Critical path begins `FND-001 → FND-003 → ING-001 → ING-002 → ING-004 → ING-005 → NRM-001 → NRM-004 → TAX-001/TAX-002 → CLS-001 → EXT-001/EXT-002 → REC-004/REC-005/REC-006 → DOC-004 / RET-007`. Dependency IDs are implementation blockers, not vague associations.

**Audit amendment (2026-10-27):** the original critical path above went through taxonomy and LLM extraction before anything could be browsed. The revised plan puts a source-fidelity slice first (critical path `FND-001 → FND-003 → ING-001 → IMP-001 → ING-003 → … → IMP-004 → IMP-005 → BRW-001`, full chain in `docs/plans/DEPENDENCY_MAP.md`). The original path is kept for history and still describes the semantic milestone.

## Phase: Foundation

### FND-001 — Bootstrap Python repository and tool configuration
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** None.
**Objective:** Create pyproject.toml, src-layout package, baseline ruff/pytest/mypy settings and Git ignore.
**Audit amendment (2026-10-27):** Add docs/CODE_STYLE.md defining the learning-friendly comment standard (module/class docstrings that explain what and why in plain English, why-comments on invariants, a short 'Talking points' block per module) and a ruff/docstring check for public functions; see IMPLEMENTATION_PLAN section 11.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: create pyproject.toml, src-layout package, baseline ruff/pytest/mypy settings and Git ignore.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Fresh venv installs and imports package**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Fresh venv installs and imports package. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### FND-002 — Environment and settings manager
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `FND-001`.
**Objective:** Define Pydantic Settings for workspace root, model egress default off, file-size limits and budgets.
**Audit amendment (2026-10-27):** Add per-capability egress policy (text_llm, vision, network_fetch, transcript_fetch), read-only raw root(s), media storage mode (copy or reference) and account namespace settings; see ADR-0007.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: define Pydantic Settings for workspace root, model egress default off, file-size limits and budgets.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Config tests reject invalid limits and never reveal secrets**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Config tests reject invalid limits and never reveal secrets. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### FND-003 — Relational persistence interface and SQLite engine
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `FND-001`, `FND-002`.
**Objective:** Implement SessionFactory, WorkspaceRepo and transaction scope with WAL/foreign keys.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: implement SessionFactory, WorkspaceRepo and transaction scope with WAL/foreign keys.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Temporary SQLite round-trip and rollback test**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Temporary SQLite round-trip and rollback test. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### FND-004 — Alembic migration baseline
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `FND-003`.
**Objective:** Create initial schema migration with constraints, indexes and downgrade/upgrade checks.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: create initial schema migration with constraints, indexes and downgrade/upgrade checks.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Upgrade empty DB twice and verify schema**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Upgrade empty DB twice and verify schema. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### FND-005 — Domain models and stable identifiers
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `FND-001`.
**Objective:** Implement SourceArtifact, Snapshot, ContentNode, EvidenceRef, Segment, KnowledgeRecord, enum contracts.
**Audit amendment (2026-10-27):** Stable-ID helpers must cover workspace/source-system/account namespace, logical conversation, message node, message revision, media blob/asset/occurrence, link/video/account and relationship IDs; see ADR-0003.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: implement SourceArtifact, Snapshot, ContentNode, EvidenceRef, Segment, KnowledgeRecord, enum contracts.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Pydantic validation and deterministic ID property tests**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Pydantic validation and deterministic ID property tests. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### FND-006 — Processing jobs and fingerprint keys
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `FND-003`, `FND-005`.
**Objective:** Create JobRepository, stage idempotency-key calculator, state transitions and persistent checkpoints.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: create JobRepository, stage idempotency-key calculator, state transitions and persistent checkpoints.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Same inputs produce cache hit, changed version creates new key**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Same inputs produce cache hit, changed version creates new key. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### FND-007 — Model-provider protocol and fake provider
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `FND-002`, `FND-005`.
**Objective:** Define StructuredModelProvider with version/cost metadata, mock/replay adapter and optional configured remote adapter.
**Audit amendment (2026-10-27):** Protocol must declare capability (text_llm, embedding, vision) and structured-output schema per call so FND-009 can enforce egress and validation.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: define StructuredModelProvider with version/cost metadata, mock/replay adapter and optional configured remote adapter.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Offline tests run without network and reject invalid provider responses**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Offline tests run without network and reject invalid provider responses. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### FND-008 — CLI skeleton and error/exit contracts
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `FND-002`, `FND-006`.
**Objective:** Build ke CLI with status/import placeholders, stable JSON and text output modes, exit codes.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: build ke CLI with status/import placeholders, stable JSON and text output modes, exit codes.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **CLI help and invalid invocation tests**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** CLI help and invalid invocation tests. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### FND-009 — Structured-output model provider adapter and egress policy
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `FND-007`, `FND-006`.
**Objective:** Implement real provider adapter(s) behind the provider protocol with JSON-schema structured output generated from Pydantic DTOs, schema validation, one bounded repair attempt then review_required, pinned model/prompt versions, per-capability egress policy, timeouts and a cost ledger.
**Origin:** added by the Audit 2026-10-27 specification audit; see `docs/reviews/SPEC_CHANGELOG.md`.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: implement real provider adapter(s) behind the provider protocol with JSON-schema structured output generated from Pydantic DTOs, schema validation, one bounded repair attempt then review_required, pinned model/prompt versions, per-capability egress policy, timeouts and a cost ledger.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Invalid provider JSON is rejected and never persisted; an egress-disabled capability fails before any network call; an identical stage key is served from cache with zero provider calls**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Invalid provider JSON is rejected and never persisted; an egress-disabled capability fails before any network call; an identical stage key is served from cache with zero provider calls. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### OPS-008 — Raw/private data Git guard and fixture redaction check
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `FND-001`.
**Objective:** Add automated checks that raw/ and private workspace paths are ignored and untracked, and that committed fixtures carry a synthetic/sanitised marker.
**Origin:** added by the Audit 2026-10-27 specification audit; see `docs/reviews/SPEC_CHANGELOG.md`.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: add automated checks that raw/ and private workspace paths are ignored and untracked, and that committed fixtures carry a synthetic/sanitised marker.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Check fails when a raw/ file is staged or a fixture lacks the synthetic marker; passes on a clean tree**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Check fails when a raw/ file is staged or a fixture lacks the synthetic marker; passes on a clean tree. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### EVAL-009 — Synthetic source-fidelity fixture suite and scale generator
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `FND-001`.
**Objective:** Create versioned synthetic fixtures: official export (single and sharded JSON, ZIP and extracted folder), split-wrapper directory, edit/regenerate branches, repeated image, missing/ambiguous asset, export v1 to v2 delta, ID collision, URL/YouTube/social cases, similar-but-unrelated and copied-prefix conversations, plus a seeded generator for 50/100/1,000-conversation batches.
**Origin:** added by the Audit 2026-10-27 specification audit; see `docs/reviews/SPEC_CHANGELOG.md`.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: create versioned synthetic fixtures: official export (single and sharded JSON, ZIP and extracted folder), split-wrapper directory, edit/regenerate branches, repeated image, missing/ambiguous asset, export v1 to v2 delta, ID collision, URL/YouTube/social cases, similar-but-unrelated and copied-prefix conversations, plus a seeded generator for 50/100/1,000-conversation batches.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Fixture manifest documents expected counts and delta categories per case; generator is deterministic for a fixed seed; no real private data**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Fixture manifest documents expected counts and delta categories per case; generator is deterministic for a fixed seed; no real private data. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

## Phase: Ingestion

### ING-001 — Secure archive storage and checksums
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `FND-003`, `FND-005`.
**Objective:** Store byte-identical content-addressed input with SHA256 and immutability checks.
**Audit amendment (2026-10-27):** raw/ is opened read-only and never written; snapshots support copy or hash-verified reference-in-place for large media (OPEN_DECISIONS OD-02).
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: store byte-identical content-addressed input with SHA256 and immutability checks.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Checksum corruption and overwrite-rejection fixtures**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Checksum corruption and overwrite-rejection fixtures. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### SRC-001 — Read-only raw source inventory and guard
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `FND-002`, `FND-005`, `FND-008`.
**Objective:** Inventory a configured raw root (directory or ZIP) metadata-only: file types, counts, sizes, hashes and format detection (official export, split-wrapper, export manifest, derived artefacts, media) using read-only access and pre/post tree-hash verification; no private text in output.
**Origin:** added by the Audit 2026-10-27 specification audit; see `docs/reviews/SPEC_CHANGELOG.md`.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: inventory a configured raw root (directory or ZIP) metadata-only: file types, counts, sizes, hashes and format detection (official export, split-wrapper, export manifest, derived artefacts, media) using read-only access and pre/post tree-hash verification; no private text in output.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Fixture raw tree is byte-identical before and after inventory; report redacts names by default; derived non-conversation JSON and unknown files are classified, not parsed as conversations**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Fixture raw tree is byte-identical before and after inventory; report redacts names by default; derived non-conversation JSON and unknown files are classified, not parsed as conversations. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### ING-002 — SourceAdapter protocol and import manifests
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `FND-005`, `ING-001`.
**Objective:** Define probe/parse/fidelity ports, structured ImportWarning, ImportManifest and adapter registry.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: define probe/parse/fidelity ports, structured ImportWarning, ImportManifest and adapter registry.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Fake adapter contract and unsupported format response**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Fake adapter contract and unsupported format response. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### IMP-001 — ImportBatch and source-file snapshot ledger
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `ING-001`, `FND-006`.
**Objective:** Record every import attempt as an ImportBatch with input root, per-file SHA-256, adapter/parser versions, status, checkpoints and diagnostics; identical file bytes reuse the existing SourceSnapshot.
**Origin:** added by the Audit 2026-10-27 specification audit; see `docs/reviews/SPEC_CHANGELOG.md`.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: record every import attempt as an ImportBatch with input root, per-file SHA-256, adapter/parser versions, status, checkpoints and diagnostics; identical file bytes reuse the existing SourceSnapshot.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Same input imported twice yields two batches, one snapshot per distinct file hash and zero new logical records; an interrupted batch is resumable and never reported as succeeded**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Same input imported twice yields two batches, one snapshot per distinct file hash and zero new logical records; an interrupted batch is resumable and never reported as succeeded. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### ING-003 — ImportCoordinator and source deduplication
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `ING-002`, `FND-006`, `IMP-001`.
**Objective:** Create atomic batch import, snapshot comparison, source ID mapping and resume checkpoints.
**Audit amendment (2026-10-27):** Scope narrowed to orchestration and snapshot-level dedup; logical identity, revisions, locking and delta reporting move to IMP-001..IMP-005. Now blocked by IMP-001. Dependencies were `ING-002;FND-006`, now `ING-002;FND-006;IMP-001`.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: create atomic batch import, snapshot comparison, source ID mapping and resume checkpoints.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Reimport same source 3 times adds zero logical copies**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Reimport same source 3 times adds zero logical copies. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### ING-004 — ChatGPT ZIP layout discovery
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `ING-001`, `ING-002`.
**Objective:** Locate conversations.json or numbered parts, reject path traversal/oversized entry and track asset inventory.
**Audit amendment (2026-10-27):** Also accept an extracted export directory, sharded conversations-NNN.json, export manifests, per-conversation asset folders, user-*/ and dalle-generations/ asset folders; stream JSON rather than loading whole files.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: locate conversations.json or numbered parts, reject path traversal/oversized entry and track asset inventory.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Multiple ZIP layouts, malicious filenames and unknown files**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Multiple ZIP layouts, malicious filenames and unknown files. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### ING-005 — ChatGPT message-graph parsing
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `ING-004`, `FND-005`.
**Objective:** Parse mapping nodes, actor metadata, parent/child links, current_node and active ancestor path.
**Audit amendment (2026-10-27):** Real data lacks children arrays: derive children from parent links; tolerate null-message root nodes; branch-kind classification lives in REL-001.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: parse mapping nodes, actor metadata, parent/child links, current_node and active ancestor path.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Branching/regenerated fixture preserves every node without fabricated chronology**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Branching/regenerated fixture preserves every node without fabricated chronology. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### ING-006 — ChatGPT content and attachment parser
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `ING-005`.
**Objective:** Extract text/code/tool/other content variants and attach asset pointers; retain unknown payload.
**Audit amendment (2026-10-27):** Cover observed content types (text, code, multimodal_text, thoughts, reasoning_recap, user_editable_context, tether_quote, tether_browsing_display, execution_output) and asset pointer schemes file-service:// and sediment://; hidden/reasoning/system content is flagged, never dropped.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: extract text/code/tool/other content variants and attach asset pointers; retain unknown payload.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Unknown content round-trips and missing asset gets explicit warning**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Unknown content round-trips and missing asset gets explicit warning. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### ING-011 — ChatGPT split-wrapper directory adapter
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `ING-002`, `ING-005`.
**Objective:** Parse per-conversation wrapper JSON (wrapper fields plus embedded native conversation object) through the native mapping parser; report wrapper/native disagreements, absent standard fields and non-conversation JSON as fidelity warnings.
**Origin:** added by the Audit 2026-10-27 specification audit; see `docs/reviews/SPEC_CHANGELOG.md`.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: parse per-conversation wrapper JSON (wrapper fields plus embedded native conversation object) through the native mapping parser; report wrapper/native disagreements, absent standard fields and non-conversation JSON as fidelity warnings.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Split-format fixture yields the same logical conversations and nodes as the equivalent official-export fixture; count-mismatch and derived-file fixtures produce warnings, not records**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Split-format fixture yields the same logical conversations and nodes as the equivalent official-export fixture; count-mismatch and derived-file fixtures produce warnings, not records. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### ING-007 — ChatGPT import integrity and audit manifest
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `ING-003`, `ING-005`, `ING-006`.
**Objective:** Compare source raw counts to canonical node/assets, record unsupported fields and fidelity summary.
**Audit amendment (2026-10-27):** Fidelity summary feeds the IMP-005 delta report and must count wrapper/native disagreements for the split-wrapper format.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: compare source raw counts to canonical node/assets, record unsupported fields and fidelity summary.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Fixture inventories reconcile and omissions never silent**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Fixture inventories reconcile and omissions never silent. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### ING-008 — Markdown/plain text adapter
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `ING-002`.
**Objective:** Read Markdown frontmatter/blocks and plain text with stable locators and encoding fallbacks.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: read Markdown frontmatter/blocks and plain text with stable locators and encoding fallbacks.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Frontmatter and Unicode fixtures preserve headings and offsets**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Frontmatter and Unicode fixtures preserve headings and offsets. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### ING-009 — Structured file adapter foundation
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `ING-002`.
**Objective:** Wrap Docling conversion behind DocumentAdapter with heading/table references, asset and extraction warnings.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: wrap Docling conversion behind DocumentAdapter with heading/table references, asset and extraction warnings.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **DOCX/PDF fixtures show provenance and unsupported extraction warnings**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** DOCX/PDF fixtures show provenance and unsupported extraction warnings. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### ING-010 — Transcript adapter with timestamps
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `ING-002`.
**Objective:** Parse VTT/SRT/text cues preserving exact timing, speaker where available and source URL.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: parse VTT/SRT/text cues preserving exact timing, speaker where available and source URL.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Out-of-order/missing timestamps represented without fabricated timing**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Out-of-order/missing timestamps represented without fabricated timing. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

## Phase: Normalisation

### NRM-001 — Canonical node normalization contract
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `ING-005`, `FND-005`.
**Objective:** Normalize roles/timestamps/text parts into ContentNode while retaining original raw pointer.
**Audit amendment (2026-10-27):** Define canonical-content hash (role + content parts + create_time) separately from raw-payload hash so cosmetic metadata drift does not invalidate derivatives (ADR-0003).
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: normalize roles/timestamps/text parts into ContentNode while retaining original raw pointer.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Canonicalization is repeatable and doesn't change source payload**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Canonicalization is repeatable and doesn't change source payload. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### NRM-002 — Conversation graph integrity checker
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `NRM-001`.
**Objective:** Detect missing parents, cycles, duplicate native IDs and disconnected nodes without discarding content.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: detect missing parents, cycles, duplicate native IDs and disconnected nodes without discarding content.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Adversarial branch graph produces explicit errors**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Adversarial branch graph produces explicit errors. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### NRM-003 — Canonical source offset and quote hashing
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `NRM-001`.
**Objective:** Establish immutable Unicode-text offset convention and quote hash helper.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: establish immutable Unicode-text offset convention and quote hash helper.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Emoji/newlines/Unicode round-trip substrings exactly**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Emoji/newlines/Unicode round-trip substrings exactly. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### NRM-004 — Topical segment proposal algorithm
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `NRM-001`, `NRM-002`.
**Objective:** Build segmenter with message-contiguous boundaries, context windows and sensible fallbacks.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: build segmenter with message-contiguous boundaries, context windows and sensible fallbacks.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Annotated multi-topic boundaries measured and source coverage preserved**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Annotated multi-topic boundaries measured and source coverage preserved. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### NRM-005 — Manual split/merge with immutable provenance
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `NRM-004`.
**Objective:** Support reviewer overrides, lineage for segment versions and revalidation after edits.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: support reviewer overrides, lineage for segment versions and revalidation after edits.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Split+merge doesn't lose source nodes; overrides survive rerun**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Split+merge doesn't lose source nodes; overrides survive rerun. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### NRM-006 — Corpus sampling and segment inventory
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `NRM-004`, `ING-007`.
**Objective:** Collect representative segment text and corpus summary without changing classifications.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: collect representative segment text and corpus summary without changing classifications.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Sampling deterministic for fixed seed and contains rare themes**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Sampling deterministic for fixed seed and contains rare themes. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

## Phase: Source identity, media and links

Added by the specification audit (2026-10-27). These tickets, together with SRC-001, IMP-001, ING-011, MED-004 and BRW-001, form the first vertical slice: read-only raw import, provenance, native branch graph, image linkage, reimport idempotency and source browsing, before any LLM stage. See `docs/plans/IMPLEMENTATION_PLAN.md`.

### REL-001 — Native branch classification and path enumeration
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `ING-005`, `NRM-002`.
**Objective:** Derive children from parent links when absent, identify the active/default path from current_node, classify sibling forks as edit (user siblings), regeneration (assistant siblings) or other, and expose alternate paths without flattening.
**Origin:** added by the Audit 2026-10-27 specification audit; see `docs/reviews/SPEC_CHANGELOG.md`.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: derive children from parent links when absent, identify the active/default path from current_node, classify sibling forks as edit (user siblings), regeneration (assistant siblings) or other, and expose alternate paths without flattening.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Edited-prompt and regenerated-answer fixtures produce correct branch kinds; no rendered or indexed transcript splices competing siblings**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Edited-prompt and regenerated-answer fixtures produce correct branch kinds; no rendered or indexed transcript splices competing siblings. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### IMP-002 — Logical identity resolver for conversations, messages and assets
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `FND-005`, `IMP-001`.
**Objective:** Resolve stable logical IDs native-ID-first within (workspace, source system, account namespace); handle missing or colliding native IDs by creating review_required candidate matches; never match on title, timestamp, text similarity or visual resemblance.
**Origin:** added by the Audit 2026-10-27 specification audit; see `docs/reviews/SPEC_CHANGELOG.md`.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: resolve stable logical IDs native-ID-first within (workspace, source system, account namespace); handle missing or colliding native IDs by creating review_required candidate matches; never match on title, timestamp, text similarity or visual resemblance.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Same conversation across two exports maps to one logical ID; two conversations with identical titles stay distinct; an ID collision with different content creates a candidate match, not a merge**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Same conversation across two exports maps to one logical ID; two conversations with identical titles stay distinct; an ID collision with different content creates a candidate match, not a merge. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### IMP-003 — Message revision and graph delta engine
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `IMP-002`, `ING-005`, `NRM-001`.
**Objective:** Classify each conversation, node and edge per import as new, unchanged, revised, new_branch or not_seen using raw-payload and canonical-content hashes; store immutable revisions; record not_seen as unknown, never deleted.
**Origin:** added by the Audit 2026-10-27 specification audit; see `docs/reviews/SPEC_CHANGELOG.md`.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: classify each conversation, node and edge per import as new, unchanged, revised, new_branch or not_seen using raw-payload and canonical-content hashes; store immutable revisions; record not_seen as unknown, never deleted.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Fixture v1 to v2 (added messages, edited message, regenerated branch, absent conversation) reports exact categories; unchanged content triggers zero derived-stage invalidations; the absent conversation stays present as not_seen_in_latest**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Fixture v1 to v2 (added messages, edited message, regenerated branch, absent conversation) reports exact categories; unchanged content triggers zero derived-stage invalidations; the absent conversation stays present as not_seen_in_latest. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### IMP-004 — Transactional idempotent commit, resume and import locking
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `IMP-003`, `ING-003`.
**Objective:** Commit import batches atomically with DB uniqueness on logical keys, idempotency keys, a single-writer import lock and checkpoint resume so concurrent or repeated imports cannot create duplicates.
**Origin:** added by the Audit 2026-10-27 specification audit; see `docs/reviews/SPEC_CHANGELOG.md`.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: commit import batches atomically with DB uniqueness on logical keys, idempotency keys, a single-writer import lock and checkpoint resume so concurrent or repeated imports cannot create duplicates.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Property test: N repeated or concurrent imports of the same fixture produce identical logical record counts; a crash injected mid-batch resumes to the same final state**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Property test: N repeated or concurrent imports of the same fixture produce identical logical record counts; a crash injected mid-batch resumes to the same final state. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### MED-001 — Media blob, asset and occurrence model
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `FND-004`, `FND-005`.
**Objective:** Define MediaBlob (content hash), MediaAsset (logical asset keyed by native file ID when present), AssetOccurrence (message/part-specific reference) and DerivedMediaArtifact (thumbnail/metadata) with availability states available, missing, unresolved, ambiguous and unsupported.
**Origin:** added by the Audit 2026-10-27 specification audit; see `docs/reviews/SPEC_CHANGELOG.md`.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: define MediaBlob (content hash), MediaAsset (logical asset keyed by native file ID when present), AssetOccurrence (message/part-specific reference) and DerivedMediaArtifact (thumbnail/metadata) with availability states available, missing, unresolved, ambiguous and unsupported.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Schema tests: one blob shared by many occurrences; an occurrence without bytes is representable as missing with evidence; a derived thumbnail never replaces the original**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Schema tests: one blob shared by many occurrences; an occurrence without bytes is representable as missing with evidence; a derived thumbnail never replaces the original. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### MED-002 — Asset pointer resolver
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `MED-001`, `ING-006`, `SRC-001`.
**Objective:** Resolve asset pointers (file-service://, sediment://, attachment metadata, export manifest entries, flattened file-ID-prefixed filenames, per-conversation asset folders) to candidate files, returning exactly one match, ambiguous, or missing with evidence.
**Origin:** added by the Audit 2026-10-27 specification audit; see `docs/reviews/SPEC_CHANGELOG.md`.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: resolve asset pointers (file-service://, sediment://, attachment metadata, export manifest entries, flattened file-ID-prefixed filenames, per-conversation asset folders) to candidate files, returning exactly one match, ambiguous, or missing with evidence.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Fixture covers each pointer scheme, a pointer with two candidate files (ambiguous) and a manifest-listed but absent file (missing); no fabricated paths**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Fixture covers each pointer scheme, a pointer with two candidate files (ambiguous) and a manifest-listed but absent file (missing); no fabricated paths. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### MED-003 — Content-addressed media dedup and occurrence persistence
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `MED-002`, `IMP-002`.
**Objective:** Hash available bytes, store or reference each distinct blob once per configured storage mode and persist every occurrence idempotently; read image type and dimensions from headers only, with no OCR or vision.
**Origin:** added by the Audit 2026-10-27 specification audit; see `docs/reviews/SPEC_CHANGELOG.md`.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: hash available bytes, store or reference each distinct blob once per configured storage mode and persist every occurrence idempotently; read image type and dimensions from headers only, with no OCR or vision.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Same image in two conversations yields one blob and two occurrences; reimport adds zero blobs or occurrences; raw files unchanged**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Same image in two conversations yields one blob and two occurrences; reimport adds zero blobs or occurrences; raw files unchanged. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### IMP-005 — Import delta report and regeneration footprint
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `IMP-004`, `ING-007`, `MED-003`, `REL-001`.
**Objective:** Produce the per-import audit report: new, unchanged and revised conversations and messages, new_branches, new_media, duplicate assets, missing_assets, candidate_duplicates, failed items and the affected derived document/index footprint, as JSON and readable text without private content.
**Origin:** added by the Audit 2026-10-27 specification audit; see `docs/reviews/SPEC_CHANGELOG.md`.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: produce the per-import audit report: new, unchanged and revised conversations and messages, new_branches, new_media, duplicate assets, missing_assets, candidate_duplicates, failed items and the affected derived document/index footprint, as JSON and readable text without private content.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Report counts reconcile exactly with fixture expectations for first import, identical reimport (all unchanged, zero model calls) and incremental export**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Report counts reconcile exactly with fixture expectations for first import, identical reimport (all unchanged, zero model calls) and incremental export. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### EVAL-010 — Import batch-scale smoke tests at 50 and 100 conversations
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `IMP-005`, `EVAL-009`.
**Objective:** Run the import, reimport and source-render path on seeded synthetic batches of 50 and 100 conversations and, locally and read-only, on 50 and 100 real raw conversations, recording timings, memory, warnings and delta counts without private text.
**Origin:** added by the Audit 2026-10-27 specification audit; see `docs/reviews/SPEC_CHANGELOG.md`.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: run the import, reimport and source-render path on seeded synthetic batches of 50 and 100 conversations and, locally and read-only, on 50 and 100 real raw conversations, recording timings, memory, warnings and delta counts without private text.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **50- and 100-conversation batches import, reimport with zero new logical records and render; a recorded report lists timings and warnings; raw tree hash unchanged**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** 50- and 100-conversation batches import, reimport with zero new logical records and render; a recorded report lists timings and warnings; raw tree hash unchanged. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### LNK-001 — URL occurrence extraction and link registry
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `NRM-003`, `IMP-003`.
**Objective:** Detect URLs in canonical message text and structured citation metadata with exact half-open spans, surrounding context, actor and origin; normalise to a canonical target while preserving the original string; treat as untrusted data and never fetch.
**Origin:** added by the Audit 2026-10-27 specification audit; see `docs/reviews/SPEC_CHANGELOG.md`.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: detect URLs in canonical message text and structured citation metadata with exact half-open spans, surrounding context, actor and origin; normalise to a canonical target while preserving the original string; treat as untrusted data and never fetch.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **A URL repeated in 3 messages gives one target and 3 occurrences; markdown, angle-bracket and trailing-punctuation cases span exactly; reimport adds zero occurrences**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** A URL repeated in 3 messages gives one target and 3 occurrences; markdown, angle-bracket and trailing-punctuation cases span exactly; reimport adds zero occurrences. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### YTB-001 — YouTube canonicaliser and video registry
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `LNK-001`.
**Objective:** Recognise watch, youtu.be, shorts, live, embed and mobile URL forms; canonicalise the video ID; preserve original URL, timestamp, playlist and channel context; create one video record per ID linked to every mention occurrence.
**Origin:** added by the Audit 2026-10-27 specification audit; see `docs/reviews/SPEC_CHANGELOG.md`.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: recognise watch, youtu.be, shorts, live, embed and mobile URL forms; canonicalise the video ID; preserve original URL, timestamp, playlist and channel context; create one video record per ID linked to every mention occurrence.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Table-driven URL fixture including invalid IDs and lookalike domains; 12 mentions of one video give 1 video and 12 occurrences; transcript status starts as not_requested**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Table-driven URL fixture including invalid IDs and lookalike domains; 12 mentions of one video give 1 video and 12 occurrences; transcript status starts as not_requested. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### YTB-002 — Transcript acquisition jobs, status and user-supplied transcripts
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `YTB-001`, `FND-006`, `FND-002`, `ING-010`.
**Objective:** Model TranscriptAcquisition (not_requested, queued, succeeded, unavailable, permission_required, rate_limited, failed) with a policy gate (network off by default), bounded attempts and provenance; import user-supplied VTT/SRT/text transcripts as TranscriptSnapshot with language and timed cues.
**Origin:** added by the Audit 2026-10-27 specification audit; see `docs/reviews/SPEC_CHANGELOG.md`.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: model TranscriptAcquisition (not_requested, queued, succeeded, unavailable, permission_required, rate_limited, failed) with a policy gate (network off by default), bounded attempts and provenance; import user-supplied VTT/SRT/text transcripts as TranscriptSnapshot with language and timed cues.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **With network disabled no job reaches a network call; a user-supplied transcript attaches with provenance; unavailable status is recorded with reason; no transcript text is ever generated**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** With network disabled no job reaches a network call; a user-supplied transcript attaches with provenance; unavailable status is recorded with reason; no transcript text is ever generated. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### SOC-001 — Social account mention detection
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `LNK-001`.
**Objective:** Detect profile URLs for configured platforms and explicit platform-qualified handles; classify bare @handles as ambiguous candidates; record raw mention, span, actor and origin; never fetch, follow or contact.
**Origin:** added by the Audit 2026-10-27 specification audit; see `docs/reviews/SPEC_CHANGELOG.md`.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: detect profile URLs for configured platforms and explicit platform-qualified handles; classify bare @handles as ambiguous candidates; record raw mention, span, actor and origin; never fetch, follow or contact.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Platform URL fixtures parse handle or ID; a bare @name without platform stays ambiguous; email addresses and code decorators are not accounts**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Platform URL fixtures parse handle or ID; a bare @name without platform stays ambiguous; email addresses and code decorators are not accounts. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### SOC-002 — Social account registry, aliases and review
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `SOC-001`, `IMP-002`.
**Objective:** Maintain deduplicated SocialAccount (platform, stable ID if known, handle, URL), AccountAlias and SocialAccountMention with first/last seen, counts, citing conversations and identity/review status; browse with a CLI listing.
**Origin:** added by the Audit 2026-10-27 specification audit; see `docs/reviews/SPEC_CHANGELOG.md`.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: maintain deduplicated SocialAccount (platform, stable ID if known, handle, URL), AccountAlias and SocialAccountMention with first/last seen, counts, citing conversations and identity/review status; browse with a CLI listing.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **The same account via URL and qualified handle resolves to one account with two mentions; an ambiguous handle never auto-links; reimport adds zero mentions**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** The same account via URL and qualified handle resolves to one account with two mentions; an ambiguous handle never auto-links; reimport adds zero mentions. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### REL-002 — Cross-conversation relationship model and structural detectors
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `IMP-003`, `LNK-001`.
**Objective:** Store typed directional conversation relationships (continues, forked_from, quotes, references, related_to, same_project) with evidence class, confidence, review state and append-only history; detect deterministic candidates from shared native IDs, identical message-prefix hashes, ChatGPT conversation/share URLs and verbatim quotations.
**Origin:** added by the Audit 2026-10-27 specification audit; see `docs/reviews/SPEC_CHANGELOG.md`.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: store typed directional conversation relationships (continues, forked_from, quotes, references, related_to, same_project) with evidence class, confidence, review state and append-only history; detect deterministic candidates from shared native IDs, identical message-prefix hashes, ChatGPT conversation/share URLs and verbatim quotations.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Copied-prefix fixture yields a forked_from candidate (review_required); similar-but-unrelated fixture yields no structural link; approvals and rejections are append-only and keep direction**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Copied-prefix fixture yields a forked_from candidate (review_required); similar-but-unrelated fixture yields no structural link; approvals and rejections are append-only and keep direction. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

## Phase: Taxonomy

### TAX-001 — Taxonomy and project registry schema
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `FND-004`, `FND-005`.
**Objective:** Implement taxonomy version, concept/project, alias, proposal tables with stable IDs.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: implement taxonomy version, concept/project, alias, proposal tables with stable IDs.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Unique aliases/version constraints and schema migration test**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Unique aliases/version constraints and schema migration test. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### TAX-002 — Published taxonomy snapshot interface
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `TAX-001`.
**Objective:** Create immutable reader/list/filter for approved terms only and explicit version lookup.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: create immutable reader/list/filter for approved terms only and explicit version lookup.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Reading unapproved terms prohibited during classification**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Reading unapproved terms prohibited during classification. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### TAX-003 — Alias normalization and candidate resolution
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `TAX-002`.
**Objective:** Match text to canonical IDs using normalized alias and scoped disambiguation.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: match text to canonical IDs using normalized alias and scoped disambiguation.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **UE5/Unreal alias fixtures map as expected, collisions flagged**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** UE5/Unreal alias fixtures map as expected, collisions flagged. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### TAX-004 — Candidate proposals and manual approval
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `TAX-001`, `TAX-003`.
**Objective:** Create approve/reject/merge review workflow with audit trail and version publish.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: create approve/reject/merge review workflow with audit trail and version publish.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Unapproved proposal cannot appear as canonical term**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Unapproved proposal cannot appear as canonical term. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### TAX-005 — Project identity, alias and merge proposals
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `TAX-001`, `NRM-006`.
**Objective:** Support persistent project IDs and high-impact rename/merge review.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: support persistent project IDs and high-impact rename/merge review.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Same name different project not automatically merged**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Same name different project not automatically merged. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### TAX-006 — Corpus discovery optional clustering backend
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `NRM-006`, `TAX-004`.
**Objective:** Implement discovery candidates, optional BERTopic adapter and deterministic baseline TF-IDF.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: implement discovery candidates, optional BERTopic adapter and deterministic baseline TF-IDF.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Discovery never writes approved terms without review**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Discovery never writes approved terms without review. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### TAX-007 — Taxonomy version diff and selective invalidation
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `TAX-002`, `TAX-004`, `FND-006`.
**Objective:** Persist changed IDs and invalidate affected stage outputs on publish.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: persist changed IDs and invalidate affected stage outputs on publish.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Unrelated project classifications untouched by alias update**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Unrelated project classifications untouched by alias update. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### TAX-008 — Taxonomy QA, governance and review reports
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `TAX-003`, `TAX-004`, `TAX-005`.
**Objective:** Report aliases, duplicates, orphan concepts, proposed terms and reviewer outcomes.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: report aliases, duplicates, orphan concepts, proposed terms and reviewer outcomes.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Duplicate/parent cycle audit fixture surfaces issues**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Duplicate/parent cycle audit fixture surfaces issues. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

## Phase: Classification

### CLS-001 — Classifier schema and allowed-label prompt
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `TAX-002`, `NRM-004`, `FND-007`, `FND-009`.
**Objective:** Define typed primary/secondary assignments with project IDs, evidence windows and approved ID constraints.
**Audit amendment (2026-10-27):** Classification calls go through FND-009 structured output; enum of approved term IDs is embedded in the JSON schema. Dependencies were `TAX-002;NRM-004;FND-007`, now `TAX-002;NRM-004;FND-007;FND-009`.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: define typed primary/secondary assignments with project IDs, evidence windows and approved ID constraints.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Forbidden/new term from fake model is rejected**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Forbidden/new term from fake model is rejected. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### CLS-002 — SegmentClassifier service
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `CLS-001`, `TAX-003`.
**Objective:** Build context, select IDs and multi-label priority using deterministic tie-break/uncertainty.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: build context, select IDs and multi-label priority using deterministic tie-break/uncertainty.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Golden mixed-project segment receives allowed labels**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Golden mixed-project segment receives allowed labels. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### CLS-003 — Keyword scoring and primary/secondary ranking
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `CLS-002`.
**Objective:** Implement corpus distinctiveness+semantic/user-emphasis scoring with frequency only as one feature.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: implement corpus distinctiveness+semantic/user-emphasis scoring with frequency only as one feature.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Decisive once-mentioned term outranks incidental repetition fixture**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Decisive once-mentioned term outranks incidental repetition fixture. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### CLS-004 — Classification persistence/review workflow
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `CLS-002`, `TAX-007`.
**Objective:** Store taxonomy/model version, confidence/evidence, unresolved proposals and reviewer corrections.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: store taxonomy/model version, confidence/evidence, unresolved proposals and reviewer corrections.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Human reviewed choice persists through repeated processing**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Human reviewed choice persists through repeated processing. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### CLS-005 — Order-independence and drift diagnostic
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `CLS-003`, `CLS-004`.
**Objective:** Shuffle segment processing order under pinned taxonomy and diff canonical outputs.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: shuffle segment processing order under pinned taxonomy and diff canonical outputs.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Three-order golden experiment yields same IDs or review flags**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Three-order golden experiment yields same IDs or review flags. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

## Phase: Extraction

### EXT-001 — Typed knowledge record/review contract
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `FND-005`, `CLS-004`.
**Objective:** Define record enums, origin/speaker/scope, extraction provenance and review states.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: define record enums, origin/speaker/scope, extraction provenance and review states.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Schema forbids unsupported confirmed records and unknown types**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Schema forbids unsupported confirmed records and unknown types. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### EXT-002 — Evidence validator and source-span audit
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `EXT-001`, `NRM-003`.
**Objective:** Validate snapshot/node IDs, offsets, quote hashes, actor and semantic support/review status.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: validate snapshot/node IDs, offsets, quote hashes, actor and semantic support/review status.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Malformed references rejected and ambiguous meanings held for review**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Malformed references rejected and ambiguous meanings held for review. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### EXT-003 — Decision and rejection extractor
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `EXT-001`, `EXT-002`.
**Objective:** Detect proposals, explicit acceptance, conditional agreement, rejections and antecedent/source actor.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: detect proposals, explicit acceptance, conditional agreement, rejections and antecedent/source actor.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Assistant suggestion plus curious user NOT accepted; explicit yes supported**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Assistant suggestion plus curious user NOT accepted; explicit yes supported. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### EXT-004 — Preference and requirement extractor
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `EXT-001`, `EXT-002`.
**Objective:** Extract preferences/constraints with scope and intensity; distinguish user from external quotation.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: extract preferences/constraints with scope and intensity; distinguish user from external quotation.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Quoted preference and soft/hard constraint fixtures separate**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Quoted preference and soft/hard constraint fixtures separate. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### EXT-005 — Actions, questions and artefacts extractor
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `EXT-001`, `EXT-002`, `MED-003`.
**Objective:** Extract agreed tasks, open questions and real output artefact IDs/missing asset flags.
**Audit amendment (2026-10-27):** Artefact records link actual MediaAsset/AssetOccurrence IDs from MED-003 or carry an explicit missing flag. Dependencies were `EXT-001;EXT-002`, now `EXT-001;EXT-002;MED-003`.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: extract agreed tasks, open questions and real output artefact IDs/missing asset flags.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Suggested task not user commitment; missing artefact reported**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Suggested task not user commitment; missing artefact reported. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### EXT-006 — External references and named entity extractor
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `EXT-001`, `EXT-002`, `TAX-003`, `LNK-001`.
**Objective:** Extract cited games/software/books/people with canonical aliases and type-specific fields.
**Audit amendment (2026-10-27):** URL, YouTube and social references come from the deterministic LNK/YTB/SOC registries; this extractor adds typed named entities and must not re-detect URLs. Dependencies were `EXT-001;EXT-002;TAX-003`, now `EXT-001;EXT-002;TAX-003;LNK-001`.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: extract cited games/software/books/people with canonical aliases and type-specific fields.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Named game doesn't create project automatically**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Named game doesn't create project automatically. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### EXT-007 — Evidence promotion/review queue
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `EXT-002`, `EXT-003`, `EXT-004`, `EXT-005`, `EXT-006`.
**Objective:** Implement validation gate, reviewer decisions, audit log and promotion to supported/confirmed.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: implement validation gate, reviewer decisions, audit log and promotion to supported/confirmed.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Unsupported candidate blocked from current truth/materialisation**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Unsupported candidate blocked from current truth/materialisation. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### EXT-008 — Extraction aggregate and processing version manager
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `EXT-007`, `FND-006`, `FND-009`.
**Objective:** Batch typed extractors, stage-specific caching and model/prompt version captures.
**Audit amendment (2026-10-27):** Extractor batches run through FND-009 (schema-validated output, one repair attempt, pinned versions) and are smoke-tested at 50/100 conversations in EVAL-011. Dependencies were `EXT-007;FND-006`, now `EXT-007;FND-006;FND-009`.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: batch typed extractors, stage-specific caching and model/prompt version captures.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Partial failure preserves successful stages, retry bounded**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Partial failure preserves successful stages, retry bounded. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

## Phase: Reconciliation

### REC-001 — Record deduplication and equivalence proposals
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `EXT-007`.
**Objective:** Find semantically equivalent claims without merging distinct scoped decisions.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: find semantically equivalent claims without merging distinct scoped decisions.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Near-miss statements remain distinct unless reviewer confirms**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Near-miss statements remain distinct unless reviewer confirms. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### REC-002 — Relationship candidate discovery
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `EXT-007`, `TAX-005`.
**Objective:** Generate same_project, elaborates, references, creates links with scope and evidence.
**Audit amendment (2026-10-27):** Record-level relationships only; conversation-level relationships (continues, forked_from, related_to) live in REL-002..REL-004.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: generate same_project, elaborates, references, creates links with scope and evidence.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Only typed allowed relations stored and links cite sources**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Only typed allowed relations stored and links cite sources. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### REC-003 — Conflict detector by scope and time
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `REC-001`, `REC-002`.
**Objective:** Find conflicting requirements/decisions in overlapping scope; mark unresolved.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: find conflicting requirements/decisions in overlapping scope; mark unresolved.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Different projects not false conflicts; no temporal winner by timestamp alone**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Different projects not false conflicts; no temporal winner by timestamp alone. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### REC-004 — Decision transition and event timeline
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `EXT-003`, `REC-003`.
**Objective:** Build proposal/accept/revise/reject timeline with immutable transition events.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: build proposal/accept/revise/reject timeline with immutable transition events.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Revisions never delete original decision history**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Revisions never delete original decision history. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### REC-005 — Scope-aware supersession reconciler
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `REC-004`.
**Objective:** Require source-supported intent and compatible project/feature scope before superseding.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: require source-supported intent and compatible project/feature scope before superseding.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Later hypothetical engine switch cannot supersede accepted Unity choice**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Later hypothetical engine switch cannot supersede accepted Unity choice. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### REC-006 — Current-state and as-of projector
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `REC-005`.
**Objective:** Derive current/at-date project decisions, conflicting/unknown outcome and explanation chain.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: derive current/at-date project decisions, conflicting/unknown outcome and explanation chain.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Historical snapshot reproducible; unresolved conflicts visible**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Historical snapshot reproducible; unresolved conflicts visible. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### REC-007 — Relationship and provenance API for downstream
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `REC-002`, `REC-006`.
**Objective:** Expose graph walk with source anchor, relationship type and current-status labels.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: expose graph walk with source anchor, relationship type and current-status labels.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Every directional claim has supporting origin; filtered traversal works**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Every directional claim has supporting origin; filtered traversal works. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

## Phase: Retrieval

### RET-001 — SQLite FTS5 lexical index and search
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `FND-004`, `NRM-001`.
**Objective:** Index canonical text with workspace and source IDs; exact/phrase/token search.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: index canonical text with workspace and source IDs; exact/phrase/token search.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Unique code and case/phrase fixtures retrievable**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Unique code and case/phrase fixtures retrievable. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### RET-002 — Embeddings provider and index protocol
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `FND-007`, `NRM-004`.
**Objective:** Define embedding model fingerprint/dimension, fake vector backend and versioned storage.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: define embedding model fingerprint/dimension, fake vector backend and versioned storage.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Change in model dimension rejects stale index**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Change in model dimension rejects stale index. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### RET-003 — Local semantic search implementation
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `RET-002`, `FND-004`.
**Objective:** Build vector upsert/query with metadata filters, source context keys and safe replay.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: build vector upsert/query with metadata filters, source context keys and safe replay.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Semantic paraphrase golden targets retrieved and scope enforced**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Semantic paraphrase golden targets retrieved and scope enforced. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### RET-004 — Hybrid rank fusion and structured results
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `RET-001`, `RET-003`.
**Objective:** Implement RRF or calibrated ranking with lexical/semantic/structured hits and deterministic ties.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: implement RRF or calibrated ranking with lexical/semantic/structured hits and deterministic ties.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Exact code doesn't disappear; hit dedup stable**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Exact code doesn't disappear; hit dedup stable. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### RET-005 — Question route planner
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `RET-004`, `REC-006`.
**Objective:** Route current-decision queries to structured records, broad concepts to hybrid, exact text to FTS.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: route current-decision queries to structured records, broad concepts to hybrid, exact text to FTS.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Question-type fixtures select expected route**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Question-type fixtures select expected route. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### RET-006 — Source context hydrator and citation resolver
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `RET-004`, `EXT-002`.
**Objective:** Fetch source window, actor and anchored passages, reject stale references.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: fetch source window, actor and anchored passages, reject stale references.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **All returned citations resolve to immutable evidence**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** All returned citations resolve to immutable evidence. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### RET-007 — Grounded answer service and abstention
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `RET-005`, `RET-006`, `FND-007`.
**Objective:** Generate cited responses strictly from retrieved evidence; explicitly state unknown/conflicts.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: generate cited responses strictly from retrieved evidence; explicitly state unknown/conflicts.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **No-evidence query abstains; citation IDs audited**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** No-evidence query abstains; citation IDs audited. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### RET-008 — Retrieval benchmarks and tuning report
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `RET-007`.
**Objective:** Measure Recall@K, MRR, exact term hit and cost across lexical/semantic/hybrid.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: measure Recall@K, MRR, exact term hit and cost across lexical/semantic/hybrid.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Pinned benchmark and regression threshold report reproducible**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Pinned benchmark and regression threshold report reproducible. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

## Phase: Documents

### DOC-001 — Document model and dependency tracking
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `REC-006`, `EXT-007`.
**Objective:** Build conversation/project/topic document DTO and record-to-document dependency graph.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: build conversation/project/topic document DTO and record-to-document dependency graph.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Single changed knowledge record maps to exact dependent docs**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Single changed knowledge record maps to exact dependent docs. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### DOC-002 — Deterministic Markdown/YAML renderer
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `FND-005`.
**Objective:** Build frontmatter writer, citation anchors, safe slug paths and atomic output.
**Audit amendment (2026-10-27):** Renderer is generic infrastructure; dependency changed from DOC-001 to FND-005 so source-level notes (BRW-001) can ship before the knowledge pipeline. Dependencies were `DOC-001`, now `FND-005`.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: build frontmatter writer, citation anchors, safe slug paths and atomic output.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Obsidian YAML parses, same inputs yield byte-identical note**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Obsidian YAML parses, same inputs yield byte-identical note. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### MED-004 — Safe media paths and Obsidian embeds
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `MED-003`, `DOC-002`.
**Objective:** Generate vault-safe attachment paths and embeds for the configured media mode, plus explicit missing/unresolved markers with evidence, and validate that every generated media link resolves.
**Origin:** added by the Audit 2026-10-27 specification audit; see `docs/reviews/SPEC_CHANGELOG.md`.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: generate vault-safe attachment paths and embeds for the configured media mode, plus explicit missing/unresolved markers with evidence, and validate that every generated media link resolves.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Link checker passes for available media; a missing asset renders a marker naming the pointer and reason; no raw/ path leaks when copy mode is configured**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Link checker passes for available media; a missing asset renders a marker naming the pointer and reason; no raw/ path leaks when copy mode is configured. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### BRW-001 — Source-level conversation browser (CLI and Markdown)
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `IMP-005`, `MED-004`, `REL-001`.
**Objective:** Provide inspect views for conversations, branches and assets and deterministic LLM-free source transcript notes that show the active path, alternate branches, image embeds or missing markers, links and per-message source anchors.
**Origin:** added by the Audit 2026-10-27 specification audit; see `docs/reviews/SPEC_CHANGELOG.md`.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: provide inspect views for conversations, branches and assets and deterministic LLM-free source transcript notes that show the active path, alternate branches, image embeds or missing markers, links and per-message source anchors.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Fixture conversation renders with every node reachable, branches labelled, images linked and anchors resolving to logical message IDs**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Fixture conversation renders with every node reachable, branches labelled, images linked and anchors resolving to logical message IDs. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### DOC-003 — Individual conversation knowledge notes
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `DOC-002`, `CLS-004`, `MED-004`, `REL-002`, `YTB-001`, `SOC-002`.
**Objective:** Render summary, classes, accepted/rejected proposals, references, actions and source links.
**Audit amendment (2026-10-27):** Notes also show branches, media embeds or missing markers, URL/YouTube/social mentions and related conversations. Dependencies were `DOC-002;CLS-004`, now `DOC-002;CLS-004;MED-004;REL-002;YTB-001;SOC-002`.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: render summary, classes, accepted/rejected proposals, references, actions and source links.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Document shows categories and exact actor-attributed evidence**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Document shows categories and exact actor-attributed evidence. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### DOC-004 — Project master/current-vs-history generator
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `DOC-002`, `REC-006`.
**Objective:** Build project master with current decisions, historical revisions, disputes, dependencies and sources.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: build project master with current decisions, historical revisions, disputes, dependencies and sources.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Master never merges old/revised choices without labels**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Master never merges old/revised choices without labels. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### DOC-005 — Topic master generator and selectors
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `DOC-002`, `RET-005`.
**Objective:** Query all sources by canonical topic and render thematic master with provenance.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: query all sources by canonical topic and render thematic master with provenance.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Recipes sample includes unrelated-source filter tests**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Recipes sample includes unrelated-source filter tests. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### DOC-006 — Obsidian safe export and incremental regeneration
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `DOC-003`, `DOC-004`, `DOC-005`, `DOC-001`, `MED-004`.
**Objective:** Generate managed vault paths, preserve manual notes, selectively rebuild affected documents.
**Audit amendment (2026-10-27):** Managed vault includes media attachments per MED-004 and validates media links. Dependencies were `DOC-003;DOC-004;DOC-005;DOC-001`, now `DOC-003;DOC-004;DOC-005;DOC-001;MED-004`.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: generate managed vault paths, preserve manual notes, selectively rebuild affected documents.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Manual changes safe, unchanged build causes no file rewrites**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Manual changes safe, unchanged build causes no file rewrites. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

## Phase: Relationships and registries (late)

Added by the specification audit (2026-10-27). These depend on retrieval, review or document tickets and therefore follow the Documents phase.

### IMP-006 — Human corrections survive incremental reprocessing
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `IMP-003`, `NRM-005`, `CLS-004`, `EXT-007`.
**Objective:** Anchor reviewer overrides (segments, classifications, records, relationships) to logical IDs plus content revision; on reimport keep overrides on unchanged content and flag overrides on revised content for review.
**Origin:** added by the Audit 2026-10-27 specification audit; see `docs/reviews/SPEC_CHANGELOG.md`.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: anchor reviewer overrides (segments, classifications, records, relationships) to logical IDs plus content revision; on reimport keep overrides on unchanged content and flag overrides on revised content for review.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **An override on an unchanged message survives reimport untouched; an override on a revised message becomes review_required with both revisions visible**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** An override on an unchanged message survives reimport untouched; an override on a revised message becomes review_required with both revisions visible. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### REL-003 — Semantic and project relatedness candidates
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `REL-002`, `RET-003`, `TAX-005`.
**Objective:** Propose related_to and same_project candidates from approved project/topic overlap, entity overlap and embedding similarity with explanations; never assert continues or forked_from from similarity alone.
**Origin:** added by the Audit 2026-10-27 specification audit; see `docs/reviews/SPEC_CHANGELOG.md`.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: propose related_to and same_project candidates from approved project/topic overlap, entity overlap and embedding similarity with explanations; never assert continues or forked_from from similarity alone.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Similar-but-unrelated fixture stays a candidate or below threshold; no candidate auto-promotes to forked_from**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Similar-but-unrelated fixture stays a candidate or below threshold; no candidate auto-promotes to forked_from. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### REL-004 — Relationship review, notes and retrieval exposure
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `REL-002`, `DOC-003`, `RET-006`.
**Objective:** Surface related conversations with kind, direction, evidence and review state in conversation, project and topic notes and in retrieval results, recording approve/reject history.
**Origin:** added by the Audit 2026-10-27 specification audit; see `docs/reviews/SPEC_CHANGELOG.md`.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: surface related conversations with kind, direction, evidence and review state in conversation, project and topic notes and in retrieval results, recording approve/reject history.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **A rejected link disappears from notes but remains in history; an accepted link renders with cited evidence in the correct direction**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** A rejected link disappears from notes but remains in history; an accepted link renders with cited evidence in the correct direction. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### YTB-003 — Transcript cue linking, search and video notes
**Priority:** P1 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `YTB-002`, `RET-001`, `DOC-002`.
**Objective:** Link timed cues to the video and every referencing message, index cues for search and render video notes with transcript status and backlinks.
**Origin:** added by the Audit 2026-10-27 specification audit; see `docs/reviews/SPEC_CHANGELOG.md`.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: link timed cues to the video and every referencing message, index cues for search and render video notes with transcript status and backlinks.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **A cue search hit resolves to the video timestamp and all citing conversations; a video without transcript shows its explicit status**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** A cue search hit resolves to the video timestamp and all citing conversations; a video without transcript shows its explicit status. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### SOC-003 — Social account registry notes
**Priority:** P1 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `SOC-002`, `DOC-002`.
**Objective:** Render a browseable account registry and per-account notes with mentions, aliases and review status.
**Origin:** added by the Audit 2026-10-27 specification audit; see `docs/reviews/SPEC_CHANGELOG.md`.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: render a browseable account registry and per-account notes with mentions, aliases and review status.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Registry note lists every accepted account with backlinks; ambiguous candidates appear in a separate review section**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Registry note lists every accepted account with backlinks; ambiguous candidates appear in a separate review section. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

## Phase: Evaluation

### EVAL-001 — Golden corpus fixtures and annotation guide
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `ING-007`, `NRM-004`.
**Objective:** Select/anonymise 30–50 diverse conversations; define expected and forbidden decisions, boundaries and spans.
**Audit amendment (2026-10-27):** Golden set must also measure run-to-run label stability and schema-failure rate per model, given earlier inconsistent results (DECISIONS_AND_HISTORY project history).
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: select/anonymise 30–50 diverse conversations; define expected and forbidden decisions, boundaries and spans.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Reviewed annotation schema available and no secrets in Git**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Reviewed annotation schema available and no secrets in Git. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### EVAL-002 — Parser/import fidelity evaluation
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `EVAL-001`, `ING-007`, `EVAL-009`, `IMP-005`.
**Objective:** Measure supported node count, branch retention, missing assets and unknown payload audit.
**Audit amendment (2026-10-27):** Uses EVAL-009 synthetic fixtures and the IMP-005 delta report. Dependencies were `EVAL-001;ING-007`, now `EVAL-001;ING-007;EVAL-009;IMP-005`.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: measure supported node count, branch retention, missing assets and unknown payload audit.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Fixtures all accounted for or warned, zero silent dropped nodes**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Fixtures all accounted for or warned, zero silent dropped nodes. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### EVAL-003 — Taxonomy/classification evaluation runner
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `EVAL-001`, `CLS-004`.
**Objective:** Compute multi-label F1, primary-category accuracy and project accuracy.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: compute multi-label F1, primary-category accuracy and project accuracy.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Baseline report with per-type confusion and version info**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Baseline report with per-type confusion and version info. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### EVAL-004 — Knowledge extraction precision/recall
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `EVAL-001`, `EXT-007`.
**Objective:** Compute per-record-type scores, actor correctness, evidence anchor validity and forbidden assertions.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: compute per-record-type scores, actor correctness, evidence anchor validity and forbidden assertions.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Zero known unsupported confirmed decisions in fixture**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Zero known unsupported confirmed decisions in fixture. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### EVAL-005 — Temporal/current-state benchmark
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `EVAL-001`, `REC-006`.
**Objective:** Test true vs false supersession, changing scope, conflicting decisions and historical retention.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: test true vs false supersession, changing scope, conflicting decisions and historical retention.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **No later-hypothetical false supersession in curated cases**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** No later-hypothetical false supersession in curated cases. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### EVAL-006 — End-to-end fixture and Obsidian golden
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `EVAL-002`, `DOC-006`, `BRW-001`.
**Objective:** Run local ZIP → classify → extract → master note/search and verify links.
**Audit amendment (2026-10-27):** End-to-end golden also verifies the LLM-free source notes from BRW-001 before the knowledge notes. Dependencies were `EVAL-002;DOC-006`, now `EVAL-002;DOC-006;BRW-001`.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: run local ZIP → classify → extract → master note/search and verify links.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Golden output parsed and anchors traceable**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Golden output parsed and anchors traceable. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### EVAL-007 — Regression gate/report and finite stop policy
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `EVAL-003`, `EVAL-004`, `EVAL-005`, `EVAL-006`.
**Objective:** Aggregate proposed release thresholds; label PASS/FAIL/REVIEW/BLOCKED with commands run.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: aggregate proposed release thresholds; label PASS/FAIL/REVIEW/BLOCKED with commands run.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Gate stops after one full pass; failures filed as tickets**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Gate stops after one full pass; failures filed as tickets. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### EVAL-008 — Shuffled-order and repeated-run variance test
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `CLS-005`, `EVAL-007`.
**Objective:** Run 3 shuffled orders and pinned provider repeats; diff canonical classification/current views.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: run 3 shuffled orders and pinned provider repeats; diff canonical classification/current views.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Differences become review items; no silent drift**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Differences become review items; no silent drift. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

## Phase: API

### API-001 — FastAPI skeleton and dependency overrides
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `FND-006`, `FND-008`.
**Objective:** Add app factory, DI for storage/providers, error model, OpenAPI version and health/status.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: add app factory, DI for storage/providers, error model, OpenAPI version and health/status.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **TestClient with overrides uses fake database/providers**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** TestClient with overrides uses fake database/providers. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### API-002 — Import and job status endpoints
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `API-001`, `ING-007`.
**Objective:** Create POST imports and GET jobs/sources/nodes with pagination/partial warnings.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: create POST imports and GET jobs/sources/nodes with pagination/partial warnings.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Import returns job ID, not premature completion**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Import returns job ID, not premature completion. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### API-003 — Taxonomy/review/knowledge endpoints
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `API-001`, `TAX-008`, `EXT-007`.
**Objective:** List concepts, propose approvals, inspect evidence and submit audited review decisions.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: list concepts, propose approvals, inspect evidence and submit audited review decisions.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Unauthorized/invalid transition rejected**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Unauthorized/invalid transition rejected. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### API-004 — Search/answer/timeline endpoints
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `API-001`, `RET-007`, `REC-007`.
**Objective:** Add GET search, POST answers, GET decision history with evidence refs.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: add GET search, POST answers, GET decision history with evidence refs.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Response citations resolve and as-of filtering works**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Response citations resolve and as-of filtering works. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### API-005 — Document build/export endpoints
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `API-001`, `DOC-006`.
**Objective:** Build/list/preview documents and safe export destinations via async jobs.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: build/list/preview documents and safe export destinations via async jobs.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **No overwrite of user files and injected paths rejected**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** No overwrite of user files and injected paths rejected. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

## Phase: Operations

### OPS-001 — Structured logs, traces and cost accounting
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `FND-006`.
**Objective:** Log job/stage/provider IDs, timings, cost and errors without private source text.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: log job/stage/provider IDs, timings, cost and errors without private source text.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Logs scrub tokens/secrets and stage lineage searchable**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Logs scrub tokens/secrets and stage lineage searchable. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### OPS-002 — Resource, timeout and queue limits
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `FND-006`, `OPS-001`.
**Objective:** Bound ZIP entries, memory, concurrency, tokens, retries and stage deadlines.
**Audit amendment (2026-10-27):** Provider timeouts, rate limits and batch concurrency are first-class limits; validated by EVAL-011.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: bound ZIP entries, memory, concurrency, tokens, retries and stage deadlines.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Synthetic overload exits with recorded capped failure**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Synthetic overload exits with recorded capped failure. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### EVAL-011 — Semantic pipeline batch smoke tests at 50 and 100 conversations
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `FND-009`, `CLS-002`, `EXT-008`, `OPS-002`.
**Objective:** Run segmentation, classification and extraction on batches of 50 and 100 conversations, first with the fake provider and then a pinned real provider under a cost cap, measuring schema-failure rate, timeouts, retries, checkpoint resume and run-to-run label stability.
**Origin:** added by the Audit 2026-10-27 specification audit; see `docs/reviews/SPEC_CHANGELOG.md`.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: run segmentation, classification and extraction on batches of 50 and 100 conversations, first with the fake provider and then a pinned real provider under a cost cap, measuring schema-failure rate, timeouts, retries, checkpoint resume and run-to-run label stability.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Both batch sizes complete or stop with recorded bounded failures; zero unvalidated outputs persisted; interrupted run resumes without repeating succeeded stage keys; a stability report is produced**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Both batch sizes complete or stop with recorded bounded failures; zero unvalidated outputs persisted; interrupted run resumes without repeating succeeded stage keys; a stability report is produced. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### OPS-003 — Local backups and verified restore
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `FND-004`, `ING-001`.
**Objective:** Snapshot DB/raw archive/manifests and test full restore in temp workspace.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: snapshot DB/raw archive/manifests and test full restore in temp workspace.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Restored hashes and record counts match baseline**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Restored hashes and record counts match baseline. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### OPS-004 — Data deletion and downstream purge
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `DOC-006`, `RET-004`, `OPS-003`, `MED-003`, `YTB-002`, `SOC-002`.
**Objective:** Compute derivative closure, purge raw/index/FTS/vector/doc cache, verify no-access.
**Audit amendment (2026-10-27):** Deletion closure includes media blobs/occurrences, transcripts, link/account mentions and relationship evidence. Dependencies were `DOC-006;RET-004;OPS-003`, now `DOC-006;RET-004;OPS-003;MED-003;YTB-002;SOC-002`.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: compute derivative closure, purge raw/index/FTS/vector/doc cache, verify no-access.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Post-delete retrieval queries return no deleted material**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Post-delete retrieval queries return no deleted material. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### OPS-005 — CI pipeline with scoped quality gates
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `EVAL-007`, `OPS-002`.
**Objective:** Add lint/type/unit/contract/integration automation and bounded semantic nightly gate.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: add lint/type/unit/contract/integration automation and bounded semantic nightly gate.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **CI reproducible with no real provider credentials**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** CI reproducible with no real provider credentials. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### OPS-006 — Privacy and prompt injection hardening
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `ING-004`, `RET-007`, `OPS-004`.
**Objective:** Harden source-as-data boundary, redaction, malicious URL/ZIP and model tool permissions.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: harden source-as-data boundary, redaction, malicious URL/ZIP and model tool permissions.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Adversarial fixtures cannot execute instructions or leak content**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Adversarial fixtures cannot execute instructions or leak content. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### OPS-007 — Packaging, upgrade and release process
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `OPS-003`, `OPS-005`.
**Objective:** Create install script/CLI distribution, migration backup, versioned changelog and rollback SOP.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: create install script/CLI distribution, migration backup, versioned changelog and rollback SOP.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Clean machine install+upgrade+restore test passes**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Clean machine install+upgrade+restore test passes. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

## Phase: Productisation

### PROD-001 — PostgreSQL migration proof-of-concept
**Priority:** P1 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `FND-004`, `OPS-007`.
**Objective:** Port SQLAlchemy schema and lexical query contract with benchmark for hosted scale.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: port SQLAlchemy schema and lexical query contract with benchmark for hosted scale.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Same integration fixtures run on SQLite and PostgreSQL**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Same integration fixtures run on SQLite and PostgreSQL. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### PROD-002 — Accounts/workspaces and role-based access
**Priority:** P1 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `PROD-001`, `API-003`.
**Objective:** Implement tenant membership, roles, service policy, audit of authorisation.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: implement tenant membership, roles, service policy, audit of authorisation.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Cross-account denied on all source and knowledge endpoints**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Cross-account denied on all source and knowledge endpoints. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### PROD-003 — Tenant isolation through all retrieval/exports
**Priority:** P1 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `PROD-002`, `RET-007`, `DOC-006`.
**Objective:** Scope SQL, FTS, vector, graph, caches, answers, exports and deletion.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: scope SQL, FTS, vector, graph, caches, answers, exports and deletion.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Adversarial multi-user corpus has zero cross-workspace exposure**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Adversarial multi-user corpus has zero cross-workspace exposure. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### PROD-004 — Deployment, security review and retention policies
**Priority:** P1 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `PROD-003`, `OPS-006`.
**Objective:** Define hosting secrets, backups, key rotation, user deletion, UK GDPR review and release checklist.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: define hosting secrets, backups, key rotation, user deletion, UK GDPR review and release checklist.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Threat model reviewed; deletion/access control tests pass**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Threat model reviewed; deletion/access control tests pass. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

## Phase: Integrations

### INT-001 — Safe website ingestion connector
**Priority:** P1 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `ING-002`, `OPS-006`.
**Objective:** Implement URL metadata/canonical URL, allowlisted fetch, SSRF/size validation, HTML extraction.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: implement URL metadata/canonical URL, allowlisted fetch, SSRF/size validation, HTML extraction.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Redirect-to-private-IP refused and canonical source anchored**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Redirect-to-private-IP refused and canonical source anchored. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### INT-002 — YouTube transcript input workflow
**Priority:** P1 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `ING-010`, `INT-001`, `YTB-002`.
**Objective:** Accept user-provided transcript or authorised captions with video URI/timestamps and access policy.
**Audit amendment (2026-10-27):** Rescoped: authorised network transcript providers only (YTB-002 owns statuses and user-supplied transcripts). Remains P1, opt-in, rate-limited, never circumvents access controls. Dependencies were `ING-010;INT-001`, now `ING-010;INT-001;YTB-002`.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: accept user-provided transcript or authorised captions with video URI/timestamps and access policy.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Unavailable transcript flagged instead of invented/downloaded**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Unavailable transcript flagged instead of invented/downloaded. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### INT-003 — Watched folders and incremental source monitoring
**Priority:** P1 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `ING-003`, `DOC-006`, `OPS-002`.
**Objective:** Watch folder changes, debounce fingerprints, schedule affected stages, report progress.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: watch folder changes, debounce fingerprints, schedule affected stages, report progress.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Repeated events import once and unrelated docs remain unchanged**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Repeated events import once and unrelated docs remain unchanged. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.
