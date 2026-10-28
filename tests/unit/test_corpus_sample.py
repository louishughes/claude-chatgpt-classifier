"""NRM-006: the corpus sample is deterministic for a seed and reaches rare themes."""

from __future__ import annotations

from knowledge_engine.segmentation.inventory import (
    SegmentText,
    sample,
    sample_ids,
    summarise,
    theme_words,
)

# 40 segments about sheds (in a few variants), 2 about sourdough, 1 about
# beekeeping. A uniform random sample of 5 would usually miss both rare ones.
SHED = [
    "Synthetic: the shed roof needs felt and the shed roof timber needs treating.",
    "Synthetic: shed floor joists sit on a gravel shed base.",
    "Synthetic: paint the shed door and the shed windows.",
    "Synthetic: the shed roof leaks; replace the shed roof felt.",
]
RARE = {
    "seg_bread_1": "Synthetic: feed the sourdough starter flour; sourdough likes warmth.",
    "seg_bread_2": "Synthetic: shape the sourdough loaf; sourdough needs steam.",
    "seg_bees": "Synthetic: the beehive needs a queen; inspect the beehive frames.",
}


def _corpus() -> list[SegmentText]:
    items = [
        SegmentText(f"seg_shed_{i:02d}", f"conv_{i % 9}", "active", 2, SHED[i % len(SHED)])
        for i in range(40)
    ]
    items += [SegmentText(k, "conv_rare", "alternate", 2, v) for k, v in RARE.items()]
    return items


def test_same_seed_same_sample_and_order_of_input_does_not_matter() -> None:
    items = _corpus()
    first = sample_ids(sample(items, 5, seed="s1"))
    assert first == sample_ids(sample(items, 5, seed="s1"))
    assert first == sample_ids(sample(list(reversed(items)), 5, seed="s1"))
    assert len(set(first)) == 5


def test_rare_themes_are_always_in_the_sample() -> None:
    items = _corpus()
    for seed in ("s1", "s2", "s3", "another"):
        drawn = set(sample_ids(sample(items, 4, seed=seed)))
        assert "seg_bees" in drawn
        assert drawn & {"seg_bread_1", "seg_bread_2"}


def test_different_seeds_can_differ_and_sizes_are_bounded() -> None:
    items = _corpus()
    seen = {tuple(sample_ids(sample(items, 6, seed=f"seed-{n}"))) for n in range(10)}
    assert len(seen) > 1
    assert sample(items, 0, seed="x") == []
    assert len(sample(items, 1_000, seed="x")) == len(items)
    assert sample([], 5, seed="x") == []


def test_theme_words_ignore_words_in_every_segment() -> None:
    themes = theme_words(_corpus())
    assert themes["seg_bees"] == "beehive"
    assert themes["seg_bread_1"] == "sourdough"
    assert "synthetic" not in themes.values()


def test_summary_holds_counts_only() -> None:
    summary = summarise(_corpus())
    assert (summary.conversations, summary.segments) == (10, 43)
    assert summary.sections == {"active": 40, "alternate": 3}
    assert summary.length_bands["short"] == 43
    assert summary.themes >= 3
    assert "Synthetic" not in repr(summary)
