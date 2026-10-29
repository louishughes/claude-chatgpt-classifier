"""Data for the Ask page: a cited answer, or an honest "don't know" (UI-007).

The PRD's Search/Q&A screen (§10) wants "cited evidence chips; show
retrieval method, filters and unknown/conflict outcomes". ``ke ask`` and
``POST /api/v1/answers`` already do the work (RET-007); this module runs the
very same ``answer`` function and shapes the result for a page:

* every sentence with numbered chips, each chip a link to the exact message
  it cites (``/chats/<id>#node-...``);
* the route the planner picked and its reasons in words (RET-005), so a
  reader can see *why* it looked where it looked;
* the status in plain words: answered, answered with a disagreement, or
  "I can't find this in your chats".

Nothing is written to the archive. The word and meaning indexes are caches
and are brought up to date first, exactly as the search page does. The
answer writer is the local extractive one: no model is called.

Talking points:
    - "The browser's Ask page runs the same answer code as the command
      line, so it can't say anything the audited answer couldn't."
    - "Every chip under a sentence opens the exact message it cites, and the
      page says which search route it used and why."
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.infrastructure.workspace import WorkspaceRow
from knowledge_engine.retrieval.answers import GroundedAnswer, answer
from knowledge_engine.retrieval.embeddings import LocalHashEmbedder
from knowledge_engine.retrieval.hybrid import HybridRetriever
from knowledge_engine.retrieval.lexical import LexicalIndex, search_index_path, sync_index
from knowledge_engine.retrieval.planner import plan
from knowledge_engine.retrieval.semantic import (
    SemanticIndex,
    StaleIndexError,
    semantic_index_path,
    sync_semantic,
)
from knowledge_engine.settings import Settings
from knowledge_engine.ui.registries import places

MAX_QUESTION = 1000  # the same cap as POST /api/v1/answers
STATUS_WORDS = {
    "answered": "Answered from your chats.",
    "conflicted": "Answered, but your chats disagree with themselves: check each source.",
    "unknown": "Not answered.",
}


class StaleMeaningIndex(RuntimeError):
    """The meaning index was built by another embedder; it needs a rebuild."""


def ask_view(session: Session, settings: Settings, question: str) -> dict[str, Any]:
    """Answer ``question`` from every workspace in this database, for the page.

    The first workspace with an answer wins; otherwise the first abstention
    is shown (one workspace is the normal case on a PC).

    Raises:
        StaleMeaningIndex: See the class.
    """
    try:
        semantic = SemanticIndex(semantic_index_path(settings), LocalHashEmbedder())
    except StaleIndexError as error:
        raise StaleMeaningIndex(str(error)) from None
    results: list[GroundedAnswer] = []
    with semantic, LexicalIndex(search_index_path(settings)) as lexical:
        sync_index(session, lexical)
        sync_semantic(session, semantic, settings.egress)
        retriever = HybridRetriever(session, lexical, semantic, settings.egress)
        for workspace_id in session.scalars(select(WorkspaceRow.workspace_id)):
            results.append(answer(session, question, retriever, lexical, workspace_id=workspace_id))
    chosen = next((r for r in results if r.status != "unknown"), results[0] if results else None)
    route = plan(question)
    view: dict[str, Any] = {
        # The route that ran can differ from the plan: a structured question
        # with no matching records falls back to searching messages.
        "route": chosen.route if chosen else route.route.value,
        "planned": route.route.value,
        "reasons": list(route.reasons),
        "status": chosen.status if chosen else "unknown",
        "status_words": STATUS_WORDS[chosen.status if chosen else "unknown"],
        "sentences": [],
        "sources": [],
        "writer": chosen.writer if chosen else None,
    }
    if chosen is None:
        return view
    number = {c.citation_id: i for i, c in enumerate(chosen.citations, 1)}
    where = places(session, (c.revision_id for c in chosen.citations))
    view["sources"] = [
        {"number": number[c.citation_id], "place": where.get(c.revision_id), "actor": c.actor}
        for c in chosen.citations
    ]
    chips = {s["number"]: s for s in view["sources"]}
    view["sentences"] = [
        {"text": s.text, "chips": [chips[number[c]] for c in s.citation_ids]}
        for s in chosen.sentences
    ]
    return view
