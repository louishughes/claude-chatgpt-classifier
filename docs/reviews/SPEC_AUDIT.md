# Specification Audit

**Date:** 2026-10-27 · **Scope:** documentation only; no application code, migrations or imports were written or run. · **Baseline:** `main` at `103bcb3`. · **Raw data:** inspected by metadata and JSON key structure only; no conversation text, titles, filenames or images appear in this report.

Severity: **P0** blocks the first vertical slice or breaks a non-negotiable owner requirement. **P1** must be fixed before the stage that needs it. **P2** is worth fixing but can wait. "Owner?" says whether a product decision is needed (details in `OPEN_DECISIONS.md`).

## 1. What was examined

| Path | Size | Read | Notes |
|---|---|---|---|
| `CLAUDE.md` | 12.7 KB | full | Includes the "Agent skills" section added earlier today |
| `AGENTS.md` | 11.0 KB | full | Mandatory reading list references several absent files (§2) |
| `README.md` | 10.4 KB | full | |
| `CLAUDE_CODE_HANDOFF_PROMPT.md` | 14.8 KB | full | Same work order the owner pasted into this session |
| `docs/PRD.md` | 10.4 KB | full | |
| `docs/TECHNICAL_REQUIREMENTS.md` | 7.8 KB | full | |
| `docs/ARCHITECTURE.md` | 19.3 KB | full | |
| `docs/DATA_MODEL_AND_CONTRACTS.md` | 8.9 KB | full | |
| `docs/TEST_STRATEGY.md` | 8.3 KB | full | |
| `docs/DECISIONS_AND_HISTORY.md` | 3.8 KB | full | |
| `docs/ROADMAP_AND_TICKETS.md` | 165 KB | structure, every ticket's header/objective/acceptance parsed; ticket bodies are a shared template | 93 tickets |
| `docs/TICKETS.csv` | 32.6 KB | full (parsed) | 93 rows |
| `docs/RESEARCH_REPORT.md` | 45 KB | relevant sections (ingestion, hurdles, reimport, model non-determinism, agent operating model, deliverables) | Narrative; treated as context |
| `docs/MOONSHOT.md` | 27.6 KB | headings and link/social/YouTube passages | Future vision; explicitly not MVP |
| `docs/agents/*.md` (3) | 7 KB | full | Tracker = GitHub Issues |
| `raw/` | ~1.2 GB | metadata; JSON key shapes of the manifest, 2 derived files and a stratified 50-conversation sample | See §3 |
| Project shared folder copies of PRD, research report and handoff prompt | | compared | Byte-identical to the repo copies |

The device folder (`V:\Programming\ChatGPT_Classifier`) and GitHub `main` contained the same documents (sizes match; `TICKETS.csv` differs only by CRLF line endings on Windows).

## 2. Inventory gaps, duplicates and path authority

