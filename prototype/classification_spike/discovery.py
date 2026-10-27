"""Spike v3, step 2: discovery, and scoring against the answer key.

What this does
--------------
One call per chat with ``schema.Discovery``: the model splits the chat into
sections (segments) and lists typed knowledge items, each pointing at a
message number. There is no fixed topic list beyond the broad level-1
subject. Plain code then checks the answer against the chat (do the sections
cover every message? do the message numbers and speakers match? do the
quotes really appear?) and, when an answer key exists, scores it.

How scoring works (all by message number, so no fuzzy text matching)
---------------------------------------------------------------------
- Section boundaries: a model boundary within 1 message of a key boundary
  counts as a match. Precision and recall of boundaries.
- Subject and purpose: compared *per message*, so a chat split differently
  still gets partial credit where the labels agree.
- Items: same type and within 1 message of a key item counts as a match.
  Precision (how many model items are real) and recall (how many key items
  were found), per type.
- Decisions: for matched decisions, is the state right, and the proposer?
- Projects: overlap of normalised project names per chat.
The same scorer compares run 2 against run 1 for consistency.

Talking points
--------------
- "Score by message number, not by wording. Two answers can be phrased
  differently and still point at the same thing."
- "One scorer, two uses: model vs answer key is accuracy, run vs run is
  consistency."
"""

from __future__ import annotations

import json
import re
import statistics
import time
from pathlib import Path

from loader import Conversation, clip_text
from providers import Provider
from report import _pct
from runner import CostMeter, Record, _call, _normalise
from schema import DISCOVERY_PROMPT, DISCOVERY_VERSION, Discovery, ItemType

ITEM_TYPES = [t.value for t in ItemType]


# --- one chat ------------------------------------------------------------------

def check_discovery(answer: dict, conv: Conversation) -> dict:
    """Plain-code checks on one discovery answer. Returns counts."""
    n = len(conv.turns)
    covered = [0] * (n + 1)
    bad_ranges = 0
    for s in answer["segments"]:
        if not (1 <= s["start"] <= s["end"] <= n):
            bad_ranges += 1
            continue
        for i in range(s["start"], s["end"] + 1):
            covered[i] += 1
    items = answer["items"]
    refs_ok = quotes_ok = decided_by_assistant = 0
    for it in items:
        m = it["message"]
        ok = 1 <= m <= n and conv.turns[m - 1].role == it["speaker"]
        if it["type"] == "decision" and it.get("state") in {"accepted", "rejected", "superseded"}:
            d = it.get("decided_in")
            if not (isinstance(d, int) and 1 <= d <= n and conv.turns[d - 1].role == "user" and d >= m):
                decided_by_assistant += 1
                ok = False
        refs_ok += ok
        src = it.get("decided_in") if it["type"] == "decision" and it.get("decided_in") else m
        quote = _normalise(it.get("evidence_quote", ""))
        if isinstance(src, int) and 1 <= src <= n and quote and quote in _normalise(conv.turns[src - 1].text):
            quotes_ok += 1
    return {
        "messages": n,
        "segments": len(answer["segments"]),
        "segment_bad_ranges": bad_ranges,
        "messages_uncovered": sum(1 for i in range(1, n + 1) if covered[i] == 0),
        "messages_overlapped": sum(1 for i in range(1, n + 1) if covered[i] > 1),
        "items": len(items),
        "item_refs_ok": refs_ok,
        "item_quotes_ok": quotes_ok,
        "decided_without_user_message": decided_by_assistant,
    }


def discover_one(conv: Conversation, provider: Provider, meter: CostMeter, budget_chars: int,
                 max_attempts: int = 3, backoff_s: float = 2.0, sleep=time.sleep) -> Record:
    full_text = conv.full_text()
    text, clipped = clip_text(full_text, budget_chars)
    rec = Record(conversation_id=conv.conversation_id, source_file=conv.source_file, status="failed",
                 model=provider.model, taxonomy_version=DISCOVERY_VERSION, chars_sent=len(text),
                 clipped=clipped, turns=len(conv.turns), branch_points=conv.branch_points)
    started = time.monotonic()
    answer, rec.status = _call(rec, provider, DISCOVERY_PROMPT, text, Discovery,
                               meter, max_attempts, backoff_s, sleep)
    if answer is not None:
        rec.served_model = rec.served_model or provider.model
        rec.label = answer.model_dump(mode="json")
        rec.checks = check_discovery(rec.label, conv)
    rec.latency_s = round(time.monotonic() - started, 3)
    return rec


