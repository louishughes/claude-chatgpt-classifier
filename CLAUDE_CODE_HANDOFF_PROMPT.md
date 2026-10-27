# First Claude Code Session — Specification Audit, Reconciliation and Implementation Plan

Copy the prompt below into Claude Code from the **repository root** (the directory that contains `CLAUDE.md`, `AGENTS.md`, `docs/` and `raw/`). This is an actionable work order, not a description of an already implemented system.

---

## PROMPT START

You are the lead software architect, principal Python engineer, knowledge-engineering specialist, technical product manager and critical specification reviewer for this repository.

**Your immediate assignment is to AUDIT and RECONCILE the existing specification, make controlled documentation improvements, and produce a complete, dependency-ordered implementation plan. DO NOT implement the application during this session.**

### 0. Ground rules

Read root `CLAUDE.md`, `AGENTS.md` and `README.md` completely before proceeding. Follow their rules throughout. Work with **actual repository state**, not assumptions about which files exist. The `docs/` directory contains an extensive previous PRD, architecture, requirements, test plans, decision history and backlog; it may include nested folders, ADRs, agent skills and an existing handoff. The `raw/` directory contains real conversations, exports and images. **It is private and immutable: inspect file structures safely, do not rename/change/delete/import/print sensitive content.**

If a conflict exists between older documents and the latest product-owner requirements in this prompt, flag it and propose or implement the appropriate *documentation* amendment. Record the rationale. Do not retroactively erase accepted decisions. Do not pretend a requirement is already implemented because a ticket exists.

Do not ask me to restate things that are already in the documents. Proceed with reasonable, labelled assumptions where possible, and surface decisions requiring owner input at the end.

### 1. Understand the complete product and its existing plan

Recursively inventory and read the relevant contents of `docs/`, not merely the headings:

- PRD and research report.
- Technical requirements and architectural diagrams.
- Data models, Pydantic DTOs, method/class signatures, state machines, provenance and API contracts.
- Development roadmap, all existing tickets and `TICKETS.csv` dependency columns; check Markdown/CSV parity.
- Unit/integration/e2e/golden evaluation strategy and quality gates.
- Decisions, history, ADRs, status/deferral/session logs and handoff.
- AGENT/AGENTS, CLAUDE, READMEs, prompts and available Development/Testing/Validation/Final skills (including hidden directories).

Report inventory coverage and missing/duplicate/contradictory sources. Check whether paths in old agent instructions still work now that the documents live under `docs/`. Resolve root-vs-nested agent file authority in the proposed documentation edits; don't delete historical files merely because they're duplicated.

### 2. Critical new product requirements — all must be explicitly specified

**2.1. `raw/` contains both conversations AND images.**

Support direct ingestion of the available original folder structure and re-export ZIPs. Maintain byte-level immutable import snapshots and fidelity reports. Model images and other attachments as separate addressable assets plus message-specific *occurrences*. Distinguish original image bytes from thumbnail/derived metadata, available from missing/unknown, and asset storage deduplication from preserving every contextual link. Map source message → asset → safe generated note/embed; clicking an image in Obsidian should have a resolvable path or an honest missing marker. Keep original conversations, roles, message IDs, timestamps, content types and source anchors. Raw input must remain untouched and untracked by Git. No cloud vision/OCR by default.

**2.2. Conversations are related in two fundamentally different ways.**

A single ChatGPT conversation can contain *native branches* (edits/regenerated responses). Store full message graph with active/default path and alternate edges; avoid flattening into a fictional chronological chat.

Separate ChatGPT conversations may be semantically similar, share a project, quote or continue another discussion, or plausibly be a manually created fork. Store explicit typed relationships and their evidence, direction, confidence/review state and provenance. Proven continuation/fork links are distinct from similarity-only candidates. Display related chat links on conversation/project/topic notes and make them retrievable. No destructive merging based on semantic similarity.

**2.3. Reimport and duplicate management are central MVP requirements.**

I will periodically export my entire ChatGPT history again. The next archive may repeat virtually everything already imported and add a handful of chats, messages or image assets. Design **idempotent, transactional, incremental ingestion**:

