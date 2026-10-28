"""Send flagged segments to a separate reviewer session (NOTE-018).

A classification goes to ``review_required`` when the classifier was unsure
or broke a rule. Those segments wait in the CLS-004 review queue for a
person. This module lets a *second* session do that review through the same
request files as ``ke classify run``: one request per flagged segment, with
the segment, the first answer and what was wrong with it. A clean reviewer
answer is stored with ``record_review``, naming the reviewer session, for
each field that was flagged; reviews already outrank machine labels, so the
chat's category settles from then on.

The reviewer is held to the same rules as the classifier (only approved IDs,
evidence from inside the segment). An answer that breaks one, or that says
it is unsure too, records nothing and the segment stays in the queue for a
person. A segment already reviewed leaves the queue, so asking again costs
no request.

Talking points:
    - "A second session looks at what the first one was unsure about, and
      its answer is filed as a named review, not as a machine label."
    - "If the reviewer is unsure too, nothing is recorded: the segment waits
      for a person."
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from pydantic import BaseModel
from sqlalchemy.orm import Session

from knowledge_engine.classification.classifier import segment_messages
from knowledge_engine.classification.schema import (
    Rank,
    SegmentMessageText,
    answer_problems,
    assignments,
    instructions,
    output_model,
    segment_input,
)
from knowledge_engine.classification.store import (
    ClassificationRow,
    flagged_fields,
    record_review,
    review_queue,
)
from knowledge_engine.orchestration.stage_keys import stage_key
from knowledge_engine.providers.base import ModelRequest
from knowledge_engine.providers.ledger import ModelOutputRow, ModelStageRunner
from knowledge_engine.rendering.transcript import StoredConversation, load_conversation
from knowledge_engine.segmentation.overrides import load_segments
from knowledge_engine.taxonomy.registry import TaxonomySnapshot

REVIEW_STAGE_ID = "classify.review.v1"
REVIEW_PROMPT_VERSION = "cls-review-prompt-v1"
REVIEW_CODE_VERSION = "note-018-v1"
_REVIEWER_MAX = 100  # the reviews table's column size


@dataclass(frozen=True)
class ReviewReport:
    """What one reviewer pass did, counted in segments.

    Attributes:
        queued: Segments waiting for review when the pass started.
        reviewed: Segments whose flagged fields got a stored review.
        unsure: Answers that broke a rule or were unsure; nothing stored.
        pending: Requests still waiting for an answer.
        failed: Requests that failed validation twice.
        missing: Queued segments that no longer exist (the chat changed).
    """

    queued: int
    reviewed: int
    unsure: int
    pending: int
    failed: int
    missing: int


def review_instructions(snapshot: TaxonomySnapshot) -> str:
    """The classifier's prompt, preceded by what a reviewer is asked to do."""
    return "\n".join(
        [
            "You are reviewing a classification another model was unsure about.",
            "The data shows the segment, that model's answer, and what was wrong with it.",
            "Give the labels you would choose, in the same answer shape and under the",
            "same rules. Do not copy the earlier answer; judge the segment yourself.",
            "",
            instructions(snapshot),
        ]
    )


def review_request(
    snapshot: TaxonomySnapshot,
    messages: Sequence[SegmentMessageText],
    row: ClassificationRow,
) -> ModelRequest:
    """One reviewer request for one flagged classification."""
    problems = json.loads(row.problems_json)
    text = "\n\n".join(
        [
            segment_input(messages),
            "[earlier answer]\n" + (row.answer_json or "none: the answer failed validation"),
            "[problems]\n" + ("\n".join(f"- {p}" for p in problems) or "- none listed"),
        ]
    )
    versions = {
        "code": REVIEW_CODE_VERSION,
        "prompt": REVIEW_PROMPT_VERSION,
        "taxonomy": snapshot.version,
        "taxonomy_sha": snapshot.content_sha256,
    }
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return ModelRequest(
        request_id=stage_key(REVIEW_STAGE_ID, digest, versions),
        stage_id=REVIEW_STAGE_ID,
        instructions=review_instructions(snapshot),
        input_text=text,
        output_model=output_model(snapshot),
        prompt_version=REVIEW_PROMPT_VERSION,
        schema_version=REVIEW_PROMPT_VERSION,
    )


def _store(
    session: Session,
    snapshot: TaxonomySnapshot,
    row: ClassificationRow,
    answer: BaseModel,
    reviewer: str,
) -> None:
    chosen: dict[str, tuple[str | None, list[str]]] = {}
    for name, item in assignments(answer):
        target = item.get("term_id") or item["project_id"]
        primary, rest = chosen.get(name, (None, []))
        if item["rank"] == Rank.PRIMARY.value:
            primary = target
        else:
            rest.append(target)
        chosen[name] = (primary, rest)
    for name in sorted(flagged_fields(row)):
        primary, rest = chosen.get(name, (None, []))
        # An empty field is the reviewer's answer "nothing in the vocabulary fits".
        record_review(
            session,
            snapshot,
            row.segment_id,
            name,
            primary=primary,
            secondary=rest,
            reviewer=reviewer,
            note="reviewer session answer",
            conversation_id=row.conversation_id,
        )


def review_flagged(
    session: Session, snapshot: TaxonomySnapshot, runner: ModelStageRunner, provider_id: str
) -> ReviewReport:
    """Ask a reviewer session about every queued segment and store its clean answers.

    Args:
        session: The caller commits.
        snapshot: The published version the queue and answers are under.
        runner: Sends requests and collects answers (egress, cache, ledger).
        provider_id: Names the reviewer when the answer carries no session.

    Raises:
        EgressDisabledError: If text egress is off.
    """
    queue = review_queue(session, snapshot.version)
    chats: dict[str, StoredConversation] = {}
    asked: list[tuple[ClassificationRow, list[SegmentMessageText], ModelRequest]] = []
    missing = 0
    for row in queue:
        chat = chats.get(row.conversation_id)
        if chat is None:
            chat = chats[row.conversation_id] = load_conversation(session, row.conversation_id)
        segment = next(
            (s for s in load_segments(session, chat) if s.segment_id == row.segment_id), None
        )
        if segment is None:
            missing += 1
            continue
        messages = segment_messages(chat, segment)
        asked.append((row, messages, review_request(snapshot, messages, row)))
    unique = list({r.request_id: r for _, _, r in asked}.values())
    first = runner.submit(unique)
    later = runner.collect(unique)
    outputs: Mapping[str, BaseModel] = {**first.outputs, **later.outputs}
    failed_keys = set(first.review_required) | set(later.review_required)
    reviewed = unsure = pending = failed = 0
    for row, messages, request in asked:
        answer = outputs.get(request.request_id)
        if answer is None:
            if request.request_id in failed_keys:
                failed += 1
            else:
                pending += 1
            continue
        problems = answer_problems(answer, [m.message_id for m in messages])
        if problems or getattr(answer, "needs_review", False):
            unsure += 1
            continue
        stored = session.get(ModelOutputRow, request.request_id)
        ref = stored.session_ref if stored is not None and stored.session_ref else provider_id
        _store(session, snapshot, row, answer, f"session:{ref}"[:_REVIEWER_MAX])
        reviewed += 1
    session.flush()
    return ReviewReport(len(queue), reviewed, unsure, pending, failed, missing)
