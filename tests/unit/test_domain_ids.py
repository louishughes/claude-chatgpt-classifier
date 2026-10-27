"""FND-005 acceptance: deterministic ID property tests (ADR-0003)."""

import re

import pytest
from hypothesis import given
from hypothesis import strategies as st

from knowledge_engine.domain import ids

native = st.text(min_size=1, max_size=40)
slug = st.from_regex(r"[a-z0-9][a-z0-9-]{0,20}", fullmatch=True)
sha = st.binary(max_size=64).map(ids.sha256_hex)
WS = "ws0"


def _conv(native_id: str = "c1", ns: str = "fixture") -> str:
    return ids.conversation_id(WS, "chatgpt", ns, native_id)


# ---------------------------------------------------------------- determinism and shape


@given(native, slug)
def test_conversation_id_is_deterministic_and_well_formed(native_id: str, ns: str) -> None:
    first = ids.conversation_id(WS, "chatgpt", ns, native_id)
    assert first == ids.conversation_id(WS, "chatgpt", ns, native_id)
    assert re.fullmatch(r"conv_[0-9a-f]{32}", first)


@given(native, native)
def test_different_native_ids_give_different_conversations(a: str, b: str) -> None:
    assert (_conv(a) == _conv(b)) == (a == b)


@given(native)
def test_namespace_and_workspace_are_part_of_identity(native_id: str) -> None:
    base = ids.conversation_id(WS, "chatgpt", "louis-personal", native_id)
    assert base != ids.conversation_id(WS, "chatgpt", "louis-work", native_id)
    assert base != ids.conversation_id("ws1", "chatgpt", "louis-personal", native_id)


@given(st.text(min_size=1, max_size=10), st.text(min_size=1, max_size=10))
def test_key_boundaries_are_unambiguous(a: str, b: str) -> None:
    # ("ab", "c") must not equal ("a", "bc"): parts are JSON-encoded, not joined.
    joined = a + b
    for split in range(1, len(joined)):
        left, right = joined[:split], joined[split:]
        if (left, right) != (a, b):
            node_a = ids.message_node_id(_conv(a), b)
            node_b = ids.message_node_id(_conv(left), right)
            assert node_a != node_b


def test_native_ids_are_used_exactly() -> None:
    # Case and whitespace are meaningful in native IDs; nothing is normalised.
    assert _conv("A1") != _conv("a1")
    assert _conv("a1") != _conv(" a1")


def test_known_value_never_changes() -> None:
    # A pinned example. If this fails, every stored ID would change: that
    # needs a new ID_SCHEME_VERSION and a migration, not an edited expectation.
    assert _conv("c1") == "conv_0bfffaf4519e5747672b77cac126e764"
    assert ids.ID_SCHEME_VERSION == "ke-id-v1"
    assert (
        ids.snapshot_id("0" * 64)
        == "snap_" + ids.sha256_hex(b'["ke-id-v1","snapshot","' + b"0" * 64 + b'"]')[:32]
    )


# ---------------------------------------------------------------- kinds never collide


@given(native)
def test_prefixes_separate_kinds(native_id: str) -> None:
    conv = _conv(native_id)
    node = ids.message_node_id(conv, native_id)
    produced = {
        conv,
        node,
        ids.message_revision_id(node, "a" * 64),
        ids.graph_edge_id(node, None),
        ids.link_target_id(native_id),
        ids.media_asset_id(WS, "chatgpt", native_file_id=native_id),
    }
    assert len({value.split("_", 1)[0] for value in produced}) == len(produced)


def test_every_prefix_is_unique() -> None:
    assert len(set(ids.PREFIXES.values())) == len(ids.PREFIXES)


def test_file_id_and_hash_keys_do_not_collide() -> None:
    digest = "b" * 64
    by_file = ids.media_asset_id(WS, "chatgpt", native_file_id=digest)
    by_hash = ids.media_asset_id(WS, "chatgpt", blob_sha256=digest)
    assert by_file != by_hash


def test_social_stable_id_and_handle_do_not_collide() -> None:
    assert ids.social_account_id("github", stable_platform_id="octo") != ids.social_account_id(
        "github", handle="octo"
    )


# ---------------------------------------------------------------- revisions, edges, occurrences


@given(sha, sha)
def test_revision_changes_only_with_content_hash(h1: str, h2: str) -> None:
    node = ids.message_node_id(_conv(), "n1")
    assert (ids.message_revision_id(node, h1) == ids.message_revision_id(node, h2)) == (h1 == h2)