# --- scoring -------------------------------------------------------------------

def _per_message(segments: list[dict], n: int, field: str) -> list[str | None]:
    out: list[str | None] = [None] * (n + 1)
    for s in segments:
        for i in range(max(1, s["start"]), min(n, s["end"]) + 1):
            out[i] = s[field]
    return out


def _boundaries(segments: list[dict]) -> list[int]:
    return sorted({s["start"] for s in segments if s["start"] > 1})


def _match(gold: list[int], pred: list[int], tol: int = 1) -> int:
    """Greedy one-to-one matching of positions within ``tol``."""
    used, hits = set(), 0
    for g in gold:
        for j, p in enumerate(pred):
            if j not in used and abs(p - g) <= tol:
                used.add(j)
                hits += 1
                break
    return hits


def _norm_name(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def score_pair(key: dict, pred: dict, n: int) -> dict:
    """Raw counts comparing one predicted answer with one reference answer."""
    out: dict = {"messages": n}
    kb, pb = _boundaries(key["segments"]), _boundaries(pred["segments"])
    out.update(boundaries_key=len(kb), boundaries_pred=len(pb), boundaries_matched=_match(kb, pb))
    for field in ("subject_l1", "purpose"):
        k, p = _per_message(key["segments"], n, field), _per_message(pred["segments"], n, field)
        out[f"{field}_messages_agree"] = sum(1 for i in range(1, n + 1) if k[i] is not None and k[i] == p[i])
    kp = {_norm_name(x) for s in key["segments"] for x in s.get("projects", [])} - {""}
    pp = {_norm_name(x) for s in pred["segments"] for x in s.get("projects", [])} - {""}
    out.update(projects_key=len(kp), projects_pred=len(pp), projects_matched=len(kp & pp))
    dec_state = dec_proposer = dec_matched = 0
    for t in ITEM_TYPES:
        ki = [i for i in key["items"] if i["type"] == t]
        pi = [i for i in pred["items"] if i["type"] == t]
        used, hits = set(), 0
        for g in ki:
            for j, p in enumerate(pi):
                if j not in used and abs(p["message"] - g["message"]) <= 1:
                    used.add(j)
                    hits += 1
                    if t == "decision":
                        dec_matched += 1
                        dec_state += g.get("state") == p.get("state")
                        # In the key, proposed_by is explicit; in a model item the
                        # proposer is the speaker of the message it points at.
                        dec_proposer += (g.get("proposed_by") or g.get("speaker")) == p.get("speaker")
                    break
        out[f"items_{t}"] = (len(ki), len(pi), hits)
    out.update(decisions_matched=dec_matched, decision_state_ok=dec_state, decision_proposer_ok=dec_proposer)
    return out


def summarise(pairs: list[dict]) -> dict:
    """Turn per-chat counts into the rates the report shows."""
    if not pairs:
        return {"chats_scored": 0}
    tot = lambda k: sum(p[k] for p in pairs)
    msgs = tot("messages")
    res = {
        "chats_scored": len(pairs),
        "boundary_recall_pct": _pct(tot("boundaries_matched"), tot("boundaries_key")),
        "boundary_precision_pct": _pct(tot("boundaries_matched"), tot("boundaries_pred")),
        "subject_l1_by_message_pct": _pct(tot("subject_l1_messages_agree"), msgs),
        "purpose_by_message_pct": _pct(tot("purpose_messages_agree"), msgs),
        "project_recall_pct": _pct(tot("projects_matched"), tot("projects_key")),
        "project_precision_pct": _pct(tot("projects_matched"), tot("projects_pred")),
        "decision_state_ok_pct": _pct(tot("decision_state_ok"), tot("decisions_matched")),
        "decision_proposer_ok_pct": _pct(tot("decision_proposer_ok"), tot("decisions_matched")),
    }
    all_k = all_p = all_h = 0
    for t in ITEM_TYPES:
        k = sum(p[f"items_{t}"][0] for p in pairs)
        pr = sum(p[f"items_{t}"][1] for p in pairs)
        h = sum(p[f"items_{t}"][2] for p in pairs)
        all_k, all_p, all_h = all_k + k, all_p + pr, all_h + h
        res[f"items_{t}"] = f"key {k} / model {pr} / matched {h}"
    res["items_recall_pct"] = _pct(all_h, all_k)
    res["items_precision_pct"] = _pct(all_h, all_p)
    return res


def load_answer_key(folder: Path) -> dict[str, dict]:
    key = {}
    for p in sorted(folder.glob("*.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        key[data["conversation_id"]] = data
    return key


def score_run(records: dict[str, dict], reference: dict[str, dict], convs: dict[str, Conversation]) -> dict:
    pairs = [score_pair(reference[cid], r["label"], len(convs[cid].turns))
             for cid, r in records.items()
             if cid in reference and cid in convs and r["status"] == "ok"]
    return summarise(pairs)


def run_checks(records: dict[str, dict]) -> dict:
    ok = [r for r in records.values() if r["status"] == "ok"]
    statuses: dict[str, int] = {}
    for r in records.values():
        statuses[r["status"]] = statuses.get(r["status"], 0) + 1
    tot = lambda k: sum(r["checks"].get(k, 0) for r in ok)
    lat = sorted(r["latency_s"] for r in ok)
    types: dict[str, int] = {}
    for r in ok:
        for it in r["label"]["items"]:
            types[it["type"]] = types.get(it["type"], 0) + 1
    return {
        "conversations": len(records),
        "status_counts": statuses,
        "repaired_ok": sum(1 for r in ok if r["repaired"]),
        "transient_errors": {k: sum(r["transient_errors"].get(k, 0) for r in records.values())
                             for k in {k for r in records.values() for k in r["transient_errors"]}},
        "cost_usd": round(sum(r["cost_usd"] for r in records.values()), 4),
        "latency_p50_s": round(statistics.median(lat), 1) if lat else None,
        "chats_with_2plus_segments": sum(1 for r in ok if r["checks"]["segments"] > 1),
        "segment_coverage_errors": sum(1 for r in ok if r["checks"]["messages_uncovered"]
                                       or r["checks"]["messages_overlapped"] or r["checks"]["segment_bad_ranges"]),
        "items_total": tot("items"),
        "items_by_type": dict(sorted(types.items())),
        "item_refs_ok_pct": _pct(tot("item_refs_ok"), tot("items")),
        "item_quotes_ok_pct": _pct(tot("item_quotes_ok"), tot("items")),
        "decided_without_user_message": tot("decided_without_user_message"),
        "distinct_subject_l2": len({s["subject_l2"] for r in ok for s in r["label"]["segments"]}),
        "distinct_project_names": len({_norm_name(p) for r in ok for s in r["label"]["segments"]
                                       for p in s["projects"]} - {""}),
    }


def to_markdown(meta: dict, checks: list[dict], vs_key: list[dict], consistency: dict | None) -> str:
    lines = ["# Discovery spike report (v3 step 2)", ""] + [f"- **{k}:** {v}" for k, v in meta.items()]
    lines += ["", "## Per run: reliability and code checks", ""]
    for i, c in enumerate(checks, 1):
        lines += [f"### Run {i}"] + [f"- {k}: {v}" for k, v in c.items()] + [""]
    lines += ["## Accuracy against the answer key", ""]
    if vs_key:
        for i, s in enumerate(vs_key, 1):
            lines += [f"### Run {i}"] + [f"- {k}: {v}" for k, v in s.items()] + [""]
    else:
        lines.append("No answer key given.")
    lines += ["", "## Consistency: run 2 scored against run 1", ""]
    lines += [f"- {k}: {v}" for k, v in (consistency or {"runs": "only one run"}).items()]
    return "\n".join(lines) + "\n"
