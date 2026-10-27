"""Turn the run files into numbers: reliability, cost and consistency.

Only counts and rates go into the report. No conversation text, titles or
summaries, so the report is safe to paste into the repo or a post.

What "consistency" means here
-----------------------------
Every conversation is labelled in each run. For each pair of runs we compare:
- agreement %: same primary domain, same purpose;
- Jaccard overlap (1.0 = identical sets) for secondary domains, knowledge
  types, outputs, topics and project names. Topics and project names are free
  text compared exactly after lowercasing, so they are strict, pessimistic
  measures;
- decision count: did both runs find the same number of decisions?
Runs process chats in different orders, so agreement also tests that labels
don't depend on processing order.

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
    states: dict[str, int] = {}
    for r in ok:
        for d in r["label"]["decisions"]:
            key = f'{d["proposed_by"]}->{d["state"]}'
            states[key] = states.get(key, 0) + 1
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
        "decision_quotes_found_right_speaker_pct": _pct(dec_found, dec_total),
        "decisions_by_proposer_and_state": dict(sorted(states.items())),
        "accepted_with_only_assistant_evidence": sum(r["decisions_assistant_accepted_unquoted"] for r in rows),
        "chats_with_project_candidates": sum(1 for r in ok if r["label"]["project_candidates"]),
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

        def agree(field: str) -> float:
            return _pct(sum(x[field] == y[field] for x, y in zip(la, lb)), len(shared))

        def overlap(field: str, norm=lambda v: v) -> float:
            return round(statistics.mean(
                jaccard({norm(v) for v in x[field]}, {norm(v) for v in y[field]}) for x, y in zip(la, lb)), 3)

        out.append({
            "runs": f"{i} vs {j}",
            "compared": len(shared),
            "primary_domain_agree_pct": agree("primary_domain"),
            "purpose_agree_pct": agree("purpose"),
            "secondary_domains_jaccard": overlap("secondary_domains"),
            "knowledge_types_jaccard": overlap("knowledge_types"),
            "outputs_jaccard": overlap("outputs"),
            "topics_jaccard": overlap("topics"),
            "project_names_jaccard": overlap("project_candidates", lambda s: " ".join(s.lower().split())),
            "decision_count_same_pct": _pct(
                sum(len(x["decisions"]) == len(y["decisions"]) for x, y in zip(la, lb)), len(shared)),
            # Each run processes chats in a different shuffled order, so this
            # is also the processing-order independence check.
            "orders_differ": any(a[c]["position"] != b[c]["position"] for c in shared),
        })
    return out


def category_spread(runs: list[dict[str, dict]]) -> dict[str, dict[str, int]]:
    """How run 1 spread chats over domains and purposes (shows if one value swallows everything)."""
    spread: dict[str, dict[str, int]] = {"primary_domain": {}, "purpose": {}}
    for r in runs[0].values() if runs else []:
        if r["status"] == "ok":
            for field, counts in spread.items():
                k = r["label"][field]
                counts[k] = counts.get(k, 0) + 1
    return {f: dict(sorted(c.items(), key=lambda kv: -kv[1])) for f, c in spread.items()}


def to_markdown(meta: dict, stats: list[dict], cons: list[dict], spread: dict[str, dict[str, int]],
                gold: list[dict] | None = None, review: dict | None = None) -> str:
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
    lines += ["", "## Your verdicts on run 1 (review sheet)", ""]
    if review:
        lines += [f"- **{k}:** {v}" for k, v in review.items()]
    else:
        lines.append("No review file given yet.")
    lines += ["", "## Accuracy vs reference labels (your verdicts and corrections, or blind gold labels)", ""]
    if gold:
        keys = list(max(gold, key=len))
        lines += ["| run | " + " | ".join(keys) + " |", "|---|" + "---|" * len(keys)]
        lines += [f"| {i} | " + " | ".join(str(g.get(k, "")) for k in keys) + " |" for i, g in enumerate(gold, 1)]
    else:
        lines.append("No reference labels yet, so accuracy was not measured (only consistency).")
    lines += ["", "## Spread (run 1)", ""]
    for field, counts in spread.items():
        lines.append(f"- **{field}:** " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    return "\n".join(lines) + "\n"

