"""RCL-002: the repeat grouping rules, on hand-made requests (no database)."""

from __future__ import annotations

import random

from knowledge_engine.recall.repeats import Request, content_words, find_repeats


def _request(n: int, chat: str, text: str, day: float | None = None) -> Request:
    return Request(
        revision_id=f"rev_{n:03d}",
        conversation_id=chat,
        native_node_id=f"node-{n}",
        title=None,
        created=None if day is None else day * 86_400,
        text=text,
    )


# Background messages so the rare-word weights behave as in a real history.
FILLER = [
    _request(100 + i, f"conv_f{i}", text)
    for i, text in enumerate(
        [
            "plan a birthday party menu for twelve people",
            "explain recursion with a simple example",
            "translate this paragraph into French",
            "what causes rust on garden tools",
            "suggest names for a grey kitten",
            "summarise the history of the printing press",
        ]
    )
]


def _members(report_groups: object) -> list[list[str]]:
    return sorted(
        sorted(m.native_node_id for m in group.members)
        for group in report_groups  # type: ignore[attr-defined]
    )


def test_content_words_drop_framing_and_stem() -> None:
    assert content_words("How do I structure the save system, please?") == {
        "structure",
        "save",
        "system",
    }
    assert content_words("thanks!") == frozenset()


def test_reworded_requests_in_two_chats_group() -> None:
    requests = [
        _request(1, "conv_a", "rewrite my CV summary for a junior Python developer role", 1),
        _request(2, "conv_b", "improve the summary on my CV for junior Python developer roles", 5),
        *FILLER,
    ]
    report = find_repeats(requests)
    assert _members(report.groups) == [["node-1", "node-2"]]
    assert report.groups[0].chats == 2
    assert [m.native_node_id for m in report.groups[0].members] == ["node-1", "node-2"]


def test_same_chat_is_a_revision_not_a_repeat() -> None:
    requests = [
        _request(1, "conv_a", "write a short poem about rivers in spring"),
        _request(2, "conv_a", "write a little poem about rivers in the spring"),
        *FILLER,
    ]
    assert find_repeats(requests).groups == ()


def test_short_messages_are_skipped() -> None:
    requests = [_request(1, "conv_a", "continue"), _request(2, "conv_b", "continue"), *FILLER]
    report = find_repeats(requests)
    assert report.groups == ()
    assert report.too_short == 2


def test_min_chats() -> None:
    requests = [
        _request(1, "conv_a", "stack status effect speed modifiers in Unity"),
        _request(2, "conv_b", "stacking speed modifiers from status effects in Unity"),
        *FILLER,
    ]
    assert len(find_repeats(requests).groups) == 1
    assert find_repeats(requests, min_chats=3).groups == ()


def test_complete_linkage_stops_a_chain() -> None:
    # A~B and B~C each share most words, but A and C share little. Single
    # linkage would make one group of three; complete linkage must not.
    a = _request(1, "conv_a", "farming game save system structure versioning")
    b = _request(2, "conv_b", "farming game save system structure shop prices")
    c = _request(3, "conv_c", "farming game shop prices structure seasons")
    report = find_repeats([a, b, c, *FILLER], threshold=0.3)
    assert report.groups  # the strongest pair still groups
    assert all(len(group.members) == 2 for group in report.groups)
    for group in report.groups:
        assert group.weakest >= 0.3


def test_order_does_not_matter() -> None:
    requests = [
        _request(1, "conv_a", "break the haggis prototype into implementation tickets"),
        _request(2, "conv_b", "split the haggis prototype into implementation tickets"),
        _request(3, "conv_c", "rewrite my CV summary for a junior Python developer role"),
        _request(4, "conv_d", "improve the summary on my CV for junior Python developer roles"),
        *FILLER,
    ]
    expected = _members(find_repeats(requests).groups)
    shuffled = list(requests)
    for seed in range(5):
        random.Random(seed).shuffle(shuffled)
        assert _members(find_repeats(shuffled).groups) == expected
