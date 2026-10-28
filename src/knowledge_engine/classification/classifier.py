"""The segment classifier: one segment in, approved labels out (CLS-002).

``SegmentClassifier`` holds **one** published taxonomy version for its whole
run (the vocabulary is frozen during a run), and labels segments in one of
two ways:

* **keyword** (default, local, free): the CLS-003 scorer and ranking. Its
  answer is built in the CLS-001 answer shape and validated like any
  model's, so it can only contain approved IDs.
* **model**: a ``ModelStageRunner`` sends the CLS-001 request through a
  provider, with the cache (same stage key, zero calls), the egress switch
  and the one-repair rule. An answer that validates but breaks a rule the
  schema can't express (evidence from outside the segment, two primaries)
  is not used: it becomes ``review_required`` with the problems listed.

Every result says which segment, which taxonomy version, which method,
its stage key and its state: ``done``, ``pending`` (a model hasn't answered
yet) or ``review_required``. An answer with ``needs_review`` set (a near
tie, say) is kept but also marked ``review_required``. Nothing is stored
here; CLS-004 keeps results and reviewer corrections.

Talking points:
    - "One frozen vocabulary per run, and both the free keyword path and a
      model path end in the same validated answer shape."
    - "A model answer that cites messages outside the segment isn't
      trusted: it goes to a person."
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass

from pydantic import BaseModel

from knowledge_engine.classification.schema import (
    CODE_VERSION,
    SegmentMessageText,
    answer_problems,
    assignments,
    classification_request,
    segment_input,
)
from knowledge_engine.classification.scoring import (
    SCORER_VERSION,
    KeywordScorer,
    as_answer,
    rank,
)
from knowledge_engine.orchestration.stage_keys import stage_key
from knowledge_engine.providers.base import ModelRequest
from knowledge_engine.providers.ledger import ModelStageRunner
from knowledge_engine.rendering.transcript import StoredConversation
from knowledge_engine.segmentation.segmenter import Segment
from knowledge_engine.taxonomy.registry import TaxonomySnapshot

KEYWORD_STAGE_ID = "classify.segment.keyword.v1"
DONE = "done"
PENDING = "pending"
REVIEW_REQUIRED = "review_required"


@dataclass(frozen=True)
class SegmentClassification:
    """The outcome for one segment.

    Attributes:
        segment_id: The ``seg_`` ID.
        conversation_id: Its ``conv_`` ID.
        taxonomy_version: The pinned version the labels come from.
        method: ``keyword`` or ``model``.
        stage_key: The fingerprint of this exact work.
        state: ``done``, ``pending`` or ``review_required``.
        answer: The validated answer (None while pending or when invalid).
        problems: Why it needs review (IDs and rule names only).
        message_ids: The segment's messages, for evidence checks later.
    """

    segment_id: str
    conversation_id: str
    taxonomy_version: str
    method: str
    stage_key: str
    state: str
    answer: BaseModel | None
    problems: tuple[str, ...]
    message_ids: tuple[str, ...]


def segment_messages(
    conversation: StoredConversation, segment: Segment
) -> list[SegmentMessageText]:
    """The segment's messages with IDs and roles: the classifier's context."""
    found = []
    for native in segment.messages:
        node = conversation.messages.get(native)
        if node is not None:
            found.append(SegmentMessageText(native, node.role, node.text))
    return found


class SegmentClassifier:
    """Labels segments against one frozen taxonomy version."""

    def __init__(
        self,
        snapshot: TaxonomySnapshot,
        *,
        scorer: KeywordScorer | None = None,
        runner: ModelStageRunner | None = None,
        min_score: float = 1.0,
        tie_margin: float = 0.1,
    ) -> None:
        """Pin the version; use the model runner if given, else keywords.

        Raises:
            ValueError: If the scorer was built for another version.
        """
        self.snapshot = snapshot
        self.scorer = scorer or KeywordScorer(snapshot)
        if self.scorer.snapshot.version != snapshot.version:
            raise ValueError("the scorer must use the same taxonomy version")
        self.runner = runner
        self.min_score = min_score
        self.tie_margin = tie_margin

    @property
    def method(self) -> str:
        """``model`` when a runner is set, otherwise ``keyword``."""
        return "model" if self.runner is not None else "keyword"

    def classify(
        self, items: Sequence[tuple[StoredConversation, Segment]]
    ) -> list[SegmentClassification]:
        """Classify segments, in the order given. Order never changes a result.

        Args:
            items: (conversation, segment) pairs.

        Returns:
            One result per segment, same order.
        """
        contexts = [(conv, seg, segment_messages(conv, seg)) for conv, seg in items]
        if self.runner is None:
            return [self._keyword(conv, seg, msgs) for conv, seg, msgs in contexts]
        return self._model(contexts)

    def _keyword(
        self, conv: StoredConversation, seg: Segment, messages: list[SegmentMessageText]
    ) -> SegmentClassification:
        ranking = rank(
            self.scorer.score(messages), min_score=self.min_score, tie_margin=self.tie_margin
        )
        answer = as_answer(self.snapshot, ranking)
        settings = json.dumps(
            [asdict(self.scorer.weights), self.min_score, self.tie_margin], sort_keys=True
        )
        versions = {
            "code": CODE_VERSION,
            "scorer": SCORER_VERSION,
            "scorer_settings": hashlib.sha256(settings.encode()).hexdigest()[:16],
            "taxonomy": self.snapshot.version,
            "taxonomy_sha": self.snapshot.content_sha256,
        }
        digest = hashlib.sha256(segment_input(messages).encode("utf-8")).hexdigest()
        key = stage_key(KEYWORD_STAGE_ID, digest, versions)
        return self._result(conv, seg, messages, "keyword", key, answer)

    def _model(
        self,
        contexts: list[tuple[StoredConversation, Segment, list[SegmentMessageText]]],
    ) -> list[SegmentClassification]:
        assert self.runner is not None
        # One request per part: a segment over the size budget is split by
        # the segmenter into overlapping parts, never clipped (LEG-005).
        asked = [
            [
                classification_request(self.snapshot, [m for m in msgs if m.message_id in part])
                for part in _part_ids(seg, msgs)
            ]
            for _, seg, msgs in contexts
        ]
        unique = list({r.request_id: r for group in asked for r in group}.values())
        first = self.runner.submit(unique)
        later = self.runner.collect(unique)
        outputs: Mapping[str, BaseModel] = {**first.outputs, **later.outputs}
        failed = set(first.review_required) | set(later.review_required)
        results = []
        for (conv, seg, msgs), group in zip(contexts, asked, strict=True):
            key = group[0].request_id if len(group) == 1 else _combined_key(group)
            if all(r.request_id in outputs for r in group):
                answers = [outputs[r.request_id] for r in group]
                results.append(self._result(conv, seg, msgs, "model", key, answers[0]))
                if len(answers) > 1 and _disagree(answers):
                    results[-1] = _make(
                        self.snapshot,
                        conv,
                        seg,
                        msgs,
                        "model",
                        key,
                        REVIEW_REQUIRED,
                        answers[0],
                        ("the parts of this long segment got different primary labels",),
                    )
            elif any(r.request_id in failed for r in group):
                problems = ("answer failed validation twice",)
                results.append(
                    _make(
                        self.snapshot,
                        conv,
                        seg,
                        msgs,
                        "model",
                        key,
                        REVIEW_REQUIRED,
                        None,
                        problems,
                    )
                )
            else:
                results.append(
                    _make(self.snapshot, conv, seg, msgs, "model", key, PENDING, None, ())
                )
        return results

    def _result(
        self,
        conv: StoredConversation,
        seg: Segment,
        messages: list[SegmentMessageText],
        method: str,
        key: str,
        answer: BaseModel,
    ) -> SegmentClassification:
        problems = answer_problems(answer, [m.message_id for m in messages])
        if getattr(answer, "needs_review", False):
            problems.append("flagged: " + (getattr(answer, "review_reason", None) or "unsure"))
        if problems:
            # A rule-breaking answer is kept for the reviewer to see, but it
            # is not ``done``: nothing downstream may use it as a label yet.
            return _make(
                self.snapshot,
                conv,
                seg,
                messages,
                method,
                key,
                REVIEW_REQUIRED,
                answer,
                tuple(problems),
            )
        return _make(self.snapshot, conv, seg, messages, method, key, DONE, answer, ())


def _part_ids(seg: Segment, msgs: list[SegmentMessageText]) -> list[set[str]]:
    if len(seg.parts) <= 1:
        return [{m.message_id for m in msgs}]
    return [set(part.messages) for part in seg.parts]


def _combined_key(group: Sequence[ModelRequest]) -> str:
    joined = ",".join(r.request_id for r in group)
    return "stg_" + hashlib.sha256(joined.encode("utf-8")).hexdigest()


def _disagree(answers: Sequence[BaseModel]) -> bool:
    # Parts must agree on every primary; secondaries from later parts are
    # not merged in (a reviewer sees the disagreement instead).
    primaries = [
        {
            name: item["term_id" if "term_id" in item else "project_id"]
            for name, item in assignments(a)
            if item["rank"] == "primary"
        }
        for a in answers
    ]
    return any(p != primaries[0] for p in primaries[1:])


def _make(
    snapshot: TaxonomySnapshot,
    conv: StoredConversation,
    seg: Segment,
    messages: list[SegmentMessageText],
    method: str,
    key: str,
    state: str,
    answer: BaseModel | None,
    problems: tuple[str, ...],
) -> SegmentClassification:
    return SegmentClassification(
        segment_id=seg.segment_id,
        conversation_id=conv.conversation_id,
        taxonomy_version=snapshot.version,
        method=method,
        stage_key=key,
        state=state,
        answer=answer,
        problems=problems,
        message_ids=tuple(m.message_id for m in messages),
    )
