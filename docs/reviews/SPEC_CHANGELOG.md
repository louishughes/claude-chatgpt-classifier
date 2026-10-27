# Specification Changelog

**Session:** 2026-10-27 specification audit (docs only). **Baseline:** `main` at `103bcb3`. Every change below is a documentation change; no source code, migrations or data were created.

Convention: existing text was **annotated, not rewritten**. Where a statement changed meaning, the original wording stays and an "Audit amendment (2026-10-27)" note follows it, so history is visible in the file itself as well as here.

## 1. Files created

| Path | Purpose |
|---|---|
| `docs/reviews/SPEC_AUDIT.md` | Findings with severities, risks and file references |
| `docs/reviews/REQUIREMENTS_TRACEABILITY.md` | Requirement → FR → TR → data → service → event → ticket → test → output |
| `docs/reviews/SPEC_CHANGELOG.md` | This file |
| `docs/reviews/OPEN_DECISIONS.md` | OD-01..OD-16 with recommended defaults |
| `docs/plans/IMPLEMENTATION_PLAN.md` | Phases, module tree, dataflow, slice demo, tests, boundaries |
| `docs/plans/DEPENDENCY_MAP.md` | Generated milestone order, critical paths, reverse dependencies |
| `docs/HANDOFF_AFTER_AUDIT.md` | What changed, what ran, what is not done, first ticket |
| `docs/adr/README.md`, `docs/adr/0002`..`0008` | Seven proposed ADRs and an index |
| `docs/diary/BUILD_DIARY.md` | Owner-requested build diary (timestamps, reasons, talking points) |

## 2. Files amended

| File | Section | Change | Why | Compatibility impact |
|---|---|---|---|---|
| `docs/PRD.md` | §3 journeys | Added journeys 9–11 (re-export, browse sources, follow references) | Owner requirements C, A, D | none |
| `docs/PRD.md` | §4 MVP | Added a bullet listing the new P0 scope | Requirements A–D | MVP grows by the source-layer tickets |
| `docs/PRD.md` | §5 P1 | Note: YouTube detection/identity/status are P0; only network acquisition stays P1 | Owner: YouTube detection must not be omitted | INT-002 rescoped |
| `docs/PRD.md` | new §8a | FR-25..FR-37 | Requirements A–D, batch smoke, type-safe output, correction survival | additive |
| `docs/PRD.md` | §11 | Amendment under "Local-only by default" pointing to ADR-0007 (proposed) | Owner: not 100% local | default still off until OD-04 |
| `docs/PRD.md` | §12 | M1 annotated (media, delta report, browsing, smoke; M2 registries) | ADR-0008 | none |
| `docs/PRD.md` | §13 | Pointer to OPEN_DECISIONS | | none |
| `docs/TECHNICAL_REQUIREMENTS.md` | TR-08 | Per-capability egress amendment | ADR-0007 | settings shape (FND-002) |
| `docs/TECHNICAL_REQUIREMENTS.md` | TR-09 | Streaming required above threshold; batch-scale smoke requirement | real export is sharded; owner request | none |
| `docs/TECHNICAL_REQUIREMENTS.md` | TR-10 | New CLI commands | FR-25..34 | additive |
| `docs/TECHNICAL_REQUIREMENTS.md` | TR-11 | Beginner-readable code rule | owner request | style only |
| `docs/TECHNICAL_REQUIREMENTS.md` | new TR-12..TR-16 | Identity/reimport, raw+media, links, relationships, model calls | ADR-0002..0007 | additive |
| `docs/ARCHITECTURE.md` | new §7 | Source-layer dataflow, class signatures, events, hurdles | ADR-0002..0008 | new modules `identity/ media/ links/ relationships/` |
| `docs/DATA_MODEL_AND_CONTRACTS.md` | new §10 | 26 tables, transactions, state machines, DTOs; reconciliation notes for `import_runs`, `sources`, `content_nodes`, `node_assets`, `relationships` | ADR-0003/0004/0005/0006 | `node_assets` superseded (kept in §1 for history) |
| `docs/TEST_STRATEGY.md` | new §12 | Fixture catalogue, unit/property/integration tests, batch-scale gates, consistency | Requirements A–D; owner requests | additive |
| `docs/DECISIONS_AND_HISTORY.md` | §Record types; end | Canonical locations; project history (Hermes/DeepSeek PoC, Codex/"Luna", OpenRouter timeouts, 20–50 batch failures); ADR index | owner context; missing files | none |
| `AGENTS.md` | Mandatory reading order | Path-reconciliation note (which listed files are absent, where outputs now live) | Inventory finding 2.1 | none |
| `docs/ROADMAP_AND_TICKETS.md` | header, phase gates, dependency map | Ticket count 122, tracker note (OD-08), two new phase gates, revised critical path note | ADR-0008 | file order ≠ execution order (stated) |
| `docs/ROADMAP_AND_TICKETS.md` | tickets | 29 new ticket sections; amendment lines on 25 existing tickets; blocker lines updated on 12 | see §3 | IDs unchanged |
| `docs/TICKETS.csv` | all rows | New column `audit_amendment`; 29 new rows; 12 dependency changes | CSV/Markdown parity | consumers must accept the extra column |

