"""OPS-008 acceptance: the guard fails when a raw/ file is staged or a fixture
lacks the synthetic marker, and passes on a clean tree."""

import shutil
import subprocess
from pathlib import Path

import pytest

from knowledge_engine.devtools.git_guard import check, main

REPO_ROOT = Path(__file__).resolve().parents[2]


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A tiny Git repo with this project's real .gitignore and one marked fixture."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q")
    shutil.copy(REPO_ROOT / ".gitignore", root / ".gitignore")
    case = root / "tests" / "fixtures" / "chatgpt" / "case_a"
    case.mkdir(parents=True)
    (case / "SYNTHETIC").write_text("synthetic\n")
    (case / "manifest.json").write_text("{}\n")
    (root / "raw").mkdir()
    (root / "raw" / "private-chat.json").write_text('{"secret": "SYNTHETIC-PRIVATE"}\n')
    _git(root, "add", ".")
    return root


def test_clean_tree_passes(repo: Path) -> None:
    assert check(repo) == []
    assert main([str(repo)]) == 0


def test_this_repository_passes() -> None:
    assert check(REPO_ROOT) == []


def test_force_added_raw_file_fails(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    _git(repo, "add", "-f", "raw/private-chat.json")
    problems = check(repo)
    assert [p.code for p in problems] == ["protected_path_tracked"]
    assert main([str(repo)]) == 1
    err = capsys.readouterr().err
    assert "raw/" in err
    assert "private-chat" not in err, "the guard must not print private file names"


def test_committed_private_file_still_fails(repo: Path) -> None:
    (repo / "private").mkdir()
    (repo / "private" / "answers.csv").write_text("synthetic\n")
    _git(repo, "add", "-f", "private/answers.csv")
    assert [p.code for p in check(repo)] == ["protected_path_tracked"]


def test_tracked_config_file_fails(repo: Path) -> None:
    (repo / "ke.toml").write_text("# synthetic\n")
    _git(repo, "add", "-f", "ke.toml")
    assert [p.code for p in check(repo)] == ["protected_path_tracked"]


def test_unmarked_fixture_fails(repo: Path) -> None:
    unmarked = repo / "tests" / "fixtures" / "chatgpt" / "case_b"
    unmarked.mkdir()
    (unmarked / "manifest.json").write_text("{}\n")
    problems = check(repo)
    assert [p.code for p in problems] == ["fixture_unmarked"]
    assert "case_b" in problems[0].detail


def test_missing_ignore_rule_fails(repo: Path) -> None:
    gitignore = repo / ".gitignore"
    gitignore.write_text(gitignore.read_text().replace("raw/\n", ""))
    assert "not_ignored" in [p.code for p in check(repo)]


def test_not_a_repository(tmp_path: Path) -> None:
    assert main([str(tmp_path)]) == 2


def test_usage_error() -> None:
    assert main(["a", "b"]) == 2


def test_pre_commit_hook_is_executable() -> None:
    hook = REPO_ROOT / ".githooks" / "pre-commit"
    assert hook.is_file()
    assert "knowledge_engine.devtools.git_guard" in hook.read_text()
