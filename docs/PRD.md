# Product Requirements Document (PRD)
**Product:** Knowledge Engine. **Version:** 1.0 specification. **Status:** Planned. **Owner:** Product owner. **Primary platform:** local desktop/server plus Obsidian export. **Goal:** trustworthy, continuously evolving personal knowledge without source-context loss.

## 1. Problem statement
Large conversational archives are difficult to navigate, contain branching and cross-topic discussions, and evolve over time. Independent LLM summarisation drifts vocabulary and misclassifies exploratory proposals as accepted decisions. Existing general-purpose note/RAG tooling does not sufficiently guarantee a globally governed ontology, actor-attributed evidence and temporal project state. The product must preserve the archive, extract structured knowledge, connect discussions, and make it useful through searchable notes and evidence-backed answers.

## 2. Target users and jobs-to-be-done
- **Solo researcher/creator:** recover decisions, themes, constraints, abandoned ideas and next actions spanning years of conversations.
- **Knowledge librarian/reviewer:** approve aliases, merge concepts, resolve uncertain claims, inspect source anchors, assess processing quality.
- **Collaborator (later):** import project documentation, ask scope-filtered questions with permissions, view decision provenance.
- **Workspace administrator (later):** control retention, deletion, access, integrations and audit.

## 3. User journeys
1. **Archive:** upload a ChatGPT export ZIP; see inventory, counts, import warnings, active/default branch and alternate branches; rerun without duplicates.
2. **Classify:** discover recurring projects/concepts globally; approve canonical taxonomy; classify topical segments with primary and secondary topic IDs.
3. **Trace:** inspect a decision and jump to exact user/assistant/source evidence; distinguish proposal, acceptance, reversal and uncertainty.
4. **Explore:** filter by project, category, date, source type, named reference, status and keywords; show related conversations with relationship explanations.
5. **Synthesize:** generate conversation notes, project masters and selected topic masters, each with cited current view and separate historical section.
6. **Ask:** request a topic/decision/current-state answer; return source references, uncertainty and disagreement where necessary.
7. **Extend:** import newer export/doc/video transcript; selectively reprocess changed nodes and regenerate dependent notes; preserve manual edits.
8. **Review:** work through proposed taxonomy terms, ambiguous decisions, failed evidence checks and unresolved contradictions.
9. **Re-export *(added 2026-10-27)*:** import a fresh full-history export that repeats almost everything; see a delta report (new, unchanged, revised, new branches, new media, missing assets, candidate duplicates, failed) and no duplicate conversations, messages or model calls.
10. **Browse sources *(added 2026-10-27)*:** open any conversation as an LLM-free source note showing the active path, alternate branches, images (or honest missing markers), links and related chats, before any classification exists.
11. **Follow references *(added 2026-10-27)*:** list every YouTube video and social account mentioned across the archive, with each citing message, and the transcript status of each video.

## 4. MVP scope (P0)
- Versioned ChatGPT export parser: ZIP, one/multiple numbered JSON files, messages, speaker roles, timestamps, parent/child mappings, active path and alternatives, raw/unknown content.
- Archive snapshot identity/hash, reimport diff, stable IDs, import manifests, structured warning report.
- Multi-topic segmentation with message-range evidence.
- Global discovery proposal pass; approved domain/category/topic/project registry with aliases and versions; locked vocabulary during classification.
- Typed records: `fact`, `proposal`, `decision`, `rejection`, `preference`, `requirement`, `idea`, `question`, `action`, `artefact`, `reference`, `recommendation`.
- Evidence span validation, speaker attribution, uncertainty/review states, chronology and explicit scope-aware supersession.
- Individual Markdown conversation notes and project/topic masters with Obsidian-compatible YAML and source backlinks.
- Exact full-text and metadata search, optional embedding search and grounded response via configured model provider.
- CLI and minimal review/API endpoints; golden benchmark, reproducibility versions and bounded processing jobs.
- *(Added 2026-10-27, see FR-25..FR-36.)* Read-only ingestion of the actual `raw/` layout (official export ZIP/folder and the split-wrapper directory), media blob/asset/occurrence linkage with honest missing states, native branch kinds, cross-conversation relationship candidates, logical identity across re-exports with delta reporting, deterministic URL/YouTube/social registries with transcript status, source-level browsing, and 50/100-conversation batch smoke gates.

## 5. Next release scope (P1)
- PDF/DOCX/Markdown/web transcript import adapters; YouTube transcript supplied by user or acquired through authorised interfaces.
  - *Audit amendment 2026-10-27:* YouTube **detection, canonical identity, mention provenance and transcript status** are now P0 (FR-31, FR-32). Only network transcript acquisition (INT-002) stays P1.
