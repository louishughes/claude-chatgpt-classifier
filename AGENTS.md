# AGENTS.md — Knowledge Engine Agent Operating Contract

**Applies to all coding agents** (Claude Code, Codex and sub-agents) operating anywhere in this repository. Read root `CLAUDE.md`, `README.md` and `CLAUDE_CODE_HANDOFF_PROMPT.md` for the current stage. This document is an instruction contract, not evidence that any code is implemented.

## Mission

Build a local-first, provenance-preserving knowledge engine that imports source conversations and assets, understands relationships without inventing facts, maintains consistent global classification and temporal decisions, produces traceable Obsidian notes and supports trustworthy search/RAG and future incremental multi-source ingestion.

## Current gate — audit before implementation

**GATE 0 / DOC-RECONCILIATION ONLY:** Existing specifications were copied into `docs/`, and the product owner has added critical requirements for raw images/assets, related/forked conversations, YouTube links/transcripts, social-account registries and repeated full-history reexports. The agent's FIRST task is to cross-read and reconcile the complete specification and return an implementation plan. No runtime application code, migrations or actual import of private material until the owner reviews that plan.

### Mandatory reading order

1. Root `CLAUDE.md` and this file.
2. Inventory `docs/` recursively (include hidden folders and skills); discover actual filename locations.
3. `docs/README.md`, `docs/PRD.md`, `docs/TECHNICAL_REQUIREMENTS.md` and `docs/DATA_MODEL_AND_CONTRACTS.md` (or the discovered equivalents).
4. `docs/ARCHITECTURE.md`, `docs/TEST_STRATEGY.md`, `docs/DECISIONS_AND_HISTORY.md`.
5. `docs/ROADMAP_AND_TICKETS.md`, `docs/TICKETS.csv`, `docs/TICKET_INDEX.md`, ADRs and relevant research.
6. `docs/HANDOFF.md`, status/deferral/session logs and all development/testing/validation/final skills present.
7. Inspect `raw/` structurally, treating it as private read-only source; don't print its conversation text or sensitive filenames to logs.

> **Path reconciliation (audit 2026-10-27):** of the files listed above, `docs/README.md`, `docs/TICKET_INDEX.md`, `docs/HANDOFF.md`, ADR files, `.agent-history/` logs and the Development/Testing/Validation/Final skills did not exist in the repository. `CLAUDE.md`, `AGENTS.md` and `README.md` live at the root, all other specs directly under `docs/`. ADRs now live in `docs/adr/`; the post-audit handoff is `docs/HANDOFF_AFTER_AUDIT.md`; review outputs are in `docs/reviews/` and plans in `docs/plans/`. Root files are authoritative over any nested copy. See `docs/reviews/SPEC_AUDIT.md` §2.

Treat research prose as context, not as a substitute for contracts. The latest explicit product-owner requirements govern proposed spec changes; nontrivial conflicts must be visible in the audit.

## Engineering invariants

| Area | Mandatory rule |
|---|---|
| `raw/` | Read-only; no renaming, cleanup, in-place conversion or commit of private inputs |
| Snapshot | Preserve original bytes, source path (internally), hash, import batch and parser version |
| Identity | Separate import snapshot, logical conversation, message node, image asset, asset occurrence and derived knowledge identities |
| Conversation graph | Preserve DAG/tree and active path vs alternative branches; never splice competing replies |
| Similar conversations | Record typed, evidence-backed links; candidate `forked_from` is not an asserted fact |
| Image | Resolve original bytes and source message/link, deduplicate storage by hash but not reference occurrences; explicit missing state |
| Reexport | Native IDs + hashes + transactional idempotent upsert; full reexport cannot duplicate unchanged logical entities |
| Missing from export | **Unknown**, not deleted |
| YouTube | Detect video reference; transcript job status + provenance; no invented/circumvented transcripts |
| Social account | Maintain source-backed platform/account registry with aliases and ambiguous-identity review |
| External access | Cloud models/network requests disabled unless configured, consented and legally permitted |
| Classification | Governed, versioned taxonomy; classifier does not mint accepted terms |
| Evidence | Preserve who said it, where, when if known and which source revision supports it |
| Decision | Assistant suggestion != user agreement; later timestamp alone != supersession |
| Retrieval | Answer with resolvable source evidence; abstain on insufficient support |
| Export | Generated notes never replace originals or overwrite unmanaged hand edits |
| Failure | A bounded explicit status is preferable to retry/rewrite loops |

## Specification audit requirements

Create a traceability matrix covering these vertical slices and showing `spec → schema → module/method → ticket → test → user-visible output`:

- Source archive and read-only `raw/` filesystem ingestion.
- Complete chat exports / repeated exports / incremental changed nodes / vanished-source semantics.
- Message parent-child paths, branch identity, cross-chat continuation and relatedness.
- Images and other media: attachment parsing, identity, missing files, safe links/embeds, lineage.
- URL extraction, YouTube canonical identity and transcript availability/acquisition modes.
- Social account mention extraction, canonical registry, occurrences, aliases and uncertainty.
- Controlled taxonomy, topical segmentation and cross-conversation classification.
- Typed knowledge extraction, decisions, historical/current projections and reconciliation.
- Search, RAG, rendered conversation notes, project/topic masters and Obsidian link validation.
- Security, privacy, source trust, operations, backups, idempotency and evaluation.

