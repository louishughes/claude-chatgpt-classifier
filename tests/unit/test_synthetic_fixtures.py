"""EVAL-009 acceptance: fixtures match their hand-written answer keys, are
deterministic, and contain no real data.

The checks here re-count everything with a small, independent reader instead
of reusing the builder, so a builder bug can't hide behind its own numbers.
"""

import filecmp
import io
import json
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

import pytest

from knowledge_engine.evaluation import synthetic

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt"
CASES = sorted(p.name for p in FIXTURES.iterdir() if p.is_dir())


# ---------------------------------------------------------------- independent reader


def _manifest(case: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((FIXTURES / case / "manifest.json").read_text("utf-8"))
    return data


def _load(case: str) -> tuple[list[dict[str, Any]], dict[str, bytes], int]:
    """Return (native conversations, image files by name, derived JSON count)."""
    export = FIXTURES / case / "export"
    conversations: list[dict[str, Any]] = []
    images: dict[str, bytes] = {}
    derived = 0
    zip_path = export / "export.zip"
    if zip_path.exists():
        with zipfile.ZipFile(io.BytesIO(zip_path.read_bytes())) as archive:
            for name in archive.namelist():
                if name.endswith(".json"):
                    conversations += json.loads(archive.read(name))
                else:
                    images[name] = archive.read(name)
        return conversations, images, 0
    for path in sorted(export.rglob("*")):
        if path.suffix == ".json" and path.parent.name == "conversations":
            data = json.loads(path.read_text("utf-8"))
            if isinstance(data.get("conversation"), dict):
                conversations.append(data["conversation"])
            else:
                derived += 1
        elif path.suffix == ".json":
            conversations += json.loads(path.read_text("utf-8"))
        elif path.suffix == ".png":
            images[path.name] = path.read_bytes()
    return conversations, images, derived


def _messages(conv: dict[str, Any]) -> list[dict[str, Any]]:
    return [n for n in conv["mapping"].values() if n.get("message")]


def _children(conv: dict[str, Any]) -> dict[str, list[str]]:
    # Rebuilt from parent links: works whether or not "children" exists.
    kids: dict[str, list[str]] = {}
    for node_id, node in conv["mapping"].items():
        if node.get("parent"):
            kids.setdefault(node["parent"], []).append(node_id)
    return kids


def _branch_kinds(conv: dict[str, Any]) -> Counter[str]:
    kinds: Counter[str] = Counter()
    for kids in _children(conv).values():
        if len(kids) > 1:
            roles = {conv["mapping"][k]["message"]["author"]["role"] for k in kids}
            if roles == {"user"}:
                kinds["edit"] += 1
            elif roles == {"assistant"}:
                kinds["regeneration"] += 1
            else:
                kinds["other"] += 1
    return kinds


def _active_path(conv: dict[str, Any]) -> list[str]:
    path, node_id = [], conv["current_node"]
    while node_id:
        node = conv["mapping"][node_id]
        if node.get("message"):
            path.append(node_id)
        node_id = node.get("parent")
    return list(reversed(path))


def _pointers(conv: dict[str, Any]) -> list[str]:
    return [
        part["asset_pointer"]
        for node in _messages(conv)
        for part in node["message"]["content"].get("parts", [])
        if isinstance(part, dict)
    ]


def _content(node: dict[str, Any]) -> str:
    message = node["message"]
    return json.dumps([message["author"]["role"], message["content"], message["create_time"]])


# ---------------------------------------------------------------- every case


def test_all_expected_cases_exist() -> None:
    assert CASES == sorted(case.name for case in synthetic.all_cases())


@pytest.mark.parametrize("case", CASES)
def test_case_is_marked_synthetic(case: str) -> None:
    assert (FIXTURES / case / synthetic.SYNTHETIC_MARKER).is_file()
    manifest = _manifest(case)
    assert manifest["synthetic"] is True
    assert manifest["case"] == case
    assert manifest["proves"]


@pytest.mark.parametrize("case", CASES)
def test_every_text_part_is_obviously_synthetic(case: str) -> None:
    conversations, _, _ = _load(case)
    for conv in conversations:
        assert "ynthetic" in conv["title"]
        for node in _messages(conv):
            content = node["message"]["content"]
            texts = [p for p in content.get("parts", []) if isinstance(p, str) and p]
            texts += [content["text"]] if content.get("text") else []
            for text in texts:
                assert "ynthetic" in text, f"{case}: unmarked text {text!r}"


@pytest.mark.parametrize("case", CASES)
def test_counts_match_the_answer_key(case: str) -> None:
    expected = _manifest(case)["expected"]
    conversations, images, derived = _load(case)
    key = "conversations_in_file" if "conversations_in_file" in expected else "conversations"
    assert len(conversations) == expected[key]
    if "mapping_nodes" in expected:
        assert sum(len(c["mapping"]) for c in conversations) == expected["mapping_nodes"]
    if "messages" in expected:
        assert sum(len(_messages(c)) for c in conversations) == expected["messages"]
    if "branch_points" in expected:
        total: Counter[str] = Counter()
        for conv in conversations:
            total += _branch_kinds(conv)
        assert {k: total[k] for k in expected["branch_points"]} == expected["branch_points"]
    if "active_path_messages" in expected:
        lengths = {c["conversation_id"]: len(_active_path(c)) for c in conversations}
        assert lengths == expected["active_path_messages"]
    if "active_path_node_ids" in expected:
        assert _active_path(conversations[0]) == expected["active_path_node_ids"]
        assert not set(expected["inactive_node_ids"]) & set(_active_path(conversations[0]))
    if "image_files" in expected:
        assert len(images) == expected["image_files"]
    if "derived_artifacts" in expected:
        assert derived == expected["derived_artifacts"]


# ---------------------------------------------------------------- specific cases


def test_format_cases_hold_identical_conversations() -> None:
    reference = _load("export_single")[0]
    for case in ("export_sharded", "export_zip"):
        assert _load(case)[0] == reference
    # The split files drop "children" (like the real ones) but are otherwise equal.
    split = _load("split_wrapper")[0]
    assert [synthetic.without_children(c) for c in reference] == split


def test_split_wrapper_has_one_deliberately_wrong_count() -> None:
    folder = FIXTURES / "split_wrapper" / "export" / "conversations"
    mismatches = 0
    for path in folder.glob("2024-*.json"):
        wrapper = json.loads(path.read_text("utf-8"))
        if wrapper["message_count"] != len(_messages(wrapper["conversation"])):
            mismatches += 1
    assert mismatches == 1


def test_no_children_case_really_has_no_children() -> None:
    conv = _load("no_children")[0][0]
    assert all("children" not in node for node in conv["mapping"].values())


def test_repeated_image_occurrences_and_shared_bytes() -> None:
    expected = _manifest("repeated_image")["expected"]
    conversations, images, _ = _load("repeated_image")
    pointers = [p for c in conversations for p in _pointers(c)]
    per_id = Counter(p.split("://", 1)[1] for p in pointers)
    assert dict(per_id) == expected["occurrences_per_asset"]
    assert len(set(images.values())) == expected["blobs"]


def test_asset_problem_pointers_match_files_on_disk() -> None:
    expected = _manifest("asset_problems")["expected"]["occurrence_states_by_pointer"]
    conversations, images, _ = _load("asset_problems")
    assert sorted(_pointers(conversations[0])) == sorted(expected)
    for pointer, state in expected.items():
        file_id = pointer.split("://", 1)[1]
        matches = [name for name in images if name.startswith(file_id)]
        assert len(matches) == {"missing": 0, "unresolved": 0, "ambiguous": 2}[state]


def test_reexport_delta_answer_key() -> None:
    expected = _manifest("reexport_v2")["expected"]
    old = {c["conversation_id"]: c for c in _load("reexport_v1")[0]}
    new = {c["conversation_id"]: c for c in _load("reexport_v2")[0]}
    conv_delta: dict[str, str] = {}
    msg_delta: Counter[str] = Counter()
    for conv_id in old.keys() | new.keys():
        if conv_id not in new:
            conv_delta[conv_id] = "not_seen"
            msg_delta["not_seen"] += len(_messages(old[conv_id]))
            continue
        if conv_id not in old:
            conv_delta[conv_id] = "new"
            msg_delta["new"] += len(_messages(new[conv_id]))
            continue
        before = {n["id"]: _content(n) for n in _messages(old[conv_id])}
        changed = False
        for node in _messages(new[conv_id]):
            if node["id"] not in before:
                msg_delta["new"] += 1
                changed = True
            elif before[node["id"]] != _content(node):
                msg_delta["revised"] += 1
                changed = True
            else:
                msg_delta["unchanged"] += 1
        conv_delta[conv_id] = "revised" if changed else "unchanged"
    assert conv_delta == expected["conversation_delta_by_id"]
    assert dict(Counter(conv_delta.values())) == expected["conversation_delta"]
    assert dict(msg_delta) == expected["message_delta"]
    new_branches = sum(_branch_kinds(c).total() for c in new.values()) - sum(
        _branch_kinds(c).total() for c in old.values()
    )
    assert new_branches == expected["new_branches"]


def test_metadata_drift_changes_metadata_but_not_content() -> None:
    old = {c["conversation_id"]: c for c in _load("reexport_v1")[0]}
    drift = _load("metadata_drift")[0][0]
    before = old[drift["conversation_id"]]
    assert json.dumps(before) != json.dumps(drift)
    assert [_content(n) for n in _messages(before)] == [_content(n) for n in _messages(drift)]


def test_id_collision_case() -> None:
    conversations = _load("id_collision")[0]
    ids = [c.get("conversation_id") for c in conversations]
    assert ids.count("c0000006-0000-4000-8000-000000000001") == 2
    assert ids.count(None) == 1
    assert json.dumps(conversations[0]["mapping"]) != json.dumps(conversations[1]["mapping"])


def test_same_title_files_get_suffixes() -> None:
    folder = FIXTURES / "same_title_different_chat" / "export"
    names = sorted(p.name for p in folder.rglob("*.json"))
    assert names == [
        "2024-01-17.synthetic-same-title-2.json",
        "2024-01-17.synthetic-same-title.json",
    ]


def test_png_files_are_valid() -> None:
    data = synthetic.tiny_png((1, 2, 3))
    assert data.startswith(b"\x89PNG\r\n\x1a\n") and data.endswith(b"IEND\xaeB`\x82")


# ---------------------------------------------------------------- determinism


def test_regenerated_fixtures_are_byte_identical(tmp_path: Path) -> None:
    # Catches both an edited fixture and an unrecorded builder change.
    synthetic.build_fixtures(tmp_path)
    comparison = filecmp.dircmp(tmp_path, FIXTURES)

    def differences(cmp: filecmp.dircmp[str]) -> list[str]:
        found = cmp.left_only + cmp.right_only + cmp.diff_files + cmp.funny_files
        for sub in cmp.subdirs.values():
            found += differences(sub)
        return found

    # dircmp compares shallowly by default; force a byte comparison too.
    assert differences(comparison) == []
    for generated in tmp_path.rglob("*"):
        if generated.is_file():
            committed = FIXTURES / generated.relative_to(tmp_path)
            assert generated.read_bytes() == committed.read_bytes(), committed


@pytest.mark.parametrize("count", [50, 100])
def test_generator_is_deterministic(tmp_path: Path, count: int) -> None:
    first = synthetic.write_generated(tmp_path / "a", count, seed=7)
    second = synthetic.write_generated(tmp_path / "b", count, seed=7)
    files = sorted(p.relative_to(first) for p in first.rglob("*") if p.is_file())
    assert files == sorted(p.relative_to(second) for p in second.rglob("*") if p.is_file())
    for relative in files:
        assert (first / relative).read_bytes() == (second / relative).read_bytes()
    conversations = list((first / "export" / "conversations").glob("*.json"))
    assert len(conversations) == count


def test_different_seeds_give_different_batches() -> None:
    assert synthetic.generate_conversations(20, 1)[0] != synthetic.generate_conversations(20, 2)[0]


def test_generator_scales_to_a_thousand_with_realistic_variety() -> None:
    conversations, images = synthetic.generate_conversations(1000, seed=2024)
    assert len(conversations) == 1000
    assert len({c["conversation_id"] for c in conversations}) == 1000
    kinds: Counter[str] = Counter()
    for conv in conversations:
        kinds += _branch_kinds(conv)
    assert kinds["edit"] > 0 and kinds["regeneration"] > 0
    pointers = [p for c in conversations for p in _pointers(c)]
    assert any("GENMISSING" in p for p in pointers)
    available = Counter(p for p in pointers if "GENMISSING" not in p)
    assert any(n > 1 for n in available.values()), "some images should be reused"
    assert len(images) == len(available)


def test_negative_count_is_rejected() -> None:
    with pytest.raises(ValueError):
        synthetic.generate_conversations(-1, 0)


def test_main_usage_error() -> None:
    assert synthetic.main([]) == 2
