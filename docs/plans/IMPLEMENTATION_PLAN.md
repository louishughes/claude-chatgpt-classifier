# Implementation Plan

**Date:** 2026-10-27 · **Status:** proposed, awaiting product-owner approval. Nothing below is implemented. All 122 tickets are `NOT_STARTED`.
**Inputs:** `docs/reviews/SPEC_AUDIT.md`, `REQUIREMENTS_TRACEABILITY.md`, ADR-0002..0008, `ROADMAP_AND_TICKETS.md`, `TICKETS.csv`. **Execution order and graph:** `DEPENDENCY_MAP.md`.

## 1. Target folder tree and module boundaries

```text
./
├── CLAUDE.md  AGENTS.md  README.md  CLAUDE_CODE_HANDOFF_PROMPT.md
├── pyproject.toml                     # FND-001
├── docs/                              # specs, reviews/, plans/, adr/, diary/, agents/, CODE_STYLE.md (FND-001)
├── raw/                               # PRIVATE, read-only, git-ignored. Never written by any command.
├── src/knowledge_engine/
│   ├── domain/            # Pydantic models, enums, stable-ID helpers. No I/O, no SDKs.
│   ├── settings.py        # egress switches, raw roots, storage modes, limits (FND-002)
│   ├── ingestion/         # RawInventory, SourceAdapter port, ChatGPT export + split-wrapper adapters, streaming parser
│   ├── identity/          # LogicalIdentityResolver, RevisionDeltaEngine, ImportCommitter, delta report   ← new
│   ├── media/             # AssetPointerResolver, MediaStore                                                ← new
│   ├── links/             # LinkExtractor, YouTube, transcripts, social registry                            ← new
│   ├── relationships/     # BranchClassifier, StructuralRelationshipDetector, review                        ← new
│   ├── normalisation/  taxonomy/  classification/  extraction/  reconciliation/   # semantic layer (existing plan)
│   ├── retrieval/  rendering/           # rendering gains SourceNoteBuilder
│   ├── orchestration/                   # jobs, stage keys, checkpoints, retry policy
│   ├── infrastructure/                  # SQLite/SQLAlchemy repos, Alembic, providers/ (the only place model SDKs live)
│   ├── evaluation/
│   └── cli/                             # `ke …`
├── tests/
│   ├── fixtures/          # synthetic only, each with a SYNTHETIC marker (OPS-008)
│   ├── unit/  contract/  property/  integration/  e2e/
└── workspace/ (outside repo, configurable)   # SQLite DB, content-addressed store, generated vault
```

**Boundary rules** (from TR-02, plus the audit): `domain` imports nothing internal. The source layer (`ingestion`, `identity`, `media`, `links`, `relationships`) never imports `infrastructure/providers`. Only `orchestration` sequences stages. `rendering` reads projections; it never writes knowledge. Generated output and the private store live outside the repo.

## 2. Dataflow

```text
raw/ (read-only)
  └─ RawInventory ── tree hash before ─────────────────────────────────────────┐
       └─ Adapter (official export | split-wrapper) ─ streaming JSON            │
            └─ native mapping parser → ImportedConversation                     │
                 └─ LogicalIdentityResolver (namespace + native IDs, candidates) │
                      └─ RevisionDeltaEngine (raw hash, content hash, delta)     │
                           ├─ BranchClassifier → branch_points                   │
                           ├─ AssetPointerResolver → MediaStore (blob/asset/occurrence)
                           ├─ LinkExtractor → YouTube registry → transcript jobs │
                           │                └→ Social registry                   │
                           └─ StructuralRelationshipDetector → candidates        │
                 ImportCommitter (lock, group tx, checkpoint, outbox) ───────────┤
                      ├─ ImportDeltaReport (+ tree hash after) ◄─────────────────┘
                      ├─ SourceNoteBuilder / `ke inspect`  (LLM-free, M1)
                      └─ ConversationDeltaCommitted (changed revisions only)
                            └─ Normaliser → Segmenter → Taxonomy → Classifier → Extractors
                               (StructuredModelProvider: egress gate, schema, cache)
                                  → EvidenceValidator → Reconciler → Projectors
                                     → Retrieval (FTS5, vectors) → Answers
                                     → Document builders → Obsidian vault (with media + related chats)
```

Unchanged revisions emit no events, so an identical re-import does no downstream work.

## 3. Core classes per new or changed subsystem

Signatures and comments are in `ARCHITECTURE.md` §7.1 (source layer) and §3 (semantic layer). Ownership summary:

