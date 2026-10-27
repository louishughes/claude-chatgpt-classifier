# Requirements Traceability Matrix

**Date:** 2026-10-27. Chain per row: owner requirement → PRD FR → technical requirement → data (tables/DTOs) → service/class → event → tickets → tests/fixtures → observable output.

- **Before** = coverage in the specs before this audit: `covered`, `partial`, `missing`, `conflicting`, `deferred`.
- **After** = coverage in the specs after the audit edits. `specified` means every link of the chain now exists **on paper**. Nothing is implemented; every ticket is `NOT_STARTED`.
- Section references: PRD §8/§8a, TR = `TECHNICAL_REQUIREMENTS.md`, DM = `DATA_MODEL_AND_CONTRACTS.md`, AR = `ARCHITECTURE.md`, TS = `TEST_STRATEGY.md`.

## A. Raw conversations and images

| ID | Owner requirement | PRD | TR | Data | Service / class | Event | Tickets | Tests / fixtures | Output | Before | After | P |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| A.1 | `raw/` is read-only; never renamed, cleaned, rewritten | FR-25, FR-02 | TR-13, TR-08 | `raw_roots.read_only`, `last_tree_hash` | `RawInventory.tree_hash` | `ImportBatchStarted` | SRC-001, ING-001, OPS-008 | TS §12.2 raw safety; tamper fixture | `ke raw inventory` report; tree hash in delta report | partial | specified | P0 |
| A.2 | Ingest the actual folder structure and re-export ZIPs (JSON/ZIP/split) | FR-01, FR-25 | TR-13 | `source_files.role` | `ChatGPTExportAdapter`, `ChatGPTSplitWrapperAdapter` | `ImportBatchStarted` | ING-004, ING-011, ING-002 | `export_single/sharded/zip`, `split_wrapper`, `derived_files` | import summary per format | missing | specified | P0 |
| A.3 | Byte-level immutable snapshots and fidelity reports | FR-02, FR-01 | TR-01, TR-12 | `source_snapshots`, `source_files`, `import_batches` | `ImportCoordinator`, `IntegrityChecker` | `SourceImported` | ING-001, IMP-001, ING-007 | checksum/overwrite fixtures; fidelity counts | fidelity section of delta report | partial | specified | P0 |
| A.4 | Preserve speaker, timestamps, message IDs, content types, unknown fields, source anchors | FR-01, FR-03 | TR-01 | `message_revisions`, `content_nodes.raw_ref` | native mapping parser, `CanonicalNormaliser` | `ConversationDeltaCommitted` | ING-005, ING-006, NRM-001 | unknown-content round-trip; content-type list from real data | `ke inspect conversation` | covered (children assumption wrong) | specified | P0 |
| A.5 | Images as separate addressable assets + message-specific occurrences | FR-26 | TR-13 | `media_blobs`, `media_assets`, `asset_occurrences` | `MediaStore` | `MediaOccurrencesCommitted` | MED-001, MED-003 | `repeated_image` | asset view in inspect | partial | specified | P0 |
| A.6 | Original bytes vs thumbnail/derived metadata | FR-26 | TR-13 | `derived_media` | `MediaStore` | — | MED-001 | schema test: derived never replaces original | — | missing | specified | P1 |
| A.7 | Available vs missing/unknown; no fabricated paths | FR-26, FR-12 | TR-13 | `asset_occurrences.availability`, evidence | `AssetPointerResolver` | `MediaOccurrencesCommitted` | MED-002, EXT-005 | `missing_asset`, `ambiguous_asset`, `unresolved_pointer` | `missing_assets` count; markers | partial | specified | P0 |
| A.8 | Storage dedup without losing contextual links | FR-26 | TR-13 | unique blob hash; unique occurrence key | `MediaStore.record_occurrence` | — | MED-003 | `repeated_image`; reimport zero new | `duplicate_assets` count | partial | specified | P0 |
| A.9 | Source message → asset → safe note/embed; clickable or honest marker in Obsidian | FR-27 | TR-07, TR-13 | `MediaStore.vault_path` | `SourceNoteBuilder`, `MarkdownRenderer.check_links` | `DocumentsInvalidated` | MED-004, BRW-001, DOC-003, DOC-006 | link checker over rendered fixtures | Obsidian embed or `missing` marker | missing | specified | P0 |
| A.10 | Raw input untracked by Git | — | TR-13 | — | git guard | — | OPS-008 | guard test | CI/pre-commit failure | partial (.gitignore only) | specified | P0 |
| A.11 | No cloud vision/OCR by default; consent-gated | FR-36 (egress) | TR-08, TR-13 | settings `vision` | `StructuredModelProvider` egress check | — | FND-002, FND-009 | egress-denied test | `egress_denied` status | partial | specified | P0 |