Not edited on purpose: `CLAUDE.md` (standing instructions; its tracker rule conflicts with the work order and is logged as OD-08 instead), `README.md`, `CLAUDE_CODE_HANDOFF_PROMPT.md`, `docs/RESEARCH_REPORT.md` (historical narrative with broken relative links, logged in SPEC_AUDIT 2.2), `docs/MOONSHOT.md`, `docs/agents/*`.

## 3. Ticket changes

### 3.1 Blockers changed (old → new)
| Ticket | Old `depends_on` | New `depends_on` | Reason |
|---|---|---|---|
| ING-003 | ING-002;FND-006 | ING-002;FND-006;IMP-001 | Scope narrowed to orchestration and snapshot-level dedup; logical identity, revisions, locking and delta reporting move to IMP-001..IMP-005. Now blocked by IMP-001. |
| CLS-001 | TAX-002;NRM-004;FND-007 | TAX-002;NRM-004;FND-007;FND-009 | Classification calls go through FND-009 structured output; enum of approved term IDs is embedded in the JSON schema. |
| EXT-005 | EXT-001;EXT-002 | EXT-001;EXT-002;MED-003 | Artefact records link actual MediaAsset/AssetOccurrence IDs from MED-003 or carry an explicit missing flag. |
| EXT-006 | EXT-001;EXT-002;TAX-003 | EXT-001;EXT-002;TAX-003;LNK-001 | URL, YouTube and social references come from the deterministic LNK/YTB/SOC registries; this extractor adds typed named entities and must not re-detect URLs. |
| EXT-008 | EXT-007;FND-006 | EXT-007;FND-006;FND-009 | Extractor batches run through FND-009 (schema-validated output, one repair attempt, pinned versions) and are smoke-tested at 50/100 conversations in EVAL-011. |
| DOC-002 | DOC-001 | FND-005 | Renderer is generic infrastructure; dependency changed from DOC-001 to FND-005 so source-level notes (BRW-001) can ship before the knowledge pipeline. |
| DOC-003 | DOC-002;CLS-004 | DOC-002;CLS-004;MED-004;REL-002;YTB-001;SOC-002 | Notes also show branches, media embeds or missing markers, URL/YouTube/social mentions and related conversations. |
| DOC-006 | DOC-003;DOC-004;DOC-005;DOC-001 | DOC-003;DOC-004;DOC-005;DOC-001;MED-004 | Managed vault includes media attachments per MED-004 and validates media links. |
| EVAL-002 | EVAL-001;ING-007 | EVAL-001;ING-007;EVAL-009;IMP-005 | Uses EVAL-009 synthetic fixtures and the IMP-005 delta report. |
| EVAL-006 | EVAL-002;DOC-006 | EVAL-002;DOC-006;BRW-001 | End-to-end golden also verifies the LLM-free source notes from BRW-001 before the knowledge notes. |
| OPS-004 | DOC-006;RET-004;OPS-003 | DOC-006;RET-004;OPS-003;MED-003;YTB-002;SOC-002 | Deletion closure includes media blobs/occurrences, transcripts, link/account mentions and relationship evidence. |
| INT-002 | ING-010;INT-001 | ING-010;INT-001;YTB-002 | Rescoped: authorised network transcript providers only (YTB-002 owns statuses and user-supplied transcripts). Remains P1, opt-in, rate-limited, never circumvents access controls. |