| Subsystem | Classes | Owns tables | Called by | Must never |
|---|---|---|---|---|
| Inventory | `RawInventory` | `raw_roots`, `source_files` | CLI, ImportCoordinator | write under raw/, print content |
| Adapters | `ChatGPTExportAdapter`, `ChatGPTSplitWrapperAdapter` | — (emit DTOs) | ImportCoordinator | guess missing fields |
| Identity | `LogicalIdentityResolver`, `RevisionDeltaEngine`, `ImportCommitter` | `import_batches`, `message_nodes`, `message_revisions`, `graph_edges`, `identity_candidates` | ImportCoordinator | merge on title/similarity; delete on absence |
| Branches | `BranchClassifier` | `branch_points` | delta engine | splice siblings |
| Media | `AssetPointerResolver`, `MediaStore` | `media_*`, `asset_occurrences`, `derived_media` | delta engine, renderer | invent paths; OCR/vision |
| Links | `LinkExtractor`, `YouTubeCanonicaliser`, `TranscriptAcquisitionService`, `SocialMentionDetector`, `SocialAccountRegistry` | `link_*`, `youtube_*`, `transcript_*`, `social_*`, `account_*` | delta engine, CLI | fetch without egress; generate transcripts; contact accounts |
| Relationships | `StructuralRelationshipDetector`, relatedness service (M4), review service | `conversation_relationships`, `relationship_reviews` | delta engine, CLI, renderer | accept forks from similarity |
| Providers | `StructuredModelProvider` | jobs/cost ledger | semantic stages | persist unvalidated output |
| Rendering | `SourceNoteBuilder` + existing builders | `document_*` | CLI | overwrite user-owned notes |

## 4. Milestones and integration gates

| Milestone | Content | Gate (all must be demonstrated by commands that actually ran) |
|---|---|---|
| **M0** Audit (done 2026-10-27) | This plan | Owner approves plan and answers or accepts defaults for OD-01..OD-16 |
| **M1** Source-fidelity slice (33 tickets, P0) | Foundation, raw inventory, both adapters, graph, branches, identity, revisions, commit/lock/resume, media, delta report, renderer core, source notes, batch smoke | **G1:** §6 demonstration passes on fixtures; EVAL-010 passes at 50 and 100 (synthetic and real, read-only); raw tree hash unchanged; zero model calls anywhere |
| **M2** Registries (9 tickets, P0) | Offsets, URL registry, YouTube + transcript status + user-supplied transcripts, social registry, structural relationship candidates, FTS5 over sources | **G2:** link/YouTube/social fixtures exact; EVAL-010c on 100 real conversations; still zero model calls |
| **M3** Semantic foundation (31 tickets, P0) | Provider protocol + structured provider, segmentation, taxonomy, classification, extraction, golden set, ops limits, semantic batch smoke | **G3:** EVAL-011 at 50 then 100 (fake, then pinned real provider under cost cap); EVAL-003/004 baselines recorded; zero unvalidated outputs stored |
| **M4** Knowledge and documents (30 tickets) | Reconciliation, retrieval, documents, late relationships (REL-003/004), transcript cues (P1), account notes (P1), correction survival, release gate | **G4:** EVAL-005..008 pass thresholds or are filed as REVIEW/BLOCKED; Obsidian vault link check clean |
| **M5** Hardening (12 tickets) | API, backups, deletion, CI, security hardening, packaging, extra adapters | **G5:** restore test, deletion test, adversarial suite, clean-machine install |
| **M6** Integrations/productisation (7 tickets, P1/P2) | Web connector, network transcript providers, watched folders, multi-user | **G6:** per-ticket acceptance; owner approval for each network integration |

Human approval points: before M1 starts (this plan); before the first real-provider call in M3 (provider, cost cap, egress profile: OD-04/05); before any network integration in M6; before any deletion/retention feature is used on real data.

## 5. Ordered tickets, dependencies and estimates

The full ordered list per milestone with blockers is in `DEPENDENCY_MAP.md` §4. Critical paths: G1 = 12 tickets (`FND-001 → FND-002 → FND-003 → ING-001 → ING-002 → ING-004 → ING-005 → NRM-001 → IMP-003 → IMP-004 → IMP-005 → BRW-001`); G3 = 18; G4 release gate = 27.

Estimates are rough agent-session sizes (S ≈ one focused session, M ≈ 2–3, L ≈ 4+), not calendar promises:

