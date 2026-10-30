"""The project's checks, run the same way on a laptop and in CI (OPS-005).

``python -m knowledge_engine.devtools.ci`` runs, in order:

* **lint** and **format**: ``ruff``;
* **types**: ``mypy`` (strict);
* **guard**: the git guard (no private data committed, fixtures marked);
* **tests**: the whole ``pytest`` suite (unit, contract and integration
  tests, including the schema-drift check against the migrations).

``--nightly`` runs the bounded semantic checks instead, on synthetic
fixtures with the fake model only:

* **gate**: the EVAL-007 release gate (one pass, no retries);
* **variance**: EVAL-008 shuffled orders and pinned repeats;
* **e2e**: EVAL-006 ZIP to vault, compared with its golden.

Every step runs with model credentials **removed** from its environment
and outbound model calls switched off, so a check that quietly needed a
real provider fails here instead of passing on a machine that happens to
have a key. The GitHub workflow calls this module and nothing else, so
"green in CI" and "green on my machine" mean the same thing.

Talking points:
    - "CI runs one command that I can also run myself, with every API key
      stripped out, so nothing in the checks can depend on a paid model."
    - "The nightly job is bounded: fixed synthetic data, a fake model, one
      pass of each evaluation, no retries."
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

# Never passed to a check. Anything that looks like a key is dropped too.
CREDENTIAL_VARIABLES = (
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_AUTH_TOKEN",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
    "GOOGLE_API_KEY",
    "YOUTUBE_API_KEY",
)
_CREDENTIAL_HINTS = ("API_KEY", "AUTH_TOKEN", "ACCESS_TOKEN", "SECRET")


@dataclass(frozen=True)
class Step:
    """One check: a name and the command it runs."""

    name: str
    command: tuple[str, ...]


def _python(*args: str) -> tuple[str, ...]:
    return (sys.executable, *args)


CHECKS = (
    Step("lint", _python("-m", "ruff", "check", "src", "tests")),
    Step("format", _python("-m", "ruff", "format", "--check", "src", "tests")),
    Step("types", _python("-m", "mypy", "src")),
    Step("guard", _python("-m", "knowledge_engine.devtools.git_guard")),
    Step("tests", _python("-m", "pytest", "-q", "-p", "no:cacheprovider")),
)
NIGHTLY = (
    Step("gate", _python("-m", "knowledge_engine.cli.main", "eval", "gate")),
    Step("variance", _python("-m", "knowledge_engine.cli.main", "eval", "variance")),
    Step("e2e", _python("-m", "knowledge_engine.cli.main", "eval", "e2e")),
)


def clean_environment(environ: Mapping[str, str]) -> dict[str, str]:
    """``environ`` without model credentials, with outbound model calls off."""
    clean = {
        name: value
        for name, value in environ.items()
        if name not in CREDENTIAL_VARIABLES
        and not any(hint in name.upper() for hint in _CREDENTIAL_HINTS)
    }
    clean["KE_CI"] = "1"
    return clean


def run(steps: Sequence[Step], environ: Mapping[str, str]) -> list[tuple[str, int, float]]:
    """Run every step (a failure doesn't stop the rest) and return (name, exit code, seconds)."""
    env = clean_environment(environ)
    results = []
    for step in steps:
        print(f"== {step.name}: {' '.join(step.command[1:])}", flush=True)
        started = time.monotonic()
        code = subprocess.run(step.command, env=env, check=False).returncode
        results.append((step.name, code, time.monotonic() - started))
    return results


def main(argv: Sequence[str] | None = None) -> int:
    """Run the checks (or the nightly ones); exit 1 if any failed."""
    parser = argparse.ArgumentParser(prog="python -m knowledge_engine.devtools.ci")
    parser.add_argument("--nightly", action="store_true", help="the bounded semantic checks")
    parser.add_argument("--list", action="store_true", help="print the steps, run nothing")
    args = parser.parse_args(argv)
    steps = NIGHTLY if args.nightly else CHECKS
    if args.list:
        for step in steps:
            print(f"{step.name}: {' '.join(step.command[1:])}")
        return 0
    results = run(steps, os.environ)
    print()
    for name, code, seconds in results:
        print(f"{'ok  ' if code == 0 else 'FAIL'} {name} ({seconds:.0f}s)")
    return 0 if all(code == 0 for _, code, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