## B. Branches and related conversations

| ID | Owner requirement | PRD | TR | Data | Service / class | Event | Tickets | Tests / fixtures | Output | Before | After | P |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| B.1 | Full message DAG; active/default vs alternates; never flatten | FR-03, FR-28 | TR-01, TR-15 | `graph_edges`, `branch_points` | `BranchClassifier.active_path` | `ConversationDeltaCommitted` | ING-005, NRM-002, REL-001 | `branches_edit`, `branches_regen`, `no_children` | branch view; labelled alternates in source notes | partial | specified | P0 |
| B.2 | Distinguish edited vs regenerated alternatives | FR-28 | TR-15 | `branch_points.kind` | `BranchClassifier.classify_fork` | — | REL-001 | edit/regenerate fixtures | branch kind labels | missing | specified | P0 |
| B.3 | Typed cross-conversation links (identity, anchors, project, entities, similarity) with explanation and evidence | FR-29 | TR-15 | `conversation_relationships` | `StructuralRelationshipDetector`, REL-003 service | `RelationshipCandidateProposed` | REL-002, REL-003 | `copied_prefix`, `similar_unrelated` | `ke relations --candidates` | partial (record-level only) | specified | P0 |
| B.4 | `continues` / `forked_from` / `related_to` proposals; no fork claim from similarity | FR-29 | TR-15 | `evidence_class`, `review_state` | detectors | `RelationshipCandidateProposed` | REL-002, REL-003 | similarity never yields fork | candidate list with reasons | missing | specified | P0 |
| B.5 | Directionality, scope and history of approvals/rejections | FR-29 | TR-15 | `relationship_reviews` | review service | — | REL-002, REL-004 | append-only history test | review history view | missing | specified | P0 |
| B.6 | Related discussions shown in notes and retrieval | FR-29 | TR-06, TR-15 | — | `ConversationNoteBuilder`, `HybridRetriever` | `DocumentsInvalidated` | REL-004, DOC-003 | rendered fixture shows related section | "Related conversations" section | partial | specified | P0 |

## C. Repeated exports and deduplication

