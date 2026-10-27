# Roadmap and Dependency-Ordered Engineering Backlog
**Status:** planned; not implemented. **Ticket count:** 93. Tickets ordered so all blockers precede their dependents.

## Phase gates
| Phase | Gate |
|---|---|
| Foundation | Packages, schema and stage contracts validated on a clean machine |
| Ingestion | Immutable source and full-fidelity branch-aware, idempotent import |
| Normalisation | Stable canonical nodes/segments/evidence anchors |
| Taxonomy | Published controlled vocabulary and review process |
| Classification | Approved labels only and order-independent identifiers |
| Extraction | Evidence backed typed records and actor validation |
| Reconciliation | Correct project history and current-state projection |
| Retrieval | Exact/semantic/structured citation-grounded search |
| Documents | Obsidian notes and living masters with safe regeneration |
| Evaluation | Golden baseline and bounded release gates |
| API | Typed endpoints and testable provider/storage overrides |
| Operations | Restore/security/release and deletion verification |
| Productisation | Hosted/multi-user rights isolation; deferred until trusted MVP |
| Integrations | Other documents/web/video and watched sources |

## Dependency map
Ticket dependency chains are defined per ticket below and in `TICKETS.csv`. Critical path begins `FND-001 → FND-003 → ING-001 → ING-002 → ING-004 → ING-005 → NRM-001 → NRM-004 → TAX-001/TAX-002 → CLS-001 → EXT-001/EXT-002 → REC-004/REC-005/REC-006 → DOC-004 / RET-007`. Dependency IDs are implementation blockers, not vague associations.

## Phase: Foundation

### FND-001 — Bootstrap Python repository and tool configuration
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** None.
**Objective:** Create pyproject.toml, src-layout package, baseline ruff/pytest/mypy settings and Git ignore.
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

## Phase: Ingestion

### ING-001 — Secure archive storage and checksums
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `FND-003`, `FND-005`.
**Objective:** Store byte-identical content-addressed input with SHA256 and immutability checks.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: store byte-identical content-addressed input with SHA256 and immutability checks.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Checksum corruption and overwrite-rejection fixtures**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Checksum corruption and overwrite-rejection fixtures. All public contracts documented; no unsupported trust promotion or source mutation introduced.
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

### ING-003 — ImportCoordinator and source deduplication
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `ING-002`, `FND-006`.
**Objective:** Create atomic batch import, snapshot comparison, source ID mapping and resume checkpoints.
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
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: extract text/code/tool/other content variants and attach asset pointers; retain unknown payload.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Unknown content round-trips and missing asset gets explicit warning**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Unknown content round-trips and missing asset gets explicit warning. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### ING-007 — ChatGPT import integrity and audit manifest
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `ING-003`, `ING-005`, `ING-006`.
**Objective:** Compare source raw counts to canonical node/assets, record unsupported fields and fidelity summary.
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
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `TAX-002`, `NRM-004`, `FND-007`.
**Objective:** Define typed primary/secondary assignments with project IDs, evidence windows and approved ID constraints.
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
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `EXT-001`, `EXT-002`.
**Objective:** Extract agreed tasks, open questions and real output artefact IDs/missing asset flags.
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
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `EXT-001`, `EXT-002`, `TAX-003`.
**Objective:** Extract cited games/software/books/people with canonical aliases and type-specific fields.
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
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `EXT-007`, `FND-006`.
**Objective:** Batch typed extractors, stage-specific caching and model/prompt version captures.
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
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `DOC-001`.
**Objective:** Build frontmatter writer, citation anchors, safe slug paths and atomic output.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: build frontmatter writer, citation anchors, safe slug paths and atomic output.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Obsidian YAML parses, same inputs yield byte-identical note**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Obsidian YAML parses, same inputs yield byte-identical note. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

### DOC-003 — Individual conversation knowledge notes
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `DOC-002`, `CLS-004`.
**Objective:** Render summary, classes, accepted/rejected proposals, references, actions and source links.
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
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `DOC-003`, `DOC-004`, `DOC-005`, `DOC-001`.
**Objective:** Generate managed vault paths, preserve manual notes, selectively rebuild affected documents.
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: generate managed vault paths, preserve manual notes, selectively rebuild affected documents.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Manual changes safe, unchanged build causes no file rewrites**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Manual changes safe, unchanged build causes no file rewrites. All public contracts documented; no unsupported trust promotion or source mutation introduced.
**Test evidence required:** failing-case reproduction (if any), focused pytest/contract command and result, fixture name, commit or working-tree reference; unresolved failures remain `BLOCKED`, not `VERIFIED`.

## Phase: Evaluation

### EVAL-001 — Golden corpus fixtures and annotation guide
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `ING-007`, `NRM-004`.
**Objective:** Select/anonymise 30–50 diverse conversations; define expected and forbidden decisions, boundaries and spans.
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
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `EVAL-001`, `ING-007`.
**Objective:** Measure supported node count, branch retention, missing assets and unknown payload audit.
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
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `EVAL-002`, `DOC-006`.
**Objective:** Run local ZIP → classify → extract → master note/search and verify links.
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
**Ordered implementation stages and subtasks:**
1. **Confirm:** Read linked contracts, predecessor output and acceptance criteria; verify dependencies are `VERIFIED`, otherwise mark `BLOCKED` and stop.
2. **Design:** Specify inputs, outputs, persistent IDs and failure states required to: bound ZIP entries, memory, concurrency, tokens, retries and stage deadlines.
3. **Implement:** Add the narrowest domain service/adapter and storage migration or interface changes necessary; preserve immutable evidence and backwards-compatible semantics.
4. **Exercise:** Create deterministic fixture(s) specific to this ticket, including nominal and malformed/boundary input; run verification: **Synthetic overload exits with recorded capped failure**.
5. **Integrate:** Exercise this component through its public interface using fake models/temporary storage; ensure retries, provenance and review states remain bounded.
6. **Finalize:** Run relevant static checks/scoped tests once after last change; record actual command/results, changed files, new decisions and explicitly unimplemented paths.
**Acceptance criterion:** Synthetic overload exits with recorded capped failure. All public contracts documented; no unsupported trust promotion or source mutation introduced.
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
**Priority:** P0 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `DOC-006`, `RET-004`, `OPS-003`.
**Objective:** Compute derivative closure, purge raw/index/FTS/vector/doc cache, verify no-access.
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
**Priority:** P1 · **Initial status:** NOT_STARTED · **Dependencies/blockers:** `ING-010`, `INT-001`.
**Objective:** Accept user-provided transcript or authorised captions with video URI/timestamps and access policy.
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
