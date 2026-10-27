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

## 2026-10-27 · SRC-001 — Read-only raw source inventory and guard (slice S0)

**Dependencies:** FND-002, FND-005, FND-008 (VERIFIED). **Status:** VERIFIED. **Branch:** `claude/project-thread-q0du34-src-001-v2`. First ticket under the adopted M1 consolidation (`docs/plans/M1_CONSOLIDATION.md`): the module lives at `ingestion/inventory.py` and the command is `ke raw inventory`.

**Changed files:** `src/knowledge_engine/ingestion/__init__.py`, `ingestion/inventory.py` (new), `cli/main.py` (`ke raw inventory [--show-names] ROOT`), `tests/unit/test_inventory.py` (new), `STATUS.md`, diary.

**Design choices:**
- Folder or ZIP root. Every file gets size, SHA-256 and a `FileKind`: official conversations list, split conversation, bare native conversation, account metadata (by known export file names), export manifest (by key names seen in the real split export, REV-007), derived JSON, invalid JSON, HTML export, media (by magic bytes, not extension), archive, oversized (listed, never read), other.
- "Is a conversation" means "has a `mapping` object", so derived files that mention conversations (an old classifier's output) are never parsed as chats.
- Read-only proof: `tree_signature` (path, type, size, mtime of every entry) before and after; `unchanged=False` (or `RawTreeChangedError` in strict mode) if anything moved. The CLI exits 1 with `raw_changed` in that case. The report carries the "before" hash so a later import can compare.
- Redacted by default: files appear as `f_` + 12 hex of the path's SHA-256; `--show-names` is for local use. Symlinks are skipped so nothing outside the root is read. ZIP members are read with a cap of limit+1 bytes so a member that lies about its size can't fill memory.
- Known limit: each file is read whole (bounded by the configured limits). Streaming hashes for large media can come with MED-003 if EVAL-010 shows memory pressure.

**Commands run:**
```
ruff check .            # All checks passed!
ruff format --check .   # OK
mypy                    # Success: no issues found in 35 source files
pytest -q               # 264 passed (33 new for SRC-001, incl. byte-identical-after check on all 14 fixture cases)
ke --json raw inventory tests/fixtures/chatgpt/split_wrapper/export   # detected chatgpt-split-v1, 3 conversations, 1 derived, no names
```
Fix attempts: 1 (my own new strict-mode test tampered only on the first run; it now writes a new file on every run).

**Next exact task:** slice I1 (ING-001 archive + IMP-001 batch ledger) in `importer/`.

## 2026-10-27 · Review recommendations received (via coordinator)

An independent review ("adjust, not rethink") recommends: (a) consolidating the M1 design (one graph module, one Import module, events deferred, ADR-0003 keys and ticket IDs kept); (b) smaller PRs, one or two tickets each, because PR #3 is too large to read; (c) running the suite on Windows once; (d) listing the real split-wrapper key names (names only) before ING-011; (e) an ADR on the AI step under the no-paid-API rule before M3. (Later decided under delegated authority, see OPEN_DECISIONS.) Actions: PR #3 gets no more tickets; DOC-002 is committed locally and waits for either PR #3 to merge or Louis's OK to use extra branches for small PRs; (c) and (d) wait for his OK to start a Remote Control session.

## 2026-10-27 · DOC-002 — Deterministic Markdown/YAML renderer

**Dependencies:** FND-005 (VERIFIED). **Status:** VERIFIED. Rebased onto `main` after PR #3 and SRC-001 merged; own PR (slice R1).

**Changed files:** `src/knowledge_engine/rendering/__init__.py`, `rendering/markdown.py` (new), `tests/unit/test_markdown_render.py` (new), `pyproject.toml` (adds `pyyaml`, dev `types-PyYAML`), `STATUS.md`.

**Design choices:**
- A note is data (`DocumentModel`: title, ordered properties, blocks `Heading`/`Paragraph`/`BulletList`/`CodeBlock`) rendered by `render_note` with `\n` line endings and one final newline.
- Frontmatter is written by `yaml.safe_dump` (order preserved) and parsed back; readable Unicode first, escaped ASCII if a character such as U+0085 doesn't survive. Datetimes must carry a timezone; NaN and unknown types are refused.
- Untrusted text (`trusted=False`, the default) goes through `escape_text`: wikilinks, embeds, `%%` comments, HTML, inline `#tags`, trailing `^block` refs and line-start heading/quote/table/list markers are neutralised. Titles and headings are forced onto one line. Code fences grow longer than any backtick run inside.
- `block_anchor` validates Obsidian block IDs for citations. `safe_filename(title, unique_suffix)` is Windows/POSIX-safe (reserved names, illegal characters, trailing dots, 80-character stem); the stable suffix, not the title, keeps names unique. `safe_relative_path` refuses `..`, separators, drive letters and empty parts.
- `write_note` writes inside the vault only, via a temp file in the same folder, `fsync` and `os.replace`; identical content is not rewritten (mtime kept); a failed write leaves no temp file.

**Commands run:**
```
ruff check .            # All checks passed!
ruff format --check .   # 42 files already formatted
mypy                    # Success: no issues found in 35 source files
pytest -q               # 278 passed (47 new for DOC-002)
git guard               # OK
extra Hypothesis run, 5,000 examples each: frontmatter round-trip and escape invariants  # ok
```
Fix attempts: (1) a title with a newline could carry `#` text, and inline `#tags` from chats would have become Obsidian tags, so tag escaping was added (a backslash before `#` can't undo it); (2) Hypothesis found that U+0085 broke the frontmatter round-trip, so an escaped-ASCII fallback was added; (3) mypy rejected monkeypatching through the module attribute in a test, so the target string form is used. Three attempts used in total; all resolved.

**Next exact task:** waiting on Louis: the architecture proposal (decides ING-001/SRC-001 onwards), the Remote Control OK (Windows run, key names), and the PR approach.

## 2026-10-27 · ING-005 — ChatGPT message-graph parsing (slice G1)

**Dependencies:** FND-005 (VERIFIED). ING-004 is listed as a blocker in the old chain, but under the adopted consolidation the graph is pure and takes a `mapping` directly, so it doesn't need the adapter (M1_CONSOLIDATION §6.2). **Status:** VERIFIED. **Branch:** `claude/project-thread-q0du34-graph-g1`.

**Changed files:** `src/knowledge_engine/graph/__init__.py`, `graph/conversation.py` (new), `tests/unit/test_conversation_graph.py` (new), `STATUS.md`, diary.

**Design choices:**
- `ConversationGraph.from_mapping(mapping, current_node)` builds `GraphNode`s (parent, children, has_message, role, create_time) once; read-only afterwards.
- Parent links are the single source of truth for children (the split export has no `children`); siblings are ordered by exported timestamp, then by ID for untimed ones. No timestamp is ever invented.
- `active_path` walks up from `current_node` with a seen-set, so cycles and dangling parents end the walk instead of hanging; unknown/missing `current_node` gives an empty path (reported as an issue in G2).
- `active_messages` drops the empty root; `message_number` is 1-based over it and None off-path.
- Malformed entries (non-object nodes, odd `message`/`author`/boolean timestamps) are tolerated here; NRM-002 (G2) reports them.

**Commands run:**
```
ruff check .            # All checks passed!
mypy                    # Success: no issues found in 41 source files
pytest -q               # 350 passed (39 new for G1, incl. all 14 fixture cases and a Hypothesis tree test)
```
Fix attempts: 0.

**Next exact task:** slice G2 (REL-001 branch kinds and alternate paths, NRM-002 integrity issues).

## 2026-10-27 · REL-001 + NRM-002 — Branch kinds, alternate paths, graph integrity (slice G2)

**Dependencies:** ING-005 (VERIFIED, PR #152). NRM-002's old blocker NRM-001 doesn't apply: integrity is structural and lives in the pure graph (M1_CONSOLIDATION §2.1). **Status:** both VERIFIED. **Branch:** `claude/project-thread-q0du34-graph-g2`.

**Changed files:** `src/knowledge_engine/graph/conversation.py` (BranchPoint, IssueCode, GraphIssue, `branch_points`, `alternate_paths()`, `issues`), `tests/unit/test_graph_branches_integrity.py` (new), `STATUS.md`, diary.

**Design choices:**
- Branch point = node with ≥2 children; kind from child roles: all user → edit, all assistant → regeneration, else other; `active_child` from the active path; `BRANCH_CLASSIFIER_VERSION = "rel-001-v1"` for the stored rows later.
- `alternate_paths()` yields every root-to-leaf path except the active one; never merged or spliced.
- Issues (codes and node IDs only, never text): invalid_node, missing_parent, self_parent, cycle, unreachable, multiple_roots, id_mismatch, duplicate_message_id, children_mismatch (exported list vs parent links), current_node_missing. Sorted deterministically. Nodes are never dropped (except non-object entries, which are reported).
- Note: JSON objects with duplicate keys are collapsed by the JSON parser before the graph sees them; detecting that needs a parse hook in the adapter (A1/A2). Recorded as a scope note.

**Commands run:**
```
ruff check .            # All checks passed!
mypy                    # Success: no issues found in 42 source files
pytest -q               # 367 passed, 6 skipped (17 new; skips = fixture layouts without conversations.json, covered by the G1 loader)
```
Hypothesis test: random trees with corrupted parent links; every node is either reachable from a root or named in an issue, and every alternate path is a real parent chain ending at a leaf. Fix attempts: 0.

**Next exact task:** slice G3 (ING-006 content parts and asset pointers, NRM-001 canonical node and the two hashes).

## 2026-10-27 · ING-006 + NRM-001 — Content parts, asset pointers, canonical node and hashes (slice G3)

**Dependencies:** ING-005, FND-005 (VERIFIED). **Status:** both VERIFIED. **Branch:** `claude/project-thread-q0du34-graph-g3`.

**Changed files:** `src/knowledge_engine/graph/nodes.py` (new), `tests/unit/test_canonical_nodes.py` (new), `STATUS.md`, diary.

**Design choices:**
- `canonical_node(node_id, node) -> CanonicalNode | None` (None for the empty root). Parts are ordered `ContentPart`s: text, asset pointer, or other (raw value kept, read-only view).
- Content types: text, multimodal_text, code, execution_output, reasoning_recap, tether_quote, tether_browsing_display, thoughts, user_editable_context, system_error, computer_output. Anything else becomes one `other` part plus the `unknown_content_type` flag. Reasoning, context and hidden nodes are flagged, never dropped.
- Asset pointers: `file-service://` and `sediment://` give a `file_id`; other schemes keep the pointer, `file_id=None` and a `unsupported_pointer_scheme` warning. A pointer-typed part without a pointer warns. Declared size/width/height kept. Resolving a pointer to a file (missing/ambiguous) is MED-002.
- Hashes: `raw_payload_hash` = SHA-256 of `["ke-raw-v1", whole node]` canonical JSON; `canonical_content_hash` = SHA-256 of `["ke-content-v1", role, content object, create_time as float]`. Message metadata is excluded (OD-13). Choice made: the whole `content` object is hashed (not just parts), so a code language or quoted URL change counts; more conservative than OD-13's minimum.

**Commands run:**
```
ruff check .            # All checks passed!
mypy                    # Success: no issues found in 44 source files
pytest -q               # 396 passed, 6 skipped (29 new for G3)
```
Key evidence: `metadata_drift` vs `reexport_v1`: all 3 messages keep their content hash and change their raw hash. Hypothesis: any content/metadata never changes the content hash through metadata. Source mapping is deep-equal before and after. Fix attempts: 1 (test loader didn't read split-layout fixtures; my own new test).

**Next exact task:** slice A1 (ING-002 adapter seam + ING-004 official export layouts).

## 2026-10-27 · ING-002 + ING-004 — Adapter seam and official export adapter (slice A1)

**Dependencies:** FND-005 (VERIFIED). The old blocker ING-001 isn't needed by the seam (snapshots are the importer's job, I1). **Status:** both VERIFIED with scope notes. **Branch:** `claude/project-thread-q0du34-adapter-a1`.

**Changed files:** `src/knowledge_engine/ingestion/source.py` (new: `SourceAdapter` protocol, `ProbeResult`, `SourceListing`, `NativeConversation`, `SourceLocator`, `SourceFile`, `MediaFile`, `ImportWarning`, `select_adapter`, `load_json`, `safe_member_name`), `ingestion/chatgpt_export.py` (new), `ingestion/inventory.py` (extracted `sniff_media` for reuse; behaviour unchanged), `tests/unit/test_source_adapters.py` (new), `STATUS.md`, diary.

**Design choices:**
- Protocol: `format_id`, `probe(path)` (names only), `open(path, max_bytes)` → listing with conversation files + SHA-256, media files, warnings and a lazy conversation stream. Adapters never parse messages.
- `select_adapter`: forced format must exist and match; otherwise exactly one match, else `UnsupportedFormatError` (none, or ambiguous: the user must pass `--format`).
- `load_json` reports duplicate keys (`duplicate_json_key`) — closes the G2 scope note — and accepts a BOM.
- Official adapter: folder or ZIP (read in place); top-level `conversations.json` and `conversations-NNN.json`, numeric shard order; any unsafe member name refuses the whole archive; size checked before reading and capped while reading ZIP members; media found by magic bytes anywhere (top level, `user-*/`, `dalle-generations/`); bad list entries become per-entry warnings.
- Scope notes: JSON is loaded per file (bounded by `max_source_file_bytes`), not streamed; real data is split-format so this is deferred until a big official export appears. The stored import manifest belongs to IMP-001/IMP-005.

**Commands run:**
```
ruff check .            # All checks passed!
ruff format --check .   # 54 files already formatted
mypy                    # Success: no issues found in 47 source files
pytest -q               # 420 passed, 6 skipped (24 new for A1)
```
Finish line: `export_single`, `export_sharded` and `export_zip` give equal `NativeConversation.native` lists; a ZIP with `../escape.png` is refused. Fix attempts: 1 (my own new shard-order test expected the wrong tie order).

**Next exact task:** slice A2 (ING-011 split-wrapper adapter).
