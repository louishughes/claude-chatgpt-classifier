"""CLS-002 / CLS-003: the segment classifier gives allowed labels, ranked sensibly."""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.classification.classifier import (
    DONE,
    PENDING,
    REVIEW_REQUIRED,
    SegmentClassifier,
    segment_messages,
)
from knowledge_engine.classification.schema import output_model
from knowledge_engine.classification.scoring import KeywordScorer, corpus_frequencies, rank
from knowledge_engine.importer import import_source
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.infrastructure.migrations import upgrade_to_head
from knowledge_engine.providers.base import FakeProvider, ModelRequest
from knowledge_engine.providers.ledger import ModelStageRunner
from knowledge_engine.rendering.transcript import StoredConversation, load_conversation
from knowledge_engine.segmentation.segmenter import Segment, segment_conversation
from knowledge_engine.settings import EgressPolicy, Settings
from knowledge_engine.taxonomy.registry import (
    Dimension,
    SnapshotProject,
    SnapshotTerm,
    TaxonomySnapshot,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt"
EXPECTED: dict[str, Any] = json.loads(
    (FIXTURES / "mixed_projects" / "manifest.json").read_text(encoding="utf-8")
)["expected"]


def _term(term_id: str, label: str, *aliases: str) -> SnapshotTerm:
    return SnapshotTerm(term_id, "topic", label, None, None, aliases)


SNAPSHOT = TaxonomySnapshot(
    "tax-5",
    "c" * 64,
    terms=(
        _term("term_gardening", "Gardening", "seedlings", "raised bed"),
        _term("term_godot", "Godot"),
        _term("term_unity", "Unity"),
        _term("term_webdesign", "Web design", "menu page"),
    ),
    projects=(
        SnapshotProject("proj_bakery", "Bakery site", ()),
        SnapshotProject("proj_garden", "Garden plan", ()),
    ),
)

Pairs = list[tuple[StoredConversation, Segment]]


@pytest.fixture(scope="module")
def pairs(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Pairs]:
    settings = Settings(workspace_root=tmp_path_factory.mktemp("cls"))
    import_source(FIXTURES / "mixed_projects" / "export", "fixture", settings=settings)
    engine = create_sqlite_engine(database_path(settings))
    with Session(engine) as session:
        ids = session.scalars(
            select(ConversationRow.conversation_id).order_by(ConversationRow.native_conversation_id)
        ).all()
        found = []
        for conversation_id in ids:
            conv = load_conversation(session, conversation_id)
            found += [(conv, seg) for seg in segment_conversation(conv)]
    engine.dispose()
    yield found


def _scorer(pairs: Pairs) -> KeywordScorer:
    base = KeywordScorer(SNAPSHOT)
    texts = ["\n".join(m.text for m in segment_messages(conv, seg)) for conv, seg in pairs]
    df, size = corpus_frequencies(base.resolver, texts)
    return KeywordScorer(SNAPSHOT, df, size)


def _labels(answer: Any) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}
    for field in ("topic", "projects"):
        items = getattr(answer, field)
        ids = [getattr(i, "term_id", None) or i.project_id for i in items]
        primary = [x for x, i in zip(ids, items, strict=True) if i.rank == "primary"]
        found[field] = {
            "primary": primary[0] if primary else None,
            "secondary": [x for x, i in zip(ids, items, strict=True) if i.rank == "secondary"],
        }
    return found


def test_golden_mixed_project_segment_receives_allowed_labels(pairs: Pairs) -> None:
    results = SegmentClassifier(SNAPSHOT, scorer=_scorer(pairs)).classify(pairs)
    assert len(pairs) == EXPECTED["conversations"]  # one segment each
    allowed = set(SNAPSHOT.allowed_ids(Dimension.TOPIC)) | set(SNAPSHOT.project_ids())
    for (conv, _), result in zip(pairs, results, strict=True):
        assert result.state == DONE, result.problems
        assert result.taxonomy_version == "tax-5" and result.method == "keyword"
        labels = _labels(result.answer)
        native = conv.native_conversation_id
        for field, want in EXPECTED["primary"][native].items():
            assert labels[field]["primary"] == want
        for field, want in EXPECTED["secondary"][native].items():
            assert labels[field]["secondary"] == want
        used = {x for v in labels.values() for x in [v["primary"], *v["secondary"]] if x}
        assert used <= allowed
        # Evidence points at messages of this segment only.
        for field in ("topic", "projects"):
            for item in getattr(result.answer, field):
                assert set(item.evidence) <= set(result.message_ids)


