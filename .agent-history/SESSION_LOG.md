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
