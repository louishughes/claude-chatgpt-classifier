# Codebase audit: what to delete, simplify or question (2026-11-10)

**Asked by:** Louis, 2026-11-10 00:24 UTC: "audit our codebase, is anything here unnecessary, overly complicated in our current setup, or based on weak assumptions? Challenge them. What can be deleted entirely? What can be simplified? Then make the changes. Prefer deleting over simplifying, simplifying over optimizing, and optimizing over automating."
**Audited:** `main` at `aa3b5d6` (64,237 lines in `src/`, 303 test files, 35 migrations, 115 docs files).
**Rules kept:** no test, evaluation criterion, answer key or reference set was changed or deleted. Anything whose removal would also remove tests is listed under **Needs Louis** instead of being done (owner guardrail 1).

## How "unnecessary" was decided

Every claim below rests on one of these checks, not on taste:

1. **Import graph.** A script parsed every module's imports and listed modules that no other production module imports.
2. **Name references.** For every top-level function and class, a script counted references in the rest of `src/` (Python and HTML templates). Zero means no production caller; it then counted references in `tests/` separately.
3. **vulture** (dead-code finder) at 60% confidence over `src` and `tests`, with false positives removed by hand (FastAPI route handlers, SQLAlchemy columns and Pydantic validators look unused to it but are called by their frameworks).
4. **Docs and decisions.** `STATUS.md`, `docs/reviews/OPEN_DECISIONS.md` and the ADRs, to see whether a piece is wanted.

**Result in one line:** at the function level the code is tight (only one truly dead function and one 28-way copy). The real weight is at the **feature** level: whole subsystems that were built while the plan said "parked", code that only tests call, two note templates side by side, and instruction docs that still describe a project with no code.

## Done in this PR (no test touched)

| # | Change | Evidence | Effect |
|---|---|---|---|
| D1 | **Deleted** `cli/main.py::_not_built` | zero callers in `src/` and `tests/`; every command is built | 11 lines gone. Exit code 4 (`NOT_IMPLEMENTED`) stays in the list, because `tests/unit/test_cli.py` pins the numbers and scripts may rely on them; the module docstring now says so. |
| S1 | **Simplified** 28 identical private `_utc_now()` functions into one `utc_now()` in `infrastructure/db.py` | the same two lines (`return datetime.now(UTC)`) in 28 modules; no test patches any of them | one definition instead of 28; every table's timestamps now come from one place |
| S2 | **Simplified** 3 identical `_aware()` helpers into one `as_utc()` beside it | same one-liner in `classification/store.py`, `reconciliation/projection.py`, `taxonomy/refresh.py` | one explained place for "SQLite gives times back without a time zone" |

Net: 31 files, about 125 lines fewer. Behaviour is unchanged: column defaults are worked out in Python, not stored in the schema, so the migrations and the schema-drift test are unaffected.

## Needs Louis (ordered by size of the win)

### N1. The "thousands of customers" premise vs the repo's own decision record

The request says the product is used by thousands of customers. The repo says the opposite, in writing:

- `docs/reviews/OPEN_DECISIONS.md` **OD-19**: "it stays a single-person, local engine. The hosted pieces ... are built and tested but unused."
- `OPEN_DECISIONS.md` scope decision (REV-001): API-001..005, PROD-001..004, OPS-007 and INT-001..003 are labelled **parked** because "122 tickets including an API, PostgreSQL and multi-user support re-open failure mode F7 (too much system too early)".
- `docs/operations/HOSTING_AND_SECURITY.md`: "Before anyone else's data goes into a hosted engine, have someone independent go through the threat model and get a data-protection opinion." That has not happened.

This audit was done to the "no corners cut" standard either way. But the answer to N2 depends on which statement is true, so it is Louis's call. **If real customers' data is in a hosted engine today, that is a UK GDPR problem before it is a code problem** (OD-19 lists the controller/processor duties).

### N2. Delete the parked hosted/multi-user layer (largest deletion available)

| Piece | Source lines | Test lines |
|---|---|---|
| `api/` (FastAPI JSON API, API-001..005) | 1,823 | `test_api*.py` (6 files, 1,250) |
| `access/` (accounts, tokens, roles, tenants; PROD-002/003) | 622 | `test_api_access.py`, `test_tenant_isolation.py`, `test_hosting_security.py` |
| PostgreSQL proof of concept (`devtools/postgres.py`, `evaluation/backend_bench.py`, the PostgreSQL branch in `importer/run.py` and `infrastructure/dialects.py`; PROD-001) | ~250 | `test_postgres_backend.py` (15 tests that skip in CI containers anyway) |
| CLI: `ke api`, `ke access`, `ke tenant` | in `cli/main.py` | in the files above |
| **Total** | **~2,700** | **~1,900** |

