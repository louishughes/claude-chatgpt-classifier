"""Model providers behind one small interface.

Why an interface
----------------
The runner never talks to a vendor SDK directly. It calls ``provider.label()``
and gets back either a validated ``ConversationLabel`` or one of a few typed
errors. That lets the unit tests use ``FakeProvider`` (free, offline,
deterministic) and lets us swap in another vendor later without touching the
runner. This is the "ports and adapters" idea from docs/ARCHITECTURE.md, in
miniature.

Talking points
--------------
- "Tests never call a paid API. A fake provider that can be told to fail
  lets me test timeouts and bad output for free."
- Errors are sorted into *transient* (worth retrying) and *permanent* (stop
  and report), which is what went wrong with the earlier batch runs.
"""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass
from typing import Protocol

import pydantic

from schema import DOMAINS, KNOWLEDGE_TYPES, OUTPUTS, PURPOSES, ConversationLabel, Decision, DecisionList

# USD per million tokens (input, output). Thinking tokens bill as output.
PRICES = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
    "fake": (0.0, 0.0),
}


class TransientError(Exception):
    """A failure that may succeed if we wait and try again (timeouts, 429, 5xx)."""

    def __init__(self, kind: str, message: str = ""):
        super().__init__(message or kind)
        self.kind = kind  # "timeout" | "rate_limit" | "connection" | "server"


class SchemaError(Exception):
    """The model answered, but the answer broke the contract in schema.py."""


class RefusalError(Exception):
    """The model declined to answer (stop_reason == "refusal")."""


class FatalError(Exception):
    """Configuration problem (bad key, bad model name, bad request). Stop the run."""


@dataclass
class CallResult:
    label: pydantic.BaseModel  # a ConversationLabel or a DecisionList
    input_tokens: int
    output_tokens: int
    served_model: str


class Provider(Protocol):
    model: str

    def parse(self, system: str, user_content: str, output_format: type[pydantic.BaseModel]) -> CallResult: ...


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    price_in, price_out = PRICES.get(model, PRICES["claude-opus-5-5"])
    return (input_tokens * price_in + output_tokens * price_out) / 1_000_000


def build_user_message(conversation_text: str, repair_note: str | None) -> str:
    msg = f"<conversation>\n{conversation_text}\n</conversation>"
    if repair_note:
        # Second chance after a validation failure: tell the model what was wrong.
        msg += f"\n\nYour previous answer was rejected: {repair_note}\nAnswer again, following every rule."
    return msg


class AnthropicProvider:
    """Calls Claude through the official ``anthropic`` SDK with structured output.

    - ``messages.parse(output_format=ConversationLabel)`` makes the API return
      JSON that matches our Pydantic model, and the SDK validates it.
    - SDK retries are turned off (``max_retries=0``) so the runner can count
      every retry itself and report it.
    - Refusal fallback (on by default): if the model declines, the API re-runs
      the same request on a fallback model inside the same call. We record
      which model actually answered.
    """

    def __init__(self, model: str, effort: str, timeout_s: float, max_tokens: int, refusal_fallback: bool):
        import anthropic  # imported here so tests don't need the SDK installed

        self._anthropic = anthropic
        # Credentials come from ANTHROPIC_API_KEY (or an `ant auth login` profile).
        self._client = anthropic.Anthropic(timeout=timeout_s, max_retries=0)
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens
        self.refusal_fallback = refusal_fallback

    def parse(self, system: str, user_content: str, output_format: type[pydantic.BaseModel]) -> CallResult:
        """One structured-output call; ``output_format`` is the Pydantic form to fill in."""
        a = self._anthropic
        kwargs = dict(
            model=self.model,
            max_tokens=self.max_tokens,
            system=system,
            messages=[{"role": "user", "content": user_content}],
            output_format=output_format,
            output_config={"effort": self.effort},
        )
        try:
            if self.refusal_fallback:
                response = self._client.beta.messages.parse(
                    **kwargs, betas=["server-side-fallback-2026-07-01"], fallbacks="default"
                )
            else:
                response = self._client.messages.parse(**kwargs)
        except pydantic.ValidationError as exc:
            raise SchemaError(f"{exc.error_count()} validation error(s): {_short(exc)}") from exc
        # Order matters: APITimeoutError is a subclass of APIConnectionError.
        except a.APITimeoutError as exc:
            raise TransientError("timeout") from exc
        except a.RateLimitError as exc:
            raise TransientError("rate_limit") from exc
        except a.APIConnectionError as exc:
            raise TransientError("connection") from exc
        except a.APIStatusError as exc:
            if exc.status_code >= 500:
                raise TransientError("server", f"HTTP {exc.status_code}") from exc
            raise FatalError(f"HTTP {exc.status_code}: {exc.message}") from exc

        if response.stop_reason == "refusal":
            raise RefusalError("model declined")
        if response.stop_reason == "max_tokens":
            raise SchemaError("answer was cut off (max_tokens); raise --max-tokens")
        if response.parsed_output is None:
            raise SchemaError("no parsed output")
        return CallResult(
            label=response.parsed_output,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            served_model=response.model,
        )