For **each uncovered requirement**, propose:
1. PRD requirement + scope (P0, P1, P2) and exact acceptance check.
2. Data records/keys/constraints and any state transitions.
3. Services/classes/method contracts and who calls whom.
4. Deterministic tests, adversarial cases, and source-to-output end-to-end fixture.
5. Implementation ticket(s) with unique ID, dependency IDs, stages, done condition and risk.

Explicitly reconcile existing work items: `ING-*`/`NRM-*`/`REC-*`/`EXT-*`/`DOC-*` if present, and `INT-002` (currently a later YouTube transcript input workflow). Do not silently assume an existing ticket adequately covers image relationships, social identities or cross-export identity reconciliation.

## Planned storage/contract distinctions to verify

- `ImportBatch`: each import attempt, original input, timestamp, hash and diagnostics.
- `SourceSnapshot`: immutable input revision; identical hash can be reused safely.
- `Conversation`: stable logical identity scoped to source system/account/workspace, not title.
- `MessageNode`: native message ID, graph relationships, role, content and revision lineage.
- `BranchEdge` / `ConversationRelationship`: native edges are authoritative; inferred relationships are proposed until supported/reviewed.
- `MediaAsset`: content hash, media type, byte availability and safe storage pointer.
- `AssetOccurrence`: message- or document-span-specific reference to an asset, including missing references.
- `ExternalLinkOccurrence`: exact original URL, source span, normalised target and mention context.
- `YouTubeVideo` + `TranscriptSnapshot` + `TranscriptCue` + `TranscriptAcquisition`: link identity, retrieval provenance, statuses, cue times.
- `SocialAccount` + `SocialAccountMention` + `AccountAlias`: deduplicated identity, platform and observed references.
- `KnowledgeRecord` + `EvidenceRef` + `ReviewDecision`: evidence-backed claims with change/acceptance history.

These are **proposed** concepts to reconcile into the actual existing schema, not a demand for duplicate competing tables. Prefer minimal models that preserve the distinctions.

## Deduplication policy (non-negotiable)

1. Repeated ZIP/raw file bytes: same content-hash snapshot identity; retain provenance of each import attempt.
2. Same logical conversation native ID across exports: one logical conversation, multiple imported snapshots/versions.
3. Same native message ID + same content hash: same logical message revision; no duplicate derived work.
4. Same native message ID + changed payload: store an immutable new revision and flag for reconciliation.
5. New node/branch in existing conversation: attach without disturbing earlier lineage, reprocess affected descendants.
6. Same image bytes across sources: one content-addressed blob (when safe), multiple occurrence links.
7. Same video ID/account: canonical entity may be shared, but each source mention stays independent.
8. Similar title/text/visual appearance without authoritative ID: propose a relationship; NEVER delete, overwrite or auto-collapse independent sources.
9. Incompletely parsed input: state limitations; reimport is resumable and cannot mark partial import as fully successful.
10. Concurrent/retried jobs: enforce DB uniqueness, transaction boundaries and idempotency keys.

## Documentation, decisions and status

The audit must create/update:

- `docs/reviews/SPEC_AUDIT.md` — evidence-based gaps, contradictions, fixes, severities and file references.
- `docs/reviews/REQUIREMENTS_TRACEABILITY.md` — complete matrix.
- `docs/reviews/SPEC_CHANGELOG.md` — changed files, reason, which requirement resolved, any compatibility impact.
- `docs/reviews/OPEN_DECISIONS.md` — explicit unresolved choices with recommended default and cost of alternatives.
- `docs/plans/IMPLEMENTATION_PLAN.md` — dependency-aware phases, MVP vertical slice and numbered order.
- `docs/plans/DEPENDENCY_MAP.md` — existing/new ticket IDs and their blockers; confirm DAG has no cycles.
- `docs/HANDOFF_AFTER_AUDIT.md` — actual changes/test evidence/not-done/first unblocked ticket.

Existing ADRs, decision logs, ticket CSV and Markdown roadmap must remain reconciled. Preserve original ticket IDs; append new stable IDs (for example new distinct `MED-*`, `LNK-*`, `SOC-*` ticket groups only if unused and warranted). If an old acceptance criterion is revised, include rationale and backwards-reference, not silent history rewriting. **Don't report work as completed because a document describes it.**

## Bounded execution and testing rules

- Audit first: documentation change set only. Only safe, read-only repository inspection and documentation checks. Do not import/rewrite user data, invoke paid models or fetch YouTube URLs during the audit.
- Future ticket work: confirm blockers `VERIFIED`, implement only bounded scope, use fixtures and deterministic tests first.
- Max one focused implementation repair after a genuine test failure, then record blocker with failing command and stop. Max three transient external attempts in any future connector job; no repeated semantic retries to force classification.
- Don't start a new tooling framework, dependency replacement, network crawler or autonomous sub-agent swarm in response to a small spec inconsistency.
- Validate only what actually ran. Report skipped/not-applicable/not-implemented items distinctly from failed tests.
- Current milestone complete when all specified audit outputs exist, major contradictions are either corrected or explicitly open, dependent tickets are reconciled, and a coherent plan is ready for user approval.

## Agent response format

At end of the audit provide: documents inspected; highest-impact gaps; exact documents/tickets changed; new P0 requirements; open owner decisions; plan phase order; first implementation ticket; checks actually performed; work explicitly **not** done. Then **STOP** pending owner approval to implement.