def test_decisive_once_mentioned_term_outranks_incidental_repetition(pairs: Pairs) -> None:
    [(conv, seg)] = [p for p in pairs if p[0].native_conversation_id.endswith("2")]
    scores = {s.target_id: s for s in _scorer(pairs).score(segment_messages(conv, seg))}
    unity, godot = scores["term_unity"], scores["term_godot"]
    assert unity.mentions > godot.mentions  # Unity is said far more often...
    assert godot.decisive and not unity.decisive  # ..."not Unity" cancels the cue for it
    assert godot.score > unity.score  # ...but the decision wins


def test_order_and_repeat_do_not_change_results(pairs: Pairs) -> None:
    classifier = SegmentClassifier(SNAPSHOT, scorer=_scorer(pairs))
    forward = classifier.classify(pairs)
    backward = classifier.classify(list(reversed(pairs)))[::-1]
    assert [(r.stage_key, r.answer) for r in forward] == [(r.stage_key, r.answer) for r in backward]


def test_near_tie_is_broken_by_id_and_flagged(pairs: Pairs) -> None:
    conv, seg = pairs[0]
    signals = _scorer(pairs).score(segment_messages(conv, seg))
    ranking = rank(signals, tie_margin=100.0)  # everything counts as a tie
    assert ranking.ties == ("projects", "topic")
    result = SegmentClassifier(SNAPSHOT, scorer=_scorer(pairs), tie_margin=100.0).classify(
        [(conv, seg)]
    )[0]
    assert result.state == REVIEW_REQUIRED
    assert any("near tie" in p for p in result.problems)


def test_scorer_must_match_the_pinned_version() -> None:
    other = TaxonomySnapshot("tax-6", "d" * 64, SNAPSHOT.terms, SNAPSHOT.projects)
    with pytest.raises(ValueError, match="same taxonomy version"):
        SegmentClassifier(SNAPSHOT, scorer=KeywordScorer(other))


def _runner(tmp_path: Path, answer: Any) -> tuple[ModelStageRunner, FakeProvider, Session]:
    engine = create_sqlite_engine(tmp_path / "m.db")
    upgrade_to_head(engine)
    session = Session(engine)
    provider = FakeProvider(answer)
    egress = EgressPolicy(text_llm=True)  # the fake sends nothing, but the switch is checked
    return ModelStageRunner(session, provider, egress), provider, session


def test_model_path_validates_checks_and_caches(pairs: Pairs, tmp_path: Path) -> None:
    conv, seg = pairs[1]
    first_message = seg.messages[0]

    def answer(request: ModelRequest) -> Mapping[str, Any]:
        cited = "not-in-segment" if "Bakery" in request.input_text else first_message
        item = {"term_id": "term_godot", "rank": "primary", "confidence": 0.8, "evidence": [cited]}
        return {"topic": [item], "projects": []}

    runner, provider, session = _runner(tmp_path, answer)
    classifier = SegmentClassifier(SNAPSHOT, runner=runner)
    good, cited_outside = classifier.classify([(conv, seg), pairs[0]])
    assert (good.state, good.method) == (DONE, "model")
    assert cited_outside.state == REVIEW_REQUIRED
    assert "evidence outside the segment" in cited_outside.problems[0]
    calls = len(provider.submitted)
    again = classifier.classify([(conv, seg)])[0]
    assert again.state == DONE and len(provider.submitted) == calls  # cache: zero calls
    session.close()


def test_model_path_pending_and_invalid(pairs: Pairs, tmp_path: Path) -> None:
    runner, _, session = _runner(tmp_path, lambda _: None)
    [waiting] = SegmentClassifier(SNAPSHOT, runner=runner).classify(pairs[:1])
    assert (waiting.state, waiting.answer) == (PENDING, None)
    session.close()
    invented = {
        "topic": [{"term_id": "term_pizza", "rank": "primary", "confidence": 1, "evidence": ["x"]}],
        "projects": [],
    }
    (tmp_path / "b").mkdir()
    runner, provider, session = _runner(tmp_path / "b", lambda _: invented)
    classifier = SegmentClassifier(SNAPSHOT, runner=runner)
    [first] = classifier.classify(pairs[:1])
    assert first.state == PENDING  # refused once; its one repair is now waiting
    [refused] = classifier.classify(pairs[:1])
    assert refused.state == REVIEW_REQUIRED and refused.answer is None
    assert len(provider.submitted) == 2  # the first ask and its one repair, never a third
    [still] = classifier.classify(pairs[:1])
    assert still.state == REVIEW_REQUIRED and len(provider.submitted) == 2
    session.close()
    assert output_model(SNAPSHOT)  # the same model the keyword path validates against