| M1 ticket | Size | Main risk |
|---|---|---|
| FND-001 bootstrap + CODE_STYLE | S | — |
| FND-002 settings/egress | S | — |
| FND-003 SQLite engine | S | WAL on Windows network drives (V:) — test locally |
| FND-004 Alembic baseline | S | — |
| FND-005 domain + stable IDs | M | getting identity keys right first time (ADR-0003) |
| FND-006 jobs/stage keys | M | — |
| FND-008 CLI skeleton | S | — |
| OPS-008 git guard | S | — |
| EVAL-009 fixtures + generator | M | fixtures must mirror real shapes without real content |
| ING-001 archive store | S | copy vs reference mode (OD-02) |
| SRC-001 raw inventory | S | — |
| ING-002 adapter port | S | — |
| IMP-001 batch ledger | S | — |
| ING-003 coordinator | S | — |
| ING-004 export layouts + streaming | M | sharded/large JSON |
| ING-005 mapping parser | M | missing `children` |
| ING-006 content/attachments | M | many content types |
| ING-011 split adapter | S | equivalence with official format |
| ING-007 integrity | S | — |
| NRM-001 canonical node + hashes | S | hash scope (OD-13) |
| NRM-002 graph integrity | S | — |
| REL-001 branch kinds | S | edge cases (system/tool siblings) |
| IMP-002 identity resolver | M | collisions |
| IMP-003 delta engine | M | correctness of categories |
| IMP-004 commit/lock/resume | M | concurrency on SQLite |
| MED-001/002/003 media | M + M + S | pointer variety |
| IMP-005 delta report | S | — |
| EVAL-010 batch smoke | S | real-data runtime |
| DOC-002 renderer core | S | — |
| MED-004 embeds | S | vault path strategy (OD-14) |
| BRW-001 source notes + inspect | M | — |

M1 total: roughly 40–55 sessions-worth of S/M work. M2: roughly 10–14. Later milestones are larger and depend on provider choices; estimate them after G2.

## 6. First vertical slice and its demonstration (Gate G1)

**Scope:** M1 tickets only. **No model calls, no network.** Fixtures from EVAL-009 plus a local read-only run on real data.

```bash
# 1. Read-only inventory (metadata only)
ke raw inventory tests/fixtures/chatgpt/reexport_v1          # counts, roles, tree hash
# 2. First import, then an identical re-import
ke import tests/fixtures/chatgpt/reexport_v1 --account-ns fixture
ke import tests/fixtures/chatgpt/reexport_v1 --account-ns fixture
ke imports report latest      # all 'unchanged', 0 new records, model_calls_triggered: 0
# 3. Incremental export with edits, a new branch, a new image, one conversation absent
ke import tests/fixtures/chatgpt/reexport_v2 --account-ns fixture
ke imports report latest      # exact new/unchanged/revised/new_branches/new_media/missing_assets/not_seen
# 4. Same conversations via the split-wrapper format
ke import tests/fixtures/chatgpt/split_wrapper --format chatgpt-split-v1 --account-ns fixture
ke imports report latest      # all 'unchanged' (same logical records as the official format)
# 5. Browse
ke inspect conversation <id> --branches --assets
ke render sources --out <tmp_vault>     # then the link checker runs over <tmp_vault>
# 6. Raw safety
ke raw inventory tests/fixtures/chatgpt/reexport_v1   # tree hash identical to step 1
```

**Pass when:** every command exits 0; reports match the fixture manifest exactly; rendered notes show active path, labelled `edit`/`regeneration` alternates, image embeds that resolve and explicit markers for missing/ambiguous assets; tree hashes match; EVAL-010 reports exist for 50 and 100 synthetic and real conversations. The real-data run writes only to the private workspace and its report contains counts, timings and warning codes only.

## 7. Test plan by level

Details in `TEST_STRATEGY.md` §2–§12. Mapping of the owner's required cases:

| Case | Level | Fixture | Ticket |
|---|---|---|---|
| Duplicate import (identical bytes, repeated N times, concurrent) | property, integration | `reexport_v1`, generator | IMP-001, IMP-004 |
| Changed branch (edit, regeneration, added branch on re-export) | unit, integration | `branches_*`, `reexport_v2` | REL-001, IMP-003 |
| Repeated image across messages/conversations | unit, integration | `repeated_image` | MED-003 |
| Missing / ambiguous / unresolved asset | unit | `missing_asset`, `ambiguous_asset`, `unresolved_pointer` | MED-002 |
| Misidentified account (bare @name, email, code decorator) | unit | `social_profiles` | SOC-001 |
| Unavailable YouTube transcript | unit, contract (fake provider) | `youtube_forms` + network off | YTB-002, INT-002 |
| Repeated links | unit | `urls_mixed`, `youtube_repeated` | LNK-001, YTB-001 |
| Unrelated-but-similar conversations | unit, integration | `similar_unrelated` | REL-002, REL-003 |
| Copied-prefix manual fork | unit | `copied_prefix` | REL-002 |
| Split vs official format equivalence | golden parser | `split_wrapper` | ING-011 |
| Metadata drift → no reprocessing | integration | `metadata_drift` | IMP-003 |
| Crash and resume | integration | generator | IMP-004 |
| Raw untouched | integration (every e2e) | all | SRC-001 |
| Batch scale 50/100 | smoke | generator + real (local) | EVAL-010, EVAL-011 |
| Semantic golden (actor-aware decisions, stability) | semantic golden | EVAL-001 corpus | EXT-*, EVAL-004/008 |
| Prompt injection inside sources | security | `prompt_injection_text` | OPS-006 |

