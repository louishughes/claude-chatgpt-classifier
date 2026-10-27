"""REL-001 and NRM-002 (slice G2): branch kinds, alternate paths, integrity issues."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from knowledge_engine.domain.enums import BranchKind
from knowledge_engine.graph.conversation import ConversationGraph, GraphIssue, IssueCode

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt"
OFFICIAL = ["export_single", "branches_edit", "branches_regen", "no_children"]


def _natives(case: str) -> list[dict[str, Any]]:
    value: list[dict[str, Any]] = json.loads(
        (FIXTURES / case / "export" / "conversations.json").read_text("utf-8")
    )
    return value


def _graph(native: dict[str, Any]) -> ConversationGraph:
    return ConversationGraph.from_mapping(native["mapping"], native.get("current_node"))


def _node(parent: str | None, role: str | None = "user", **extra: Any) -> dict[str, Any]:
    message = None if role is None else {"author": {"role": role}, **extra}
    return {"parent": parent, "message": message}


@pytest.mark.parametrize("case", OFFICIAL)
def test_branch_kinds_match_the_answer_key(case: str) -> None:
    manifest = json.loads((FIXTURES / case / "manifest.json").read_text("utf-8"))
    counts: Counter[str] = Counter()
    for native in _natives(case):
        counts.update(bp.kind.value for bp in _graph(native).branch_points)

    expected = manifest["expected"]["branch_points"]
    assert {kind: counts.get(kind, 0) for kind in expected} == expected
    assert counts.get("other", 0) == 0


@pytest.mark.parametrize("case", sorted(p.name for p in FIXTURES.iterdir() if p.is_dir()))
def test_fixtures_have_no_integrity_issues_except_known_ones(case: str) -> None:
    export = FIXTURES / case / "export"
    if not (export / "conversations.json").exists():
        pytest.skip("covered through the official layouts")
    for native in _natives(case):
        assert _graph(native).issues == ()


def test_active_child_and_alternate_paths_for_a_regeneration() -> None:
    (native,) = _natives("branches_regen")
    graph = _graph(native)
    (bp,) = graph.branch_points

    assert bp.kind is BranchKind.REGENERATION
    assert bp.active_child == "regen-a0b"
    alternates = sorted(path[-1] for path in graph.alternate_paths())
    assert alternates == sorted(set(bp.children) - {"regen-a0b"})
    shared = graph.active_path[: graph.active_path.index(bp.parent_id) + 1]
    for path in graph.alternate_paths():
        assert path[: len(shared)] == shared


def test_edit_branch_alternate_keeps_its_own_answer() -> None:
    (native,) = _natives("branches_edit")
    graph = _graph(native)
    (bp,) = graph.branch_points

    assert bp.kind is BranchKind.EDIT
    (alternate,) = list(graph.alternate_paths())
    assert alternate[-2:] == (f"{native['conversation_id']}-u0", f"{native['conversation_id']}-a0")
    assert not set(alternate[-2:]) & set(graph.active_path)


def test_mixed_roles_are_other() -> None:
    mapping = {"r": _node(None, None), "a": _node("r", "user"), "b": _node("r", "tool")}
    (bp,) = ConversationGraph.from_mapping(mapping, "a").branch_points
    assert bp.kind is BranchKind.OTHER


def test_adversarial_mapping_reports_every_problem_and_loses_nothing() -> None:
    mapping: dict[str, Any] = {
        "root": {**_node(None, None), "id": "root", "children": ["u"]},
        "u": {**_node("root", "user", id="m1"), "id": "u", "children": ["ghost"]},
        "dup": {**_node("u", "assistant", id="m1"), "id": "renamed"},
        "orphan": _node("nowhere"),
        "below-orphan": _node("orphan"),
        "x": _node("y"),
        "y": _node("x"),
        "hangs-off-loop": _node("x"),
        "self": _node("self"),
        "root2": _node(None, None),
        "junk": 42,
    }

    graph = ConversationGraph.from_mapping(mapping, "missing")

    assert set(graph.nodes) == set(mapping) - {"junk"}
    assert set(graph.issues) == {
        GraphIssue(IssueCode.INVALID_NODE, "junk"),
        GraphIssue(IssueCode.CURRENT_NODE_MISSING),
        GraphIssue(IssueCode.MULTIPLE_ROOTS),
        GraphIssue(IssueCode.CHILDREN_MISMATCH, "u"),
        GraphIssue(IssueCode.ID_MISMATCH, "dup"),
        GraphIssue(IssueCode.DUPLICATE_MESSAGE_ID, "dup"),
        GraphIssue(IssueCode.MISSING_PARENT, "orphan"),
        GraphIssue(IssueCode.UNREACHABLE, "below-orphan"),
        GraphIssue(IssueCode.CYCLE, "x"),
        GraphIssue(IssueCode.CYCLE, "y"),
        GraphIssue(IssueCode.UNREACHABLE, "hangs-off-loop"),
        GraphIssue(IssueCode.SELF_PARENT, "self"),
    }
    assert list(graph.issues) == sorted(graph.issues, key=lambda i: (i.code.value, i.node_id or ""))


@st.composite
def _dags(draw: st.DrawFn) -> tuple[dict[str, Any], str]:
    size = draw(st.integers(min_value=2, max_value=25))
    mapping: dict[str, Any] = {"n0": _node(None, None)}
    for i in range(1, size):
        parent = f"n{draw(st.integers(min_value=0, max_value=i - 1))}"
        mapping[f"n{i}"] = _node(parent, draw(st.sampled_from(["user", "assistant"])))
    # Corrupt a few parent links at random: dangling, self or backwards.
    for _ in range(draw(st.integers(min_value=0, max_value=3))):
        victim = f"n{draw(st.integers(min_value=1, max_value=size - 1))}"
        mapping[victim]["parent"] = draw(
            st.sampled_from(["gone", victim, f"n{draw(st.integers(0, size - 1))}"])
        )
    return mapping, f"n{draw(st.integers(min_value=0, max_value=size - 1))}"


@given(_dags())
def test_any_corruption_is_reported_and_no_node_is_lost(tree: tuple[dict[str, Any], str]) -> None:
    mapping, current = tree
    graph = ConversationGraph.from_mapping(mapping, current)

    assert set(graph.nodes) == set(mapping)
    flagged = {i.node_id for i in graph.issues}
    roots = {n for n, v in mapping.items() if v["parent"] is None}
    # Every node is either reachable from a root or named in an issue.
    reached: set[str] = set()
    stack = list(roots)
    while stack:
        node = stack.pop()
        if node not in reached:
            reached.add(node)
            stack.extend(graph.children(node))
    assert set(mapping) <= reached | flagged
    # Every alternate path is a real parent chain ending at a leaf.
    for path in graph.alternate_paths():
        assert not graph.children(path[-1])
        for parent, child in zip(path, path[1:], strict=False):
            assert graph.nodes[child].parent_id == parent