def _short(exc: pydantic.ValidationError) -> str:
    return "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in exc.errors()[:3])


class FakeProvider:
    """Deterministic stand-in for a real model, used by tests and dry runs.

    The label depends only on a hash of the text, so the same input always
    gets the same answer (perfect stability). Failures can be injected by
    conversation id to exercise the retry and repair paths.
    """

    model = "fake"

    def __init__(self, fail_plan: dict[str, list[str]] | None = None, latency_s: float = 0.0,
                 responders: dict | None = None):
        # fail_plan maps a marker found in the text to a queue of failures to
        # raise on successive calls, e.g. {"conv-3": ["timeout", "timeout"]}.
        self.fail_plan = {k: list(v) for k, v in (fail_plan or {}).items()}
        self.latency_s = latency_s
        self.calls = 0
        self.responders = responders or {}

    def parse(self, system: str, user_content: str, output_format: type[pydantic.BaseModel]) -> CallResult:
        self.calls += 1
        if self.latency_s:
            time.sleep(self.latency_s)
        for marker, queue in self.fail_plan.items():
            if marker in user_content and queue:
                kind = queue.pop(0)
                if kind == "schema":
                    raise SchemaError("injected schema failure")
                if kind == "refusal":
                    raise RefusalError("injected refusal")
                if kind == "fatal":
                    raise FatalError("injected fatal error")
                raise TransientError(kind)
        tokens = len(user_content) // 4
        if output_format in self.responders:
            # Tests can plug in their own answer for a form.
            return CallResult(self.responders[output_format](user_content), tokens, 100, "fake")
        if output_format is DecisionList:
            return CallResult(_fake_decisions(user_content), tokens, 100, "fake")
        return CallResult(_fake_label(user_content), tokens, 150, "fake")


def _fake_label(text: str) -> ConversationLabel:
    digest = int(hashlib.sha256(text.encode()).hexdigest(), 16)
    domains, purposes = list(DOMAINS), list(PURPOSES)
    primary = domains[digest % len(domains)]
    secondary = domains[(digest // 7) % len(domains)]
    return ConversationLabel(
        primary_domain=primary,
        secondary_domains=[secondary] if digest % 2 and secondary != primary else [],
        purpose=purposes[(digest // 11) % len(purposes)],
        project_candidates=["Synthetic Project"] if digest % 3 == 0 else [],
        topics=[f"topic {digest % 13}"],
        knowledge_types=[list(KNOWLEDGE_TYPES)[digest % len(KNOWLEDGE_TYPES)]],
        outputs=[list(OUTPUTS)[digest % len(OUTPUTS)]],
        summary="Synthetic summary from the fake provider.",
        confidence=0.8,
    )


def _fake_decisions(text: str) -> DecisionList:
    """One decision: the user's first message, decided by the user in that same message."""
    match = re.search(r"\[#(\d+) user\]: ([^\n]{1,40})", text)
    if not match:
        return DecisionList(decisions=[])
    n = int(match.group(1))
    return DecisionList(decisions=[Decision(
        statement="Synthetic decision.", proposed_by="user", proposed_in=n, state="accepted",
        decided_in=n, evidence_quote=match.group(2))])
