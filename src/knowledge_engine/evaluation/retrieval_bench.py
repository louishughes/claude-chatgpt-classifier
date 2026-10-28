"""A pinned retrieval benchmark: words vs meaning vs combined, and answers (RET-008).

Search quality is easy to break without noticing: a tweak that helps
reworded questions can bury exact codes. This module runs one **fixed**
benchmark and reports the same numbers every time, so a change shows up as
a change in the report and a drop below a pinned threshold fails a test.

**The benchmark** is synthetic and lives here in code: 36 short messages
in 8 chats (a shed, a cluster, bread, travel, a parser, a game, a
greenhouse, and eight near-identical "deploy error" messages as noise),
and 21 questions of five kinds:

* ``exact_code``: ``ERR-4012``, ``parse_export``, ``KE-77``;
* ``keyword``: the message's own words;
* ``paraphrase``: the same meaning in other words;
* ``misspelling``: typos;
* ``no_answer``: nothing in the chats answers it.

**Measured, per method** (``lexical`` = the word index, ``semantic`` = the
meaning index, ``hybrid`` = RET-004 with codes pinned):

* **Recall@K**: of the messages that answer a question, the share found in
  the top K (K = 1, 5, 10), averaged over the answerable questions;
* **MRR** (mean reciprocal rank): 1 / the rank of the first right message,
  averaged (0 when none is found in the top 10);
* **exact-term hit**: the share of ``exact_code`` questions whose right
  message is first;
* **cost**: texts embedded and model requests (wall time is measured but
  left out of the report, since it changes from run to run).

**Answers** (RET-007, the extractive writer): the share of answerable
questions answered with a citation of a right message, and the share of
``no_answer`` questions where it correctly says it doesn't know.

The report is plain Markdown with numbers only. The committed copy,
``docs/evaluation/RET-008_BENCHMARK.md``, must equal a fresh run; a test
checks it, and checks the ``THRESHOLDS``.

Talking points:
    - "One fixed set of questions with known answers; every change to
      search is measured against it, and the numbers must not drop."
    - "It shows the trade-off: word search nails codes, meaning search
      handles rewording, the combined search has to do both."
"""

from __future__ import annotations

import json
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.importer.run import run_import
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.infrastructure.workspace import WorkspaceRow
from knowledge_engine.retrieval.answers import MIN_SIMILARITY, answer
from knowledge_engine.retrieval.embeddings import LocalHashEmbedder
from knowledge_engine.retrieval.hybrid import RRF_K, HybridRetriever
from knowledge_engine.retrieval.lexical import LexicalIndex, search_index_path, sync_index
from knowledge_engine.retrieval.planner import codes
from knowledge_engine.retrieval.semantic import SemanticIndex, semantic_index_path, sync_semantic
from knowledge_engine.settings import EgressPolicy, Settings

BENCH_VERSION = "ret-008-v1"
METHODS = ("lexical", "semantic", "hybrid")
KS = (1, 5, 10)
KINDS = ("exact_code", "keyword", "paraphrase", "misspelling", "no_answer")

CHATS: dict[str, tuple[str, ...]] = {
    "b1": (
        "Synthetic: we painted the garden shed bright red last weekend",
        "Synthetic: red is a bold colour for a shed; use exterior paint",
        "Synthetic: the shed roof leaks when it rains heavily",
        "Synthetic: replace the roofing felt and seal the edges",
    ),
    "b2": (
        "Synthetic: the kubernetes cluster keeps restarting its pods",
        "Synthetic: check the liveness probe timeout settings",
        "Synthetic: deploy fails with ERR-4012 after the upgrade",
        "Synthetic: ERR-4012 means the image registry rejected the token",
    ),
    "b3": (
        "Synthetic: I am baking sourdough bread with a new starter",
        "Synthetic: feed the starter twice a day at room temperature",
        "Synthetic: my loaf came out dense and flat",
        "Synthetic: a dense crumb usually means underproofing",
    ),
    "b4": (
        "Synthetic: booking flights to Lisbon for the conference in May",
        "Synthetic: the hotel near the venue costs 140 euros a night",
        "Synthetic: remember to renew my passport before travelling",
        "Synthetic: passport renewals take about three weeks",
    ),
    "b5": (
        "Synthetic: parse_export crashes on empty mapping objects",
        "Synthetic: guard parse_export against a missing current_node",
        "Synthetic: the unit tests for parse_export now pass",
        "Synthetic: add a fixture with an empty conversation",
    ),
    "b6": (
        "Synthetic: I've decided to use Godot for the platformer",
        "Synthetic: Godot's tilemap editor suits pixel art levels",
        "Synthetic: the player jump feels floaty",
        "Synthetic: raise gravity while falling for a snappier jump",
    ),
    "b7": (
        "Synthetic: tomatoes in the greenhouse have yellow leaves",
        "Synthetic: yellowing lower leaves often mean a nitrogen shortage",
        "Synthetic: ticket KE-77 tracks the greenhouse sensor",
        "Synthetic: the humidity sensor reports every five minutes",
    ),
    "b8": tuple(f"Synthetic: the deploy error came back again on server {n}" for n in range(8)),
}