Evidence it is unused: OD-19 (above); `ke ui` (the web pages Louis actually uses) does not import `api/` or `access/`; no `.bat` launcher starts `ke api`.
Cost of deleting: `infrastructure/dialects.py` itself must stay, because all the trigger migrations call its `run_triggers`; only its PostgreSQL branch goes. It removes tests (needs Louis's yes); migration 0029's tables stay in existing databases (migrations are history and are never edited), so a later migration would drop them, or they stay unused.
**Recommendation:** delete, if N1's answer is "single person". Git keeps it all; it can come back if hosting is ever real.

### N3. Delete the other parked integrations, or confirm they are wanted

| Ticket | Module | Src / test lines | Notes |
|---|---|---|---|
| INT-001 website fetching | `ingestion/web.py` | 470 / 230 | off by default (`network_fetch` switch, empty allowlist) |
| INT-002 YouTube captions via the Data API (OAuth) | `links/youtube_captions.py` | 182 / 214 | user-supplied transcripts (YTB-002) already cover the requirement without OAuth |
| INT-003 watched folders | `importer/watch.py` | 235 / 242 | re-running `ke import` does the same thing, idempotently |

All three were labelled *parked* by the scope decision and built anyway. **Recommendation:** delete INT-002 and INT-003 (a manual `ke import` and user-supplied transcripts already meet requirements C and D); keep INT-001 only if website import is on the roadmap.

### N4. Code that only tests call (no production path reaches it)

| Code | Lines | What it is |
|---|---|---|
| `classification/drift.py` (CLS-005) | 140 | order-independence experiment; no `ke` command runs it |
| `taxonomy/projects.py` (TAX-005) | 111 | project-name proposals; nothing in the pipeline calls `propose_project` |
| `providers/base.py::ReplayProvider` | 39 | replays recorded answers; only tests use it |
| `taxonomy/discovery.py::discover` | 55 | the module's other parts are used, this entry point isn't |
| `segmentation/segmenter.py::boundary_scores`, `classification/scoring.py::corpus_frequencies`, `graph/offsets.py` UTF-16/UTF-8 converters, `links/video_transcripts.py::video_status`, `documents/notes.py::related_conversations`, `evaluation/end_to_end.py::build_fixture` | ~85 | helpers kept for tests or "for later" |

Each one either becomes wired into a real command or is deleted with its tests. **Recommendation:** wire `drift.py` into `ke eval` (it guards a real requirement: classification must not depend on order) and delete the rest. `evaluation/relationship_key.py::key_schema` is also uncalled, but it belongs to the answer-key tooling a PC session may use, so it was left alone.

### N5. Two note templates side by side

`ke docs vault` and `ke docs chat` still write the **v1** layout (`documents/notes.py`, DOC-003/005) by default; the **v2** rich note (`documents/rich_note.py`, `readable_master.py`, NOTE-001/010) is what the dashboard shows and what every recent ticket and the 1 Nov independent review improved. The code says "v1 stays the default for now" (`cli/main.py`, `_docs_note`). That "for now" is the weak assumption: two renderers mean every note fix is made twice or only half-made. **Recommendation:** make v2 the only template, delete v1's renderer (keeping the helpers v2 imports from it). This changes the e2e golden and note tests, so it needs Louis.

### N6. The throwaway spike

`prototype/classification_spike/` (14 files, ~3,000 lines, its own tests) is described in `pyproject.toml` as "throwaway", and its verdict is recorded in `docs/plans/SPIKE_VERDICT.md`. CI, ruff and mypy all skip it, so nothing checks it still works. **Recommendation:** delete it (git history keeps it). Its tests go with it, so this needs Louis's yes.

### N7. Instruction docs that describe a project with no code

Every agent reads these first, and they say the wrong thing:

- `CLAUDE.md` line 3: "Do not start implementing the application until the specification audit ... approved." The application is 64,000 lines.
- `README.md`: "Current status: specification audit and planning; not a completed application", "no application code is written".
- `AGENTS.md` "Current gate": "GATE 0 / DOC-RECONCILIATION ONLY ... No runtime application code."
- `CLAUDE_CODE_HANDOFF_PROMPT.md` (root) and `docs/HANDOFF_AFTER_AUDIT.md`: first-session instructions for an audit finished on 2026-10-27.
- `STATUS.md` already flags that AGENTS.md guardrail 1 still says the owner approves the gold set, which the project rules have since changed.

**Recommendation:** delete the two handoff files, and rewrite the top of `README.md`, `CLAUDE.md` and `AGENTS.md` to say what exists and how to run it. Agents are not allowed to edit `AGENTS.md` themselves, so this waits for Louis.

### N8. Four logs that say the same thing

Each ticket is written up in up to four places: `STATUS.md` (72 KB), `.agent-history/SESSION_LOG.md` + `sessions/` (33 files), `docs/diary/BUILD_DIARY.md` (390 KB) + `entries/` (37 files), and the GitHub Issue. For example, `docs/diary/entries/2026-11-01-1752-RCL-004.md` and `.agent-history/sessions/2026-11-01-1752-RCL-004.md` are word-for-word the same. **Recommendation:** keep the diary (a project rule) and GitHub Issues (the ticket system), shrink `STATUS.md` to a short "what works today" page, and stop writing `.agent-history/` session files. The diary rule comes from the project instructions, so this needs Louis.

### N9. Simplify later (not urgent)

`cli/main.py` is one 5,450-line file holding every `ke` command. Splitting it by command group (import, docs, eval, ...) would make it far easier to read, but it is a large move with no behaviour change, so it should wait until N2 to N6 have shrunk it.

## Not changed, and why

- **Migrations** (35 files): they are the history of every existing database; editing or deleting one breaks upgrades.
- **The `vision` egress switch** that nothing uses yet: it is the promise that images are never sent anywhere silently (CLAUDE.md requirement A), and removing it would make existing config files that mention it fail to load.
- **ORM classes that look unused** (`DerivedMediaArtifactRow`, `PurgeEventRow`): they define tables the purge code and the schema-drift test rely on.
- **Anything on Louis's PC** (`raw/`, gold notes, reference digests): not read. Nothing deleted here is importable by a script on the PC except through the names removed in D1/S1/S2, which were private (underscore) names.
