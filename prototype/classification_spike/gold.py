"""A small hand-labelled "gold set" so we can measure accuracy, not just agreement.

Why
---
Two runs agreeing only proves the model is *consistent*. It can be
consistently wrong. So Louis labels 10-20 of the sampled chats himself, and
the report compares the model's labels with his.

How
---
1. ``spike.py ... --gold-template 15`` writes ``gold_template.csv`` into the
   private output folder: id, file name, title, and empty label columns.
2. Louis fills in ``primary_category`` (and optionally
   ``secondary_categories``, separated by ``;``) using the category keys from
   ``schema.py``, and saves it as e.g. ``gold.csv``.
3. ``spike.py ... --gold gold.csv`` adds a "vs gold" section to the report.

Talking points
--------------
- "Consistency is not correctness. I hand-labelled a small gold set to check both."
- Fifteen labels is enough to catch a model that is confidently wrong.
"""

from __future__ import annotations

import csv
from pathlib import Path

from loader import Conversation
from report import _pct, jaccard
from schema import CATEGORIES

FIELDS = ["conversation_id", "source_file", "title", "primary_category", "secondary_categories", "notes"]


def write_template(convs: list[Conversation], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        for c in convs:
            w.writerow({"conversation_id": c.conversation_id, "source_file": c.source_file, "title": c.title})


def load_gold(path: Path) -> dict[str, dict]:
    """Read a filled-in template. Rows without a primary category are ignored.

    Unknown category keys raise an error straight away, so a typo can't
    silently count as the model being wrong.
    """
    gold: dict[str, dict] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            primary = (row.get("primary_category") or "").strip()
            if not primary:
                continue
            secondary = [s.strip() for s in (row.get("secondary_categories") or "").split(";") if s.strip()]
            for key in [primary, *secondary]:
                if key not in CATEGORIES:
                    raise ValueError(f"unknown category {key!r} for {row['conversation_id']}")
            gold[row["conversation_id"]] = {"primary": primary, "secondary": set(secondary)}
    return gold


def gold_stats(records: dict[str, dict], gold: dict[str, dict]) -> dict:
    """Compare one run with the gold labels."""
    scored = [(records[cid], g) for cid, g in gold.items()
              if cid in records and records[cid]["status"] == "ok"]
    if not scored:
        return {"gold_labelled": len(gold), "scored": 0}
    hits = sum(r["label"]["primary_category"] == g["primary"] for r, g in scored)
    # "Lenient" counts the model as right if your primary appears anywhere in
    # its primary or secondary categories: useful when a chat honestly spans two.
    lenient = sum(g["primary"] in {r["label"]["primary_category"], *r["label"]["secondary_categories"]}
                  for r, g in scored)
    return {
        "gold_labelled": len(gold),
        "scored": len(scored),
        "primary_accuracy_pct": _pct(hits, len(scored)),
        "primary_in_any_pct": _pct(lenient, len(scored)),
        "secondary_jaccard": round(sum(
            jaccard(set(r["label"]["secondary_categories"]), g["secondary"]) for r, g in scored) / len(scored), 3),
    }
