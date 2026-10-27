# Session Log

Append-only record of each ticket closure: what changed, what ran, and the real results. Newest at the bottom.

## 2026-10-27 · FND-001 — Bootstrap Python repository and tool configuration

**Dependencies:** none. **Status:** VERIFIED.

**Changed files:** `pyproject.toml` (new), `src/knowledge_engine/__init__.py` (new), `src/knowledge_engine/py.typed` (new), `tests/unit/test_package.py` (new), `docs/CODE_STYLE.md` (new, audit amendment), `.gitignore` (workspace/ and tool caches), `README.md` §9 (developer setup), `STATUS.md` (new), `docs/TICKETS.csv` (FND-001 status → VERIFIED).

**Design choices:**
- Build backend: hatchling, src/ layout, `requires-python >= 3.12` (TECHNICAL_REQUIREMENTS baseline; owner's PC runs 3.13).
- No runtime dependencies yet; each is added by the ticket that first needs it.
- Ruff with pydocstyle `D` rules (Google convention) enforces the docstring rule for public modules, classes and functions; tests exempt. `docs/` and `prototype/` excluded from ruff (illustrative snippets and throwaway spike).
- mypy `strict` on `src/` and `tests/`.
- pytest collects `tests/` only, so the spike's tests (which need the Anthropic SDK) are not part of the package suite.
- `workspace/` git-ignored: the local DB/media store/vault lives inside the project folder by owner preference.

**Commands run (fresh venv in the session scratchpad, Python 3.13.17, Linux):**
```
python3 -m venv <scratch>/venv && <scratch>/venv/bin/pip install -e ".[dev]"   # ok
cd /tmp && python -c "import knowledge_engine; print(knowledge_engine.__version__)"   # 0.0.1
ruff check .            # All checks passed!
ruff format --check .   # 6 files already formatted
mypy                    # Success: no issues found in 2 source files
pytest -q               # 3 passed
```
Negative check: a temporary public module and function without docstrings produced `D100` and `D103` from `ruff check src`; the probe file was deleted.

**Not done / not tested:** not run on Windows yet (owner's PC). No CI (OPS ticket later). No licence chosen (OD-16).

**Next exact task:** FND-002 — Pydantic settings with per-capability egress switches (off by default), read-only raw roots, media storage mode, account namespace.

## 2026-10-27 · FND-002 — Environment and settings manager

**Dependencies:** FND-001 (VERIFIED). **Status:** VERIFIED.

**Changed files:** `src/knowledge_engine/settings.py` (new), `tests/unit/test_settings.py` (new), `ke.example.toml` (new), `pyproject.toml` (adds `pydantic`, `pydantic-settings`), `.gitignore` (`ke.toml`, `.env`), `STATUS.md`, `docs/TICKETS.csv` (FND-002 → VERIFIED).

**Design choices:**
- One frozen `Settings` object (pydantic-settings). Sources, highest first: keyword overrides, optional TOML file, `KE_*` env vars (nested with `__`), defaults.
- Audit amendment / ADR-0007: `EgressPolicy` with separate `text_llm`, `embedding`, `vision`, `network_fetch`, `transcript_fetch` switches, all off; `require()` raises `EgressDisabledError` naming the switch.
- `raw_roots`: path + `account_namespace` (OD-03 default: configured label, slug-validated) + `source_format`. A validator rejects any overlap between the workspace and a raw root (after resolving `..`), and duplicate raw roots.
- `media_storage_mode` defaults to `reference` (OD-02 default; JSON copy behaviour is ING-001's concern).
- `Limits`: file sizes > 0, batch size 1..10,000, model calls ≥ 0 (default 0), cost ≥ 0 and finite (default 0).
- Secrets: `anthropic_api_key` as `SecretStr`, from `KE_ANTHROPIC_API_KEY` or `ANTHROPIC_API_KEY` only; a config file containing it is refused, and the error names the key, not the value.
- Unknown keys in code/config fail (`extra="forbid"`).

**Commands run (same scratch venv, Python 3.13.17, pydantic 2.14.1, pydantic-settings 2.16.1):**
```
pip install -e ".[dev]"   # ok
ruff check .              # All checks passed!
ruff format --check .     # 10 files already formatted
mypy                      # Success: no issues found in 4 source files
pytest -q                 # 39 passed (3 FND-001 + 36 FND-002)
load_settings(config_file=Path("ke.example.toml"))   # parses; one raw root, workspace "workspace"
```
First mypy run flagged an unneeded `type: ignore` in the new test; removed (fix attempt 1 of 3, resolved).

**Known limitation:** a misspelt *environment variable* (e.g. `KE_EGRES__TEXT_LLM`) is silently ignored by pydantic-settings. That fails safe (the switch stays off) but is not reported. Typos in the config file or code are rejected.

**Not done / not tested:** Windows run. No `ke config show` command (FND-008 CLI). ADR-0007 remains `proposed`.

**Next exact task:** FND-003 — SQLAlchemy engine for SQLite with WAL and foreign keys, session factory, transaction scope, round-trip and rollback test.

## 2026-10-27 · FND-003 — Relational persistence interface and SQLite engine

**Dependencies:** FND-001, FND-002 (both VERIFIED). **Status:** VERIFIED.

**Changed files:** `src/knowledge_engine/infrastructure/__init__.py`, `infrastructure/db.py`, `infrastructure/workspace.py` (new), `tests/unit/test_db.py` (new), `pyproject.toml` (adds `sqlalchemy>=2.0.36,<2.1`), `STATUS.md`, `docs/TICKETS.csv` (FND-003 → VERIFIED).

**Design choices:**
- `create_sqlite_engine`: per-connection `foreign_keys=ON`, `journal_mode=WAL` (raises `DatabaseConfigError` if refused), `busy_timeout` (default 5 s), `synchronous=NORMAL`. Pragmas re-checked on a first connection.
- The pysqlite driver's implicit transaction handling is disabled and `BEGIN` is emitted by an engine event (SQLAlchemy's documented fix), so savepoints work.
- `SessionFactory.transaction(write=True)`: commit on success, rollback on exception, always close. Write transactions use `BEGIN IMMEDIATE` (take the write lock up front); `write=False` uses `BEGIN DEFERRED`.
- `Base` declarative class with a constraint naming convention for Alembic (FND-004).
- `WorkspaceRow` / `WorkspaceRepo` (`workspaces`: random 32-hex ID, unique name, created_at UTC). Repos flush but never commit. Table creation in tests uses `create_all`; FND-004 replaces that with migrations.
- Database path: `<workspace_root>/knowledge.db`.

**Commands run (scratch venv, Python 3.13.17, SQLAlchemy 2.0.55, SQLite 3.45.1):**
```
ruff check .            # All checks passed!
ruff format --check .   # 14 files already formatted
mypy                    # Success: no issues found in 8 source files
pytest -q               # 54 passed (15 new for FND-003)
```
Mutation check: switching write transactions to `DEFERRED` made `test_write_transaction_takes_the_lock_before_its_first_write` fail (1 failed, 14 passed); reverted, all pass. First mypy run flagged a `str | None` attribute access in a new test; fixed (attempt 1 of 3).

**Risk carried forward:** the plan notes WAL on Windows network drives. `V:` must be checked on the owner's PC: SQLite may accept WAL on a network share and still be unsafe. To verify during the first Remote Control run.

**Not done / not tested:** Windows run; Alembic (FND-004).

**Next exact task:** FND-004 (Alembic baseline) or FND-005 (domain models and stable IDs); both unblocked.

## 2026-10-27 · Housekeeping — bytecode caches untracked

The root `.gitignore` had no `__pycache__/` entry (only `prototype/.gitignore` did), so the FND-001..003 commits included 8 `.pyc` files. Added `__pycache__/`, `*.py[cod]`, `.pytest_cache/`, `.venv/` to the root `.gitignore` and untracked the files (separate commit).

## 2026-10-27 · FND-004 — Alembic migration baseline

**Dependencies:** FND-003 (VERIFIED). **Status:** VERIFIED.

**Changed files:** `src/knowledge_engine/infrastructure/migrations/` (new: `__init__.py` helpers, `env.py`, `script.py.mako`, `versions/0001_baseline.py`), `tests/unit/test_migrations.py` (new), `pyproject.toml` (adds `alembic>=1.14,<2`), `STATUS.md`, `docs/TICKETS.csv` (FND-004 → VERIFIED).

**Design choices:**
- Migrations ship inside the package (no `alembic.ini`); `alembic_config(engine)` passes the app's configured engine to `env.py`, so migrations run with the same pragmas and explicit-BEGIN handling.
- `render_as_batch=True` for future SQLite column changes; `compare_type=True`.
- Hand-written, numbered revision IDs (`0001_baseline`) for readability.
- Baseline contains only `workspaces` (the only table so far). Each later ticket adds its own migration.
- Helpers: `upgrade_to_head`, `downgrade_to`, `current_revision`, `head_revision` (fails if the scripts branch).

**Commands run (scratch venv, Alembic 1.20.1):**
```
ruff check .            # All checks passed! (after ruff --fix sorted env.py imports: attempt 1 of 3)
ruff format --check .   # 18 files already formatted (after formatting one blank line)
mypy                    # Success: no issues found in 12 source files
pytest -q               # 61 passed (7 new for FND-004)
pip wheel . ; fresh venv install of the wheel; upgrade a new DB   # "installed wheel migrates to 0001_baseline"
```
Tests cover: upgrade empty DB twice (no-op second time), schema equals table definitions (Alembic `compare_metadata` → no diff), constraint names, downgrade to base and re-upgrade, existing rows survive a re-upgrade, migrated DB works with `WorkspaceRepo`.
Mutation check: adding an unmigrated column to `WorkspaceRow` made the drift test (and two others) fail; reverted.

**Not done / not tested:** Windows run. No CLI command yet (`ke db upgrade` belongs to FND-008).

**Next exact task:** FND-005 — domain models and stable identifiers (ADR-0003).

## 2026-10-27 · Owner answer — `V:` is a local disk

Louis confirmed (21:06 UTC) that `V:` is a local disk, not a network drive. The FND-003 risk about WAL on network drives does not apply; the database stays at `V:\Programming\ChatGPT_Classifier\workspace\knowledge.db` (git-ignored).

## 2026-10-27 · FND-005 — Domain models and stable identifiers

**Dependencies:** FND-001 (VERIFIED). **Status:** VERIFIED, with a scope note.

**Changed files:** `src/knowledge_engine/domain/` (new: `__init__.py`, `ids.py`, `enums.py`, `models.py`), `tests/unit/test_domain_ids.py`, `tests/unit/test_domain_models.py` (new), `pyproject.toml` (dev: `hypothesis`), `STATUS.md`, `docs/TICKETS.csv` (FND-005 → VERIFIED), diary (FND-004 entry time corrected from 21:06 to 21:03).

**Design choices (ADR-0003, ADR-0004):**
- IDs are `<prefix>_<first 32 hex of SHA-256>` over a JSON-encoded key `["ke-id-v1", kind, parts...]`. JSON makes part boundaries unambiguous; the kind and per-kind prefix keep kinds from colliding; `ID_SCHEME_VERSION` makes any future change explicit.
- Helpers for snapshot, conversation `(workspace, source_system, account_ns, native_id)`, message node `(conversation, native_node_id)`, message revision `(node, canonical_content_hash)`, graph edge `(child, parent|root)`, media asset (tagged native file ID, else tagged blob hash), asset occurrence `(revision, part_index, pointer)`, link target, link occurrence `(revision, start, end, origin)`, YouTube video ID validation, social account (tagged stable platform ID, else lower-cased handle without `@`), relationship `(from, kind, to, detector)`.
- Native IDs are used exactly (no trimming or case folding); empty native IDs raise. Titles are never part of a key.
- Enums from DATA_MODEL §10: `SourceSystem`, `Role`, `DeltaCategory`, `PresenceState`, `ImportBatchStatus`, `AssetAvailability`, `BranchKind`, `ReviewState`, plus `check_transition` for the §10.2 lifecycles (import batch never returns to running; presence toggles; review candidate → accepted/rejected, accepted → superseded).
- Frozen, `extra="forbid"` models: `SourceSnapshot`, `MessageRevision`, `AssetOccurrence`, `EvidenceRef`. Each model with an ID checks the ID against its key. Timestamps must carry a timezone; missing stays `None`. An `available` occurrence must name its asset.

**Scope note (for owner review):** the original objective also lists `SourceArtifact`, `ContentNode`, `Segment` and `KnowledgeRecord`. `ContentNode`/`SourceArtifact` are superseded by the ADR-0003 node/revision model; `Segment` and `KnowledgeRecord` are left to the M3 tickets that use them, because their shape depends on the taxonomy work the spike reshaped. The acceptance criterion (Pydantic validation and deterministic ID property tests) is unchanged.

**Commands run:**
```
ruff check .            # All checks passed!
ruff format --check .   # 24 files already formatted (after formatting one test file)
mypy                    # Success: no issues found in 18 source files
pytest -q               # 120 passed (59 new for FND-005, Hypothesis property tests included)
```
Fix attempts: mypy rejected the dict-copy typing in `check_transition` (attempt 1, rewritten with an explicit type check first); one line over 100 characters (same pass). A pinned known-value test (`conv_0bfffaf4519e5747672b77cac126e764` for `ws0/chatgpt/fixture/c1`) guards the scheme.

**Not done / not tested:** Windows run; no database tables for these objects yet (IMP-001/IMP-002/MED-* add them with migrations).

**Next exact task:** FND-006 (jobs and stage keys) or EVAL-009 (synthetic fixtures). EVAL-009 is the more useful next step for the import slice.

## 2026-10-27 · Owner direction — build all milestones

Louis (21:33 UTC, via the project chat): "WE need to do all the milestones". Work continues ticket by ticket in DEPENDENCY_MAP order through M1–M6, still stopping at the plan's human approval points (before the first real-provider call in M3, before any network integration in M6, before deletion features on real data) and under the owner guardrails. A separate thread is creating GitHub Issues for all tickets; commits will reference issue numbers once they exist.

## 2026-10-27 · EVAL-009 — Synthetic source-fidelity fixture suite and scale generator

**Dependencies:** FND-001 (VERIFIED). **Status:** VERIFIED, with a scope note.

**Changed files:** `src/knowledge_engine/evaluation/__init__.py`, `evaluation/synthetic.py` (new), `tests/fixtures/chatgpt/` (14 generated cases), `tests/fixtures/README.md`, `tests/unit/test_synthetic_fixtures.py` (new), `.gitattributes` (`tests/fixtures/** -text`), `STATUS.md`, `docs/TICKETS.csv` (EVAL-009 → VERIFIED).

**Design choices:**
- Fixtures are generated by code (`python -m knowledge_engine.evaluation.synthetic tests/fixtures/chatgpt`) and committed. A test regenerates them and compares byte for byte. Images are 4×4 PNGs with uncompressed (stored) deflate so bytes don't depend on the zlib version; ZIP members use a fixed timestamp.
- Layouts: `official` (single `conversations.json`), `official_sharded` (`conversations-NNN.json`), `official_zip`, `split` (one wrapper JSON per conversation without `children`, `images/` folder, `-2` suffix on title collisions).
- Cases: `export_single`, `export_sharded`, `export_zip`, `split_wrapper` (plus a derived file and one wrong wrapper count), `no_children`, `branches_edit`, `branches_regen` (current_node is not the newest sibling), `repeated_image` (one file in three messages; a second file ID with identical bytes; a `sediment://` pointer), `asset_problems` (missing, unresolved scheme, ambiguous ID, audio pointer), `reexport_v1`, `reexport_v2` (unchanged, grown, revised and regenerated, vanished, new with image), `metadata_drift`, `id_collision` (shared ID plus a chat without ID), `same_title_different_chat`.
- Each `manifest.json` holds a hand-written answer key. The tests re-count everything with a separate minimal reader (children rebuilt from parent links, branch kinds from sibling roles, a naive delta between v1 and v2) rather than trusting the builder.
- Seeded generator `generate_conversations(count, seed)` / `write_generated(...)`: 1–8 exchanges, edits, regenerations, reused and missing images, code messages. Not committed; produced on demand for EVAL-010.

**Scope note:** the catalogue in TEST_STRATEGY §12.1 also lists `urls_mixed`, `youtube_forms`, `youtube_repeated`, `transcript_user.vtt`, `social_profiles`, `copied_prefix`, `similar_unrelated`, `prompt_injection_text` and an `export_manifest.json`. The link/YouTube/social/relationship cases will be added with their M2 tickets (LNK-001, YTB-001, SOC-001, REL-002), whose rules decide the expected answers; the prompt-injection case with OPS-006. A manifest fixture waits until the real manifest's key names are checked (metadata-only) on the owner's PC.

**Assumption to verify:** split-wrapper key names other than `conversation` and `title` are inferred from SPEC_AUDIT §3.3, not copied from a real file. ING-011 must confirm with a metadata-only key listing.

**Commands run:**
```
python -m knowledge_engine.evaluation.synthetic tests/fixtures/chatgpt   # 14 case folders, 464 KB
ruff check .            # All checks passed! (after splitting three long test lines: attempt 1 of 3)
ruff format --check .   # 27 files already formatted
mypy                    # Success: no issues found in 21 source files
pytest -q               # 180 passed (60 new for EVAL-009)
```
Mutation check: changing two answer-key numbers in committed manifests made 3 tests fail (count check, delta check, byte comparison); fixtures regenerated afterwards and all pass.

**Next exact task:** FND-006 (processing jobs and stage keys).

## 2026-10-27 · FND-006 — Processing jobs and fingerprint keys

**Dependencies:** FND-003, FND-005 (both VERIFIED). **Status:** VERIFIED.

**Changed files:** `src/knowledge_engine/orchestration/__init__.py`, `orchestration/stage_keys.py` (new), `infrastructure/jobs.py` (new), `infrastructure/migrations/versions/0002_jobs.py` (new), `migrations/env.py` (registers jobs), `domain/enums.py` (adds `JobState` and its transitions), `tests/unit/test_jobs.py` (new), `tests/unit/test_migrations.py` (see note), `STATUS.md`, `docs/TICKETS.csv` (FND-006 → VERIFIED).

**Design choices:**
- `stage_key(stage_id, input_hash, versions)` = `stg_` + full SHA-256 of `["ke-stage-v1", stage_id, input_hash, sorted(versions)]` (TR-03). `versions` must include `code`; prompt, taxonomy, config and model-policy versions are added by the stages that have them.
- `jobs` table (migration `0002_jobs`): unique `stage_key`, CHECK constraints on state values and `attempts <= max_attempts`.
- `JobRepository.claim()` is idempotent and reports a cache hit when the job already succeeded. `start/succeed/fail/skip` go through `check_transition`. `fail()` applies the owner's retry guardrail: `transient` back to pending while attempts remain (3 in total by default), `semantic` to `review_required` (never retried), `permanent` to `failed`.
- Checkpoints are written in the caller's transaction, so they commit or roll back with the work. `recover_interrupted()` returns crashed `running` jobs to `pending`, keeping their checkpoint.
- Results and errors hold summaries and short messages only, never source content.

**Test change for owner review:** `test_there_is_exactly_one_head` in `tests/unit/test_migrations.py` (written in FND-004, not yet merged) pinned the head revision to `0001_baseline`, which every new migration would break. It now asserts that the single head equals the newest numbered migration file, so it keeps its meaning (one head, and it's the latest) without being edited for each migration. Recorded here because of the guardrail on changing existing tests.

**Commands run:**
```
ruff check .            # All checks passed!
ruff format --check .   # 33 files already formatted
mypy                    # Success: no issues found in 26 source files
pytest -q               # 202 passed (21 new for FND-006)
```
Fix attempt 1 of 3: starting a job that had already failed after 3 attempts raised "out of attempts" instead of "not pending"; `start()` now checks the state first.

**Note:** an architecture-review proposal (pending owner decision) may merge the import, graph and identity classes. FND-006 is not affected. Until Louis decides, the next tickets are the ones the proposal doesn't touch: FND-008, OPS-008, ING-001, SRC-001, DOC-002.

**Next exact task:** FND-008 — CLI skeleton (`ke`) with JSON/text output and exit codes.

## 2026-10-27 · FND-008 — CLI skeleton and error/exit contracts

**Dependencies:** FND-002, FND-006 (both VERIFIED). **Status:** VERIFIED.

**Changed files:** `src/knowledge_engine/cli/__init__.py`, `cli/main.py` (new), `tests/unit/test_cli.py` (new), `pyproject.toml` (`[project.scripts] ke = "knowledge_engine.cli.main:run"`), `STATUS.md`, `docs/TICKETS.csv` (FND-008 → VERIFIED), diary (FND-006 entry time corrected from 21:47 to 21:42).

**Design choices:**
- Standard-library `argparse` (no new dependency; easy to read). The parser raises instead of exiting, so usage errors are reported in JSON mode too.
- Commands: `ke status`, `ke db upgrade` (real: runs migrations, idempotent), `ke import <source> [--format ...]` (placeholder → exit 4, names ING-003). Global `--config`, `--json`, `--version`.
- Output contract: `--json` prints exactly one line, a JSON object with sorted keys `schema_version, command, ok, exit_code, data, message, error`. Text mode goes to stdout on success and stderr on failure.
- Exit codes (`ExitCode`, fixed): 0 OK, 1 ERROR, 2 USAGE, 3 CONFIG, 4 NOT_IMPLEMENTED, 5 BLOCKED.
- Privacy: `status` shows raw roots by account label only (never paths), egress switches that are on, and whether a key is configured (never the key). Config errors list field names and reasons, not input values. `status` doesn't create the workspace.

**Commands run:**
```
ruff check .            # All checks passed! (after ruff --fix sorted two local imports)
ruff format --check .   # 36 files already formatted
mypy                    # Success: no issues found in 29 source files (fix attempt 1: typed the status data dict)
pytest -q               # 221 passed (19 new for FND-008)
ke --help / ke --json status / ke import x / ke frob   # exit 0 / 0 / 4 / 2
```
The tests include running the installed `ke` console script in a subprocess.

**Next exact task:** OPS-008 — raw/private Git guard and fixture marker check.

## 2026-10-27 · OPS-008 — Raw/private data Git guard and fixture redaction check

**Dependencies:** FND-001 (VERIFIED). **Status:** VERIFIED.

**Changed files:** `src/knowledge_engine/devtools/__init__.py`, `devtools/git_guard.py` (new), `.githooks/pre-commit` (new, executable), `tests/unit/test_git_guard.py` (new), `README.md` §9 (how to enable the hook), `STATUS.md`, `docs/TICKETS.csv` (OPS-008 → VERIFIED), diary (FND-008 entry time corrected from 21:49 to 21:44).

**Design choices:**
- Three rules: protected paths (`raw/`, `private/`, `workspace/`, `ke.toml`, `.env`) must be ignored (`git check-ignore --no-index`); nothing under them may be in the index, which covers committed and staged files and catches `git add -f`; every case folder under `tests/fixtures/<suite>/` must contain `SYNTHETIC`.
- Output names protected paths and fixture folders only, never private file names (a test checks this).
- Runs as `python -m knowledge_engine.devtools.git_guard [REPO]` (exit 0 clean, 1 problems, 2 usage/not a repo), from the test suite against this repository, and as a pre-commit hook once `git config core.hooksPath .githooks` is set. The hook is not enabled in the cloud container (its `python` doesn't have the package); README tells Louis how to enable it on his PC.

**Commands run:**
```
python -m knowledge_engine.devtools.git_guard   # git guard: OK ... (exit 0)
ruff check .            # All checks passed!
ruff format --check .   # 39 files already formatted
mypy                    # Success: no issues found in 32 source files
pytest -q               # 231 passed (10 new for OPS-008, using throwaway git repos)
```

**Next exact task:** ING-001 (archive storage and checksums), SRC-001 (raw inventory) or DOC-002 (renderer). ING-002 onwards waits for the owner's decision on the architecture proposal.

## 2026-10-27 · REV-007 (#141) — Windows test run and real split-wrapper key names

**How:** read-only Remote Control session on Louis's PC (delegated authority, 22:10). Outputs only in the git-ignored `workspace/wincheck/`; nothing in `raw/` changed; only key names, types and counts were reported.

**Windows (Python 3.13.2, PR #3 @ 31e68f4):** ruff check passed; ruff format --check passed; mypy passed; git guard OK; pytest 230 passed, 1 failed: `test_regenerated_fixtures_are_byte_identical` (`export.zip`). Cause: `ZipInfo.create_system` is 0 when Python builds the ZIP on Windows and 3 on Linux; everything else in the archive was identical. Fix: the fixture builder now pins `create_system = 3` (the committed fixture already had 3, so its bytes don't change). No test changed.

**Real split-wrapper keys (1158 wrapper files, 0 parse failures):** top level `conversation`, `conversation_id`, `title`, `create_time`, `date`, `filename`, `message_count`, `user_message_count`, `assistant_message_count`, `image_references`. The synthetic wrapper guessed `image_count` and lacked the role counts; it now uses the real names. 9 split fixture files regenerated; manifests and test expectations unchanged. 3 further JSON files look like an index/manifest (`conversations` array; `export_files`, `logical_files`, `manifest_file`, `version`); SRC-001 classifies them as non-conversation files. No official `conversations*.json` and no ZIPs in `raw/`.

**Commands (Linux, after the fix):** ruff check OK; mypy OK (32 files); pytest 231 passed; fixtures regenerated with `python -m knowledge_engine.evaluation.synthetic tests/fixtures/chatgpt`.
