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
