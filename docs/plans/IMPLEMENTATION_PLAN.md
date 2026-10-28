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

**Boundary rules** (from TR-02, plus the audit): `domain` imports nothing internal. The source layer (`ingestion`, `identity`, `media`, `links`, `relationships`) never imports `infrastructure/providers`. Only `orchestration` sequences stages. `rendering` reads projections; it never writes knowledge. Generated output and the private store live outside the repo or in a git-ignored folder inside it (e.g. `private/`, owner preference 2026-10-27 to keep everything in one project folder).

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

**Commitment (REV-001, decided under delegated authority 2026-10-27, revisitable):** only **M1 and M2 are committed**. M3–M6 are roadmap: planned, not committed. They are re-planned at gate G2 using real-data results from M1/M2. Entry conditions for M3: ADR-0009 (the model step under the no-paid-API rule, REV-002) is accepted, and the owner has approved the answer key (REV-003). The product tickets API-001..005, PROD-001..004, OPS-007 and INT-001..003 are labelled `parked` in GitHub Issues: kept, not closed or renumbered, and not worked on. Reason: building all 122 tickets (API, PostgreSQL, multi-user) before the core works on real data repeats failure mode F7 ("too much system too early") from `docs/reference/previous-attempts-review.md`.

**Superseded by the owner (2026-10-27 23:32 UTC):** Louis wrote "Also continue the old goal of implementing all the tickets". All milestones M1–M6 are back in scope and are built in plan order, in small PRs (two tickets at most, each with a teach-back). What still holds from REV-001 and the guardrails: no paid API calls (model steps use ADR-0009: a Claude Code session on the owner's subscription, with fake providers in tests); egress stays off by default; anything that needs the owner (the answer key, REV-003; changing tests or the gold set; a third failed fix attempt) is logged as blocked and skipped, not waited on. `parked` labels are removed as each of those tickets is reached. The F7 risk ("too much system too early") is managed by keeping each later ticket small and behind the working core, not by leaving it out.

**Owner decision (2026-10-28 08:54 UTC):** Louis answered "Do a and b" to the coordinator's two optional calls. (a) **One** EVAL-011 smoke run with a real paid model is approved, as a single exception: kept as small as the ticket allows, on synthetic chats, with a hard cost cap, and its cost recorded in the diary. The no-paid-API rule stays for everything else. (b) The 13 parked tickets (API-001..005, PROD-001..004, OPS-007, INT-001..003) are unparked and built as part of all tickets, after M5 and M6, in small PRs. Their `parked` labels were removed the same morning.

Human approval points: before M1 starts (this plan); before the first real-provider call in M3 (provider, cost cap, egress profile: OD-04/05); before any network integration in M6; before any deletion/retention feature is used on real data.

### 4a. Local interface (owner requirement, 2026-10-28 00:14 UTC: "Make sure there is also an easy to use interface")

Louis is a Python beginner, so a CLI on its own isn't enough. A small **local web interface** is added. It is started with one command (`ke ui`), opens in the browser, listens on `127.0.0.1` only, and has no accounts, no cloud and no JavaScript build step: pages are rendered by the server, with plain HTML and a little CSS. It calls the same modules as the CLI (`import_source`, the stored import reports, `rendering/transcript`), so it adds screens, not new logic. Tickets (GitHub Issues; IDs new, frozen CSV untouched):

| Ticket | Milestone | What the user gets | Blocked by |
|---|---|---|---|
| UI-001 | M1 tail (next) | `ke ui` starts the app; home screen with workspace status and the list of past imports; one import's report in plain words (what's new, changed, missing, needs a look) | IMP-005, BRW-001 (done) |
| UI-002 | M1 tail | Import from the browser: pick a configured raw folder or type a path, press Import, watch progress, land on the report | UI-001 |
| UI-003 | M1 tail | Browse chats: list with filter, a chat page showing the active path, labelled branches, images (or missing markers), and its import history | UI-001 |
| UI-004 | M2 | Links, YouTube videos and social accounts pages; search box once RET-001 lands | UI-003, LNK-001, YTB-001, SOC-002, RET-001 |
| UI-005 | M3 | Read-only view of AI suggestions and of what the independent reviewer sessions decided and why (no owner action required) | UI-003, EXT-007, TAX-004 |

Each is one PR (at most two tickets per PR, with a teach-back). The parked API tickets (API-001..005) stay parked: the UI uses server-rendered pages, not a public API.

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
ke inspect <id> --redact      # --redact: 8-character ID prefixes, for anything pasted into a report or checklist (OPS-009)
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
- At most 3 fix attempts after a genuine failure (owner guardrail, 2026-10-27; replaces the earlier one-fix rule). Still failing → mark `BLOCKED` with the failing command and stop and ask.
- Existing tests, acceptance criteria and gold-set labels are changed only with owner approval.
- Taxonomy version is frozen for the duration of any classification run.
- Transient provider errors: 3 attempts total with backoff; then `failed` for that item, batch continues and resumes later.
- Semantic disagreement → review item, never a retry loop.
- Real-provider runs only inside EVAL-011 and later gates, always with a cost cap and pinned versions.
- No new frameworks, architecture rewrites or prompt rewrites in response to one failing test.

## 9. Decisions, changes and status accounting

