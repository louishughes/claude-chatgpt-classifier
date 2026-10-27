"""Git guard: refuse to commit private data, and require markers on test fixtures.

The repository is public, and ``raw/`` holds the owner's real conversations
and images. A single ``git add -f raw/...`` would publish them. This check
runs before every commit (``.githooks/pre-commit``) and in the test suite,
and fails when:

1. a protected path (``raw/``, ``private/``, ``workspace/``, ``ke.toml``,
   ``.env``) is not covered by ``.gitignore``;
2. any file under a protected path is tracked or staged anyway (``git add
   -f`` bypasses ``.gitignore``, so rule 1 alone is not enough);
3. a fixture case folder under ``tests/fixtures/<suite>/`` lacks the
   ``SYNTHETIC`` marker that says its contents are generated, not real.

It prints file *counts* and protected-path names only, never the names of
private files, so its own output is safe to paste into an issue.

Talking points:
    - "My repo checks itself before every commit: if a private file is
      staged, the commit is refused."
    - "'.gitignore' isn't enough on its own, because 'git add -f' ignores it,
      so the guard checks what's actually in the index."
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

PROTECTED_DIRS = ("raw", "private", "workspace")
PROTECTED_FILES = ("ke.toml", ".env")
FIXTURES_DIR = Path("tests") / "fixtures"
MARKER = "SYNTHETIC"


@dataclass(frozen=True)
class GuardProblem:
    """One reason the guard failed.

    Attributes:
        code: Short machine-readable name, e.g. ``"protected_path_tracked"``.
        detail: Human explanation. Names protected paths or fixture folders,
            never private file names.
    """

    code: str
    detail: str


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=False
    )


def _is_ignored(repo: Path, relative: str) -> bool:
    # --no-index: answer from .gitignore rules even if a file is tracked.
    return _git(repo, "check-ignore", "-q", "--no-index", relative).returncode == 0


def _tracked_files(repo: Path) -> list[str]:
    # The index holds both committed and staged files, so this covers both.
    result = _git(repo, "ls-files", "-z", "--cached")
    if result.returncode != 0:
        raise RuntimeError("not a git repository (git ls-files failed)")
    return [name for name in result.stdout.split("\0") if name]


def check(repo: Path) -> list[GuardProblem]:
    """Run every guard rule on a repository.

    Args:
        repo: The repository root.

    Returns:
        The problems found; empty means the tree is clean.

    Raises:
        RuntimeError: If ``repo`` is not a Git repository.
    """
    problems: list[GuardProblem] = []
    for directory in PROTECTED_DIRS:
        if not _is_ignored(repo, f"{directory}/probe.json"):
            problems.append(GuardProblem("not_ignored", f"{directory}/ is not in .gitignore"))
    for name in PROTECTED_FILES:
        if not _is_ignored(repo, name):
            problems.append(GuardProblem("not_ignored", f"{name} is not in .gitignore"))

    tracked = _tracked_files(repo)
    for directory in PROTECTED_DIRS:
        count = sum(1 for path in tracked if path.startswith(f"{directory}/"))
        if count:
            problems.append(
                GuardProblem(
                    "protected_path_tracked",
                    f"{count} file(s) under {directory}/ are tracked or staged; "
                    f"remove them with: git rm -r --cached {directory}/",
                )
            )
    for name in PROTECTED_FILES:
        if any(path == name or path.endswith(f"/{name}") for path in tracked):
            problems.append(GuardProblem("protected_path_tracked", f"{name} is tracked or staged"))

    fixtures = repo / FIXTURES_DIR
    if fixtures.is_dir():
        for suite in sorted(p for p in fixtures.iterdir() if p.is_dir()):
            for case in sorted(p for p in suite.iterdir() if p.is_dir()):
                if not (case / MARKER).is_file():
                    relative = case.relative_to(repo).as_posix()
                    problems.append(
                        GuardProblem("fixture_unmarked", f"{relative} has no {MARKER} marker")
                    )
    return problems


def main(argv: list[str] | None = None) -> int:
    """Run the guard: ``python -m knowledge_engine.devtools.git_guard [REPO]``.

    Args:
        argv: Optional repository path (defaults to the current folder).

    Returns:
        0 when clean, 1 when problems were found, 2 on usage errors.
    """
    args = sys.argv[1:] if argv is None else argv
    if len(args) > 1:
        print("usage: python -m knowledge_engine.devtools.git_guard [REPO]", file=sys.stderr)
        return 2
    repo = Path(args[0]) if args else Path.cwd()
    try:
        problems = check(repo)
    except RuntimeError as error:
        print(f"git guard: {error}", file=sys.stderr)
        return 2
    if not problems:
        print("git guard: OK (private paths ignored and untracked; fixtures marked)")
        return 0
    print("git guard: refusing. Problems found:", file=sys.stderr)
    for problem in problems:
        print(f"  [{problem.code}] {problem.detail}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