- ImportBatch identity (every attempt), exact file/snapshot hashes, parser/version/checkpoints.
- Stable logical conversation identity by source-native ID (with account/workspace namespace); handle ID absence/collision conservatively.
- Stable native message ID and immutable revisions; graph edge changes/alternate branch detection.
- Byte-identical asset deduplication while retaining *all* source occurrences.
- Exact unchanged skip, newly added messages, changed message payloads, imported branch additions and derived-dependency invalidation.
- Source disappearance from later export = NOT proof of deletion.
- Avoid unnecessary LLM reruns on unchanged content; human corrections survive incremental reprocessing.
- Support interrupted import recovery, double import and concurrent job race conditions.
- An understandable per-import delta report: `new`, `unchanged`, `revised`, `new_branches`, `new_media`, `missing_assets`, `candidate_duplicates`, `failed` and document/index regeneration footprint.

No fuzzy automatic merge by title, textual similarity or apparent visual resemblance; use candidate links/review instead. Design golden fixtures proving rerun produces zero logical duplicates.

**2.4. Detect every YouTube link and support transcript enrichment.**

Extract source-backed URL occurrences from chat/document content. Recognise standard watch links, short links, Shorts and live URLs. Canonicalise video IDs without losing original URL, timestamp, playlist context and exact message/source span. A new video reference creates a tracked item for optional transcript acquisition. Architect an authorised, rate-limited, opt-in transcript acquisition pipeline (user-supplied transcripts first; other legitimate services only if permitted). Keep status for not-requested, queued, succeeded, unavailable, permission-required, and failure. Capture language, transcript provenance and timed cues. Link transcript and cues to the video entity and all conversation messages that referenced it. Never fabricate a transcript or work around access restrictions. Consider no-network default and cost/privacy implications.

**2.5. Detect and catalogue social-media accounts.**

Where any conversation/document references a social profile URL or an unambiguous account handle, extract and preserve a source-backed account mention. Build a browsable account registry (platform, stable ID if known, handle/URL, display name if evidenced, aliases, first/last seen, reference counts, all citing conversations/spans, review/uncertainty). Normalize duplicate references without losing occurrences. A non-specific `@handle` must not be asserted as an identified real account when platform/identity are ambiguous. Account registry extraction does NOT authorise crawling profiles or contacting people.

**2.6. Existing core requirements must remain intact.**

Global taxonomy discovery and governance; topical segmentation; controlled primary/secondary topic classification; evidence-backed decisions/actions/likes/references/artifacts; historical/current state and supersession; master topic/project documents; search/RAG with source citations; Obsidian YAML/frontmatter and backlinks; versioned provenance, constrained agent execution and future multi-user capability.

### 3. Perform a rigorous gap and conflict audit

Cross-reference the above requirements against every existing spec. For each requirement, find:

`Product requirement → explicit PRD FR → technical constraint → data table/DTO/indices → service/class/function → pipeline event → roadmap ticket and blockers → fixture/tests/metric → observable CLI/API/UI/Obsidian output`.

Create a traceability table. Mark status `covered / partially covered / missing / conflicting / deferred`, scope `P0/P1/P2`, severity and precise document section or ticket references. Do not mark a requirement covered merely because it is vaguely mentioned. Look especially at media/asset lineage, branch identity, cross-chat relationships, repeat export identity and URL/account extraction. Determine which existing tickets (`ING-*`, `NRM-*`, `EXT-*`, `REC-*`, `DOC-*`, `INT-002`, etc.) need expansion, splitting, resequencing or new prerequisites.

Audit other architectural risks too: raw folder permissions, large/streamed JSON input, missing native IDs, malformed graph, missing image bytes, unreliable link matching, rate limits/transcript access, privacy/security, parser version drift, export schema drift, taxonomy drift, dedup concurrency, checkpoint rollback, Obsidian attachment links, prompt injection, testing time/cost and event dependency cycles.

For major concerns, recommend a primary solution **plus** practical alternatives/trade-offs, deterministic acceptance checks, and a failure/fallback state. Identify explicit decisions only the product owner can make.

### 4. Make controlled improvements to documentation (not source code)

Edit existing specifications to incorporate indisputable omissions and bring cross-references into alignment. You may edit Markdown specifications, CSV backlog and documentation-only diagrams/templates; do not implement `src/`, DB migrations, app endpoints, clients, ingestion jobs, provider calls or runtime code. Preserve meaningful original content; avoid destructive rewrites.

