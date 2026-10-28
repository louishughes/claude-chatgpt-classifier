"""REL-002 detector edge cases that need no database."""

from __future__ import annotations

from knowledge_engine.relationships.detect import _Chat, _copied_prefixes, _quotes

U, A = ("user", "k-u"), ("assistant", "k-a")


def test_one_shared_message_is_not_a_fork() -> None:
    a = _Chat("conv_a", 1.0, opening=[U, ("assistant", "x")])
    b = _Chat("conv_b", 2.0, opening=[U, ("assistant", "y")])
    assert list(_copied_prefixes([a, b])) == []


def test_assistant_only_prefix_is_not_a_fork() -> None:
    a = _Chat("conv_a", 1.0, opening=[A, ("assistant", "k2"), U])
    b = _Chat("conv_b", 2.0, opening=[A, ("assistant", "k2")])
    assert list(_copied_prefixes([a, b])) == []


def test_fork_points_at_the_longest_earlier_match() -> None:
    first = _Chat("conv_1", 1.0, opening=[U, A])
    second = _Chat("conv_2", 2.0, opening=[U, A, ("user", "k3")])
    third = _Chat("conv_3", 3.0, opening=[U, A, ("user", "k3"), ("assistant", "k4")])
    assert sorted(_copied_prefixes([third, first, second])) == [
        ("conv_1", "conv_2", 2),
        ("conv_2", "conv_3", 3),
    ]


def test_unknown_times_give_one_undirected_pair() -> None:
    a = _Chat("conv_a", None, opening=[U, A])
    b = _Chat("conv_b", None, opening=[U, A])
    assert list(_copied_prefixes([a, b])) == [("conv_a", "conv_b", 2)]


def test_quotes_need_times_and_skip_boilerplate() -> None:
    def chat(name: str, at: float | None, role: str = "user") -> _Chat:
        return _Chat(name, at, paragraphs={"p": (f"rev_{name}", role, at)})

    assert list(_quotes([chat("a", None, "assistant"), chat("b", None)])) == []
    assert list(_quotes([chat("a", 1.0, "assistant"), chat("b", 2.0)])) == [("b", "a", ["rev_b"])]
    # An assistant repeating text isn't a user quoting it.
    assert list(_quotes([chat("a", 1.0), chat("b", 2.0, "assistant")])) == []
    spread = [chat(str(i), float(i)) for i in range(6)]
    assert list(_quotes(spread)) == []