| # | Finding | Severity | Recommendation | Owner? |
|---|---|---|---|---|
| 2.1 | Referenced but **absent**: `docs/README.md`, `docs/TICKET_INDEX.md`, `docs/HANDOFF.md`, `HANDOFF.md`, `CHANGELOG.md`, `AGENT.md`, `docs/adr/*`, `.agent-history/*` (DECISION_LOG, STATUS, SESSION_LOG, DEFERRED), `prompts/CODEX_BOOTSTRAP.md`, `prompts/CLAUDE_BOOTSTRAP.md`, the four Development/Testing/Validation/Final skills under `.claude/skills/` and `.agents/skills/`, `knowledge_engine_blueprint.zip`. The research report says the original package had 37 files; 13 arrived. | P1 | Don't pretend they exist. AGENTS.md now carries a path-reconciliation note. `docs/adr/` created. Restore or regenerate the rest when implementation starts (OD-11). | Yes (OD-11) |
| 2.2 | `RESEARCH_REPORT.md` links `./AGENTS.md`, `./CLAUDE.md`, `./AGENT.md`, `./HANDOFF.md`, `./CHANGELOG.md` and `../knowledge_engine_blueprint.zip` relative to `docs/`; all break now. | P2 | Left unedited as a historical narrative; recorded here. | No |
| 2.3 | `DECISIONS_AND_HISTORY.md` puts ADRs in `docs/adr/` and logs in `.agent-history/`; `docs/agents/domain.md` expects `CONTEXT.md` and `docs/adr/` at root. Consistent on ADRs; `CONTEXT.md` absent (domain.md says proceed silently). | P2 | Canonical locations recorded in `DECISIONS_AND_HISTORY.md`. | No |
| 2.4 | **Tracker conflict.** `CLAUDE.md` "Agent skills" and `docs/agents/issue-tracker.md` say GitHub Issues is the tracker and that `TICKETS.csv`/`ROADMAP_AND_TICKETS.md` are legacy and should **not** be kept in sync. The work order (and the older CLAUDE.md §3 step 4) require updating both in sync. | P1 | This session followed the work order (latest explicit instruction) and kept both in sync. Recommended default: after plan approval, create GitHub Issues for M1 from the revised CSV and freeze the CSV/Markdown as reference. | Yes (OD-08) |
| 2.5 | `CLAUDE.md` §4 says skills live in `docs/.claude/skills/` or `docs/skills/`; none exist. Engineering skills installed for this account (tdd, code-review, domain-modeling…) are global, not in the repo. | P2 | Covered by OD-11. | Yes |
| 2.6 | Ticket bodies in `ROADMAP_AND_TICKETS.md` are one template with the objective and acceptance inserted. Implementation detail lives in ARCHITECTURE/DATA_MODEL, not the tickets. | P2 | Acceptable; new tickets follow the same template so CSV/MD parity holds. | No |
| 2.7 | The repository is **public** (per the owner's setup notes). | P1 | Every committed doc must stay free of raw content. This audit reports counts and key shapes only. OPS-008 adds an automated guard. | No |

No duplicate copies of specs were found inside `docs/` (no nested `docs/docs/`, `prompts/` or hidden skill folders).

## 3. Raw data findings (metadata only)

| # | Finding | Severity | Consequence | Response |
|---|---|---|---|---|
| 3.1 | `raw/` is **not** an official ChatGPT export. It holds `export_manifest.json`, `conversations/` and `images/`, produced by an earlier Hermes extraction step (owner confirmed 2026-10-27). | P0 | ING-004 assumed a ZIP with `conversations.json`. Nothing in the specs could import today's data. | ADR-0002, SRC-001, ING-011 |
| 3.2 | `conversations/`: 1,160 JSON files. 1,158 per-conversation "split-wrapper" files named `YYYY-MM-DD.<slug>.json` (by year: 217 / 282 / 494 / 165 for 2023–2026), plus 2 derived classifier outputs. Slugs collide on title (a `-2` suffix seen). Largest file ~1.6 MB, total ~82 MB. | P0 | Titles and filenames can never be identity. Derived files must not be parsed as conversations. | ADR-0002/0003, ING-011 |
| 3.3 | Wrapper keys: conversation ID, title, create time, date, filename, message counts, image reference count and the full native conversation object (`mapping`, `current_node`, flags such as archived/temporary/starred, memory scope, template ID, plugin IDs…). | P1 | The native object is the source of truth; wrapper counts are hints to cross-check. | ING-011 |
| 3.4 | Sampled nodes have `id`, `message`, `parent` but **no `children`**. Messages carry `author`, `content`, `create_time`, `id`, `metadata` only; fields such as `status`, `end_turn`, `weight`, `recipient` are absent. | P1 | ING-005 must derive children. The split format may be lossy; fidelity warnings needed. | ING-005 amendment, ING-011 |
| 3.5 | Sample of 50 conversations: 1,747 nodes; 14 fork points; 0 orphan parents; 0 multi-root graphs; `current_node` chain valid in 50/50. Roles: user, assistant, system, tool. Content types: text, thoughts, reasoning_recap, code, user_editable_context, multimodal_text, tether_quote, tether_browsing_display, execution_output. | P1 | Branch handling is needed from day one. Reasoning ("thoughts"), custom-instruction (`user_editable_context`) and browsing content need explicit treatment: preserved, flagged, excluded from user-decision evidence by default. | ING-006, REL-001 |
| 3.6 | Image pointers use `file-service://` and `sediment://` schemes. In the sample, 26 of 29 pointers matched a file in `raw/images/` by file-ID prefix; 3 did not. | P0 | Missing images are real, not hypothetical. | ADR-0004, MED-002 |
| 3.7 | `images/`: 913 files (534 png, 227 webp, 130 jpg, 22 jpeg; ~1.15 GB), named `file_<hex>-<uuid>` or `file-<id>-<uuid>`, plus an empty `unknown_origin/`. | P1 | Copying all media into a vault duplicates ~1.15 GB. | OD-02, OD-14 |
| 3.8 | `export_manifest.json` (v1) lists 1,726 original export files (~1.6 GB): 12 sharded `conversations-NNN.json` parts, `chat.html`, 5 account JSON files, ~721 `.wav`, 13 `.mp4`, ~931 images across `user-*/`, `dalle-generations/`, root uploads and 26 per-conversation asset folders. | P1 | The original sharded JSON, all audio and all video are not in `raw/`. Manifest lets us report them as `missing` with evidence. | OD-01, OD-10, MED-002 |
| 3.9 | In the sample, 12 URLs, 2 of them YouTube; no social profile URLs; no bare `@handle` matches. | P2 | Real volume is modest; fixtures must carry the edge cases. | EVAL-009 |
| 3.10 | `raw/` is listed in `.gitignore`; the repository tracks no `raw/` files (`git ls-files` shows only docs and root files). | — | Good. OPS-008 keeps it that way. | — |

## 4. Requirement findings (owner requirements A–D and 2.1–2.6)

Full matrix: `REQUIREMENTS_TRACEABILITY.md`. Status is what the specs said **before** this audit.

### 4.1 Raw conversations and images (CLAUDE.md §2.A, work order 2.1)
| # | Finding | Prior status | Sev | Amendment made |
|---|---|---|---|---|
| A1 | Actual raw layout (split wrapper, flattened images, manifest) not covered (§3.1). | missing | P0 | ADR-0002; FR-25; TR-13; SRC-001, ING-011; ING-004 amended |
| A2 | `node_assets` conflates file and occurrence; no blob/asset/occurrence split; no `unresolved/ambiguous`; no thumbnail separation (DATA_MODEL §1). | partial | P0 | ADR-0004; DATA_MODEL §10; MED-001..MED-003 |
| A3 | No pointer-resolution contract (`collect_assets(zip_manifest)` in ARCHITECTURE §3 only lists ZIP entries). | missing | P0 | MED-002; ARCHITECTURE §7.1 `AssetPointerResolver` |
| A4 | No Obsidian embed/missing-marker contract; DOC tickets mention "source links" only. | missing | P0 | FR-27; MED-004; DOC-003/DOC-006 amended |
| A5 | "No cloud vision/OCR by default" was implied by local-only default but not stated for images. | partial | P1 | TR-13; ADR-0007 `vision` switch |
| A6 | Raw read-only rule exists in CLAUDE/AGENTS but no ticket or test enforces it. | partial | P1 | SRC-001 tree-hash check; OPS-008 |

### 4.2 Branches and related conversations (§2.B, 2.2)
| # | Finding | Prior | Sev | Amendment |
|---|---|---|---|---|
| B1 | Active path and alternatives covered (FR-03, ING-005), but no branch *kind* (edit vs regeneration) and no branch record (`ConversationThread.node_ids` is a flat list). | partial | P0 | ADR-0005; FR-28; REL-001; `branch_points` table |
| B2 | ING-005 assumes `children` exist; real data has none (§3.4). | conflicting | P1 | ING-005 amendment |
| B3 | Cross-conversation links: REC-002 predicates are record-level (`same_project, elaborates, references, creates`). No `continues/forked_from`, no evidence class, no direction rules for conversations, no review history. | partial | P0 | ADR-0005; FR-29; REL-002..REL-004; `conversation_relationships` |
| B4 | Related chats in notes/retrieval: PRD journey 4 mentions "related conversations with explanations" but no ticket renders them. | partial | P0 | REL-004; DOC-003 amended |

### 4.3 Repeat exports and deduplication (§2.C, 2.3)
| # | Finding | Prior | Sev | Amendment |
|---|---|---|---|---|
| C1 | Identity is per snapshot (`content_nodes` keyed by `snapshot_id`): a second full export would duplicate every message. No account namespace. | conflicting | P0 | ADR-0003; TR-12; DATA_MODEL §10; IMP-002 |
| C2 | ImportBatch (attempt) vs SourceSnapshot (bytes) conflated in `import_runs`. | partial | P0 | IMP-001; `import_batches` |
| C3 | No message revision model, no delta categories, no `not_seen` semantics in the data model (PRD only says "absence is unknown"). | missing | P0 | IMP-003; FR-30 |
| C4 | Missing/colliding native IDs: not covered. | missing | P0 | IMP-002 candidates |
| C5 | Concurrency/locking: only "unique constraints" (TR-05). No lock, no crash-resume test for imports. | partial | P1 | IMP-004 |
| C6 | Zero model calls on unchanged input: TR-09 states it; no mechanism tied to message identity. Cosmetic metadata drift would invalidate everything under a single-hash scheme. | partial | P0 | Two-hash scheme (ADR-0003, NRM-001 amendment) |
| C7 | Per-import delta report: PRD import dashboard lists counts, but not the owner's categories. | partial | P0 | IMP-005 |
| C8 | Human corrections surviving reimport: FR-22 is about Obsidian edits only. | missing | P1 | IMP-006; FR-37 |

### 4.4 URLs, YouTube and social accounts (§2.D, 2.4, 2.5)
| # | Finding | Prior | Sev | Amendment |
|---|---|---|---|---|
| D1 | No deterministic URL occurrence capture; EXT-006 is an LLM reference extractor in the semantic phase. | missing | P0 | ADR-0006; LNK-001; EXT-006 amended |
| D2 | YouTube only in INT-002 (P1, behind the web connector). Detection, canonical ID and status would arrive last. | conflicting (with owner's "must not be omitted") | P0 | YTB-001, YTB-002; INT-002 rescoped |
| D3 | Transcript statuses and provenance: README lists statuses; no data model. ING-010 parses VTT/SRT but has no link to videos or mentions. | partial | P0 | YTB-002; `transcript_*` tables |
| D4 | Social account registry: absent from PRD, TR, data model and tickets (MOONSHOT mentions profiles as future). | missing | P0 | SOC-001..SOC-003; FR-33 |

### 4.5 Core requirements (2.6) — remain intact
Taxonomy governance (FR-06/07, TAX-*), segmentation (FR-05, NRM-004/005), primary/secondary classification (FR-08, CLS-*), typed evidence-backed records (FR-09/10, EXT-*), historical/current state (FR-11, REC-*), masters (FR-14, DOC-004/005), search/RAG (FR-15/16, RET-*), Obsidian (FR-13, DOC-*), provenance (FR-20), multi-user later (FR-23, PROD-*). **Status: covered** at specification level. Audit changes touch them only to add dependencies (CLS-001/EXT-008 on FND-009; EXT-005/006 on media/link registries; DOC-003 on media/relationships).

### 4.6 Sequencing
| # | Finding | Sev | Amendment |
|---|---|---|---|
| S1 | Nothing browsable until DOC-001, which waits for REC-006 (whole LLM pipeline). DOC-002 (generic renderer) depended on DOC-001 without technical need. | P0 | ADR-0008; DOC-002 now depends on FND-005; BRW-001 |
| S2 | No batch-scale tests before the 1k performance run; owner asked for 50/100 early. | P0 | EVAL-010 (M1), EVAL-011 (M3); TEST_STRATEGY §12.4 |

### 4.7 Model use and consistency (owner input during the audit)
| # | Finding | Prior | Sev | Amendment |
|---|---|---|---|---|
| M1 | Docs say local-only default; owner now says cloud and agents are fine where they help. | conflicting | P1 | ADR-0007 (proposed); PRD §11, TR-08 annotated; OD-04 |
| M2 | FND-007 provides a protocol and fake provider only. No real provider, no structured-output enforcement, no repair policy. Past failures were exactly untyped, inconsistent output. | partial | P0 (for M3) | FND-009; TR-16 |
| M3 | Timeouts/rate limits/batch failures (seen on OpenRouter) handled generically by TR-03; no batch smoke test. | partial | P1 | OPS-002 amendment; EVAL-011 |
| M4 | Beginner-readable code and talking points requested by the owner; CLAUDE.md §5 asks for sparse "why" comments. | partial | P2 | Reconciled: docstrings that explain what/why + why-comments on invariants + module talking points; no line-by-line noise. FND-001 amendment; TR-11; plan §11 |

## 5. Architectural risk review

For each: primary solution, alternatives, deterministic check, failure state.

| Risk | Primary | Alternatives / trade-off | Acceptance check | Failure state |
|---|---|---|---|---|
| Raw folder permissions / accidental writes | Read-only open + pre/post tree hash + OPS-008 git guard | OS-level read-only ACL (stronger, more setup) | Tree hash equal after every command in fixtures | Abort import, report `raw_modified` |
| Large JSON | Streaming parser per conversation | Load per shard (simpler, needs RAM) | 100 MB synthetic shard under memory cap | Fail that file with `too_large`, continue others |
| Missing native IDs | Candidate match + review | Deterministic synthetic ID from position (risky across exports) | `missing_ids` fixture | Imported as separate, flagged |
| Malformed graph (cycles, orphans) | Integrity checker keeps all nodes, flags | Drop bad nodes (loses data) | adversarial graph fixture | `graph_warning`, render as disconnected section |
| Missing image bytes | Availability states + manifest evidence | — | `missing_asset` fixture | Marker in notes |
| Unreliable link matching | Strict span rules; raw string kept | Use a URL library's parser only (misses markdown edge cases) | table-driven spans | `unparsed` occurrence kept |
| Transcript access/rate limits | Status machine, opt-in, user-supplied first | Paid transcript API (cost, terms) | network-off test | `unavailable`/`permission_required` |
| Privacy/security | Per-capability egress, redacted logs, public-repo guard | Fully offline (repeats past quality problems) | log-scrub test; OPS-008 | Refuse call, record `egress_denied` |
| Parser version drift | Parser version in batch + stage keys | — | version bump re-parses only, no re-classify unless content hash changes | Old and new parse coexist |
| Export schema drift | Unknown fields preserved; fidelity warnings; two hashes | Strict schema (breaks on change) | `metadata_drift` fixture | Warning, not failure |
| Taxonomy drift | Unchanged (TAX-* governance, versioned) | — | EVAL-008 | Review |
| Dedup concurrency | Import lock + unique keys + idempotency keys | Advisory file lock only | concurrent test | Second writer refused |
| Checkpoint rollback | Group transactions + checkpoint row in same tx | Whole-import transaction (simple, huge) | crash injection | `partial`, resume |
| Obsidian attachment links | Hash-based vault paths + link checker | Absolute paths to `raw/` (fragile, leaks paths) | MED-004 | Marker, not broken embed |
| Prompt injection | Source-as-data boundary; extraction has no tools | — | `prompt_injection_text` fixture | Text stored only |
| Testing time/cost | Fake provider by default; real provider only in EVAL-011 with cost cap | Record/replay cassettes | CI runs without credentials | Gate `BLOCKED`, not looped |
| Event dependency cycles | Source layer emits forward only; unchanged revisions emit nothing | — | event graph listed in ARCHITECTURE §7.2 | — |
| Model inconsistency (history) | Structured output, enum IDs, pinned versions, stability metric | Ensemble voting (more cost) | EVAL-008/011 | Review queue |

## 6. Ticket reconciliation summary

Full list with old/new text: `SPEC_CHANGELOG.md`. Graph: `docs/plans/DEPENDENCY_MAP.md`.

- **Added (29):** FND-009, OPS-008, EVAL-009, SRC-001, IMP-001, ING-011, REL-001, IMP-002, IMP-003, IMP-004, MED-001, MED-002, MED-003, IMP-005, EVAL-010, LNK-001, YTB-001, YTB-002, SOC-001, SOC-002, REL-002, MED-004, BRW-001, EVAL-011, IMP-006, REL-003, REL-004, YTB-003, SOC-003.
- **Blockers changed (12):** ING-003, CLS-001, EXT-005, EXT-006, EXT-008, DOC-002, DOC-003, DOC-006, EVAL-002, EVAL-006, OPS-004, INT-002.
- **Scope amended without blocker change (13):** FND-001, FND-002, FND-005, FND-007, ING-001, ING-004, ING-005, ING-006, ING-007, NRM-001, REC-002, EVAL-001, OPS-002.
- **Rescoped:** ING-003 (orchestration only; identity moved to IMP-*), INT-002 (network providers only; statuses in YTB-002), EXT-006 (consumes link registries).
- **Priority changes:** none to existing tickets. YouTube detection is P0 through new tickets; INT-002 stays P1.
- IDs never renumbered. The graph stays acyclic (checked).

## 7. Decisions only the owner can make
OD-01 original export ZIP availability · OD-02 media storage mode · OD-03 account namespace · OD-04 cloud egress policy · OD-05 provider/model · OD-06 vision opt-in · OD-07 transcript sources · OD-08 tracker of record · OD-09 derived files inside `raw/` · OD-10 audio/video scope · OD-11 missing skills/history files · OD-12 fork-detection thresholds · OD-13 two-hash scope · OD-14 Obsidian attachments · OD-15 social registry scope · OD-16 packaging, licence and monetisation. See `OPEN_DECISIONS.md`.
