"""Pick the right search for a question, then run it (RET-005).

Different questions need different searches:

* **"What did I decide about the game engine?"** is about the *current*
  state of things. Fuzzy text search would happily return the old Unity
  decision that was later replaced. So it goes to the ``structured`` route:
  the REC-006 projection, which knows what is current, replaced, in
  conflict or pending.
* **``ERR-4012``**, **``parse_export``** or **"quoted text"** is exact text.
  It goes to the ``exact`` route: the word index, character for character.
* **Anything else** ("ideas for marketing my game") is a broad concept and
  goes to the ``hybrid`` route (RET-004). Codes inside a longer question
  are passed on as exact terms, so their messages are still pinned first.

The planner is plain rules, no model: the same question always gets the
same route, and the plan says *why* (``reasons``), so a wrong route is easy
to spot and fix. Order of the rules:

1. no words at all: ``empty`` (nothing is searched);
2. quoted text: ``exact`` on the quoted text;
3. a question about my decisions, requirements, preferences or rejections
   (decision words *and* "I/we/my/current/latest..."): ``structured``,
   limited to the record kinds the words name;
4. only codes, apart from search words like "find" or "where": ``exact``;
5. otherwise ``hybrid``.

If the structured route finds no record about the subject, the run falls
back to hybrid and says so (``fallback``), rather than answering "nothing".

Not yet: dates in the question ("in March") are not read; ``as_of`` is a
separate argument. Records are matched to the subject by shared words.

Talking points:
    - "'What did I decide?' reads the decision records, so a replaced
      decision is shown as replaced, not as the answer."
    - "Codes and quoted text get an exact search; everything else gets the
      combined search."
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.extraction.records import KnowledgeRecord, RecordType
from knowledge_engine.extraction.store import KnowledgeRecordRow
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.reconciliation.projection import Status, project
from knowledge_engine.reconciliation.relations import place
from knowledge_engine.retrieval.hybrid import HybridHit, HybridRetriever, query_words
from knowledge_engine.retrieval.lexical import LexicalIndex, SearchMode

PLANNER_VERSION = "ret-005-v1"


class Route(StrEnum):
    """Which search answers a question."""

    STRUCTURED = "structured"
    EXACT = "exact"
    HYBRID = "hybrid"
    EMPTY = "empty"


# Quoted text: straight, curly or back quotes, with at least one word inside.
_QUOTED = re.compile(r"\"([^\"]*\w[^\"]*)\"|“([^”]*\w[^”]*)”|`([^`]*\w[^`]*)`")
_TOKEN = re.compile(r"\S+")
_EDGE = "\"'“”‘’`()[]{}<>,;:!?."
# A code: letters and digits mixed (ERR-4012, v12), snake_case, camelCase,
# a path, a dotted name (export.py) or a URL.
_CODE = re.compile(
    r"^(?=.*[A-Za-z])(?=.*\d)[\w.\-/:#]{3,}$"
    r"|^\w*_\w+$"
    r"|^[a-z]+[A-Z]\w*$"
    r"|^[\w.\-]*/[\w.\-/]+$"
    r"|^\w+\.\w{1,5}$"
    r"|^https?://\S+$"
)
_SEARCH_WORDS = frozenset(
    "find search show look lookup where when which what did do does mention mentioned "
    "said say says message messages chat chats about the a an for in of me my i is are was "
    "were it that to any all".split()
)
# Decision words, each naming the record kinds it asks about.
_KINDS: tuple[tuple[re.Pattern[str], tuple[RecordType, ...]], ...] = (
    (
        re.compile(
            r"\b(?:decid\w*|decision\w*|chose|choos\w*|chosen|pick(?:ed)?|settled?|"
            r"go(?:ing)? with|went with|opted|using|use)\b",
            re.IGNORECASE,
        ),
        (RecordType.DECISION,),
    ),
    (re.compile(r"\bprefer\w*\b", re.IGNORECASE), (RecordType.PREFERENCE,)),
    (re.compile(r"\b(?:requir\w*|must|need to)\b", re.IGNORECASE), (RecordType.REQUIREMENT,)),
    (
        re.compile(r"\b(?:reject\w*|ruled? out|turned down|said no)\b", re.IGNORECASE),
        (RecordType.REJECTION,),
    ),
)
# "Mine, now": without one of these, "how do decision trees work?" is a concept.
_PERSONAL = re.compile(
    r"\b(?:i|we|my|our|me|us|current(?:ly)?|latest|now|still|so far)\b", re.IGNORECASE
)
# Words that only steer the route; left out when matching records to the subject.
_ROUTING_WORDS = query_words(
    "decide decided decision decisions chose choose chosen pick picked settle settled going "
    "went opted prefer preference preferences require requirement requirements must need "
    "reject rejected rejection ruled turned current currently latest still what which did "
    "do does am are have has"
)


@dataclass(frozen=True)
class Plan:
    """How a question will be answered.

    Attributes:
        route: The search to run.
        query: The text to search for (for a quoted ``exact`` query, the quote).
        exact_terms: Codes and quotes whose exact matches are pinned first.
        record_types: For ``structured``: the record kinds asked about.
        reasons: Why this route, in words.
        version: The planner's version.
    """

    route: Route
    query: str
    exact_terms: tuple[str, ...] = ()
    record_types: tuple[RecordType, ...] = ()
    reasons: tuple[str, ...] = ()
    version: str = PLANNER_VERSION


def codes(question: str) -> list[str]:
    """The code-like tokens in a question, in order, without surrounding punctuation."""
    found = []
    for token in _TOKEN.findall(question):
        word = token.strip(_EDGE)
        if word and _CODE.match(word) and word not in found:
            found.append(word)
    return found


def plan(question: str) -> Plan:
    """Choose the route for ``question`` (see the module text for the rules)."""
    text = question.strip()
    if not re.search(r"\w", text):
        return Plan(Route.EMPTY, "", reasons=("no words to search for",))
    quoted = [next(g for g in m.groups() if g is not None) for m in _QUOTED.finditer(text)]
    if quoted:
        return Plan(
            Route.EXACT,
            quoted[0].strip(),
            exact_terms=tuple(q.strip() for q in quoted),
            reasons=("quoted text is searched exactly",),
        )
    found = codes(text)
    kinds = tuple(dict.fromkeys(k for pattern, ks in _KINDS if pattern.search(text) for k in ks))
    if kinds and _PERSONAL.search(text):
        return Plan(
            Route.STRUCTURED,
            text,
            exact_terms=tuple(found),
            record_types=kinds,
            reasons=("asks what I decided, need, prefer or rejected: read the current records",),
        )
    if found:
        rest = [
            w
            for w in re.findall(r"\w+", text.lower())
            if w not in _SEARCH_WORDS and not any(w in c.lower() for c in found)
        ]
        if not rest:
            return Plan(
                Route.EXACT,
                found[0],
                exact_terms=tuple(found),
                reasons=("only codes: searched exactly",),
            )
        return Plan(
            Route.HYBRID,
            text,
            exact_terms=tuple(found),
            reasons=("a question with codes in it: combined search, codes pinned first",),
        )
    return Plan(Route.HYBRID, text, reasons=("a broad question: combined search",))


@dataclass(frozen=True)
class RecordAnswer:
    """A stated record that answers a structured question.

    Attributes:
        record_id: The ``krec_`` ID.
        record_type: Its kind.
        status: Current, superseded, conflicted, pending or unknown (REC-006).
        assertion: What it says, as stored on the record.
        conversation_id: The chat its evidence is in.
        revisions: The message versions its evidence cites.
        because: The events and conflicts that explain the status.
        superseded_by: Records that replaced it.
        conflicts_with: Records it is in open conflict with.
        shared_words: How many subject words it shares with the question.
    """

    record_id: str
    record_type: str
    status: Status
    assertion: str
    conversation_id: str | None
    revisions: tuple[str, ...]
    because: tuple[str, ...]
    superseded_by: tuple[str, ...]
    conflicts_with: tuple[str, ...]
    shared_words: int


@dataclass(frozen=True)
class RouteResult:
    """What running a plan found.

    Attributes:
        plan: The plan that ran.
        route: The route actually used (``hybrid`` after a fallback).
        fallback: True if the structured route found nothing and hybrid ran.
        records: For ``structured``: the matching records, current first.
        hits: For ``exact`` and ``hybrid``: the messages and records found.
    """

    plan: Plan
    route: Route
    fallback: bool
    records: tuple[RecordAnswer, ...]
    hits: tuple[HybridHit, ...]


# Current answers first; replaced ones last, still shown so the history is visible.
_STATUS_ORDER = {
    Status.CURRENT: 0,
    Status.CONFLICTED: 1,
    Status.PENDING: 2,
    Status.UNKNOWN: 3,
    Status.SUPERSEDED: 4,
}


def structured_answers(
    session: Session,
    question_plan: Plan,
    *,
    workspace_id: str,
    as_of: float | None = None,
) -> list[RecordAnswer]:
    """Stated records of the asked kinds about the question's subject, current first.

    Subject words are the question's content words minus the routing words
    ("decide", "what"...). A question with no subject words left ("what
    did I decide?") matches every record of the asked kinds.
    """
    subject = query_words(question_plan.query) - _ROUTING_WORDS
    state = project(session, as_of=as_of)
    rows = {
        e.record_id: KnowledgeRecord.model_validate_json(
            session.get_one(KnowledgeRecordRow, e.record_id).record_json
        )
        for e in state.entries
    }
    placed = {p.record.record_id: p for p in place(session, list(rows.values()))}
    workspaces = _chat_workspaces(session, {p.conversation_id for p in placed.values()})
    kinds = {k.value for k in question_plan.record_types}
    answers = []
    for entry in state.entries:
        record = rows[entry.record_id]
        where = placed[entry.record_id]
        if entry.record_type not in kinds:
            continue
        if workspaces.get(where.conversation_id or "") != workspace_id:
            continue
        shared = len(subject & query_words(record.assertion))
        if subject and not shared:
            continue
        answers.append(
            RecordAnswer(
                entry.record_id,
                entry.record_type,
                entry.status,
                record.assertion,
                where.conversation_id,
                tuple(where.revisions),
                entry.because,
                entry.superseded_by,
                entry.conflicts_with,
                shared,
            )
        )
    answers.sort(key=lambda a: (_STATUS_ORDER[a.status], -a.shared_words, a.record_id))
    return answers


def _chat_workspaces(session: Session, conversation_ids: set[str | None]) -> dict[str, str]:
    wanted = sorted(c for c in conversation_ids if c)
    if not wanted:
        return {}
    return {
        conversation: workspace
        for conversation, workspace in session.execute(
            select(ConversationRow.conversation_id, ConversationRow.workspace_id).where(
                ConversationRow.conversation_id.in_(wanted)
            )
        )
    }


def run_plan(
    session: Session,
    question_plan: Plan,
    retriever: HybridRetriever,
    lexical: LexicalIndex,
    *,
    workspace_id: str,
    limit: int = 20,
    as_of: float | None = None,
) -> RouteResult:
    """Run a plan in one workspace. Reads only.

    Args:
        session: A read session on the archive.
        question_plan: From ``plan``.
        retriever: For the hybrid route (and the structured fallback).
        lexical: For the exact route.
        workspace_id: Only this workspace.
        limit: At most this many records or hits.
        as_of: For the structured route: the state on this source time.
    """
    route = question_plan.route
    if route is Route.EMPTY:
        return RouteResult(question_plan, route, False, (), ())
    if route is Route.STRUCTURED:
        answers = structured_answers(session, question_plan, workspace_id=workspace_id, as_of=as_of)
        if answers:
            return RouteResult(question_plan, route, False, tuple(answers[:limit]), ())
    if route is Route.EXACT:
        hits: list[HybridHit] = []
        for term in question_plan.exact_terms or (question_plan.query,):
            for hit in lexical.search(
                term, workspace_id=workspace_id, mode=SearchMode.EXACT, limit=limit
            ):
                if all(h.key != hit.node_key for h in hits):
                    hits.append(
                        HybridHit(
                            "message",
                            hit.node_key,
                            hit.conversation_id,
                            (hit.revision_id,),
                            0.0,
                            {"lexical": len(hits) + 1},
                            pinned=True,
                            native_node_id=hit.native_node_id,
                            role=hit.role,
                            snippet=hit.snippet,
                        )
                    )
        return RouteResult(question_plan, route, False, (), tuple(hits[:limit]))
    result = retriever.search(
        question_plan.query,
        workspace_id=workspace_id,
        limit=limit,
        exact_terms=question_plan.exact_terms or None,
    )
    return RouteResult(question_plan, Route.HYBRID, route is Route.STRUCTURED, (), result.hits)