Property-based tests (Hypothesis): random message DAGs (no cycles lost, every node reachable or flagged), random repeat/permute import sequences (idempotent counts), URL span round-trips over random surrounding text.

## 8. Verification strategy and stop rules

- Per ticket: run the ticket's focused tests, then the package's tests, once after the last change (TEST_STRATEGY §10).
- One focused fix after a genuine failure, then one rerun. Still failing → mark `BLOCKED` with the failing command and stop.
- Transient provider errors: 3 attempts total with backoff; then `failed` for that item, batch continues and resumes later.
- Semantic disagreement → review item, never a retry loop.
- Real-provider runs only inside EVAL-011 and later gates, always with a cost cap and pinned versions.
- No new frameworks, architecture rewrites or prompt rewrites in response to one failing test.

## 9. Decisions, changes and status accounting

- Every ticket closure appends to `.agent-history/SESSION_LOG.md` and updates `STATUS.md` (create on first ticket), and adds a dated entry to `docs/diary/BUILD_DIARY.md`.
- Architecture changes → new ADR in `docs/adr/` (append-only, `supersedes`). Small choices → `.agent-history/DECISION_LOG.md`.
- Status words from `DECISIONS_AND_HISTORY.md`: `NOT_STARTED`, `IN_PROGRESS`, `BLOCKED`, `REVIEW_REQUIRED`, `VERIFIED`, `DEFERRED`, `CANCELLED`, `FAILED`, `UNKNOWN`. A ticket is `VERIFIED` only with the acceptance commands' real output.
- Distinguish in every report: test not run, test failed, not implemented, intentionally omitted, source lacks the feature.
- Tracker: until OD-08 is decided, `TICKETS.csv`/`ROADMAP_AND_TICKETS.md` stay in sync. If GitHub Issues becomes the tracker, issues are created from the CSV for M1 and the files get a "frozen; see issues" banner.

## 10. Boundaries

**In scope after approval:** M1 tickets one at a time in `DEPENDENCY_MAP.md` order; synthetic fixtures; local read-only runs on `raw/` that write only to the private workspace.

**Not in scope without a further explicit approval:** any model/provider call with real data; any network fetch (URLs, YouTube, profiles); any write, move or clean-up under `raw/`; deleting anything; creating GitHub Issues; hosting or sharing outputs; packaging for sale.

**Never:** OCR/vision/face recognition on images by default; inventing transcripts or accounts; merging conversations or images by similarity; treating a missing conversation as deleted; committing private data (the repository is public).

## 11. Code readability, learning and portfolio standard (owner request, 2026-10-27)

The owner is learning Python and wants the code to work as a portfolio piece and possibly a product. This reconciles with CLAUDE.md §5 ("comments explain why, not restate code"):

- **Module docstring** (every module): 3–6 plain-English sentences: what the module does, why it exists, which invariant it protects. Then a short `Talking points:` list (2–4 bullets) that the owner can reuse when explaining the design in an interview or post.
- **Class and public function docstrings:** what it takes, what it returns, what can go wrong (Google style). Beginner-readable; define jargon once ("idempotent: running it twice has the same effect as once").
- **Inline comments:** only for a *why* (an invariant, a surprising choice, a real-data quirk such as "exports omit `children`, so we rebuild it from `parent`"). No line-by-line narration.
- **Typed everything:** type hints on all public functions; Pydantic models at boundaries. This is also the main fix for the past "not type-safe" problem.
- **Small, readable functions** over clever ones; names that match `CONTEXT.md`/glossary terms once it exists.
- FND-001 writes these rules into `docs/CODE_STYLE.md` and adds a docstring lint for public functions.
- Each ticket's diary entry ends with "What I learned" and "Talking points" (see `docs/diary/BUILD_DIARY.md`).

Packaging and monetisation are recorded as a future option (OD-16) and do not enlarge the MVP. The one early action worth considering is choosing a licence, because the repository is public.