def test_same_native_node_in_two_conversations_is_two_nodes() -> None:
    assert ids.message_node_id(_conv("c1"), "n1") != ids.message_node_id(_conv("c2"), "n1")


def test_root_edge_differs_from_child_edge() -> None:
    conv = _conv()
    child = ids.message_node_id(conv, "child")
    parent = ids.message_node_id(conv, "parent")
    assert ids.graph_edge_id(child, None) != ids.graph_edge_id(child, parent)


def test_same_image_in_two_messages_is_two_occurrences_of_one_asset() -> None:
    conv = _conv()
    rev_a = ids.message_revision_id(ids.message_node_id(conv, "a"), "1" * 64)
    rev_b = ids.message_revision_id(ids.message_node_id(conv, "b"), "1" * 64)
    pointer = "file-service://file-SYNTHETIC1"
    asset_a = ids.media_asset_id(WS, "chatgpt", native_file_id="file-SYNTHETIC1")
    asset_b = ids.media_asset_id(WS, "chatgpt", native_file_id="file-SYNTHETIC1")
    assert asset_a == asset_b
    assert ids.asset_occurrence_id(rev_a, 0, pointer) != ids.asset_occurrence_id(rev_b, 0, pointer)
    assert ids.asset_occurrence_id(rev_a, 0, pointer) != ids.asset_occurrence_id(rev_a, 1, pointer)


def test_relationship_direction_matters() -> None:
    a, b = _conv("a"), _conv("b")
    assert ids.relationship_id(a, "continues", b, "structural-v1") != ids.relationship_id(
        b, "continues", a, "structural-v1"
    )


def test_social_handles_are_case_and_at_insensitive() -> None:
    expected = ids.social_account_id("x", handle="someone")
    assert ids.social_account_id("x", handle="@SomeOne") == expected
    assert ids.social_account_id("x", handle=" someone ") == expected


@given(st.integers(min_value=0, max_value=10_000), st.integers(min_value=1, max_value=500))
def test_link_occurrence_depends_on_exact_span(start: int, length: int) -> None:
    rev = ids.message_revision_id(ids.message_node_id(_conv(), "n"), "c" * 64)
    one = ids.link_occurrence_id(rev, start, start + length, "message_text")
    assert one == ids.link_occurrence_id(rev, start, start + length, "message_text")
    assert one != ids.link_occurrence_id(rev, start, start + length + 1, "message_text")
    assert one != ids.link_occurrence_id(rev, start, start + length, "citation_metadata")


# ---------------------------------------------------------------- rejected inputs


@pytest.mark.parametrize(
    "call",
    [
        lambda: ids.conversation_id(WS, "chatgpt", "fixture", ""),
        lambda: ids.conversation_id("", "chatgpt", "fixture", "c1"),
        lambda: ids.conversation_id(WS, "ChatGPT", "fixture", "c1"),
        lambda: ids.conversation_id(WS, "chatgpt", "Louis Personal", "c1"),
        lambda: ids.message_node_id("not-a-conv-id", "n1"),
        lambda: ids.message_node_id(_conv(), ""),
        lambda: ids.message_revision_id(ids.message_node_id(_conv(), "n"), "XYZ"),
        lambda: ids.message_revision_id(_conv(), "a" * 64),  # conv ID where node ID expected
        lambda: ids.snapshot_id("A" * 64),
        lambda: ids.media_asset_id(WS, "chatgpt"),
        lambda: ids.asset_occurrence_id(
            ids.message_revision_id(ids.message_node_id(_conv(), "n"), "a" * 64), -1, "p"
        ),
        lambda: ids.link_occurrence_id(
            ids.message_revision_id(ids.message_node_id(_conv(), "n"), "a" * 64), 5, 5, "x"
        ),
        lambda: ids.social_account_id("x"),
        lambda: ids.social_account_id("x", handle="@"),
        lambda: ids.youtube_video_id("too-short"),
        lambda: ids.youtube_video_id("dQw4w9WgXcQ&"),
    ],
)
def test_invalid_keys_are_rejected(call: object) -> None:
    with pytest.raises(ValueError):
        call()  # type: ignore[operator]


def test_bool_and_float_parts_are_rejected() -> None:
    with pytest.raises(TypeError):
        ids._stable_id("link_target", True)
    with pytest.raises(TypeError):
        ids._stable_id("link_target", 1.5)  # type: ignore[arg-type]


def test_youtube_id_is_returned_unchanged() -> None:
    assert ids.youtube_video_id("dQw4w9WgXcQ") == "dQw4w9WgXcQ"
