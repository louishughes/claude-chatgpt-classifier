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
2. Louis fills in ``primary_domain`` and ``purpose`` (keys from
   ``schema.py``), optionally ``secondary_domains`` (separated by ``;``) and
   ``projects`` (names, ``;``-separated, for eyeballing only), and saves it
   as e.g. ``gold.csv``.
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
from schema import DOMAINS, PURPOSES

FIELDS = ["conversation_id", "source_file", "title", "primary_domain", "purpose",
          "secondary_domains", "projects", "notes"]


def write_template(convs: list[Conversation], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        for c in convs:
            w.writerow({"conversation_id": c.conversation_id, "source_file": c.source_file, "title": c.title})


def _split(cell: str | None) -> list[str]:
    return [s.strip() for s in (cell or "").split(";") if s.strip()]


def load_gold(path: Path) -> dict[str, dict]:
    """Read a filled-in template. Rows without a primary domain are ignored.

    Unknown keys raise an error straight away, so a typo can't silently count
    as the model being wrong.
    """
    gold: dict[str, dict] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            cid = row["conversation_id"]
            primary = (row.get("primary_domain") or "").strip()
            if not primary:
                continue
            purpose = (row.get("purpose") or "").strip()
            secondary = _split(row.get("secondary_domains"))
            for key in [primary, *secondary]:
                if key not in DOMAINS:
                    raise ValueError(f"unknown domain {key!r} for {cid}")
            if purpose and purpose not in PURPOSES:
                raise ValueError(f"unknown purpose {purpose!r} for {cid}")
            gold[cid] = {"primary": primary, "secondary": set(secondary), "purpose": purpose}
    return gold


def gold_stats(records: dict[str, dict], gold: dict[str, dict]) -> dict:
    """Compare one run with the gold labels."""
    scored = [(records[cid]["label"], g) for cid, g in gold.items()
              if cid in records and records[cid]["status"] == "ok"]
    if not scored:
        return {"gold_labelled": len(gold), "scored": 0}
    hits = sum(m["primary_domain"] == g["primary"] for m, g in scored)
    # "In any" counts the model as right if your primary domain appears in its
    # primary or secondary domains: useful when a chat honestly spans two.
    anywhere = sum(g["primary"] in {m["primary_domain"], *m["secondary_domains"]} for m, g in scored)
    with_purpose = [(m, g) for m, g in scored if g["purpose"]]
    return {
        "gold_labelled": len(gold),
        "scored": len(scored),
        "primary_domain_accuracy_pct": _pct(hits, len(scored)),
        "primary_domain_in_any_pct": _pct(anywhere, len(scored)),
        "purpose_accuracy_pct": _pct(sum(m["purpose"] == g["purpose"] for m, g in with_purpose), len(with_purpose)),
        "secondary_domains_jaccard": round(sum(
            jaccard(set(m["secondary_domains"]), g["secondary"]) for m, g in scored) / len(scored), 3),
    }
