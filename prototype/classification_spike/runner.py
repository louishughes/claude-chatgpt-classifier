"""Run the model over a sample, safely: retries, a cost cap, and resume.

How one conversation is handled
-------------------------------
Two calls per chat: one fills in the labels (domain, purpose, ...), a second,
separate one finds the decisions. Run 1 showed decisions were the weak spot
(7 of 13 right) while labels were fine, so decisions get their own focused
prompt, can use a different model or effort, and are checked by code.

For each call:
1. Ask the provider.
2. Timeout / rate limit / server error -> wait (exponential backoff) and try
   again, at most ``max_attempts`` calls in total.
3. Answer broke the schema -> one repair attempt that tells the model what
   was wrong. Still broken -> ``review_required`` (a human looks later).
4. Refusal -> recorded as ``refusal``. Configuration error -> stop the run.

Retries are only for *transport* problems (timeouts, overload) and *format*
problems (the answer broke the schema). A label that is well-formed but wrong
is never retried: asking again just produces another variation of the same
mistake. Wrong answers are found by the gold set and fixed by changing the
method, not by looping.

Every result is appended to a JSONL file as soon as it finishes. If the run
crashes or is stopped, running it again skips everything already done.

Talking points
--------------
- "Checkpoint after every item. A crash at item 87 should cost one item, not 87."
- "A hard cost cap is checked before every call, so a bug can't run up a bill."
- Retries are bounded. Endless retry loops hide problems instead of fixing them.
"""

from __future__ import annotations

import json
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

from loader import Conversation, clip_text
import pydantic

from providers import (FatalError, Provider, RefusalError, SchemaError, TransientError, build_user_message,
                       cost_usd)
from schema import DECISIONS_PROMPT, SYSTEM_PROMPT, TAXONOMY_VERSION, ConversationLabel, DecisionList

# A conversation counts as finished if it has one of these. "failed" is not
# here, so resuming a run retries the ones that failed last time.
FINISHED = {"ok", "review_required", "refusal"}


class CostMeter:
    """Running total of spend, shared by all worker threads."""

    def __init__(self, cap_usd: float, already_spent: float = 0.0):
        self.cap_usd = cap_usd
        self.spent = already_spent
        self._lock = threading.Lock()

    def can_spend(self) -> bool:
        with self._lock:
            return self.spent < self.cap_usd

    def add(self, amount: float) -> None:
        with self._lock:
            self.spent += amount


@dataclass
class Record:
    conversation_id: str
    source_file: str
    status: str  # ok | review_required | refusal | failed | skipped_cost_cap
    model: str
    served_model: str = ""
    taxonomy_version: str = TAXONOMY_VERSION
    label: dict | None = None
    calls: int = 0
    transient_errors: dict[str, int] = field(default_factory=dict)
    schema_failures: int = 0
    schema_errors: list[str] = field(default_factory=list)  # validator messages (no chat text)
    repaired: bool = False
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_s: float = 0.0
    chars_sent: int = 0
    clipped: bool = False
    turns: int = 0
    branch_points: int = 0
    decisions_status: str = ""           # ok | review_required | refusal | failed | skipped_cost_cap
    decisions_model: str = ""
    decisions_total: int = 0
    decisions_quote_found: int = 0       # quote found in the message it points at
    decisions_refs_ok: int = 0           # message numbers exist and match the speakers
    decisions_decided_by_assistant: int = 0  # accepted/rejected but decided_in isn't a user message
    position: int = 0                    # order this chat was processed in (order-independence check)
    error: str = ""


def _normalise(s: str) -> str:
    return " ".join(s.split()).lower()


def check_decisions(record: Record, conv: Conversation) -> None:
    """Check every decision against the chat with plain code.

    - ``proposed_in`` must exist and be written by ``proposed_by``.
    - accepted / rejected / superseded must have a ``decided_in`` that the
      *user* wrote, at or after the proposal. This is the rule run 1 broke.
    - the evidence quote must appear in the message it points at.
    We check against the full chat, not the clipped text sent to the model.
    """
    if not record.label:
        return
    turns = conv.turns

    def turn(n) -> object | None:
        return turns[n - 1] if isinstance(n, int) and 1 <= n <= len(turns) else None

    for d in record.label.get("decisions", []):
        record.decisions_total += 1
        proposed = turn(d.get("proposed_in"))
        decided = turn(d.get("decided_in"))
        refs_ok = proposed is not None and proposed.role == d.get("proposed_by")
        if d.get("state") in {"accepted", "rejected", "superseded"}:
            if decided is None or decided.role != "user":
                record.decisions_decided_by_assistant += 1
                refs_ok = False
            elif d["decided_in"] < d["proposed_in"]:
                refs_ok = False
        record.decisions_refs_ok += refs_ok
        source = decided or proposed
        quote = _normalise(d.get("evidence_quote", ""))
        if source is not None and quote and quote in _normalise(source.text):
            record.decisions_quote_found += 1


