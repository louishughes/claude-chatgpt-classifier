# Code Style

**Ticket:** FND-001 · **Source:** `docs/plans/IMPLEMENTATION_PLAN.md` §11, `CLAUDE.md` §5.

The owner is learning Python, and this code is also a portfolio piece. So the code must be readable by a beginner and explainable to an employer, without turning into line-by-line narration. These rules reconcile both goals.

## 1. Comments and docstrings

| Where | What to write | Checked by |
|---|---|---|
| **Every module** | A docstring of 3–6 plain-English sentences: what the module does, why it exists, which invariant (rule that must always hold) it protects. Then a `Talking points:` list of 2–4 bullets the owner could say in an interview or a post. | ruff `D100`/`D104` (presence); review (content) |
| **Every public class and function** | Google-style docstring: one summary line, then `Args:`, `Returns:`, `Raises:` as needed. Define jargon the first time it appears, e.g. "idempotent: running it twice has the same effect as running it once". | ruff `D` rules, `convention = "google"` |
| **Inline comments** | Only for a *why*: an invariant, a surprising choice, or a quirk of real data ("exports sometimes omit `children`, so we rebuild it from `parent`"). | review |
| **Never** | Comments that repeat the code (`i += 1  # add one to i`), commented-out code, or anything copied from `raw/`. | review |

Private helpers (names starting with `_`) need a docstring only when what they do is not obvious from the name. Tests are exempt from docstring rules; a good test name is its documentation.

### Module docstring template

```python
"""One-line summary of what this module does.

Two to five sentences: why it exists, how it fits with its neighbours, and
which rule it protects (for example "raw/ is never written to").

Talking points:
    - "One sentence you could say out loud about the design."
    - "Another one, ideally about a trade-off or a lesson."
"""
```

## 2. Types

- Type hints on every function, public or private. `mypy --strict` must pass on `src/` and `tests/`.
- Pydantic models at boundaries (settings, data read from files, data written to the database). Plain dataclasses or functions inside.
- Stable IDs never depend on display labels such as titles (`CLAUDE.md` §5).

## 3. Shape of the code

- Small, readable functions over clever ones. If a function needs a comment to explain *what* it does, split it or rename it.
- Names follow the glossary terms once `CONTEXT.md` exists (conversation, message node, revision, asset, occurrence, …).
- Layers import in one direction only (`IMPLEMENTATION_PLAN.md` §1): `domain` imports nothing internal; the source layer never imports model providers.
- A new dependency is added by the ticket that first needs it, with a one-line comment in `pyproject.toml` if the reason isn't obvious.

## 4. Running the checks

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"

ruff check .        # style, bugs and docstrings
ruff format --check .
mypy                # strict type check (paths come from pyproject.toml)
pytest              # tests under tests/ only; prototype/ is excluded
```

All four must pass before a ticket is marked `VERIFIED`.