### 3.2 Scope amendments (objective and acceptance text unchanged; amendment added)
| Ticket | Amendment |
|---|---|
| FND-001 | Add docs/CODE_STYLE.md defining the learning-friendly comment standard (module/class docstrings that explain what and why in plain English, why-comments on invariants, a short 'Talking points' block per module) and a ruff/docstring check for public functions; see IMPLEMENTATION_PLAN section 11. |
| FND-002 | Add per-capability egress policy (text_llm, vision, network_fetch, transcript_fetch), read-only raw root(s), media storage mode (copy or reference) and account namespace settings; see ADR-0007. |
| FND-005 | Stable-ID helpers must cover workspace/source-system/account namespace, logical conversation, message node, message revision, media blob/asset/occurrence, link/video/account and relationship IDs; see ADR-0003. |
| FND-007 | Protocol must declare capability (text_llm, embedding, vision) and structured-output schema per call so FND-009 can enforce egress and validation. |
| ING-001 | raw/ is opened read-only and never written; snapshots support copy or hash-verified reference-in-place for large media (OPEN_DECISIONS OD-02). |
| ING-004 | Also accept an extracted export directory, sharded conversations-NNN.json, export manifests, per-conversation asset folders, user-*/ and dalle-generations/ asset folders; stream JSON rather than loading whole files. |
| ING-005 | Real data lacks children arrays: derive children from parent links; tolerate null-message root nodes; branch-kind classification lives in REL-001. |
| ING-006 | Cover observed content types (text, code, multimodal_text, thoughts, reasoning_recap, user_editable_context, tether_quote, tether_browsing_display, execution_output) and asset pointer schemes file-service:// and sediment://; hidden/reasoning/system content is flagged, never dropped. |
| ING-007 | Fidelity summary feeds the IMP-005 delta report and must count wrapper/native disagreements for the split-wrapper format. |
| NRM-001 | Define canonical-content hash (role + content parts + create_time) separately from raw-payload hash so cosmetic metadata drift does not invalidate derivatives (ADR-0003). |
| REC-002 | Record-level relationships only; conversation-level relationships (continues, forked_from, related_to) live in REL-002..REL-004. |
| EVAL-001 | Golden set must also measure run-to-run label stability and schema-failure rate per model, given earlier inconsistent results (DECISIONS_AND_HISTORY project history). |
| OPS-002 | Provider timeouts, rate limits and batch concurrency are first-class limits; validated by EVAL-011. |

