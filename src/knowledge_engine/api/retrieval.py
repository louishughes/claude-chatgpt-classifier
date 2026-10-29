"""Search, grounded answers and decision history endpoints (API-004).

The same retrieval as ``ke search``, ``ke find``, ``ke ask`` and
``ke timeline``, as JSON. Each request first brings the word and meaning
indexes up to date (a cheap step when nothing changed), then reads.

* ``GET /search``: words in messages (exact, phrase or tokens), optionally
  narrowed by day, speaker and vocabulary term (RET-009).
* ``GET /find``: the planner picks the route (structured records, exact
  words or hybrid) and returns records and message hits.
* ``POST /answers``: an answer where every sentence cites stored text, or
  an honest "I don't know" (RET-007). Citations carry the conversation,
  message revision and character span, so a program can open the exact
  words with ``/sources/{id}/nodes``. The answer writer is the local
  extractive one; no model is called.
* ``GET /decisions/{record_id}/history``: what happened to one decision,
  oldest first (replaced, conflicts, revoked), with each event's evidence.

``as_of`` (epoch seconds, the time the chats said it) answers decision
questions as they stood then: a decision made later doesn't exist yet.

Talking points:
    - "Answers over the API come with citations a program can follow back
      to the exact characters in the original message."
    - "Asking 'as of last March' gives the decisions as they were then, not
      what replaced them later."
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from knowledge_engine.api.deps import ApiError, SessionsDep, SettingsDep
from knowledge_engine.extraction.store import GateError, load
from knowledge_engine.infrastructure.workspace import WorkspaceRow
from knowledge_engine.reconciliation.timeline import DecisionEventRow, timeline
from knowledge_engine.retrieval.answers import answer, to_json
from knowledge_engine.retrieval.embeddings import LocalHashEmbedder
from knowledge_engine.retrieval.filters import (
    BadFilterDate,
    BadFilterRole,
    UnknownFilterTerm,
    build_filters,
)
from knowledge_engine.retrieval.hybrid import HybridRetriever
from knowledge_engine.retrieval.lexical import (
    LexicalIndex,
    SearchMode,
    search_index_path,
    sync_index,
)
from knowledge_engine.retrieval.planner import plan, run_plan
from knowledge_engine.retrieval.semantic import (
    SemanticIndex,
    StaleIndexError,
    semantic_index_path,
    sync_semantic,
)
from knowledge_engine.settings import Settings

router = APIRouter()

Question = Annotated[str, Query(min_length=1, max_length=1000)]
Limit = Annotated[int, Query(ge=1, le=100)]
AsOf = Annotated[float | None, Query(ge=0)]
# The index files are single-writer; requests take turns syncing them.
_INDEX_LOCK = threading.Lock()


class AnswerRequest(BaseModel):
    """``POST /answers``."""

    question: str = Field(min_length=1, max_length=1000)
    limit: int = Field(default=8, ge=1, le=50)
    as_of: float | None = Field(default=None, ge=0)


@dataclass
class _Indexes:
    session: Session
    lexical: LexicalIndex
    retriever: HybridRetriever
    workspaces: list[str]


@contextmanager
def _indexes(settings: Settings, session: Session) -> Iterator[_Indexes]:
    """Synced word and meaning indexes and a hybrid retriever, for one request."""
    with _INDEX_LOCK:
        try:
            semantic = SemanticIndex(semantic_index_path(settings), LocalHashEmbedder())
        except StaleIndexError as error:
            raise ApiError(
                503,
                "stale_index",
                "the meaning index was built differently: run ke similar --rebuild",
            ) from error
        with semantic, LexicalIndex(search_index_path(settings)) as lexical:
            sync_index(session, lexical)
            sync_semantic(session, semantic, settings.egress)
            yield _Indexes(
                session,
                lexical,
                HybridRetriever(session, lexical, semantic, settings.egress),
                list(session.scalars(select(WorkspaceRow.workspace_id))),
            )


@router.get("/search", tags=["retrieval"])
def search(
    q: Question,
    settings: SettingsDep,
    sessions: SessionsDep,
    mode: SearchMode = SearchMode.TOKENS,
    conversation_id: Annotated[str | None, Query(max_length=100)] = None,
    limit: Limit = 20,
    since: Annotated[str | None, Query(max_length=10, description="YYYY-MM-DD, UTC")] = None,
    until: Annotated[str | None, Query(max_length=10, description="YYYY-MM-DD, UTC")] = None,
    role: Annotated[str | None, Query(max_length=20)] = None,
    term: Annotated[str | None, Query(max_length=100)] = None,
    taxonomy: Annotated[str | None, Query(max_length=100)] = None,
) -> dict[str, Any]:
    """Messages containing the words, with a short snippet and their anchors.

    ``since``/``until``/``role``/``term`` narrow the search (RET-009), with the
    same checks as ``ke search``. An unapproved ``term`` is refused, never ignored.
    """
    with sessions.transaction(write=False) as session:
        try:
            filters = build_filters(
                session, since=since, until=until, role=role, term=term, taxonomy=taxonomy
            )
        except (BadFilterDate, BadFilterRole) as error:
            raise ApiError(400, "bad_filter", str(error)) from None
        except UnknownFilterTerm as error:
            raise ApiError(400, "unknown_term", str(error)) from None
        with _indexes(settings, session) as ix:
            hits = [
                {
                    "conversation_id": hit.conversation_id,
                    "native_node_id": hit.native_node_id,
                    "revision_id": hit.revision_id,
                    "role": hit.role,
                    "snippet": hit.snippet,
                }
                for workspace_id in ix.workspaces
                for hit in ix.lexical.search(
                    q,
                    workspace_id=workspace_id,
                    mode=mode,
                    limit=limit,
                    conversation_id=conversation_id,
                    filters=filters,
                )
            ][:limit]
            undated = sum(
                ix.lexical.undated(
                    q,
                    workspace_id=workspace_id,
                    mode=mode,
                    conversation_id=conversation_id,
                    filters=filters,
                )
                for workspace_id in ix.workspaces
            )
    body: dict[str, Any] = {"mode": mode.value, "hits": hits}
    if filters is not None and filters.dated:
        body["undated_left_out"] = undated
    return body


@router.get("/find", tags=["retrieval"])
def find(
    q: Question, settings: SettingsDep, sessions: SessionsDep, limit: Limit = 10, as_of: AsOf = None
) -> dict[str, Any]:
    """The planner's route: knowledge records first for decision questions, then messages."""
    question = plan(q)
    records: list[dict[str, Any]] = []
    hits: list[dict[str, Any]] = []
    fallback = False
    with sessions.transaction(write=False) as session, _indexes(settings, session) as ix:
        for workspace_id in ix.workspaces:
            result = run_plan(
                session,
                question,
                ix.retriever,
                ix.lexical,
                workspace_id=workspace_id,
                limit=limit,
                as_of=as_of,
            )
            fallback = fallback or result.fallback
            records += [
                {
                    "record_id": r.record_id,
                    "record_type": r.record_type,
                    "status": r.status.value,
                    "assertion": r.assertion,
                    "conversation_id": r.conversation_id,
                    "revisions": list(r.revisions),
                    "superseded_by": list(r.superseded_by),
                    "conflicts_with": list(r.conflicts_with),
                }
                for r in result.records
            ]
            hits += [
                {
                    "kind": h.kind,
                    "conversation_id": h.conversation_id,
                    "revision_id": h.revision_id,
                    "score": round(h.score, 6),
                    "role": h.role,
                    "snippet": h.snippet,
                    "record_type": h.record_type,
                }
                for h in result.hits
            ]
    return {
        "route": question.route.value,
        "reasons": list(question.reasons),
        "fallback": fallback,
        "records": records[:limit],
        "hits": hits[:limit],
    }


