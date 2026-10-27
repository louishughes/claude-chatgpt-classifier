"""Run the model over a sample, safely: retries, a cost cap, and resume.

How one conversation is handled
-------------------------------
1. Ask the provider for a label.
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
from providers import FatalError, Provider, RefusalError, SchemaError, TransientError, cost_usd
from schema import SYSTEM_PROMPT, TAXONOMY_VERSION

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
    repaired: bool = False
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_s: float = 0.0
    chars_sent: int = 0
    clipped: bool = False
    turns: int = 0
    branch_points: int = 0
    decisions_total: int = 0
    decisions_quote_found: int = 0       # quote appears in a message by the stated speaker
    decisions_user_accepted: int = 0
    decisions_assistant_accepted_unquoted: int = 0  # "accepted" with only assistant evidence
    position: int = 0                    # order this chat was processed in (order-independence check)
    error: str = ""


def _normalise(s: str) -> str:
    return " ".join(s.split()).lower()


def check_quotes(record: Record, conv: Conversation) -> None:
    """Does each decision's evidence quote really appear, said by the right speaker?

    This catches the model inventing evidence or putting the assistant's words
    in the user's mouth, the two failures that most damage a knowledge base.
    We check against the full chat, not the clipped text sent to the model.
    """
    if not record.label:
        return
    by_speaker = {
        role: _normalise("\n".join(t.text for t in conv.turns if t.role == role))
        for role in ("user", "assistant")
    }
    for d in record.label.get("decisions", []):
        record.decisions_total += 1
        quote = _normalise(d.get("evidence_quote", ""))
        if quote and quote in by_speaker.get(d.get("evidence_speaker"), ""):
            record.decisions_quote_found += 1
        if d.get("state") == "accepted":
            if d.get("evidence_speaker") == "user":
                record.decisions_user_accepted += 1
            else:
                # Accepted, but the only evidence is the assistant talking.
                # Not necessarily wrong ("Agreed, we'll do X" after the user
                # chose X), but worth counting.
                record.decisions_assistant_accepted_unquoted += 1


def label_one(
    conv: Conversation,
    provider: Provider,
    meter: CostMeter,
    budget_chars: int,
    max_attempts: int = 3,
    backoff_s: float = 2.0,
    sleep=time.sleep,
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
    repair_note: str | None = None
    transient_calls = 0
    started = time.monotonic()
    while True:
        if not meter.can_spend():
            rec.status = "skipped_cost_cap"
            break
        rec.calls += 1
        try:
            result = provider.label(SYSTEM_PROMPT, text, repair_note)
        except TransientError as exc:
            rec.transient_errors[exc.kind] = rec.transient_errors.get(exc.kind, 0) + 1
            transient_calls += 1
            if transient_calls >= max_attempts:
                rec.error = f"gave up after {transient_calls} {exc.kind} errors"
                break
            # Exponential backoff with jitter: 2s, 4s, ... plus up to 1s random,
            # so parallel workers don't all retry at the same instant.
            sleep(backoff_s * 2 ** (transient_calls - 1) + random.random())
            continue
        except SchemaError as exc:
            rec.schema_failures += 1
            if repair_note is None:
                repair_note = str(exc)[:500]
                continue
            rec.status = "review_required"
            rec.error = str(exc)[:500]
            break
        except RefusalError as exc:
            rec.status = "refusal"
            rec.error = str(exc)
            break
        # Success.
        spent = cost_usd(provider.model, result.input_tokens, result.output_tokens)
        meter.add(spent)
        rec.input_tokens += result.input_tokens
        rec.output_tokens += result.output_tokens
        rec.cost_usd += spent
        rec.served_model = result.served_model
        rec.label = result.label.model_dump(mode="json")
        rec.repaired = repair_note is not None
        rec.status = "ok"
        check_quotes(rec, conv)
        break
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
            rec = label_one(conv, provider, meter, budget_chars, max_attempts, backoff_s)
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