@dataclass(frozen=True)
class BenchQuery:
    """One question and the messages (``<chat>-m<n>``) that answer it."""

    query_id: str
    text: str
    kind: str
    relevant: tuple[str, ...]


QUERIES = (
    BenchQuery("q01", "ERR-4012", "exact_code", ("b2-m2", "b2-m3")),
    BenchQuery("q02", "parse_export", "exact_code", ("b5-m0", "b5-m1", "b5-m2")),
    BenchQuery("q03", "KE-77", "exact_code", ("b7-m2",)),
    BenchQuery("q04", "deploy error ERR-4012", "exact_code", ("b2-m2", "b2-m3")),
    BenchQuery("q05", "liveness probe", "keyword", ("b2-m1",)),
    BenchQuery("q06", "roofing felt", "keyword", ("b1-m3",)),
    BenchQuery("q07", "passport renewal", "keyword", ("b4-m2", "b4-m3")),
    BenchQuery("q08", "tilemap editor", "keyword", ("b6-m1",)),
    BenchQuery("q09", "what colour did we paint the shed", "paraphrase", ("b1-m0", "b1-m1")),
    BenchQuery("q10", "why is my bread so heavy and flat", "paraphrase", ("b3-m2", "b3-m3")),
    BenchQuery("q11", "jumping feels too floaty in my game", "paraphrase", ("b6-m2", "b6-m3")),
    BenchQuery("q12", "hotel price per night near the venue", "paraphrase", ("b4-m1",)),
    BenchQuery("q13", "tomato plants with yellowing leaves", "paraphrase", ("b7-m0", "b7-m1")),
    BenchQuery("q14", "how often should I feed my sourdough starter", "paraphrase", ("b3-m1",)),
    BenchQuery("q15", "kubernetis pods restartin", "misspelling", ("b2-m0",)),
    BenchQuery("q16", "sourdogh startr", "misspelling", ("b3-m0", "b3-m1")),
    BenchQuery("q17", "greenhose humidty sensor", "misspelling", ("b7-m2", "b7-m3")),
    BenchQuery("q18", "what is the capital of peru", "no_answer", ()),
    BenchQuery("q19", "how do I tune a violin", "no_answer", ()),
    BenchQuery("q20", "tax return deadline", "no_answer", ()),
    BenchQuery("q21", "quantum chromodynamics lecture notes", "no_answer", ()),
)

# Regression floors, pinned from the first run (ret-008-v1) a little below
# its numbers. A change that drops a metric under its floor fails the test;
# raising a floor needs a new run and the owner's say (AGENTS.md).
THRESHOLDS: dict[str, dict[str, float]] = {
    "lexical": {"exact_term_hit": 0.75},
    "semantic": {"recall@10": 0.9},
    "hybrid": {"recall@5": 0.9, "recall@10": 0.95, "mrr": 0.9, "exact_term_hit": 1.0},
    "answers": {"answered_with_right_citation": 0.8, "abstained_when_unanswerable": 1.0},
}


@dataclass(frozen=True)
class MethodScore:
    """One method's numbers over the answerable questions."""

    method: str
    recall: dict[int, float]
    mrr: float
    exact_term_hit: float
    recall5_by_kind: dict[str, float]
    ranks: dict[str, int | None]  # question -> rank of the first right message
    texts_embedded: int


@dataclass(frozen=True)
class BenchReport:
    """A benchmark run.

    Attributes:
        scores: Per method.
        answered_with_right_citation: Answerable questions answered citing a right message.
        abstained_when_unanswerable: ``no_answer`` questions answered "I don't know".
        answer_routes: Question -> (route, status), for the record.
        index_texts_embedded: Texts embedded to build the meaning index.
        model_requests: Model calls made (always 0: no model is used).
        seconds: Wall time (not in the Markdown report).
    """

    scores: dict[str, MethodScore]
    answered_with_right_citation: float
    abstained_when_unanswerable: float
    answer_routes: dict[str, tuple[str, str]]
    index_texts_embedded: int
    model_requests: int = 0
    seconds: float = field(default=0.0, compare=False)


class _Counting(LocalHashEmbedder):
    # The local embedder, counting the texts it embeds (the "cost" column).
    def __init__(self) -> None:
        super().__init__()
        self.texts = 0

    def vectors(self, texts: Sequence[str]) -> list[list[float]]:
        self.texts += len(texts)
        return super().vectors(texts)


