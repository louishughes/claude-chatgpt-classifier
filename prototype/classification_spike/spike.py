"""Command line entry point for the classification spike.

Typical use on the PC that holds raw/:

    # 1. See what it would cost. Makes no API calls.
    python spike.py --raw-dir ../../raw --sample 50 --out ~/spike-out --dry-run

    # 2. Two runs over 50 chats with a $5 cap, then the report.
    python spike.py --raw-dir ../../raw --sample 50 --runs 2 --out ~/spike-out --max-cost-usd 5

    # 3. Same again at 100. The 100 sample contains the 50 sample.
    python spike.py --raw-dir ../../raw --sample 100 --runs 2 --out ~/spike-out-100 --max-cost-usd 10

The output folder holds model answers about your private chats, so it must be
outside the Git repository. The script refuses to write inside it.

Talking points
--------------
- "Dry run first: know the cost before you spend it."
- "Private outputs never land in the repo by accident; the script checks."
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from loader import clip_text, sample_conversations
from providers import PRICES, AnthropicProvider, FakeProvider, FatalError
from report import category_spread, consistency, run_stats, to_markdown
from runner import CostMeter, load_records, run_once
from schema import SYSTEM_PROMPT, TAXONOMY_VERSION

# Rough output size per call, including the model's thinking. Only used for
# the dry-run estimate; the real run uses the API's exact token counts.
EST_OUTPUT_TOKENS = 1500


def inside_git_repo(path: Path) -> bool:
    for parent in [path, *path.parents]:
        if (parent / ".git").exists():
            return True
    return False


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Throwaway spike: is the AI labelling step consistent?")
    p.add_argument("--raw-dir", type=Path, required=True, help="raw/ folder (read-only)")
    p.add_argument("--out", type=Path, required=True, help="output folder, outside the repo")
    p.add_argument("--sample", type=int, default=50)
    p.add_argument("--seed", type=int, default=20261027)
    p.add_argument("--runs", type=int, default=2)
    p.add_argument("--provider", choices=["anthropic", "fake"], default="anthropic")
    p.add_argument("--model", default="claude-opus-5-5", choices=[m for m in PRICES if m != "fake"])
    p.add_argument("--effort", choices=["low", "medium", "high"], default="low")
    p.add_argument("--max-cost-usd", type=float, default=5.0)
    p.add_argument("--budget-chars", type=int, default=24000, help="max characters sent per chat")
    p.add_argument("--max-tokens", type=int, default=8000)
    p.add_argument("--timeout-s", type=float, default=90.0)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--no-refusal-fallback", action="store_true")
    p.add_argument("--dry-run", action="store_true", help="estimate cost, make no calls")
    p.add_argument("--allow-out-in-repo", action="store_true", help="tests only")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    out = args.out.expanduser().resolve()
    if inside_git_repo(out) and not args.allow_out_in_repo:
        print(f"Refusing: {out} is inside a Git repository. Choose a private folder.", file=sys.stderr)
        return 2
    convs, skipped = sample_conversations(args.raw_dir.expanduser(), args.sample, args.seed)
    print(f"Sampled {len(convs)} conversations (skipped: {skipped})")
    if not convs:
        return 1

    model = "fake" if args.provider == "fake" else args.model
    sent_chars = sum(len(clip_text(c.full_text(), args.budget_chars)[0]) for c in convs)
    est_in = (sent_chars + len(SYSTEM_PROMPT)) // 4 + 50 * len(convs)
    est_out = EST_OUTPUT_TOKENS * len(convs)
    price_in, price_out = PRICES[model]
    est_cost = (est_in * price_in + est_out * price_out) / 1_000_000
    print(f"Estimate per run: ~{est_in:,} input + ~{est_out:,} output tokens = ~${est_cost:.2f} "
          f"({model}); x{args.runs} runs = ~${est_cost * args.runs:.2f}. Cap: ${args.max_cost_usd:.2f}")
    if args.dry_run:
        return 0

    out.mkdir(parents=True, exist_ok=True)
    (out / "sample.json").write_text(json.dumps(
        {"seed": args.seed, "size": len(convs), "files": [c.source_file for c in convs]}, indent=1))

    if args.provider == "fake":
        provider = FakeProvider()
    else:
        provider = AnthropicProvider(args.model, args.effort, args.timeout_s, args.max_tokens,
                                     refusal_fallback=not args.no_refusal_fallback)

    # Spend already recorded in this folder counts towards the cap, so
    # resuming can't quietly double the budget.
    previous = sum(r["cost_usd"] for i in range(1, args.runs + 1)
                   for r in load_records(out / f"run-{i}.jsonl").values())
    meter = CostMeter(args.max_cost_usd, already_spent=previous)
    runs = []
    try:
        for i in range(1, args.runs + 1):
            print(f"Run {i}/{args.runs}")
            runs.append(run_once(convs, provider, out / f"run-{i}.jsonl", meter,
                                 args.budget_chars, workers=args.workers))
    except FatalError as exc:
        print(f"Stopped: {exc}", file=sys.stderr)
        return 3

    stats = [run_stats(r) for r in runs]
    cons = consistency(runs)
    meta = {
        "date_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "model": model, "effort": args.effort, "taxonomy": TAXONOMY_VERSION,
        "sample": len(convs), "seed": args.seed, "runs": args.runs, "workers": args.workers,
        "budget_chars": args.budget_chars, "timeout_s": args.timeout_s,
        "total_cost_usd": round(meter.spent, 4),
    }
    (out / "report.json").write_text(json.dumps(
        {"meta": meta, "runs": stats, "consistency": cons, "spread": category_spread(runs)}, indent=1))
    (out / "report.md").write_text(to_markdown(meta, stats, cons, category_spread(runs)))
    print(f"Report: {out / 'report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
