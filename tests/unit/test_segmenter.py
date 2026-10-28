"""NRM-004 / LEG-005 edge cases: sizes, overlaps, unknown times, short replies."""

from __future__ import annotations

from knowledge_engine.segmentation.segmenter import (
    SegmenterSettings,
    SegmentMessage,
    boundary_scores,
    segment_section,
)


def msg(n: str, role: str, text: str, at: float | None = None) -> SegmentMessage:
    return SegmentMessage(n, f"rev_{n}", role, text, at)


def exchanges(count: int, size: int, *, start: float | None = 0.0) -> list[SegmentMessage]:
    out = []
    for i in range(count):
        at = None if start is None else start + 60 * i
        out += [msg(f"u{i}", "user", "q" * size, at), msg(f"a{i}", "assistant", "a" * size, at)]
    return out


def test_long_segment_is_split_with_overlap_never_clipped() -> None:
    settings = SegmenterSettings(max_characters=250)
    [segment] = segment_section(exchanges(5, 50), conversation_id="conv_x", settings=settings)
    parts = segment.parts
    assert len(parts) > 1
    assert parts[0].messages[:2] == ("u0", "a0")  # head kept
    assert parts[-1].messages[-2:] == ("u4", "a4")  # tail kept
    for left, right in zip(parts, parts[1:], strict=False):
        assert left.messages[-2:] == right.messages[:2]  # one exchange shared
    assert all(p.characters <= 250 and not p.oversized for p in parts)


def test_one_exchange_over_budget_is_kept_whole_and_flagged() -> None:
    settings = SegmenterSettings(max_characters=50)
    [segment] = segment_section(exchanges(2, 100), conversation_id="conv_x", settings=settings)
    assert [p.messages for p in segment.parts] == [("u0", "a0"), ("u1", "a1")]
    assert all(p.oversized and p.characters == 200 for p in segment.parts)


def test_unknown_times_never_force_a_break() -> None:
    messages = exchanges(4, 50, start=None)
    assert len(segment_section(messages, conversation_id="conv_x")) == 1


def test_long_pause_breaks_even_mid_topic() -> None:
    messages = exchanges(2, 50) + [
        msg("late-u", "user", "q" * 50, 7 * 3600.0),
        msg("late-a", "assistant", "a" * 50, 7 * 3600.0),
    ]
    segments = segment_section(messages, conversation_id="conv_x")
    assert [(s.messages[0], s.reason) for s in segments] == [("u0", "start"), ("late-u", "gap")]


def test_short_user_replies_never_open_a_segment() -> None:
    messages = [
        msg("u0", "user", "Synthetic: here is a long question about one thing entirely", 0.0),
        msg("a0", "assistant", "Synthetic answer", 1.0),
        msg("no", "user", "no", 10 * 3600.0),  # even after a pause
    ]
    [segment] = segment_section(messages, conversation_id="conv_x")
    assert segment.messages == ("u0", "a0", "no")


def test_boundary_scores() -> None:
    assert boundary_scores([], [])["f1"] == 1.0
    assert boundary_scores(["a", "b"], ["b", "c"]) == {"precision": 0.5, "recall": 0.5, "f1": 0.5}
    assert boundary_scores(["a"], [])["precision"] == 0.0