def write_export(root: Path) -> Path:
    """Write the benchmark chats as a ChatGPT-style export folder."""
    conversations: list[dict[str, Any]] = []
    for chat, texts in CHATS.items():
        nodes: list[tuple[str, str | None]] = [(f"{chat}-root", None)]
        nodes += [(f"{chat}-m{i}", text) for i, text in enumerate(texts)]
        mapping: dict[str, Any] = {}
        for i, (node, text) in enumerate(nodes):
            mapping[node] = {
                "id": node,
                "parent": nodes[i - 1][0] if i else None,
                "children": [nodes[i + 1][0]] if i + 1 < len(nodes) else [],
                "message": None
                if text is None
                else {
                    "id": node,
                    "author": {"role": "user" if i % 2 else "assistant"},
                    "create_time": 1704067200.0 + 3600 * int(chat[1:]) + 60 * i,
                    "content": {"content_type": "text", "parts": [text]},
                    "metadata": {},
                },
            }
        conversations.append(
            {
                "id": f"bench-{chat}",
                "title": f"Synthetic bench {chat}",
                "mapping": mapping,
                "current_node": nodes[-1][0],
            }
        )
    root.mkdir(parents=True, exist_ok=True)
    (root / "conversations.json").write_text(json.dumps(conversations), encoding="utf-8")
    return root


def _score(method: str, found: dict[str, list[str]], embedded: int) -> MethodScore:
    answerable = [q for q in QUERIES if q.relevant]
    recall = {k: 0.0 for k in KS}
    reciprocal = 0.0
    ranks: dict[str, int | None] = {}
    by_kind: dict[str, list[float]] = {}
    for q in answerable:
        ranked = found[q.query_id][: max(KS)]
        right = set(q.relevant)
        for k in KS:
            recall[k] += len(right & set(ranked[:k])) / len(right)
        first = next((i for i, n in enumerate(ranked, 1) if n in right), None)
        ranks[q.query_id] = first
        reciprocal += 1 / first if first else 0.0
        by_kind.setdefault(q.kind, []).append(len(right & set(ranked[:5])) / len(right))
    codes_asked = [q for q in answerable if q.kind == "exact_code"]
    exact = sum(1 for q in codes_asked if ranks[q.query_id] == 1) / len(codes_asked)
    return MethodScore(
        method,
        {k: round(v / len(answerable), 3) for k, v in recall.items()},
        round(reciprocal / len(answerable), 3),
        round(exact, 3),
        {kind: round(sum(v) / len(v), 3) for kind, v in sorted(by_kind.items())},
        ranks,
        embedded,
    )


def run_benchmark(workdir: Path) -> BenchReport:
    """Import the benchmark into ``workdir`` (a fresh folder) and measure everything."""
    began = time.perf_counter()
    settings = Settings(workspace_root=workdir / "ws")
    run_import(write_export(workdir / "export"), "bench", format_id=None, settings=settings)
    egress = EgressPolicy()
    embedder = _Counting()
    engine = create_sqlite_engine(database_path(settings))
    try:
        with (
            Session(engine) as session,
            LexicalIndex(search_index_path(settings)) as lexical,
            SemanticIndex(semantic_index_path(settings), embedder) as semantic,
        ):
            sync_index(session, lexical)
            sync_semantic(session, semantic, egress)
            index_texts = embedder.texts
            workspace = session.scalars(select(WorkspaceRow.workspace_id)).one()
            retriever = HybridRetriever(session, lexical, semantic, egress)
            found: dict[str, dict[str, list[str]]] = {m: {} for m in METHODS}
            spent = dict.fromkeys(METHODS, 0)
            for q in QUERIES:
                limit = max(KS)
                found["lexical"][q.query_id] = [
                    h.native_node_id
                    for h in lexical.search(q.text, workspace_id=workspace, limit=limit)
                ]
                before = embedder.texts
                found["semantic"][q.query_id] = [
                    h.native_node_id
                    for h in semantic.search(
                        q.text, workspace_id=workspace, egress=egress, limit=limit
                    )
                ]
                spent["semantic"] += embedder.texts - before
                before = embedder.texts
                hits = retriever.search(
                    q.text, workspace_id=workspace, limit=limit, exact_terms=codes(q.text) or None
                ).hits
                spent["hybrid"] += embedder.texts - before
                found["hybrid"][q.query_id] = [h.native_node_id for h in hits if h.native_node_id]
            scores = {m: _score(m, found[m], spent[m]) for m in METHODS}

            routes: dict[str, tuple[str, str]] = {}
            right_answers = abstained = 0
            for q in QUERIES:
                reply = answer(session, q.text, retriever, lexical, workspace_id=workspace)
                routes[q.query_id] = (reply.route, reply.status)
                cited = {c.native_node_id for c in reply.citations}
                if q.relevant and reply.status != "unknown" and cited & set(q.relevant):
                    right_answers += 1
                if not q.relevant and reply.status == "unknown":
                    abstained += 1
    finally:
        engine.dispose()
    answerable = sum(1 for q in QUERIES if q.relevant)
    return BenchReport(
        scores,
        round(right_answers / answerable, 3),
        round(abstained / (len(QUERIES) - answerable), 3),
        routes,
        index_texts,
        seconds=time.perf_counter() - began,
    )