| ID | Owner requirement | PRD | TR | Data | Service / class | Event | Tickets | Tests / fixtures | Output | Before | After | P |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| C.1 | ImportBatch identity for every attempt; hashes; parser versions; checkpoints | FR-04, FR-30 | TR-12 | `import_batches` | `ImportCommitter` | `ImportBatchStarted/Completed` | IMP-001 | repeated import → 2 batches, 1 snapshot | batch list | partial | specified | P0 |
| C.2 | Stable logical conversation ID by native ID + account namespace | FR-30 | TR-12 | `sources.account_ns`, unique keys | `LogicalIdentityResolver` | — | IMP-002, FND-005 | `same_title_different_chat` | stable IDs in inspect | conflicting | specified | P0 |
| C.3 | Absent/colliding IDs handled conservatively | FR-30 | TR-12 | `identity_candidates` | resolver | — | IMP-002 | `id_collision`, `missing_ids` | `candidate_duplicates` count | missing | specified | P0 |
| C.4 | Stable message ID + immutable revisions; edge changes; new branches | FR-30 | TR-12 | `message_nodes`, `message_revisions`, `graph_edges` | `RevisionDeltaEngine` | `ConversationDeltaCommitted` | IMP-003 | `reexport_v1→v2` | `revised`, `new_branches` counts | missing | specified | P0 |
| C.5 | Byte-identical asset dedup, all occurrences kept | FR-26 | TR-13 | see A.8 | `MediaStore` | — | MED-003 | `repeated_image` | `new_media`, `duplicate_assets` | partial | specified | P0 |
| C.6 | Unchanged skip; zero redundant model calls | FR-04, FR-17 | TR-03, TR-09, TR-12 | stage keys on `canonical_content_hash` | `RevisionDeltaEngine`, `ProcessingPipeline` | none emitted for unchanged | IMP-003, IMP-005, FND-006 | identical reimport: `model_calls_triggered == 0`; `metadata_drift` | delta report field | partial | specified | P0 |
| C.7 | Missing from later export ≠ deletion | FR-30 | TR-12 | `message_nodes.presence` | `mark_not_seen` | — | IMP-003, OPS-004 | absent conversation stays queryable | `not_seen` count | partial (PRD prose) | specified | P0 |
| C.8 | Human corrections survive incremental reprocessing | FR-37, FR-22 | TR-12 | `review_overrides` | override service | — | IMP-006 | override survives / flags | review item | missing | specified | P1 |
| C.9 | Interrupted import, double import, concurrent jobs | FR-30 | TR-12, TR-03 | lock token, checkpoints | `ImportCommitter` | — | IMP-004 | crash injection; concurrent property test | `partial` status; resume | partial | specified | P0 |
| C.10 | Per-import delta report incl. regeneration footprint | FR-30 | TR-12 | `ImportDeltaReport` | report builder | `ImportBatchCompleted` | IMP-005 | exact counts for 3 scenarios | `ke imports report` | partial | specified | P0 |
| C.11 | No fuzzy auto-merge by title/text/visual similarity | FR-29, FR-30 | TR-12, TR-15 | — | resolver + detectors | — | IMP-002, MED-003, REL-002 | `similar_unrelated`, byte-only dedup | — | partial | specified | P0 |
| C.12 | Golden fixtures prove rerun = zero logical duplicates | FR-35 | TR-12 | — | — | — | EVAL-009, EVAL-010 | property test N imports | smoke report | partial | specified | P0 |

## D. URLs, YouTube and social accounts

| ID | Owner requirement | PRD | TR | Data | Service / class | Event | Tickets | Tests / fixtures | Output | Before | After | P |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| D.1 | Every URL occurrence with exact span and context | FR-31 | TR-14 | `link_targets`, `link_occurrences` | `LinkExtractor` | `LinksCommitted` | LNK-001 | `urls_mixed` span round-trip | `ke links` | missing | specified | P0 |
| D.2 | YouTube canonical identity (watch, youtu.be, shorts, live) preserving URL, timestamp, playlist/channel | FR-32 | TR-14 | `youtube_videos`, `youtube_mentions` | `YouTubeCanonicaliser` | `LinksCommitted` | YTB-001 | `youtube_forms`, `youtube_repeated` | `ke links --youtube` | deferred (INT-002 P1) | specified | P0 |
| D.3 | Video record created on discovery; transcript as separate opt-in job with statuses | FR-32 | TR-14 | `transcript_acquisitions` | `TranscriptAcquisitionService` | — | YTB-002 | network-off test; status transitions | status column | partial (README only) | specified | P0 |
| D.4 | User-supplied transcripts first; authorised sources only; never invent or bypass | FR-32 | TR-14, TR-08 | `transcript_snapshots` provenance | `attach_user_transcript`; INT-002 providers | `TranscriptAttached` | YTB-002, ING-010, INT-002 | `transcript_user.vtt`; no generated text | `ke transcripts attach` | partial | specified (network: P1) | P0/P1 |
| D.5 | Timed cues link to video and all referencing conversations | FR-32 | TR-14 | `transcript_cues` | indexer, video note | `TranscriptAttached` | YTB-003 | cue search resolves | video note | missing | specified | P1 |
| D.6 | Social account mentions with platform, raw mention, handle/URL, span, dates, conversations | FR-33 | TR-14 | `account_mentions` | `SocialMentionDetector` | `LinksCommitted` | SOC-001 | `social_profiles` | — | missing | specified | P0 |
| D.7 | Browseable deduplicated registry with aliases and identity status | FR-33 | TR-14 | `social_accounts`, `account_aliases` | `SocialAccountRegistry` | — | SOC-002, SOC-003 | URL + handle → one account | `ke accounts`; registry note (P1) | missing | specified | P0/P1 |
| D.8 | Ambiguous `@name` never asserted as a real account | FR-33 | TR-14 | `resolution=ambiguous` | detector | — | SOC-001, SOC-002 | misidentified-account trap | `ke accounts --ambiguous` | missing | specified | P0 |
| D.9 | No scraping, following or contact | FR-33 | TR-14 | — | — | — | SOC-001 (acceptance), OPS-006 | sockets blocked in tests | — | missing | specified | P0 |
| D.10 | Every occurrence preserved even when entity deduplicated | FR-31..33 | TR-14 | unique occurrence keys | registries | — | LNK-001, YTB-001, SOC-002 | 12 mentions → 1 video | mention counts | missing | specified | P0 |

