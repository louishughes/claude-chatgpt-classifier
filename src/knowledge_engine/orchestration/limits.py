"""Run budgets: how much one run may send, how big, how fast and how long (OPS-002).

Every bound comes from ``Settings.limits`` and is checked *before* the work
it bounds, so going over a limit never costs anything:

* ``max_model_calls_per_run``: calls (first tries and repairs) one run may
  make. Requests past the cap are not sent; they stay unsent and a later
  run with budget left picks them up.
* ``max_input_tokens_per_request``: a request estimated (four characters
  per token) to be bigger is never sent. It is recorded as a capped
  failure, ``review_required`` with error ``limit:max_input_tokens``.
* ``max_requests_per_batch``: the most requests in one provider batch.
* ``provider_timeout_s``: a request waiting longer is recorded as
  ``review_required`` with error ``timeout``.
* ``stage_deadline_s``: once a stage has run this long, it starts nothing
  new; the rest is deferred to the next run, never dropped.

Each limit reached is logged as a ``limit.reached`` event (OPS-001) with
the limit's name, its value and what was asked for.

Talking points:
    - "Limits are checked before the work, so hitting one costs nothing,
      and it's recorded, not silent."
    - "Work over a cap isn't lost: it waits for the next run."
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass, field

from knowledge_engine.infrastructure.logs import EventLog, null_log
from knowledge_engine.settings import Limits

CHARS_PER_TOKEN = 4


def estimated_tokens(characters: int) -> int:
    """A cautious token estimate for a request of ``characters`` characters."""
    return math.ceil(characters / CHARS_PER_TOKEN)


@dataclass
class RunBudget:
    """What one run may still spend, shared by every stage of the run.

    Attributes:
        limits: The configured bounds.
        log: Where ``limit.reached`` events go.
        calls: Model calls made so far in this run.
        reached: Names of the limits reached so far (for the run report).
    """

    limits: Limits
    log: EventLog = field(default_factory=null_log)
    calls: int = 0
    reached: list[str] = field(default_factory=list)

    def take_calls(self, wanted: int) -> int:
        """Reserve up to ``wanted`` calls; return how many may go."""
        allowed = max(0, min(wanted, self.limits.max_model_calls_per_run - self.calls))
        self.calls += allowed
        if allowed < wanted:
            self.hit("max_model_calls_per_run", self.limits.max_model_calls_per_run, wanted)
        return allowed

    def fits(self, characters: int, *, stage_key: str | None = None) -> bool:
        """Whether a request of this size may be sent at all."""
        tokens = estimated_tokens(characters)
        if tokens <= self.limits.max_input_tokens_per_request:
            return True
        self.hit(
            "max_input_tokens_per_request",
            self.limits.max_input_tokens_per_request,
            tokens,
            stage_key=stage_key,
        )
        return False

    def hit(self, name: str, limit: float, value: float, *, stage_key: str | None = None) -> None:
        """Record that a limit was reached."""
        self.reached.append(name)
        self.log.emit(
            "limit.reached", limit_name=name, limit=limit, value=value, stage_key=stage_key
        )


@dataclass
class Deadline:
    """A stage's wall-clock budget.

    Attributes:
        seconds: ``Limits.stage_deadline_s``.
        clock: Monotonic seconds (replaceable in tests).
    """

    seconds: float
    clock: Callable[[], float] = time.monotonic
    started: float = field(init=False)

    def __post_init__(self) -> None:
        """Start the clock when the deadline is created."""
        self.started = self.clock()

    @property
    def passed(self) -> bool:
        """True once the stage has used its time."""
        return self.clock() - self.started >= self.seconds