Where new class/function contracts are required, specify precise responsibilities, inputs/outputs, error states and explanatory pseudocode comments. Where tables/indices or events are needed, describe constraints and transactional responsibilities. Where acceptance criteria are missing, add concrete tests. Update backlog ticket ordering, blockers and implementation stages. Keep all prior ticket IDs stable; any new IDs must be unique and have dependency edges that form an acyclic graph. Keep `TICKETS.csv` consistent with the ticket Markdown and explain tickets that have changed scope/priority.

Log every meaningful spec edit with old/new section, rationale and implications. For architectural changes create an ADR; preserve historical decisions and explicitly label proposed alternatives. If a conflicting requirement genuinely needs owner input, leave a clearly documented open decision with a recommended default rather than silently pretending it is agreed.

**Prioritisation:** The first useful vertical slice must verify read-only `raw/` import, source/message provenance, native branch graph, available image linkage, full-history reimport idempotency and source-level browsing **before** any LLM semantic pipeline. URL/social link capture should follow the same source-span foundation; transcript acquisition may be phased, but YouTube detection/provenance/status must not be omitted.

### 5. Create a concrete engineering plan

Write a comprehensive implementation plan, not a vague outline. Include:

1. Resolved target folder tree and module boundaries.
2. Dataflow from raw source to normalised nodes, media/link registries, knowledge records, retrieval and Obsidian.
3. Named core classes/functions for each new/altered subsystem, with method signatures/comments and ownership boundaries.
4. P0/P1/P2 phased milestones and explicit integration gates.
5. Ordered ticket list (existing and added), dependency graph, critical path, estimates if defensible, test fixtures, acceptance criteria and definition of done.
6. Exact first vertical slice and its CLI-level or fixture-based demonstration.
7. Unit, property-based, integration, golden-set and end-to-end tests; include duplicate-import, changed branch, repeated image, missing asset, misidentified account, unavailable YouTube transcript, repeated links and unrelated-but-similar conversation cases.
8. Verification strategy with bounded retries and no infinite test/refactor loops.
9. Decision/ADR/change log handling and accurate not-started/not-tested/blocked/deferred accounting.
10. Explicit implementation/non-implementation boundaries and human approval points.

The plan should be practical for a coding agent to execute one blocked-free ticket at a time. Don't claim a ticket is complete based on proposed code.

### 6. Required deliverables (actual repository files)

Produce or update these, creating directories if needed:

```text
docs/reviews/SPEC_AUDIT.md
docs/reviews/REQUIREMENTS_TRACEABILITY.md
docs/reviews/SPEC_CHANGELOG.md
docs/reviews/OPEN_DECISIONS.md
docs/plans/IMPLEMENTATION_PLAN.md
docs/plans/DEPENDENCY_MAP.md
docs/HANDOFF_AFTER_AUDIT.md
```

Also update the relevant existing `docs/PRD.md`, `docs/TECHNICAL_REQUIREMENTS.md`, `docs/ARCHITECTURE.md`, `docs/DATA_MODEL_AND_CONTRACTS.md`, `docs/ROADMAP_AND_TICKETS.md`, `docs/TICKETS.csv`, `docs/TEST_STRATEGY.md`, `docs/DECISIONS_AND_HISTORY.md`, ADRs and skill instructions **only insofar as needed**. If actual paths differ, reference actual locations and explain. Use separate files rather than stuffing the entire result into a chat answer.

### 7. Verification and final response

Run only finite, relevant document integrity checks: existing references/paths, ticket ID uniqueness, ticket dependencies (no missing blockers or cycles), CSV/Markdown ticket agreement, traceability completeness, no accidental raw-folder writes, Git diff confined to intended docs, and no invalid assumptions about absent source files. If a tool cannot check one, report NOT RUN rather than inventing success. Do not invoke paid providers or fetch outside URLs during this stage.

In the final response tell me: (a) what you examined, (b) the most important gaps, (c) which documents and tickets changed, (d) what remains undecided, (e) the revised implementation phases and earliest unblocked task, (f) checks actually passed/failed/not run, and (g) what has not been implemented.

**Then STOP. Ask for my approval before commencing implementation. No unbounded loops, no self-directed architectural rewrites, and no automatic transition to FND-001 or coding tickets.**

## PROMPT END
