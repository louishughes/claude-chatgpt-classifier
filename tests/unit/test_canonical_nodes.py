"""ING-006 + NRM-001 (slice G3): content parts, asset pointers and the two hashes."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from knowledge_engine.graph.nodes import (
    NodeFlag,
    NodeWarning,
    PartKind,
    canonical_node,
    parse_pointer,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt"


def _natives(case: str) -> list[dict[str, Any]]:
    export = FIXTURES / case / "export"
    official = export / "conversations.json"
    if official.exists():
        value: list[dict[str, Any]] = json.loads(official.read_text("utf-8"))
        return value
    wrappers = [
        json.loads(p.read_text("utf-8")) for p in sorted(export.glob("conversations/*.json"))
    ]
    return [w["conversation"] for w in wrappers if isinstance(w.get("conversation"), dict)]


def _node(content: Any, role: str = "user", **message: Any) -> dict[str, Any]:
    return {
        "id": "n1",
        "parent": "r",
        "message": {"id": "n1", "author": {"role": role}, "content": content, **message},
    }


def test_root_without_message_is_none() -> None:
    assert canonical_node("r", {"id": "r", "message": None, "parent": None}) is None


@pytest.mark.parametrize(
    "case", ["export_single", "reexport_v1", "repeated_image", "asset_problems"]
)
def test_canonicalisation_is_repeatable_and_leaves_the_source_alone(case: str) -> None:
    for native in _natives(case):
        before = copy.deepcopy(native)
        first = [canonical_node(k, v) for k, v in native["mapping"].items()]
        second = [canonical_node(k, v) for k, v in native["mapping"].items()]
        assert first == second
        assert native == before


def test_metadata_drift_changes_raw_hash_but_not_content_hash() -> None:
    (drifted,) = _natives("metadata_drift")
    original = next(
        n for n in _natives("reexport_v1") if n["conversation_id"] == drifted["conversation_id"]
    )
    compared = 0
    for node_id, node in drifted["mapping"].items():
        new = canonical_node(node_id, node)
        old = canonical_node(node_id, original["mapping"][node_id])
        if new is None or old is None:
            continue
        compared += 1
        assert new.canonical_content_hash == old.canonical_content_hash
        assert new.raw_payload_hash != old.raw_payload_hash
    assert compared == 3


def test_content_change_changes_content_hash() -> None:
    a = canonical_node("n1", _node({"content_type": "text", "parts": ["hello"]}, create_time=1.0))
    b = canonical_node("n1", _node({"content_type": "text", "parts": ["hello!"]}, create_time=1.0))
    c = canonical_node("n1", _node({"content_type": "text", "parts": ["hello"]}, create_time=2.0))
    d = canonical_node(
        "n1", _node({"content_type": "text", "parts": ["hello"]}, "assistant", create_time=1.0)
    )
    assert a and b and c and d
    assert (
        len(
            {
                a.canonical_content_hash,
                b.canonical_content_hash,
                c.canonical_content_hash,
                d.canonical_content_hash,
            }
        )
        == 4
    )


def test_int_and_float_timestamps_hash_the_same() -> None:
    a = canonical_node("n1", _node({"content_type": "text", "parts": ["x"]}, create_time=5))
    b = canonical_node("n1", _node({"content_type": "text", "parts": ["x"]}, create_time=5.0))
    assert a and b and a.canonical_content_hash == b.canonical_content_hash


def test_image_parts_become_ordered_pointers() -> None:
    (native,) = [n for n in _natives("repeated_image")][:1]
    pointers = [
        p
        for k, v in native["mapping"].items()
        if (node := canonical_node(k, v))
        for p in node.asset_pointers
    ]
    assert pointers
    for p in pointers:
        assert p.scheme in {"file-service", "sediment"}
        assert p.file_id and p.pointer.endswith(p.file_id)
        assert (p.width, p.height) == (4, 4)


def test_asset_problems_give_explicit_warnings() -> None:
    (native,) = _natives("asset_problems")
    nodes = [n for k, v in native["mapping"].items() if (n := canonical_node(k, v))]
    pointers = {p.pointer: p for n in nodes for p in n.asset_pointers}
    warnings = [w for n in nodes for w in n.warnings]

    assert set(pointers) == {
        "file-service://file-SYNMISSING",
        "weird-scheme://abc",
        "file-service://file-SYN0005",
        "sediment://file_00000000synthaudio",
    }
    assert pointers["weird-scheme://abc"].file_id is None
    assert pointers["sediment://file_00000000synthaudio"].content_type == "audio_asset_pointer"
    assert warnings == [NodeWarning.UNSUPPORTED_POINTER_SCHEME]
    # Text after the pointers is kept in order.
    multimodal = next(n for n in nodes if n.content_type == "multimodal_text")
    assert [p.kind for p in multimodal.parts][-1] is PartKind.TEXT


@pytest.mark.parametrize(
    ("content", "expected_text"),
    [
        ({"content_type": "code", "language": "python", "text": "print(1)"}, "print(1)"),
        ({"content_type": "execution_output", "text": "1"}, "1"),
        ({"content_type": "reasoning_recap", "content": "Thought for 3s"}, "Thought for 3s"),
        (
            {"content_type": "tether_quote", "url": "u", "domain": "d", "title": "T", "text": "Q"},
            "T\n\nQ",
        ),
        ({"content_type": "tether_browsing_display", "result": "R", "summary": None}, "R"),
        (
            {
                "content_type": "thoughts",
                "thoughts": [{"summary": "s", "content": "c1"}, {"content": "c2"}],
            },
            "c1\n\nc2",
        ),
        (
            {
                "content_type": "user_editable_context",
                "user_profile": "P",
                "user_instructions": "I",
            },
            "P\n\nI",
        ),
    ],
)
def test_observed_content_types(content: dict[str, Any], expected_text: str) -> None:
    node = canonical_node("n1", _node(content))
    assert node is not None
    assert node.text == expected_text
    assert node.warnings == ()


def test_reasoning_context_and_hidden_are_flagged_not_dropped() -> None:
    thoughts = canonical_node(
        "n1", _node({"content_type": "thoughts", "thoughts": []}, "assistant")
    )
    context = canonical_node(
        "n1", _node({"content_type": "user_editable_context", "user_profile": "p"}, "user")
    )
    hidden = canonical_node(
        "n1",
        _node(
            {"content_type": "text", "parts": [""]},
            "system",
            metadata={"is_visually_hidden_from_conversation": True},
        ),
    )
    assert thoughts and NodeFlag.REASONING in thoughts.flags
    assert context and NodeFlag.CONTEXT in context.flags and context.text == "p"
    assert hidden and NodeFlag.HIDDEN in hidden.flags


def test_unknown_content_round_trips() -> None:
    content = {"content_type": "brand_new_type", "payload": {"deep": [1, 2]}}
    node = canonical_node("n1", _node(content))

    assert node is not None
    assert NodeFlag.UNKNOWN_CONTENT_TYPE in node.flags
    (part,) = node.parts
    assert part.kind is PartKind.OTHER
    assert dict(part.raw) == content
    assert json.loads(json.dumps(dict(part.raw))) == content


def test_unknown_parts_inside_text_are_kept() -> None:
    odd = {"content_type": "something_else", "x": 1}
    node = canonical_node("n1", _node({"content_type": "multimodal_text", "parts": ["a", odd, 3]}))
    assert node is not None
    assert [p.kind for p in node.parts] == [PartKind.TEXT, PartKind.OTHER, PartKind.OTHER]
    assert dict(node.parts[1].raw) == odd and node.parts[2].raw == 3


def test_malformed_content_is_reported() -> None:
    bad_parts = canonical_node("n1", _node({"content_type": "text", "parts": "oops"}))
    not_a_dict = canonical_node("n1", _node("oops"))
    pointerless = canonical_node(
        "n1",
        _node(
            {"content_type": "multimodal_text", "parts": [{"content_type": "image_asset_pointer"}]}
        ),
    )
    assert bad_parts and NodeWarning.MALFORMED_CONTENT in bad_parts.warnings
    assert not_a_dict and not_a_dict.warnings == (NodeWarning.MALFORMED_CONTENT,)
    assert pointerless and pointerless.warnings == (NodeWarning.ASSET_PART_WITHOUT_POINTER,)


def test_raw_parts_are_read_only() -> None:
    node = canonical_node(
        "n1", _node({"content_type": "multimodal_text", "parts": [{"content_type": "x", "a": 1}]})
    )
    assert node is not None
    with pytest.raises(TypeError):
        node.parts[0].raw["a"] = 2


@pytest.mark.parametrize(
    ("pointer", "expected"),
    [
        ("file-service://file-abc", ("file-service", "file-abc")),
        ("sediment://file_00ab", ("sediment", "file_00ab")),
        ("weird://x", ("weird", None)),
        ("file-service://", ("file-service", None)),
        ("no-scheme", (None, None)),
        ("://x", (None, None)),
    ],
)
def test_parse_pointer(pointer: str, expected: tuple[str | None, str | None]) -> None:
    assert parse_pointer(pointer) == expected


_json = st.recursive(
    st.none() | st.booleans() | st.integers() | st.text(max_size=5),
    lambda inner: (
        st.lists(inner, max_size=3) | st.dictionaries(st.text(max_size=4), inner, max_size=3)
    ),
    max_leaves=10,
)


@given(content=_json, role=st.none() | st.text(max_size=5), metadata=_json)
def test_any_content_is_handled_and_metadata_never_affects_content_hash(
    content: Any, role: str | None, metadata: Any
) -> None:
    base: dict[str, Any] = {
        "id": "n",
        "message": {"author": {"role": role}, "content": content, "create_time": 1.0},
    }
    with_meta = copy.deepcopy(base)
    with_meta["message"]["metadata"] = metadata
    a = canonical_node("n", base)
    b = canonical_node("n", with_meta)
    assert a is not None and b is not None
    assert a.canonical_content_hash == b.canonical_content_hash
