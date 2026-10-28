"""EVAL-006: ZIP to Obsidian vault end to end, every link checked, shape vs golden."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from knowledge_engine.evaluation.end_to_end import (
    BASE_FIXTURE,
    E2E_FIXTURE,
    E2E_GOLDEN,
    E2E_QUERY,
    build_fixture,
    check_vault,
    golden_diff,
    run_end_to_end,
    vault_golden,
)


def test_committed_fixture_is_exactly_what_the_builder_makes(tmp_path: Path) -> None:
    assert build_fixture(BASE_FIXTURE, tmp_path / "e2e.zip") == E2E_FIXTURE.read_bytes()


def test_zip_to_vault_passes_and_matches_the_golden(tmp_path: Path) -> None:
    report = run_end_to_end(E2E_FIXTURE, tmp_path, query=E2E_QUERY)
    assert report.check.clean, (report.check.broken_links, report.check.broken_embeds)
    assert report.sources_first and report.search_hit_in_vault and report.passed
    assert report.conversations == 5 and report.records >= 3
    golden = json.loads(E2E_GOLDEN.read_text(encoding="utf-8"))
    assert golden_diff(vault_golden(report.check), golden) == []
    kinds = golden["kinds"]
    assert kinds["source_transcript"] == kinds["conversation_knowledge"] == 5
    assert kinds["video"] == 1 and kinds["social_account"] == 1


def _note(vault: Path, name: str, text: str) -> None:
    path = vault / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_checker_finds_every_kind_of_broken_link(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    _note(vault, "A.md", "---\nke_type: a\n---\n# Top\n\nline ^here\n\n## Part two\n")
    _note(vault, "x/Same.md", "")
    _note(vault, "y/Same.md", "")
    _note(vault, "img/p.png", "not really a png")
    _note(
        vault,
        "B.md",
        "---\nke_type: b\n---\n"
        "[[A]] [[A#^here]] [[A#Part two]] [[A|shown]] [[#^mine]] ![[img/p.png]] ^mine\n"
        "\\[[escaped]] `[[in code]]`\n```\n[[in a fence]]\n```\n"
        "[[Nope]] [[A#^gone]] [[A#No such heading]] [[Same]] ![[img/q.png]]\n",
    )
    _note(vault, "C.md", "---\nke_type: [unclosed\n---\nbody\n")
    check = check_vault(vault)
    assert sorted(t for _, t in check.broken_links) == [
        "A#No such heading",
        "A#^gone",
        "Nope",
        "Same",  # two notes share the name: Obsidian would have to guess
    ]
    assert check.broken_embeds == [("B.md", "img/q.png")]
    assert check.bad_frontmatter == ["C.md"]
    assert check.shapes["B.md"].kind == "b" and check.shapes["B.md"].links == 9
    assert not check.clean


def test_golden_diff_says_what_changed() -> None:
    old = {"notes": {"A.md": {"kind": "a", "links": 1}, "Gone.md": {"kind": "a"}}}
    new = {"notes": {"A.md": {"kind": "a", "links": 2}, "New.md": {"kind": "a"}}}
    assert golden_diff(new, old) == [
        "missing note: Gone.md",
        "new note: New.md",
        "A.md: links 1 -> 2",
    ]


def test_cli_eval_e2e_and_docs_check(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from knowledge_engine.cli.main import main

    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(tmp_path / "ws"))
    assert main(["--json", "eval", "e2e"]) == 0
    data = json.loads(capsys.readouterr().out)["data"]
    assert data["passed"] and data["golden_differences"] == []
    vault = tmp_path / "vault"
    _note(vault, "A.md", "[[Missing]]\n")
    assert main(["--json", "docs", "check", "--vault", str(vault)]) != 0
    out = json.loads(capsys.readouterr().out)
    assert out["error"]["code"] == "broken_links"
    assert out["data"]["broken_links"] == [["A.md", "Missing"]]
