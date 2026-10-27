"""Turn the run files into numbers: reliability, cost and consistency.

Only counts and rates go into the report. No conversation text, titles or
summaries, so the report is safe to paste into the repo or a post.

What "consistency" means here
-----------------------------
Every conversation is labelled in each run. For each pair of runs we compare:
- primary agreement: % of chats given the same primary category;
- secondary Jaccard: overlap of the secondary category sets (1.0 = identical);
- topic Jaccard: overlap of the topic phrases (exact match after lowercasing,
  so this is a strict, pessimistic measure).

Talking points
--------------
- "Run the same 50 chats twice. If the labels move, the system isn't ready."
- Measure before tuning: the numbers decide the model and prompt, not vibes.
"""

from __future__ import annotations

import statistics
from itertools import combinations


def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def _pct(n: int, d: int) -> float:
    return round(100 * n / d, 1) if d else 0.0


def run_stats(records: dict[str, dict]) -> dict:
    rows = list(records.values())
    n = len(rows)
    by_status: dict[str, int] = {}
    transient: dict[str, int] = {}
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
        for k, v in r["transient_errors"].items():
            transient[k] = transient.get(k, 0) + v
    ok = [r for r in rows if r["status"] == "ok"]
    lat = sorted(r["latency_s"] for r in ok)
    dec_total = sum(r["decisions_total"] for r in rows)
    dec_found = sum(r["decisions_quote_found"] for r in rows)
    return {
        "conversations": n,
        "status_counts": by_status,
        "ok_pct": _pct(len(ok), n),
        "first_try_schema_failures": sum(1 for r in rows if r["schema_failures"] > 0),
        "repaired_ok": sum(1 for r in ok if r["repaired"]),
        "transient_errors": transient,
        "calls_total": sum(r["calls"] for r in rows),
        "clipped_inputs": sum(1 for r in rows if r["clipped"]),
        "latency_p50_s": round(statistics.median(lat), 1) if lat else None,
        "latency_p95_s": round(lat[min(len(lat) - 1, int(0.95 * len(lat)))], 1) if lat else None,
        "input_tokens": sum(r["input_tokens"] for r in rows),
        "output_tokens": sum(r["output_tokens"] for r in rows),
        "cost_usd": round(sum(r["cost_usd"] for r in rows), 4),
        "served_models": sorted({r["served_model"] for r in ok}),
        "decisions": dec_total,
        "decision_quotes_found_pct": _pct(dec_found, dec_total),
        "mean_confidence": round(statistics.mean(r["label"]["confidence"] for r in ok), 3) if ok else None,
    }


def consistency(runs: list[dict[str, dict]]) -> list[dict]:
    out = []
    for (i, a), (j, b) in combinations(enumerate(runs, start=1), 2):
        shared = [
            cid for cid in a
            if cid in b and a[cid]["status"] == "ok" and b[cid]["status"] == "ok"
        ]
        if not shared:
            out.append({"runs": f"{i} vs {j}", "compared": 0})
            continue
        la = [a[c]["label"] for c in shared]
        lb = [b[c]["label"] for c in shared]
        same = sum(x["primary_category"] == y["primary_category"] for x, y in zip(la, lb))
        out.append({
            "runs": f"{i} vs {j}",
            "compared": len(shared),
            "primary_agreement_pct": _pct(same, len(shared)),
            "secondary_jaccard": round(statistics.mean(
                jaccard(set(x["secondary_categories"]), set(y["secondary_categories"])) for x, y in zip(la, lb)), 3),
            "topic_jaccard": round(statistics.mean(
                jaccard(set(x["topics"]), set(y["topics"])) for x, y in zip(la, lb)), 3),
            "decision_count_same_pct": _pct(
                sum(len(x["user_decisions"]) == len(y["user_decisions"]) for x, y in zip(la, lb)), len(shared)),
        })
    return out


def category_spread(runs: list[dict[str, dict]]) -> dict[str, int]:
    """How many chats got each primary category in run 1 (shows if one category swallows everything)."""
    spread: dict[str, int] = {}
    for r in runs[0].values() if runs else []:
        if r["status"] == "ok":
            k = r["label"]["primary_category"]
            spread[k] = spread.get(k, 0) + 1
    return dict(sorted(spread.items(), key=lambda kv: -kv[1]))


def to_markdown(meta: dict, stats: list[dict], cons: list[dict], spread: dict[str, int],
                gold: list[dict] | None = None) -> str:
    lines = ["# Classification spike report", ""]
    lines += [f"- **{k}:** {v}" for k, v in meta.items()]
    lines += ["", "## Per run", "", "| metric | " + " | ".join(f"run {i}" for i in range(1, len(stats) + 1)) + " |",
              "|---|" + "---|" * len(stats)]
    for key in stats[0] if stats else []:
        lines.append(f"| {key} | " + " | ".join(str(s[key]) for s in stats) + " |")
    lines += ["", "## Run-to-run consistency", ""]
    if cons:
        keys = list(max(cons, key=len))
        lines += ["| " + " | ".join(keys) + " |", "|" + "---|" * len(keys)]
        lines += ["| " + " | ".join(str(c.get(k, "")) for k in keys) + " |" for c in cons]
    else:
        lines.append("Only one run, so nothing to compare.")
    lines += ["", "## Accuracy vs your hand labels (gold set)", ""]
    if gold:
        keys = list(max(gold, key=len))
        lines += ["| run | " + " | ".join(keys) + " |", "|---|" + "---|" * len(keys)]
        lines += [f"| {i} | " + " | ".join(str(g.get(k, "")) for k in keys) + " |" for i, g in enumerate(gold, 1)]
    else:
        lines.append("No gold file given, so accuracy was not measured (only consistency).")
    lines += ["", "## Primary category spread (run 1)", ""]
    lines += [f"- {k}: {v}" for k, v in spread.items()]
    return "\n".join(lines) + "\n"

