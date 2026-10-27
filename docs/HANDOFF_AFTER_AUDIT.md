# Handoff After Specification Audit

**Date:** 2026-10-27 · **Session type:** documentation-only audit (Gate 0) · **Baseline:** `main` at `103bcb3` · **Branch:** `claude/project-thread-bk4540` · **State:** awaiting product-owner approval. **No application code exists.**

## 1. What changed
- Created: `docs/reviews/{SPEC_AUDIT, REQUIREMENTS_TRACEABILITY, SPEC_CHANGELOG, OPEN_DECISIONS}.md`, `docs/plans/{IMPLEMENTATION_PLAN, DEPENDENCY_MAP}.md`, this file, `docs/adr/README.md` + ADR-0002..0008 (all `proposed`), `docs/diary/BUILD_DIARY.md`.
- Amended (annotations, no destructive rewrites): `docs/PRD.md` (FR-25..FR-37, journeys 9–11), `docs/TECHNICAL_REQUIREMENTS.md` (TR-12..TR-16), `docs/ARCHITECTURE.md` (§7 source layer), `docs/DATA_MODEL_AND_CONTRACTS.md` (§10), `docs/TEST_STRATEGY.md` (§12), `docs/DECISIONS_AND_HISTORY.md` (locations, project history, ADR index), `AGENTS.md` (path note), `docs/ROADMAP_AND_TICKETS.md` + `docs/TICKETS.csv` (93 → 122 tickets; 12 blocker changes; 25 amended tickets; new `audit_amendment` CSV column).
- Full list with old/new text: `docs/reviews/SPEC_CHANGELOG.md`.

## 2. Checks actually run

| Check | Method | Result |
|---|---|---|
| Ticket ID uniqueness | Python over CSV and Markdown | PASS (122 unique in each) |
| CSV ↔ Markdown agreement | Same set, same order; title, priority, dependencies, objective, acceptance compared field by field | PASS (0 mismatches) |
| Missing blockers / self-dependencies | Python | PASS (none) |
| Dependency cycles | Kahn topological sort | PASS (acyclic, 122/122 sorted) |
| Blockers precede dependents in file order | Python | PASS |
| Traceability completeness | Every ticket ID cited in reviews/plans/ADRs exists; every new ticket appears in the traceability matrix | PASS |
| Relative Markdown links and backticked `docs/…` paths in changed files | Python | PASS except intentional mentions of absent files (`docs/README.md`, `docs/TICKET_INDEX.md`, `docs/.claude/skills`, `docs/skills`, `docs/docs`) and placeholders (`docs/adr/NNNN-title.md`, the range shorthand `docs/adr/0002`) |
| No raw writes | Device listing of `raw/`, `raw/conversations/` (1,160 entries) and `raw/images/` (914 entries) compared before and after: names, sizes, modification times | PASS (identical) |
| raw/ not tracked by Git | `git ls-files` | PASS (0 files under `raw/`) |
| No private names leaked into docs | Every changed file searched for all 1,120 conversation slugs and 911 image file-ID prefixes from the raw listing, plus account/conversation ID fragments seen during inspection | PASS (0 hits) |
| Git diff confined to intended docs | `git status --porcelain` | PASS (only `AGENTS.md`, `docs/*.md`, `docs/TICKETS.csv`, new `docs/adr|diary|plans|reviews/`) |
| Paid providers / outside URLs | none invoked | n/a |
| Unit/integration tests | **NOT RUN**: no code exists | — |
| Markdown rendering of Mermaid diagrams | **NOT RUN** | — |
| CSV consumers with the new column | **NOT RUN**: none exist yet | — |

How the raw data was looked at: directory listings, and JSON key names/value types (never values) of the manifest, the two derived files and a stratified sample of 50 conversations, copied temporarily into the session container and deleted afterwards. Aggregate counts only appear in the docs.

## 3. Not done (explicitly)
- No `src/`, tests, migrations, CLI, imports, model calls, network fetches.
- FND-001 not started. No ticket moved from `NOT_STARTED`.
- GitHub Issues not created (OD-08).
- Missing package files (skills, `.agent-history/`, prompts, `AGENT.md`, `HANDOFF.md`, `CHANGELOG.md`) not recreated (OD-11).
- `RESEARCH_REPORT.md` broken relative links not fixed (historical narrative).
- `CLAUDE.md` not edited (its tracker rule vs the work order is OD-08).
- The two derived files inside `raw/conversations/` were not moved (`raw/` is read-only; OD-09).
- ADRs are `proposed`, not accepted.

## 4. Decisions waiting for the owner
OD-01..OD-16 in `docs/reviews/OPEN_DECISIONS.md`. The ones that shape M1: **OD-01** (original export ZIP?), **OD-02** (media copy vs reference), **OD-03** (account namespace). Approving the plan without answering them accepts the recommended defaults.

## 5. Revised phases
M0 audit (done) → **M1 source-fidelity slice** (33 tickets, LLM-free, ends with source notes and 50/100 batch smoke) → M2 link/YouTube/social/relationship registries (9) → M3 semantic foundation with structured-output provider and 50/100 semantic smoke (31) → M4 reconciliation, retrieval, documents, late relationships (30) → M5 hardening/API (12) → M6 integrations/productisation (7). Details: `docs/plans/IMPLEMENTATION_PLAN.md` §4, order: `docs/plans/DEPENDENCY_MAP.md` §4.

## 6. Next step (updated 2026-10-27, owner decision)
Before FND-001, the owner chose to validate the AI labelling step with the throwaway spike in `prototype/classification_spike/` (IMPLEMENTATION_PLAN §12):
1. Done: schema with separate fields, decisions with speaker and state, 40 synthetic tests.
2. Waiting on the owner: API-data OK, cost cap, and run location (Remote Control session or owner runs it).
3. Gold sheet: `spike.py --sample 50 --gold-template 20`, then the owner labels about 20 chats (~1 hour).
4. Run 50 chats twice, then the owner reviews the report.
5. Go/no-go. Go means 100 chats, then FND-001. No-go means change the method and re-run against the same gold set.

Guardrails now in force: see `AGENTS.md` "Owner guardrails".

## 6a. First unblocked ticket (after the spike)
**FND-001 — Bootstrap Python repository and tool configuration** (no blockers). Includes the audit amendment: `docs/CODE_STYLE.md` with the learning-friendly comment standard. Next in order: FND-002, FND-003, FND-004, FND-005, FND-006, FND-008, OPS-008, EVAL-009 (EVAL-009 and OPS-008 only need FND-001 and can run right after it).

**Do not start FND-001 until the owner approves this plan.**