@router.post("/answers", tags=["retrieval"])
def post_answer(
    body: AnswerRequest, settings: SettingsDep, sessions: SessionsDep
) -> dict[str, Any]:
    """A cited answer per workspace, or an abstention; ``answer`` is the best one."""
    answers: list[dict[str, Any]] = []
    with sessions.transaction(write=False) as session, _indexes(settings, session) as ix:
        for workspace_id in ix.workspaces:
            found = answer(
                session,
                body.question,
                ix.retriever,
                ix.lexical,
                workspace_id=workspace_id,
                limit=body.limit,
                as_of=body.as_of,
            )
            answers.append(json.loads(to_json(found)))
    answered = [a for a in answers if a["status"] != "unknown"]
    best = (answered or answers)[0] if answers else None
    return {"answer": best, "answers": answers}


@router.get("/decisions/{record_id}/history", tags=["retrieval"])
def decision_history(record_id: str, sessions: SessionsDep) -> dict[str, Any]:
    """Every event touching one record, oldest first, with each event's evidence."""
    with sessions.transaction(write=False) as session:
        try:
            record = load(session, record_id)
        except GateError as error:
            raise ApiError(404, "not_found", "no such record") from error
        entries = timeline(session, [record_id])
        evidence = {
            row.event_id: json.loads(row.evidence_json or "{}")
            for row in session.scalars(
                select(DecisionEventRow).where(
                    or_(
                        DecisionEventRow.from_record == record_id,
                        DecisionEventRow.to_record == record_id,
                        DecisionEventRow.event_id.in_([e.event_id for e in entries]),
                    )
                )
            )
        }
    return {
        "record_id": record_id,
        "record_type": record.record_type.value,
        "trust": record.trust.value,
        "evidence": [e.model_dump(mode="json") for e in record.evidence],
        "events": [{**asdict(e), "evidence": evidence.get(e.event_id, {})} for e in entries],
    }