## E. Core knowledge engine (2.6 / CLAUDE.md §2.E)

| ID | Requirement | PRD | Tickets | Before | After | P |
|---|---|---|---|---|---|---|
| E.1 | Immutable evidence; versioned, revocable derivations; lawful deletion | FR-02, FR-20, FR-24 | ING-001, EXT-008, OPS-004 (scope widened) | covered | covered (+media/links in deletion closure) | P0 |
| E.2 | Topical segmentation | FR-05 | NRM-004, NRM-005 | covered | covered | P0 |
| E.3 | Global governed versioned taxonomy; classifier can't mint terms | FR-06, FR-07 | TAX-001..008 | covered | covered | P0 |
| E.4 | Primary/secondary multi-axis classification | FR-08 | CLS-001..005 | covered | covered (+FND-009 structured output) | P0 |
| E.5 | Suggestion ≠ acceptance; typed records with evidence | FR-09, FR-10 | EXT-001..008 | covered | covered | P0 |
| E.6 | Historical/current state, explicit supersession, unknown/review | FR-11 | REC-003..006 | covered | covered | P0 |
| E.7 | Master project/topic documents | FR-14 | DOC-004, DOC-005 | covered | covered | P0 |
| E.8 | Search/RAG with citations; abstention | FR-15, FR-16 | RET-001..008 | covered | covered | P0 |
| E.9 | Obsidian YAML/frontmatter and backlinks | FR-13 | DOC-002, DOC-006 | covered | covered (+media embeds) | P0 |
| E.10 | Provenance: pipeline/model/prompt versions | FR-20 | FND-006, EXT-008, FND-009 | covered | covered | P0 |
| E.11 | Source text is untrusted data | — | OPS-006 | covered | covered (+URLs, transcripts) | P0 |
| E.12 | Constrained agent execution; bounded retries | — | EVAL-007, OPS-002 | covered | covered (+EVAL-011) | P0 |
| E.13 | Future multi-user | FR-23 | PROD-001..004 | deferred | deferred (P2) | P2 |
| E.14 | Cloud-capable models, type-safe output, stability measured (owner input 2026-10-27) | FR-36 | FND-009, EVAL-001, EVAL-011 | conflicting / partial | specified (ADR-0007 proposed) | P0 |
| E.15 | Batch smoke at 50 and 100 early (owner input) | FR-35 | EVAL-010, EVAL-011 | missing | specified | P0 |

## Completeness check
Every row above names at least one PRD FR, one ticket and one test/fixture. Rows with no event are synchronous parts of an import transaction or configuration. No row is marked implemented.
