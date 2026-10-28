"""Structured run logs without private text (OPS-001).

Every job writes one JSON object per line to
``<workspace>/logs/events-YYYYMMDD.jsonl``: what happened (``event``), when,
and IDs, versions, timings, counts and cost. The log is meant to be read
when something went wrong, so it must never become a second copy of the
owner's conversations. Three rules keep it clean:

1. **Allow-listed fields only.** ``emit`` refuses any field name not in
   ``FIELDS``. There is no ``text``, ``title`` or ``message`` field, so
   source text has no way in. Adding a field is a code change a reviewer
   sees.
2. **Errors by type name only.** ``error_type(exc)`` gives ``KeyError``,
   never the message, because exception messages often quote their input.
3. **Scrubbing as a last line of defence.** Every string value passes
   through ``scrub``: API keys, bearer tokens, GitHub and AWS tokens and
   the configured secret values are replaced with ``[secret]``, and long
   strings are cut short.

Lineage is searchable because every event carries the same IDs the
database uses (``stage_key``, ``job_id``, ``segment_id``...):
``search(log_dir, stage_key=...)`` (or ``ke logs --stage-key ...``) lists
everything that happened to one stage key, across days.

Talking points:
    - "Logs only accept a fixed list of fields, all IDs and numbers, so
      chat text can't end up in them even by accident."
    - "Errors are logged by type, never by message, and anything shaped
      like a key is scrubbed."
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from knowledge_engine.settings import Settings

LOG_VERSION = "ops-001-v1"
MAX_STRING = 200

# Every field an event may carry. IDs, versions, states, counts, timings
# and cost: nothing that can hold a sentence.
FIELDS = frozenset(
    {
        "attempts",
        "batch_id",
        "cached",
        "characters",
        "conversation_id",
        "cost_usd",
        "count",
        "done",
        "duration_ms",
        "error_type",
        "extractor",
        "failed",
        "gave_up",
        "import_id",
        "job_id",
        "limit",
        "limit_name",
        "model",
        "outcome",
        "pending",
        "prompt_version",
        "provider_id",
        "record_id",
        "records",
        "repairs",
        "review_required",
        "run_id",
        "schema_version",
        "segment_id",
        "skipped",
        "stage_id",
        "stage_key",
        "state",
        "submitted",
        "taxonomy_version",
        "value",
        "version",
    }
)

_SECRET_PATTERNS = (
    re.compile(r"sk-(?:ant-)?[A-Za-z0-9_\-]{16,}"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{16,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)(?:api[_-]?key|token|secret|password)\s*[=:]\s*\S+"),
)
SECRET = "[secret]"

Value = str | int | float | bool | None


def scrub(text: str, secrets: Sequence[str] = ()) -> str:
    """Replace anything secret-shaped (and the given secret values), then cap the length."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, SECRET)
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(SECRET, text)
    return text if len(text) <= MAX_STRING else text[: MAX_STRING - 1] + "…"


def error_type(error: BaseException) -> str:
    """The exception's type name: its message may quote private input."""
    return type(error).__name__


@dataclass
class EventLog:
    """Appends structured events to the day's JSON-lines file.

    Attributes:
        directory: Usually ``<workspace>/logs`` (git-ignored with the workspace).
        secrets: Configured secret values to scrub even if they don't look
            like a key.
        enabled: False checks every event but writes nothing (the default
            for library code that wasn't handed a log).
    """

    directory: Path
    secrets: tuple[str, ...] = ()
    enabled: bool = True

    def emit(self, event: str, **fields: Value) -> dict[str, Value]:
        """Write one event and return what was written.

        Raises:
            ValueError: A field not in ``FIELDS``, or a value that isn't a
                plain scalar. Refusing is safer than guessing what's private.
        """
        unknown = sorted(set(fields) - FIELDS)
        if unknown:
            raise ValueError(f"log fields not allowed: {unknown}")
        if not re.fullmatch(r"[a-z][a-z0-9_.]{0,79}", event):
            raise ValueError("an event name is a short dotted identifier")
        line: dict[str, Value] = {
            "at": datetime.now(UTC).isoformat(timespec="milliseconds"),
            "event": event,
            "log_version": LOG_VERSION,
        }
        for name, value in sorted(fields.items()):
            if value is not None and not isinstance(value, str | int | float | bool):
                raise ValueError(f"log field {name} must be a plain value")
            line[name] = scrub(value, self.secrets) if isinstance(value, str) else value
        if not self.enabled:
            return line
        self.directory.mkdir(parents=True, exist_ok=True)
        path = self.directory / f"events-{datetime.now(UTC):%Y%m%d}.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n")
        return line

    @contextmanager
    def timed(self, event: str, **fields: Value) -> Iterator[dict[str, Value]]:
        """Log ``event`` with its duration and outcome when the block ends.

        The block may add allowed fields (counts, cost) to the yielded dict.
        An exception is logged by type and then re-raised.
        """
        extra: dict[str, Value] = {}
        started = time.perf_counter()
        try:
            yield extra
        except BaseException as error:
            duration = round((time.perf_counter() - started) * 1000, 3)
            self.emit(
                event,
                **fields,
                **extra,
                outcome="error",
                error_type=error_type(error),
                duration_ms=duration,
            )
            raise
        duration = round((time.perf_counter() - started) * 1000, 3)
        self.emit(event, **fields, **extra, outcome="ok", duration_ms=duration)


def null_log() -> EventLog:
    """A log that checks fields but writes nothing."""
    return EventLog(Path("."), enabled=False)


def event_log(settings: Settings) -> EventLog:
    """The workspace's log, scrubbing the configured secrets."""
    key = settings.anthropic_api_key
    return EventLog(
        settings.workspace_root / "logs",
        secrets=(key.get_secret_value(),) if key is not None else (),
    )


def search(directory: Path, **match: str) -> list[dict[str, Value]]:
    """Every logged event whose fields equal all of ``match``, oldest first.

    Example: ``search(log_dir, stage_key="stg_...")`` is one stage key's
    whole lineage: submitted, repaired, stored, extracted.
    """
    unknown = sorted(set(match) - FIELDS - {"event"})
    if unknown:
        raise ValueError(f"cannot search on {unknown}")
    found: list[dict[str, Value]] = []
    for path in sorted(directory.glob("events-*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            event = json.loads(line)
            if all(event.get(k) == v for k, v in match.items()):
                found.append(event)
    return found


def totals(events: Sequence[Mapping[str, Value]]) -> dict[str, float]:
    """Summed cost, characters and duration of some events (for a quick cost view)."""
    sums = {"cost_usd": 0.0, "characters": 0.0, "duration_ms": 0.0}
    for event in events:
        for name in sums:
            value = event.get(name)
            if isinstance(value, int | float) and not isinstance(value, bool):
                sums[name] += value
    return {name: round(value, 6) for name, value in sums.items()}