def check(report: BenchReport) -> list[str]:
    """The metrics below their pinned floor, as ``method.metric: value < floor``."""
    failures = []
    for method, floors in THRESHOLDS.items():
        for metric, floor in floors.items():
            if method == "answers":
                value = float(getattr(report, metric))
            else:
                score = report.scores[method]
                value = (
                    score.recall[int(metric.split("@")[1])]
                    if metric.startswith("recall@")
                    else float(getattr(score, metric))
                )
            if value < floor:
                failures.append(f"{method}.{metric}: {value} < {floor}")
    return failures


def to_markdown(report: BenchReport) -> str:
    """The report as Markdown: numbers and question IDs only, identical for identical runs."""
    lines = [
        "<!-- Generated by `ke eval retrieval` from the pinned synthetic benchmark. "
        "Numbers only; regenerate, never edit by hand. -->",
        "",
        f"# Retrieval benchmark ({BENCH_VERSION})",
        "",
        f"- Benchmark: {sum(len(t) for t in CHATS.values())} synthetic messages in "
        f"{len(CHATS)} chats; {len(QUERIES)} questions "
        + ", ".join(f"{k} {sum(1 for q in QUERIES if q.kind == k)}" for k in KINDS),
        f"- Embedder: local stems + trigrams (`ret-002-v1`); fusion: RRF, K = {RRF_K}; "
        f"answer gate: meaning-only similarity >= {MIN_SIMILARITY}",
        f"- Cost: {report.index_texts_embedded} texts embedded for the index; "
        f"{report.model_requests} model requests",
        "",
        "## Search",
        "",
        "| Method | Recall@1 | Recall@5 | Recall@10 | MRR | Exact-term hit | Query embeddings |",
        "|---|---|---|---|---|---|---|",
    ]
    for method in METHODS:
        s = report.scores[method]
        lines.append(
            f"| {method} | {s.recall[1]:.3f} | {s.recall[5]:.3f} | {s.recall[10]:.3f} | "
            f"{s.mrr:.3f} | {s.exact_term_hit:.3f} | {s.texts_embedded} |"
        )
    kinds = [k for k in KINDS if k != "no_answer"]
    lines += [
        "",
        "## Recall@5 by question kind",
        "",
        "| Method | " + " | ".join(kinds) + " |",
        "|---|" + "---|" * len(kinds),
    ]
    for method in METHODS:
        by_kind = report.scores[method].recall5_by_kind
        lines.append(f"| {method} | " + " | ".join(f"{by_kind[k]:.3f}" for k in kinds) + " |")
    lines += [
        "",
        "## Rank of the first right message (— = not in the top 10)",
        "",
        "| Question | Kind | " + " | ".join(METHODS) + " | Answer route | Answer |",
        "|---|---|" + "---|" * len(METHODS) + "---|---|",
    ]
    for q in QUERIES:
        ranks = [report.scores[m].ranks.get(q.query_id) for m in METHODS]
        cells = ["n/a" if not q.relevant else (str(r) if r else "—") for r in ranks]
        route, status = report.answer_routes[q.query_id]
        lines.append(
            f"| {q.query_id} | {q.kind} | " + " | ".join(cells) + f" | {route} | {status} |"
        )
    lines += [
        "",
        "## Answers (extractive writer)",
        "",
        f"- Answerable questions answered with a citation of a right message: "
        f"{report.answered_with_right_citation:.3f}",
        f"- Unanswerable questions where it said it doesn't know: "
        f"{report.abstained_when_unanswerable:.3f}",
        "",
        "## Regression floors",
        "",
        "| Method | Metric | Floor |",
        "|---|---|---|",
    ]
    for method, floors in THRESHOLDS.items():
        lines += [f"| {method} | {metric} | {floor} |" for metric, floor in floors.items()]
    failures = check(report)
    lines += ["", f"Result: {'PASS' if not failures else 'FAIL: ' + '; '.join(failures)}", ""]
    return "\n".join(lines)
