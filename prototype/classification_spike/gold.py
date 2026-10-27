"""A small hand-labelled "gold set" so we can measure accuracy, not just agreement.

Why
---
Two runs agreeing only proves the model is *consistent*. It can be
consistently wrong. So Louis labels 10-20 of the sampled chats himself, and
the report compares the model's labels with his.

How
---
1. ``spike.py ... --gold-template 20`` picks about 20 *varied* chats from the
   sample (short and long, with and without images or branches, spread over
   time) and writes ``gold_template.csv`` plus ``gold_instructions.txt`` into
   the private output folder. Each row shows the title, date, size and the
   start of your first message, so you can label most chats without opening
   them. Label columns are left empty on purpose: pre-filling them with the
   model's guess would nudge you towards agreeing with it.
2. Louis fills in ``primary_domain`` and ``purpose`` (keys from
   ``schema.py``), optionally ``secondary_domains`` (separated by ``;``) and
   ``projects`` (names, ``;``-separated, for eyeballing only), and saves it
   as e.g. ``gold.csv``.
3. ``spike.py ... --gold gold.csv`` adds a "vs gold" section to the report.

Talking points
--------------
- "Consistency is not correctness. I hand-labelled a small gold set to check both."
- "Twenty varied labels catch a model that is confidently wrong."
- The gold file is fingerprinted (SHA-256) in every report, so nobody,
  human or agent, can quietly edit the answers to make a run look better.
"""

from __future__ import annotations

import csv
import hashlib
import random
from datetime import datetime, timezone
from pathlib import Path

from loader import Conversation
from report import _pct, jaccard
from schema import DOMAINS, PURPOSES

CONTEXT_FIELDS = ["conversation_id", "source_file", "title", "date", "turns", "has_images",
                  "has_branches", "first_user_message"]
LABEL_FIELDS = ["primary_domain", "purpose", "secondary_domains", "projects", "notes"]
FIELDS = CONTEXT_FIELDS + LABEL_FIELDS


def _size(c: Conversation) -> str:
    return "short" if len(c.turns) <= 4 else "medium" if len(c.turns) <= 20 else "long"


def pick_diverse(convs: list[Conversation], n: int, seed: int) -> list[Conversation]:
    """Choose ``n`` chats that cover different shapes of conversation.

    Groups chats by size and by whether they have images or branches, then
    takes one from each group in turn (round robin). Within a group, chats are
    ordered by date and the walk starts at a random point, so the set is
    spread over time too. Same seed, same pick.

    Why not just random? A random 20 from a skewed history is mostly short
    chats, and the gold set would never test the long, messy ones.
    """
    groups: dict[tuple, list[Conversation]] = {}
    for c in convs:
        key = (_size(c), c.image_refs > 0, c.branch_points > 0)
        groups.setdefault(key, []).append(c)
    rng = random.Random(seed)
    queues = []
    for key in sorted(groups):
        members = sorted(groups[key], key=lambda c: (c.create_time or 0, c.conversation_id))
        start = rng.randrange(len(members))
        queues.append(members[start:] + members[:start])
    picked: list[Conversation] = []
    while len(picked) < min(n, len(convs)):
        for q in queues:
            if q and len(picked) < n:
                picked.append(q.pop(0))
    return picked


def _date(ts: float | None) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d") if ts else ""


def write_template(convs: list[Conversation], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        for c in convs:
            w.writerow({
                "conversation_id": c.conversation_id, "source_file": c.source_file, "title": c.title,
                "date": _date(c.create_time), "turns": len(c.turns),
                "has_images": "yes" if c.image_refs else "", "has_branches": "yes" if c.branch_points else "",
                "first_user_message": c.first_user_text(),
            })
    (path.parent / "gold_instructions.txt").write_text(INSTRUCTIONS, encoding="utf-8")


def fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


INSTRUCTIONS = """How to label the gold set (about 3 minutes per chat)

Open gold_template.csv in Excel or Google Sheets. For each row:
1. Read the title and first message. Open the chat in ChatGPT only if you
   can't tell what it was about.
2. primary_domain: the ONE main subject area (copy a key from the list).
3. purpose: what you were mainly trying to do (copy a key from the list).
4. Optional: secondary_domains (up to 3, separated by ;), projects (names
   of your projects it was about, separated by ;), notes.
5. Not sure? Pick your best answer and write "unsure" in notes. Leaving
   primary_domain empty skips the row.

Label it the way YOU see it. Don't try to guess what the model will say.
Save as gold.csv (CSV, UTF-8) in the same folder.

Domains:
""" + "\n".join(f"  {k}: {v}" for k, v in DOMAINS.items()) + """

Purposes:
""" + "\n".join(f"  {k}: {v}" for k, v in PURPOSES.items()) + "\n"


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