- Relationship-assisted exploration, batch review UI, human correction longevity, live master-document dependency propagation.
- Per-stage cost/token estimates, compare model policies on benchmark, export/import project bundles.

## 6. Later scope (P2)
- Multi-user and permissioned workspaces; shareable knowledge collections; user-managed provider keys; hosted deployment; retention policies; SSO/integrations; commercial frontend and audit UI.

## 7. Explicit non-goals for MVP
- Replacing Obsidian; magically recovering deleted/inaccessible conversations or assets; unrestricted web crawling; full autonomous taxonomy approval; invented decisions; guaranteed zero hallucination; perfect reconstruction of multimedia not present in exports; graph database, message bus, distributed microservices, autonomous agent swarms and payment infrastructure.

## 8. Functional requirements
| ID | Priority | Requirement | Acceptance |
|---|---|---|---|
| FR-01 | P0 | Import original ChatGPT export(s) | Every supported conversation/message preserved with stable anchors; omissions explicitly counted |
| FR-02 | P0 | Maintain immutable snapshots | Source byte hash verified after import; no overwrite |
| FR-03 | P0 | Preserve branching topology | Parent/child and selected branch reconstructed without false merge |
| FR-04 | P0 | Idempotent reimport | Unchanged import creates zero additional logical sources/records |
| FR-05 | P0 | Segment multi-topic discussions | User-reviewed boundary evaluation and manual split/merge supported |
| FR-06 | P0 | Discover corpus themes | Generates candidate topics/projects; does not auto-approve |
| FR-07 | P0 | Govern canonical taxonomy | Stable IDs, aliases, version, approved/proposed/rejected and audit history |
| FR-08 | P0 | Multi-axis classification | Assign project/domain/category/primary and secondary topics using approved IDs |
| FR-09 | P0 | Evidence-grounded extraction | Every confirmed assertion has actor, source span, extraction version |
| FR-10 | P0 | Distinguish speech acts | Never silently promote assistant idea into user's accepted decision |
| FR-11 | P0 | Historical and current views | Preserve revisions and explain current state with evidence, including unknown |
| FR-12 | P0 | Track actions and artefacts | Status, dependencies, output references and missing assets |
| FR-13 | P0 | Generate Obsidian Markdown | Valid flat frontmatter, source backlinks, safe filenames |
| FR-14 | P0 | Generate project/topic masters | Query source records, separate current decisions/history, cite each material claim |
| FR-15 | P0 | Search/filter | Filters over approved concepts, exact terms, source type and dates |
| FR-16 | P0 | Evidence-backed QA | Answer only from permitted retrieved source evidence; abstain when insufficient |
| FR-17 | P0 | Incremental regeneration | Changed record invalidates only affected document/search dependencies |
| FR-18 | P0 | Review queue | Expose unresolved classifications, contradictions, unsupported evidence |
| FR-19 | P0 | Processing observability | Persist stage jobs, status, versions, errors and retry counts |
| FR-20 | P0 | Reproducibility | Record provider, model identifier, prompt version, taxonomy and code version |
| FR-21 | P1 | Additional source adapters | Testable adapter contract with explicit fidelity report |
| FR-22 | P1 | Editing protection | Preserve user-authored notes/regions on re-export |
| FR-23 | P2 | Workspace permissions | Enforce at every retrieval/derivative and export operation |
| FR-24 | P2 | Deletion/retention | Locate and purge derivatives with testable deletion manifest |

### 8a. Requirements added by the 2026-10-27 specification audit
Source: product-owner work order of 2026-10-27 and CLAUDE.md §2 A–D. Traceability: `docs/reviews/REQUIREMENTS_TRACEABILITY.md`.

