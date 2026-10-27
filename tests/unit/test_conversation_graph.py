"""ING-005 (slice G1): ConversationGraph over every EVAL-009 fixture."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from knowledge_engine.graph.conversation import ConversationGraph

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt"
CASES = sorted(p.name for p in FIXTURES.iterdir() if p.is_dir())


def _natives(case: str) -> list[dict[str, Any]]:
    """Native conversation objects of a fixture, whatever its layout."""
    export = FIXTURES / case / "export"
    blobs: list[bytes] = []
    for path in sorted(export.rglob("*")):
        if path.suffix == ".zip":
            with zipfile.ZipFile(io.BytesIO(path.read_bytes())) as archive:
                blobs += [archive.read(n) for n in archive.namelist() if n.endswith(".json")]
        elif path.suffix == ".json":
            blobs.append(path.read_bytes())
    natives: list[dict[str, Any]] = []
    for blob in blobs:
        value = json.loads(blob)
        if isinstance(value, list):
            natives += [v for v in value if isinstance(v, dict) and "mapping" in v]
        elif isinstance(value.get("conversation"), dict):
            natives.append(value["conversation"])
    return natives


def _graph(native: dict[str, Any]) -> ConversationGraph:
    return ConversationGraph.from_mapping(native["mapping"], native.get("current_node"))


def _expected(case: str) -> dict[str, Any]:
    manifest = json.loads((FIXTURES / case / "manifest.json").read_text("utf-8"))
    expected: dict[str, Any] = manifest["expected"]
    return expected


@pytest.mark.parametrize("case", CASES)
def test_every_node_is_kept_and_children_follow_parent_links(case: str) -> None:
    natives = _natives(case)
    assert natives
    for native in natives:
        graph = _graph(native)
        mapping = native["mapping"]
        assert set(graph.nodes) == set(mapping)
        for node_id, node in mapping.items():
            expected_kids = {k for k, v in mapping.items() if v.get("parent") == node_id}
            assert set(graph.children(node_id)) == expected_kids
            assert graph.nodes[node_id].parent_id == node.get("parent")


@pytest.mark.parametrize("case", CASES)
def test_active_path_runs_from_a_root_to_current_node(case: str) -> None:
    for native in _natives(case):
        graph = _graph(native)
        path = graph.active_path
        assert path[-1] == native["current_node"]
        assert graph.nodes[path[0]].parent_id is None
        for parent, child in zip(path, path[1:], strict=False):
            assert graph.nodes[child].parent_id == parent


def test_active_message_counts_match_the_answer_key() -> None:
    expected = _expected("export_single")["active_path_messages"]
    counts = {
        n["conversation_id"]: len(_graph(n).active_messages) for n in _natives("export_single")
    }
    assert counts == expected


@pytest.mark.parametrize("case", ["branches_edit", "branches_regen"])
def test_branches_are_kept_but_not_spliced_into_the_active_path(case: str) -> None:
    expected = _expected(case)
    (native,) = _natives(case)
    graph = _graph(native)

    assert list(graph.active_messages) == expected["active_path_node_ids"]
    for node_id in expected["inactive_node_ids"]:
        assert node_id in graph.nodes
        assert node_id not in graph.active_path
        assert graph.message_number(node_id) is None


def test_regeneration_children_are_all_present() -> None:
    (native,) = _natives("branches_regen")
    graph = _graph(native)
    user_node = next(n for n in graph.active_messages if n.endswith("-u0"))

    assert len(graph.children(user_node)) == _expected("branches_regen")["branch_children"]


def test_missing_children_lists_give_the_same_tree() -> None:
    (native,) = _natives("no_children")
    assert all("children" not in node for node in native["mapping"].values())
    graph = _graph(native)

    with_children = json.loads(json.dumps(native))
    for node_id, node in with_children["mapping"].items():
        node["children"] = list(graph.children(node_id))
    assert _graph(with_children).active_path == graph.active_path
    assert any(len(graph.children(n)) > 1 for n in graph.nodes)


def test_message_numbers_are_1_based_on_the_active_path() -> None:
    (native,) = _natives("branches_edit")
    graph = _graph(native)

    numbers = [graph.message_number(n) for n in graph.active_messages]
    assert numbers == list(range(1, len(numbers) + 1))
    root = graph.active_path[0]
    assert not graph.nodes[root].has_message
    assert graph.message_number(root) is None
    assert graph.message_number("not-a-node") is None


# ---------------------------------------------------------------- hand-made edge cases


def _node(parent: str | None, role: str | None = "user", t: Any = None) -> dict[str, Any]:
    message = None if role is None else {"author": {"role": role}, "create_time": t}
    return {"parent": parent, "message": message}


def test_no_fabricated_chronology() -> None:
    mapping = {
        "r": _node(None, None),
        "b": _node("r", "assistant", None),
        "a": _node("r", "assistant", None),
        "c": _node("r", "assistant", 5.0),
    }
    graph = ConversationGraph.from_mapping(mapping, "a")

    assert graph.nodes["a"].create_time is None
    assert graph.nodes["c"].create_time == 5.0
    # Timed siblings first, then untimed ones by ID; no time is made up.
    assert graph.children("r") == ("c", "a", "b")


def test_unknown_or_missing_current_node_gives_an_empty_path() -> None:
    mapping = {"r": _node(None, None), "u": _node("r")}

    for current in (None, "ghost"):
        graph = ConversationGraph.from_mapping(mapping, current)
        assert graph.current_node is None
        assert graph.active_path == ()
        assert set(graph.nodes) == {"r", "u"}


def test_cycle_and_dangling_parent_do_not_hang_or_lose_nodes() -> None:
    mapping = {
        "x": _node("y"),
        "y": _node("x"),
        "orphan": _node("missing-parent"),
        "self": _node("self"),
        "junk": "not an object",
    }

    cyclic = ConversationGraph.from_mapping(mapping, "x")
    orphan = ConversationGraph.from_mapping(mapping, "orphan")
    selfish = ConversationGraph.from_mapping(mapping, "self")

    assert cyclic.active_path == ("y", "x")
    assert orphan.active_path == ("orphan",)
    assert selfish.active_path == ("self",)
    assert set(cyclic.nodes) == {"x", "y", "orphan", "self"}
    assert cyclic.children("self") == ()


def test_odd_values_are_tolerated() -> None:
    mapping = {
        "r": {"parent": None, "message": "not a dict"},
        "u": {"parent": "r", "message": {"author": "nobody", "create_time": True}},
    }
    graph = ConversationGraph.from_mapping(mapping, "u")

    assert graph.nodes["r"].has_message is False
    assert (graph.nodes["u"].role, graph.nodes["u"].create_time) == (None, None)
    assert graph.active_messages == ("u",)


@st.composite
def _trees(draw: st.DrawFn) -> tuple[dict[str, Any], str]:
    size = draw(st.integers(min_value=1, max_value=30))
    mapping: dict[str, Any] = {"n0": _node(None, None)}
    for i in range(1, size):
        parent = f"n{draw(st.integers(min_value=0, max_value=i - 1))}"
        role = draw(st.sampled_from(["user", "assistant", "tool"]))
        mapping[f"n{i}"] = _node(parent, role, draw(st.none() | st.floats(0, 1e9)))
    return mapping, f"n{draw(st.integers(min_value=0, max_value=size - 1))}"


@given(_trees())
def test_any_tree_keeps_every_node_and_a_valid_active_path(
    tree: tuple[dict[str, Any], str],
) -> None:
    mapping, current = tree
    graph = ConversationGraph.from_mapping(mapping, current)

    assert set(graph.nodes) == set(mapping)
    assert sum(len(graph.children(n)) for n in graph.nodes) == len(mapping) - 1
    assert graph.active_path[0] == "n0"
    assert graph.active_path[-1] == current
    assert [graph.message_number(n) for n in graph.active_messages] == list(
        range(1, len(graph.active_messages) + 1)
    )
