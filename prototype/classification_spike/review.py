"""Evaluator mode: the model labels first, Louis marks each answer right or wrong.

Why this exists
---------------
Louis is the evaluator, not the labeller. So instead of a blank sheet, the
spike writes ``review_sheet.csv`` for ~20 varied chats after run 1. Each row
shows what the chat was (title, date, first message) and what the model said
(domain, purpose, projects, summary, decisions). Louis types ``y`` or ``n``
in the verdict columns, and can write the right answer when it's ``n``.

The report then shows how often the model was right, according to Louis.
Where he gave the right answer, that becomes a reference label, so later
runs (and other models) are scored against it too.

Known weakness, stated honestly
-------------------------------
Seeing the model's answer first makes a reviewer more likely to agree with
it ("anchoring"). Three things limit that: the sheet asks for a plain y/n
per field, not a general impression; the summary and first message are
shown so a wrong label is easy to spot; and the instructions say "mark n if
you'd have picked something else", not "if it's unreasonable".

Talking points
--------------
- "I'm the evaluator. The model does the work; I mark it."
- "Every verdict is mine, fingerprinted, and never edited by an agent."
"""

from __future__ import annotations

import csv
from pathlib import Path

from gold import _date, pick_diverse
from loader import Conversation
from report import _pct
from schema import DOMAINS, PURPOSES

CONTEXT = ["conversation_id", "title", "date", "turns", "first_user_message"]
MODEL = ["model_primary_domain", "model_secondary_domains", "model_purpose", "model_projects",
         "model_summary", "model_decisions"]
VERDICTS = ["domain_ok", "purpose_ok", "decisions_ok", "right_domain", "right_purpose", "notes"]
FIELDS = CONTEXT + MODEL + VERDICTS

INSTRUCTIONS = """How to review (about 1 minute per chat, ~20 minutes total)

Open review_sheet.csv in Excel or Google Sheets. For each row, read the title,
first message and the model's summary, then fill in:

  domain_ok     y or n. Mark n if YOU would have picked a different main subject.
  purpose_ok    y or n. Mark n if you were mainly trying to do something else.
  decisions_ok  y, n, or na if there are none. Mark n if any listed decision is
                wrong: something you never agreed to marked "accepted", a
                rejected idea marked "accepted", or it's the wrong speaker.
  right_domain / right_purpose   optional: when you marked n, the right key
                from the lists below. These become reference answers.
  notes         anything else.

Leave a verdict blank to skip it. Save as review.csv in the same folder.

Domains:
""" + "\n".join(f"  {k}: {v}" for k, v in DOMAINS.items()) + """

Purposes:
""" + "\n".join(f"  {k}: {v}" for k, v in PURPOSES.items()) + "\n"


def _decisions_text(label: dict) -> str:
    return " | ".join(f'{d["proposed_by"]} proposed, {d["state"]}: {d["statement"]}' for d in label["decisions"])


def write_review_sheet(convs: list[Conversation], run1: dict[str, dict], n: int, seed: int, out: Path) -> Path | None:
    """Write the sheet for ``n`` varied chats that run 1 labelled successfully.

    Never overwrites an existing sheet, because it may already hold verdicts.
    """
    path = out / "review_sheet.csv"
    if path.exists():
        return None
    labelled = [c for c in convs if run1.get(c.conversation_id, {}).get("status") == "ok"]
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDS)
        w.writeheader()
        for c in pick_diverse(labelled, n, seed):
            label = run1[c.conversation_id]["label"]
            w.writerow({
                "conversation_id": c.conversation_id, "title": c.title, "date": _date(c.create_time),
                "turns": len(c.turns), "first_user_message": c.first_user_text(),
                "model_primary_domain": label["primary_domain"],
                "model_secondary_domains": "; ".join(label["secondary_domains"]),
                "model_purpose": label["purpose"],
                "model_projects": "; ".join(label["project_candidates"]),
                "model_summary": label["summary"],
                "model_decisions": _decisions_text(label),
            })
    (out / "review_instructions.txt").write_text(INSTRUCTIONS, encoding="utf-8")
    return path


def _yn(cell: str | None) -> bool | None:
    v = (cell or "").strip().lower()
    if v in {"y", "yes"}:
        return True
    if v in {"n", "no"}:
        return False
    return None


def load_review(path: Path) -> tuple[dict, dict[str, dict]]:
    """Read Louis's verdicts.

    Returns (verdict stats, reference labels). A reference label exists for a
    chat when the model's answer was marked right, or when it was marked wrong
    and the right answer was given. Unknown keys raise an error, so a typo
    can't silently count against the model.
    """
    counts = {"domain": [0, 0], "purpose": [0, 0], "decisions": [0, 0]}  # [right, judged]
    reference: dict[str, dict] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            cid = row["conversation_id"]
            verdicts = {"domain": _yn(row.get("domain_ok")), "purpose": _yn(row.get("purpose_ok")),
                        "decisions": _yn(row.get("decisions_ok"))}
            for field, ok in verdicts.items():
                if ok is not None:
                    counts[field][1] += 1
                    counts[field][0] += ok
            right_domain = (row.get("right_domain") or "").strip()
            right_purpose = (row.get("right_purpose") or "").strip()
            if right_domain and right_domain not in DOMAINS:
                raise ValueError(f"unknown domain {right_domain!r} for {cid}")
            if right_purpose and right_purpose not in PURPOSES:
                raise ValueError(f"unknown purpose {right_purpose!r} for {cid}")
            domain = row["model_primary_domain"] if verdicts["domain"] else right_domain if verdicts["domain"] is False else ""
            purpose = row["model_purpose"] if verdicts["purpose"] else right_purpose if verdicts["purpose"] is False else ""
            if domain:
                reference[cid] = {"primary": domain, "secondary": set(), "purpose": purpose}
    stats = {f"{field}_correct_pct": _pct(r, j) for field, (r, j) in counts.items()}
    stats.update({f"{field}_judged": j for field, (_, j) in counts.items()})
    return stats, reference
