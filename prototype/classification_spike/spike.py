"""Command line entry point for the classification spike.

Everything stays inside the project folder. By default the script reads
``<project>/raw`` and writes to ``<project>/private/spike-out``, a folder Git
ignores, so private outputs can't be committed by accident. Run from
``prototype/classification_spike``:

    # 1. See what it would cost. Makes no API calls.
    python spike.py --sample 50 --dry-run

    # 2. Two runs over 50 chats. Also writes review_sheet.csv: ~20 varied
    #    chats with the model's answers for you to mark y/n (~20 minutes).
    python spike.py --sample 50 --runs 2

    # 3. Save your marked sheet as review.csv and re-run: finished chats are
    #    skipped (no new cost) and the report adds accuracy by your verdicts.
    python spike.py --sample 50 --runs 2 --review ../../private/spike-out/review.csv

    # 4. Same again at 100, in its own folder. The 100 sample contains the 50.
    python spike.py --sample 100 --runs 2 --out ../../private/spike-out-100 --review ../../private/spike-out/review.csv

    # Alternative to review mode: label chats blind yourself (--gold-template, --gold; see gold.py).

The output folder holds model answers about your private chats. The script
refuses to write anywhere inside a Git repository unless Git ignores that
path.

Talking points
--------------
- "Dry run first: know the cost before you spend it."
- "Private outputs never land in the repo by accident; the script asks Git."
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from discovery import discover_one, load_answer_key, run_checks, score_run
from discovery import to_markdown as discovery_markdown
from gold import fingerprint, gold_stats, load_gold, pick_diverse, write_template
from review import load_review, write_review_sheet
from loader import clip_text, sample_conversations
from providers import PRICES, AnthropicProvider, FakeProvider, FatalError
from report import category_spread, consistency, run_stats, to_markdown
from runner import CostMeter, load_records, run_once
from schema import DECISIONS_PROMPT, DISCOVERY_PROMPT, DISCOVERY_VERSION, SYSTEM_PROMPT, TAXONOMY_VERSION

# Rough output size per call, including the model's thinking. Only used for
# the dry-run estimate; the real run uses the API's exact token counts.
EST_OUTPUT_TOKENS = 1500


# prototype/classification_spike/spike.py -> the project root is two folders up.
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def git_root(path: Path) -> Path | None:
    for parent in [path, *path.parents]:
        if (parent / ".git").exists():
            return parent
    return None


def safe_output_dir(path: Path) -> bool:
    """True if ``path`` is outside any Git repo, or inside one but ignored by Git.

    We ask Git itself (``git check-ignore``) rather than reading .gitignore
    ourselves, so the answer matches what ``git add`` would really do. If Git
    isn't installed we can't check, so we refuse.
    """
    root = git_root(path)
    if root is None:
        return True
    try:
        result = subprocess.run(["git", "-C", str(root), "check-ignore", "-q", str(path)],
                                capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Throwaway spike: is the AI labelling step consistent?")
    p.add_argument("--raw-dir", type=Path, default=PROJECT_ROOT / "raw", help="raw/ folder (read-only)")
    p.add_argument("--out", type=Path, default=PROJECT_ROOT / "private" / "spike-out",
                   help="output folder; must be outside Git or ignored by it")
    p.add_argument("--sample", type=int, default=50)
    p.add_argument("--seed", type=int, default=20261027)
    p.add_argument("--runs", type=int, default=2)
    p.add_argument("--provider", choices=["anthropic", "fake"], default="anthropic")
    p.add_argument("--model", default="claude-haiku-5-5", choices=[m for m in PRICES if m != "fake"])
    p.add_argument("--effort", choices=["low", "medium", "high"], default="low")
    p.add_argument("--decisions-model", choices=[m for m in PRICES if m != "fake"],
                   help="model for the separate decisions step (default: same as --model)")
    p.add_argument("--decisions-effort", choices=["low", "medium", "high"], default="medium",
                   help="decisions need more care than labels, so default one level higher")
    p.add_argument("--max-cost-usd", type=float, default=2.0)
    # Run 1 clipped 12 of 50 chats at 24k characters, and clipped chats were
    # wrong far more often. Haiku 5.5 reads 1M tokens, so send nearly everything:
    # 200k characters is ~65k tokens, under $0.01 per chat on Haiku.
    p.add_argument("--budget-chars", type=int, default=200_000, help="max characters sent per chat")
    p.add_argument("--max-tokens", type=int, default=8000)
    p.add_argument("--timeout-s", type=float, default=90.0)
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--no-refusal-fallback", action="store_true")
    p.add_argument("--gold-template", type=int, metavar="N",
                   help="pick N varied sampled chats, write a labelling sheet, then stop")
    p.add_argument("--gold", type=Path, help="filled-in gold CSV: adds accuracy to the report")
    p.add_argument("--review", type=Path, help="review.csv with your y/n verdicts: adds accuracy to the report")
    p.add_argument("--reviewer", default="owner", help="who made the verdicts in --review (shown in the report)")
    p.add_argument("--review-size", type=int, default=20, help="chats in the review sheet")
    p.add_argument("--dry-run", action="store_true", help="estimate cost, make no calls")
    p.add_argument("--mode", choices=["label", "discover"], default="label",
                   help="label: spike 0.3 per-chat labels; discover: spike v3 step 2 (segments + typed items)")
    p.add_argument("--answer-key", type=Path, default=PROJECT_ROOT / "private" / "answer-key",
                   help="folder of answer-key JSON files (discover mode scores against it if present)")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    out = args.out.expanduser().resolve()
    if not safe_output_dir(out):
        print(f"Refusing: {out} is inside a Git repository and not ignored by it. "
              f"Use the default private/ folder or add the path to .gitignore.", file=sys.stderr)
        return 2
    convs, skipped = sample_conversations(args.raw_dir.expanduser(), args.sample, args.seed)
    print(f"Sampled {len(convs)} conversations (skipped: {skipped})")
    if not convs:
        return 1
    if args.mode == "discover":
        return run_discovery(args, out, convs)

    if args.gold_template:
        out.mkdir(parents=True, exist_ok=True)
        write_template(pick_diverse(convs, args.gold_template, args.seed), out / "gold_template.csv")
        print(f"Wrote {out / 'gold_template.csv'} and gold_instructions.txt. Fill it in, save as gold.csv.")
        return 0
    gold = load_gold(args.gold.expanduser()) if args.gold else {}
    review_stats: dict = {}
    if args.review:
        # Your verdicts double as reference labels for scoring every run.
        review_stats, reference = load_review(args.review.expanduser())
        gold = {**reference, **gold}  # blind gold labels win where both exist

    model = "fake" if args.provider == "fake" else args.model
    d_model = "fake" if args.provider == "fake" else (args.decisions_model or args.model)
    sent_chars = sum(len(clip_text(c.full_text(), args.budget_chars)[0]) for c in convs)

    def estimate(prompt: str, price_model: str) -> tuple[int, int, float]:
        # ~4 characters per token, plus ~30% because newer Claude tokenizers
        # count the same text as more tokens. Deliberately pessimistic.
        tin = int((sent_chars + len(prompt) * len(convs)) / 4 * 1.3)
        tout = EST_OUTPUT_TOKENS * len(convs)
        pin, pout = PRICES[price_model]
        return tin, tout, (tin * pin + tout * pout) / 1_000_000

    # Two calls per chat: labels, then decisions (possibly a different model).
    li, lo, lc = estimate(SYSTEM_PROMPT, model)
    di, do, dc = estimate(DECISIONS_PROMPT, d_model)
    est_cost = lc + dc
    print(f"Estimate per run: labels ~{li:,} in + ~{lo:,} out ({model}) ${lc:.2f}; "
          f"decisions ~{di:,} in + ~{do:,} out ({d_model}) ${dc:.2f}; "
          f"total ~${est_cost:.2f} x{args.runs} runs = ~${est_cost * args.runs:.2f}. Cap: ${args.max_cost_usd:.2f}")
    if args.dry_run:
        return 0

    out.mkdir(parents=True, exist_ok=True)
    (out / "sample.json").write_text(json.dumps(
        {"seed": args.seed, "size": len(convs), "files": [c.source_file for c in convs]}, indent=1))

    if args.provider == "fake":
        provider = decisions_provider = FakeProvider()
    else:
        # Haiku 5.5 has no server-side refusal fallback; asking for one is an error.
        fallback = not args.no_refusal_fallback and not args.model.startswith("claude-haiku")
        provider = AnthropicProvider(args.model, args.effort, args.timeout_s, args.max_tokens,
                                     refusal_fallback=fallback)
        decisions_provider = AnthropicProvider(
            d_model, args.decisions_effort, args.timeout_s, args.max_tokens,
            refusal_fallback=not args.no_refusal_fallback and not d_model.startswith("claude-haiku"))

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
                                 args.budget_chars, workers=args.workers,
                                 order_seed=args.seed + i, decisions_provider=decisions_provider))
    except FatalError as exc:
        print(f"Stopped: {exc}", file=sys.stderr)
        return 3

    stats = [run_stats(r) for r in runs]
    cons = consistency(runs)
    meta = {
        "date_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "model": model, "effort": args.effort,
        "decisions_model": d_model,
        "decisions_effort": args.decisions_effort, "taxonomy": TAXONOMY_VERSION,
        "sample": len(convs), "seed": args.seed, "runs": args.runs, "workers": args.workers,
        "budget_chars": args.budget_chars, "timeout_s": args.timeout_s,
        "total_cost_usd": round(meter.spent, 4),
        # Fingerprint of the answer key, so any later edit to it is visible.
        "gold_file_sha256": fingerprint(args.gold.expanduser()) if args.gold else "none",
        "reviewer": args.reviewer if args.review else "none",
        "review_file_sha256": fingerprint(args.review.expanduser()) if args.review else "none",
        "reference_labels": len(gold),
    }
    vs_gold = [gold_stats(r, gold) for r in runs] if gold else []
    (out / "report.json").write_text(json.dumps(
        {"meta": meta, "runs": stats, "consistency": cons, "review": review_stats, "gold": vs_gold,
         "spread": category_spread(runs)}, indent=1))
    (out / "report.md").write_text(to_markdown(meta, stats, cons, category_spread(runs), vs_gold, review_stats))
    sheet = write_review_sheet(convs, runs[0], args.review_size, args.seed, out)
    if sheet:
        print(f"Review sheet: {sheet} (mark y/n, save as review.csv in the same folder)")
    print(f"Report: {out / 'report.md'}")
    return 0


def run_discovery(args: argparse.Namespace, out: Path, convs: list) -> int:
    """Spike v3 step 2: discover segments and typed items, check them, score them."""
    model = "fake" if args.provider == "fake" else args.model
    sent = sum(len(clip_text(c.full_text(), args.budget_chars)[0]) for c in convs)
    tin = int((sent + len(DISCOVERY_PROMPT) * len(convs)) / 4 * 1.3)
    tout = 4000 * len(convs)  # sections + up to 60 items + thinking, pessimistic
    pin, pout = PRICES[model]
    est = (tin * pin + tout * pout) / 1_000_000
    clipped = sum(1 for c in convs if clip_text(c.full_text(), args.budget_chars)[1])
    print(f"Discovery estimate per run: ~{tin:,} in + ~{tout:,} out ({model}) = ~${est:.2f}; "
          f"x{args.runs} = ~${est * args.runs:.2f}. Chats clipped at {args.budget_chars:,} chars: {clipped}. "
          f"Cap: ${args.max_cost_usd:.2f}")
    if args.dry_run:
        return 0
    out.mkdir(parents=True, exist_ok=True)
    if args.provider == "fake":
        provider = FakeProvider()
    else:
        provider = AnthropicProvider(args.model, args.decisions_effort, args.timeout_s, max(args.max_tokens, 16000),
                                     refusal_fallback=not args.no_refusal_fallback
                                     and not args.model.startswith("claude-haiku"))
    previous = sum(r["cost_usd"] for i in range(1, args.runs + 1)
                   for r in load_records(out / f"discover-{i}.jsonl").values())
    meter = CostMeter(args.max_cost_usd, already_spent=previous)
    one = lambda conv: discover_one(conv, provider, meter, args.budget_chars)
    runs = []
    try:
        for i in range(1, args.runs + 1):
            print(f"Discovery run {i}/{args.runs}")
            runs.append(run_once(convs, provider, out / f"discover-{i}.jsonl", meter, args.budget_chars,
                                 workers=args.workers, order_seed=args.seed + i, one=one))
    except FatalError as exc:
        print(f"Stopped: {exc}", file=sys.stderr)
        return 3
    by_id = {c.conversation_id: c for c in convs}
    key = load_answer_key(args.answer_key.expanduser()) if args.answer_key.expanduser().is_dir() else {}
    vs_key = []
    for r in runs:
        scored = score_run(r, key, by_id) if key else {}
        if key:
            # Split by whether the chat was cut to fit: earlier runs did worse on clipped chats.
            scored["clipped_only"] = score_run({k: v for k, v in r.items() if v["clipped"]}, key, by_id)
            scored["unclipped_only"] = score_run({k: v for k, v in r.items() if not v["clipped"]}, key, by_id)
            vs_key.append(scored)
    cons = None
    if len(runs) > 1:
        ref = {cid: rec["label"] for cid, rec in runs[0].items() if rec["status"] == "ok"}
        cons = score_run(runs[1], ref, by_id)
    meta = {
        "date_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M"),
        "model": model, "effort": args.decisions_effort, "version": DISCOVERY_VERSION,
        "sample": len(convs), "seed": args.seed, "runs": args.runs, "budget_chars": args.budget_chars,
        "answer_key_chats": len(key),
        # The key is written by Claude and approved by the owner; until approved,
        # treat accuracy as provisional.
        "answer_key_sha256": _folder_fingerprint(args.answer_key.expanduser()) if key else "none",
        "total_cost_usd": round(meter.spent, 4),
    }
    checks = [run_checks(r) for r in runs]
    (out / "discovery_report.json").write_text(json.dumps(
        {"meta": meta, "runs": checks, "vs_answer_key": vs_key, "consistency": cons}, indent=1))
    (out / "discovery_report.md").write_text(discovery_markdown(meta, checks, vs_key, cons))
    print(f"Report: {out / 'discovery_report.md'}")
    return 0


def _folder_fingerprint(folder: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    for p in sorted(folder.glob("*.json")):
        h.update(p.name.encode())
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


if __name__ == "__main__":
    sys.exit(main())