| ID | Priority | Requirement | Acceptance |
|---|---|---|---|
| FR-25 | P0 | Read-only ingestion of the actual raw layout | Official export (ZIP or folder, single or sharded JSON) and split-wrapper directory both import; `raw/` tree hash identical before and after; derived/non-conversation files reported, not parsed |
| FR-26 | P0 | Media as blob, asset and occurrence | Same image bytes in N messages = 1 blob, N occurrences; states `available/missing/unresolved/ambiguous/unsupported` with evidence; thumbnails separate from originals; no OCR/vision by default |
| FR-27 | P0 | Resolvable media links in notes | Every available image link in generated notes resolves; missing ones render an explicit marker naming pointer and reason |
| FR-28 | P0 | Native branch kinds | Fork points classified `edit`/`regeneration`/`other`; active path from `current_node`; no transcript splices siblings |
| FR-29 | P0 | Cross-conversation relationships | Typed, directional `continues/forked_from/quotes/references/related_to/same_project` links with evidence class, confidence, review state and history; similarity alone never yields `continues`/`forked_from`; nothing merged by similarity |
| FR-30 | P0 | Logical identity and delta across re-exports | Native-ID-first identity with account namespace; delta categories reported per import; identical reimport = zero new logical records and zero model calls; absent conversation = `not_seen`, never deleted; ID collisions become review candidates |
| FR-31 | P0 | URL occurrence registry | Every URL occurrence stored with exact span, context, actor, origin and canonical target; repeated URLs keep every occurrence |
| FR-32 | P0 | YouTube video registry and transcript status | Supported URL forms canonicalised to one video per ID; original URL, timestamp and playlist kept; transcript status tracked; user-supplied transcripts attach with cues and provenance; no invented transcripts |
| FR-33 | P0 | Social account registry | Profile URLs and platform-qualified handles create source-backed mentions in a deduplicated, browsable registry; bare `@name` stays ambiguous; no crawling or contact |
| FR-34 | P0 | Source-level browsing before semantics | CLI inspect and LLM-free source notes for conversations, branches, media, links and related chats |
| FR-35 | P0 | Batch-scale smoke gates | Import path smoke-tested at 50 and 100 conversations in M1; semantic path at 50 and 100 in M3, with timings, failures and stability recorded |
| FR-36 | P0 | Type-safe model output | Every model output validated against a generated JSON Schema before persistence; one repair attempt then review; pinned model/prompt versions; run-to-run stability measured |
| FR-37 | P1 | Corrections survive re-export | Reviewer overrides persist on unchanged content and become review items when content changes |

## 9. Success metrics and gates
These targets are *proposed*, to be calibrated against a human-reviewed 30–50-conversation benchmark. Import integrity: 100% supported nodes accounted for or flagged. Schema-valid committed records: 100%. Reimport idempotency: zero duplicates. Unsupported user decisions: zero in release benchmark. Primary category (= primary domain, see OD-17) agreement >=90%; explicit decision recall >=90%; asserted relationship precision >=90%; Recall@10 >=90% on benchmark; exact evidence anchor validity 100%. Report precision/recall **per type**, not a single inflated score.

## 10. UX and reports
- **Import dashboard:** source counts, nodes, branches, attachments, parser warnings and stage timings.
- **Corpus explorer:** taxonomy tree, facets, project selectors, segment previews and source anchors.
- **Review queue:** actor/source assertion side-by-side; approve, reject, correct or defer.
- **Timeline:** current state atop chronological proposals/decisions and supersession links.
- **Master generator:** specify topic/project and `current`, `historical`, `all` modes; preview dependencies.
- **Search/Q&A:** cited evidence chips; show retrieval method, filters and unknown/conflict outcomes.

## 11. Constraints and assumptions
- Local-only by default; outbound model requests require configured permission and documented handling of private data.
  - *Audit amendment 2026-10-27 (proposed, ADR-0007, OD-04):* the owner stated the workflow need not be 100% local. Proposed reading: the source layer stays deterministic and local; semantic stages may use cloud models once `text_llm` egress is enabled in the workspace profile; image/vision upload and URL/transcript fetching remain separate explicit switches. The default in code stays "off" until the owner confirms.
- Text is first-class; non-text material is preserved and separately marked until a suitable extraction stage supports it.
- A single conversation may contribute to multiple projects/topics.
- Absence of a record is *unknown*, not proof of a negative.
- Taxonomy approval remains controlled; system may recommend reviews rather than block the entire import.

## 12. Launch exit conditions
Milestone M1: real export can import, preserve branches/unknown fields, inspect evidence and reimport idempotently *(audit 2026-10-27: M1 now also covers media occurrences, delta report, source browsing and 50/100 batch smoke; link/YouTube/social registries form M2; see `docs/plans/IMPLEMENTATION_PLAN.md`)*. M2: golden extraction/classification produces correct actor attribution and current/historical decision state. M3: Obsidian export and query/search return traceable sources. M4: incremental import only updates affected derivatives. M5: multi-user isolation and privacy release checks (later).

## 13. Outstanding product decisions
- Which model/provider can receive private source text and at what cost? **Unresolved; configurable.**
- What is the authoritative list of categories? **Discover on sample corpus and approve.**
- Should Obsidian edits be one-way or bi-directionally synced? **Default one-way generated notes + separate manual edits.**
- Offline embeddings versus paid API embeddings? **Benchmark both; design provider interface.**
- How are project merges/rebrands reviewed? **Manual review for high impact.**
- Is all imported data user-owned and licit to process? **Explicit per-workspace attestation in future product.**
- *(Added 2026-10-27)* Further open choices (original export availability, media storage mode, account namespace, cloud provider, transcript sources, tracker of record, Obsidian attachment strategy, packaging/licensing) are tracked in `docs/reviews/OPEN_DECISIONS.md`.