def _call(rec: Record, provider: Provider, system: str, text: str, output_format,
          meter: CostMeter, max_attempts: int, backoff_s: float, sleep) -> tuple[pydantic.BaseModel | None, str]:
    """One structured call with bounded retries. Returns (answer or None, status)."""
    repair_note: str | None = None
    transient_calls = 0
    while True:
        if not meter.can_spend():
            return None, "skipped_cost_cap"
        rec.calls += 1
        try:
            result = provider.parse(system, build_user_message(text, repair_note), output_format)
        except TransientError as exc:
            rec.transient_errors[exc.kind] = rec.transient_errors.get(exc.kind, 0) + 1
            transient_calls += 1
            if transient_calls >= max_attempts:
                rec.error = f"gave up after {transient_calls} {exc.kind} errors"
                return None, "failed"
            # Exponential backoff with jitter: 2s, 4s, ... plus up to 1s random,
            # so parallel workers don't all retry at the same instant.
            sleep(backoff_s * 2 ** (transient_calls - 1) + random.random())
            continue
        except SchemaError as exc:
            rec.schema_failures += 1
            rec.schema_errors.append(str(exc)[:300])
            if repair_note is None:
                repair_note = str(exc)[:500]
                continue
            rec.error = str(exc)[:500]
            return None, "review_required"
        except RefusalError as exc:
            rec.error = str(exc)
            return None, "refusal"
        spent = cost_usd(provider.model, result.input_tokens, result.output_tokens)
        meter.add(spent)
        rec.input_tokens += result.input_tokens
        rec.output_tokens += result.output_tokens
        rec.cost_usd += spent
        rec.repaired = rec.repaired or repair_note is not None
        if output_format is ConversationLabel:
            rec.served_model = result.served_model
        return result.label, "ok"


def label_one(
    conv: Conversation,
    provider: Provider,
    meter: CostMeter,
    budget_chars: int,
    max_attempts: int = 3,
    backoff_s: float = 2.0,
    sleep=time.sleep,
    decisions_provider: Provider | None = None,
) -> Record:
    full_text = conv.full_text()
    text, clipped = clip_text(full_text, budget_chars)
    rec = Record(
        conversation_id=conv.conversation_id,
        source_file=conv.source_file,
        status="failed",
        model=provider.model,
        chars_sent=len(text),
        clipped=clipped,
        turns=len(conv.turns),
        branch_points=conv.branch_points,
    )
    started = time.monotonic()
    label, rec.status = _call(rec, provider, SYSTEM_PROMPT, text, ConversationLabel,
                              meter, max_attempts, backoff_s, sleep)
    if label is not None:
        rec.label = label.model_dump(mode="json")
        dp = decisions_provider or provider
        rec.decisions_model = dp.model
        found, rec.decisions_status = _call(rec, dp, DECISIONS_PROMPT, text, DecisionList,
                                            meter, max_attempts, backoff_s, sleep)
        rec.label["decisions"] = found.model_dump(mode="json")["decisions"] if found else []
        if found is None:
            # Labels are fine but decisions are missing: needs a look, not a silent pass.
            rec.status = "review_required" if rec.decisions_status != "skipped_cost_cap" else "skipped_cost_cap"
        check_decisions(rec, conv)
    rec.latency_s = round(time.monotonic() - started, 3)
    return rec


def load_records(path: Path) -> dict[str, dict]:
    """Latest record per conversation id from a JSONL checkpoint file."""
    latest: dict[str, dict] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                latest[row["conversation_id"]] = row
    return latest


def run_once(
    conversations: list[Conversation],
    provider: Provider,
    out_file: Path,
    meter: CostMeter,
    budget_chars: int,
    workers: int = 4,
    max_attempts: int = 3,
    backoff_s: float = 2.0,
    progress=print,
    order_seed: int | None = None,
    decisions_provider: Provider | None = None,
) -> dict[str, dict]:
    """Label every conversation not already finished in ``out_file``.

    ``order_seed`` shuffles the processing order. Each run uses a different
    order on purpose: every call is independent (no shared vocabulary that
    grows during the run), so the labels must not depend on order. If two
    runs in different orders still agree, that is evidence of it.
    """
    done = {cid for cid, r in load_records(out_file).items() if r["status"] in FINISHED}
    todo = [c for c in conversations if c.conversation_id not in done]
    if order_seed is not None:
        random.Random(order_seed).shuffle(todo)
    positions = {c.conversation_id: i for i, c in enumerate(todo)}
    progress(f"  {out_file.name}: {len(done)} already done, {len(todo)} to go")
    lock = threading.Lock()
    fatal: list[str] = []

    def work(conv: Conversation) -> None:
        if fatal:
            return
        try:
            rec = label_one(conv, provider, meter, budget_chars, max_attempts, backoff_s,
                            decisions_provider=decisions_provider)
        except FatalError as exc:
            fatal.append(str(exc))
            return
        rec.position = positions[conv.conversation_id]
        with lock, out_file.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(rec)) + "\n")
        progress(f"  {rec.status:<16} calls={rec.calls} {rec.latency_s:>6.1f}s  spent=${meter.spent:.2f}")

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        list(pool.map(work, todo))
    if fatal:
        raise FatalError(fatal[0])
    return load_records(out_file)