- Every ticket closure appends to `.agent-history/SESSION_LOG.md` and updates `STATUS.md` (create on first ticket), and adds a dated entry to `docs/diary/BUILD_DIARY.md`.
- Architecture changes → new ADR in `docs/adr/` (append-only, `supersedes`). Small choices → `.agent-history/DECISION_LOG.md`.
- Status words from `DECISIONS_AND_HISTORY.md`: `NOT_STARTED`, `IN_PROGRESS`, `BLOCKED`, `REVIEW_REQUIRED`, `VERIFIED`, `DEFERRED`, `CANCELLED`, `FAILED`, `UNKNOWN`. A ticket is `VERIFIED` only with the acceptance commands' real output.
- Distinguish in every report: test not run, test failed, not implemented, intentionally omitted, source lacks the feature.
- Tracker: GitHub Issues (OD-08 resolved, REV-006). `TICKETS.csv`/`ROADMAP_AND_TICKETS.md` are frozen reference and carry no status.

## 10. Boundaries

**In scope after approval:** M1 then M2 tickets one at a time in `DEPENDENCY_MAP.md` order (M3–M6 only after the G2 re-plan, see §4); synthetic fixtures; local read-only runs on `raw/` that write only to the private workspace.

**Not in scope without a further explicit approval:** any model/provider call with real data; any network fetch (URLs, YouTube, profiles); any write, move or clean-up under `raw/`; deleting anything; creating GitHub Issues; hosting or sharing outputs; packaging for sale; any ticket labelled `parked`.

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

## 12. Pre-M1 classification spike (owner decision, 2026-10-27) — CLOSED

**Closed the same day** (owner: "we need to learn"). Verdict, lessons and how to resume are in `docs/plans/SPIKE_VERDICT.md`. M1 starts now. It is LLM-free, so it doesn't depend on the open classification question. The history below is kept for the record.

**Lessons carried into the plan:**
- **FND-009 / provider adapter:** direct provider APIs; retry transport and format errors only; trim harmless overflows in code; log schema-error kinds.
- **M3 design:** discover, then consolidate into an owner-approved two-level taxonomy and project registry, then classify *segments*. Items cite message numbers, which code checks (speaker, decided-by-user, quote present). No clipping, or clipped results reported separately. Keep code messages.
- **EVAL-001** (2026-10-28: no owner review; see OPEN_DECISIONS "reference set"): the answer key in `private/answer-key/` (10 chats, 95 items, to be reviewed by an independent Claude session, not the owner) is the seed of the golden set. Score by message number. Reports must name the reviewer. An AI check is never reported as accuracy.
- **M1 dependency:** NRM/IMP must keep message order and numbering stable per active branch, because evidence anchors and segment ranges use them. They must also keep `code` content.
The owner chose to validate the AI labelling step before starting M1. `prototype/classification_spike/` is throwaway code that labels a reproducible sample of 50, then 100, real conversations twice with schema-checked output, and reports:
- **Reliability:** ok rate, first-try schema failures, repairs, timeouts and rate limits, latency, cost. Retries cover transport and format errors only; a well-formed wrong answer is never retried.
- **Separate dimensions** (OD-17): primary/secondary domain, purpose, project candidates, topics, knowledge types, outputs, and decisions with proposer, state and a quoted speaker. One mixed "primary category" is not used.
- **Consistency:** per-field agreement and Jaccard overlap between runs. Each run processes chats in a different shuffled order, so this also tests processing-order independence (calls share no state, and a unit test runs three orders).
- **Accuracy:** agreement with a small gold set of 10–20 chats that the owner hand-labels (domain and purpose). Consistency alone is not enough, because a model can be consistently wrong. Gold labels come from the owner, never from the agent being judged.
- **Evidence:** share of decision quotes found verbatim in a message by the stated speaker, and "accepted" decisions backed only by assistant text.

Known limits, from the earlier post-mortem (`docs/reference/2026-10-27-why-the-classifier-failed.md`, PR #2): one call per chat cannot validate project identity (that needs the corpus-wide registry), labels are per chat not per segment, and decision recall needs the fuller EVAL-001 reference set.

**Agreed sequence (owner, 2026-10-27):**
1. Schema with separate fields and attributed decisions (done, taxonomy `spike-0.2`).
2. Owner gives the API-data OK, a cost cap and the run location (done: Claude Haiku 5.5, $2 cap, on the owner's PC). Run 50 chats twice in different orders.
3. **Owner as evaluator** (owner, 2026-10-27: "I am just the evaluator, I am not doing any tagging myself"). After run 1 the spike writes a review sheet for about 20 varied chats (size, images, branches, spread over time) showing the model's answers. The owner marks domain, purpose and decisions `y`/`n` and may give the right answer. Verdicts give accuracy, and confirmed or corrected answers become reference labels that score every run and later models. The review file's hash is recorded in every report, and agents never fill in or edit verdicts. Seeing the model's answer first biases reviewers towards agreeing, so this accuracy is treated as an upper bound. Blind labelling (`--gold-template`) remains available. The owner reviews the report before anything scales.
4. **Go/no-go.** Go if the README targets are met (headline: primary-domain agreement ≥ 90%, primary-domain accuracy by owner verdicts ≥ 85% (higher bar than blind labels, to allow for anchoring), decision quotes verified ≥ 95%, no unrecovered transient errors at 50). Then run 100 chats, and if that also holds, start M1 at FND-001. **No-go:** change the method (input selection, fields, segment-level labelling, model or effort), not the prompt wording, and re-run against the *same* gold set.

Targets are in the spike README. Results feed OD-05 (provider/model, cost cap), the FND-009 contract and the EVAL-001 golden set: the gold labels become its first entries. Nothing in `src/` will import the spike.