### 3.3 New tickets
| Ticket | Phase | P | Title | Blocked by |
|---|---|---|---|---|
| FND-009 | Foundation | P0 | Structured-output model provider adapter and egress policy | FND-007;FND-006 |
| OPS-008 | Foundation | P0 | Raw/private data Git guard and fixture redaction check | FND-001 |
| EVAL-009 | Foundation | P0 | Synthetic source-fidelity fixture suite and scale generator | FND-001 |
| SRC-001 | Ingestion | P0 | Read-only raw source inventory and guard | FND-002;FND-005;FND-008 |
| IMP-001 | Ingestion | P0 | ImportBatch and source-file snapshot ledger | ING-001;FND-006 |
| ING-011 | Ingestion | P0 | ChatGPT split-wrapper directory adapter | ING-002;ING-005 |
| REL-001 | Source identity, media and links | P0 | Native branch classification and path enumeration | ING-005;NRM-002 |
| IMP-002 | Source identity, media and links | P0 | Logical identity resolver for conversations, messages and assets | FND-005;IMP-001 |
| IMP-003 | Source identity, media and links | P0 | Message revision and graph delta engine | IMP-002;ING-005;NRM-001 |
| IMP-004 | Source identity, media and links | P0 | Transactional idempotent commit, resume and import locking | IMP-003;ING-003 |
| MED-001 | Source identity, media and links | P0 | Media blob, asset and occurrence model | FND-004;FND-005 |
| MED-002 | Source identity, media and links | P0 | Asset pointer resolver | MED-001;ING-006;SRC-001 |
| MED-003 | Source identity, media and links | P0 | Content-addressed media dedup and occurrence persistence | MED-002;IMP-002 |
| IMP-005 | Source identity, media and links | P0 | Import delta report and regeneration footprint | IMP-004;ING-007;MED-003;REL-001 |
| EVAL-010 | Source identity, media and links | P0 | Import batch-scale smoke tests at 50 and 100 conversations | IMP-005;EVAL-009 |
| LNK-001 | Source identity, media and links | P0 | URL occurrence extraction and link registry | NRM-003;IMP-003 |
| YTB-001 | Source identity, media and links | P0 | YouTube canonicaliser and video registry | LNK-001 |
| YTB-002 | Source identity, media and links | P0 | Transcript acquisition jobs, status and user-supplied transcripts | YTB-001;FND-006;FND-002;ING-010 |
| SOC-001 | Source identity, media and links | P0 | Social account mention detection | LNK-001 |
| SOC-002 | Source identity, media and links | P0 | Social account registry, aliases and review | SOC-001;IMP-002 |
| REL-002 | Source identity, media and links | P0 | Cross-conversation relationship model and structural detectors | IMP-003;LNK-001 |
| MED-004 | Documents | P0 | Safe media paths and Obsidian embeds | MED-003;DOC-002 |
| BRW-001 | Documents | P0 | Source-level conversation browser (CLI and Markdown) | IMP-005;MED-004;REL-001 |
| IMP-006 | Relationships and registries (late) | P0 | Human corrections survive incremental reprocessing | IMP-003;NRM-005;CLS-004;EXT-007 |
| REL-003 | Relationships and registries (late) | P0 | Semantic and project relatedness candidates | REL-002;RET-003;TAX-005 |
| REL-004 | Relationships and registries (late) | P0 | Relationship review, notes and retrieval exposure | REL-002;DOC-003;RET-006 |
| YTB-003 | Relationships and registries (late) | P1 | Transcript cue linking, search and video notes | YTB-002;RET-001;DOC-002 |
| SOC-003 | Relationships and registries (late) | P1 | Social account registry notes | SOC-002;DOC-002 |
| EVAL-011 | Operations | P0 | Semantic pipeline batch smoke tests at 50 and 100 conversations | FND-009;CLS-002;EXT-008;OPS-002 |

New ID prefixes: `SRC` (raw source), `IMP` (import identity/reimport), `MED` (media), `REL` (conversation relationships), `LNK` (links), `YTB` (YouTube), `SOC` (social accounts), `BRW` (source browsing). New numbers in existing groups: `FND-009`, `ING-011`, `OPS-008`, `EVAL-009..011`. None of these IDs existed before.

### 3.4 Priority changes
None for existing tickets. INT-002 stays P1 with a narrower scope; YouTube detection and status became P0 through YTB-001/YTB-002.

## 4. ADRs
ADR-0002..ADR-0008 created with status `proposed`. ADR-0001 is reserved for the SQLite/FTS5 decision that `DECISIONS_AND_HISTORY.md` uses as its worked example; no ADR file existed. No accepted decision was reversed. ADR-0007 refines (does not supersede) the local-only default pending OD-04.

