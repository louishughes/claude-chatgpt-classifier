"""A real model behind the provider contract: the Anthropic Messages API (EVAL-011, OD-05).

This is the one adapter that can spend money, so it is fenced three ways:

1. **Egress switch.** It declares ``text_llm``; ``ModelStageRunner`` refuses
   to hand it a request unless ``[egress] text_llm = true`` is set.
2. **Hard cost cap.** Every request's worst case (its input, plus the full
   ``max_tokens`` of output, at the pinned model's list price) must fit in
   what is left of ``max_cost_usd``. A request that doesn't fit is **not
   sent**: it stays pending and ``capped`` is set, so the run reports it.
   After each answer the real cost (from the API's token counts) is added.
3. **Pinned model with known prices.** Only models in ``PRICES`` can run, so
   a cap can always be computed. The answer's model ID is stored with it.

The model is asked for JSON that fits the request's schema (structured
outputs, ``output_config.format``). Its text then goes through the same
``result_from_response`` as every other provider: a provider error is
``transient``, a cut-off answer is ``invalid``, anything else is validated
by the engine's own schema check.

The SDK (``pip install -e ".[api]"``) is imported only when this provider is
built, so nothing else needs it. Answers are made synchronously in
``submit``; ``collect`` hands them back.

Talking points:
    - "The real-model adapter can't send anything unless the egress switch
      is on, and it won't send a request whose worst-case price would break
      the cap, so the bill has a hard ceiling."
    - "Its answers go through exactly the same checks as the fake's."
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from knowledge_engine.providers.base import (
    BatchHandle,
    ModelRequest,
    ProviderIdentity,
    ProviderResult,
    RawResponse,
    ResultState,
    result_from_response,
)
from knowledge_engine.settings import Capability

ADAPTER_VERSION = "anthropic-api-v1"
# Default model: the one the 2026-10-27 spike ran (OD-05). List prices in
# US dollars per million tokens (input, output), for the cost cap.
DEFAULT_MODEL = "claude-haiku-5-5"
PRICES: dict[str, tuple[float, float]] = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-opus-5-5": (4.00, 20.00),
}
# The pinned model's tokenizer counts roughly one token per 2.5-3 characters
# of English, so characters / 2 over-estimates input tokens: the worst-case
# check stays on the safe side.
_CHARS_PER_TOKEN = 2
CAPPED = "cost cap: not sent (worst-case price would exceed what is left of the cap)"


def worst_case_usd(model: str, characters: int, max_tokens: int) -> float:
    """The most one request could cost: all its input plus the full output allowance."""
    price_in, price_out = PRICES[model]
    tokens_in = characters / _CHARS_PER_TOKEN + 50  # + message framing
    return (tokens_in * price_in + max_tokens * price_out) / 1_000_000


def actual_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """What a request cost, from the token counts the API reported."""
    price_in, price_out = PRICES[model]
    return (input_tokens * price_in + output_tokens * price_out) / 1_000_000


@dataclass
class AnthropicProvider:
    """Answers structured requests with a pinned Claude model, under a hard cost cap.

    Attributes:
        max_cost_usd: The cap for this provider's lifetime (one run).
        model: The pinned model; must be in ``PRICES``.
        max_tokens: Output allowance per request.
        client: An SDK client, or anything with ``messages.create`` (tests
            pass a stand-in). Built from the environment when None.
        spent_usd: Cost so far, from the API's token counts.
        capped: How many requests the cap kept back.
        calls: Requests actually sent.
    """

    max_cost_usd: float
    model: str = DEFAULT_MODEL
    max_tokens: int = 2048
    client: Any = None
    spent_usd: float = 0.0
    capped: int = 0
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    _answers: dict[str, ProviderResult] = field(default_factory=dict)

    def __post_init__(self) -> None:
        """Refuse a model without known prices or a cap that allows nothing."""
        if self.model not in PRICES:
            raise ValueError(f"no list price for {self.model!r}; pin one of {sorted(PRICES)}")
        if self.max_cost_usd <= 0:
            raise ValueError("a real provider needs a cost cap above zero")
        if self.client is None:
            import anthropic  # optional dependency: pip install -e ".[api]"

            # Three attempts in all for rate limits and server errors (ADR-0007 §5).
            self.client = anthropic.Anthropic(max_retries=2)

    @property
    def identity(self) -> ProviderIdentity:
        """A text model that sends data off the machine."""
        return ProviderIdentity("anthropic", Capability.TEXT_LLM, ADAPTER_VERSION)

    def submit(self, requests: Sequence[ModelRequest]) -> BatchHandle:
        """Ask each request now (within the cap); ``collect`` returns the answers."""
        for request in requests:
            self._answers[request.request_id] = self._ask(request)
        return BatchHandle((f"anthropic-{self.calls}",), tuple(r.request_id for r in requests))

    def collect(
        self, handle: BatchHandle, requests: Mapping[str, ModelRequest]
    ) -> list[ProviderResult]:
        """The answers made in ``submit``; pending for anything not asked."""
        return [
            self._answers.pop(r, ProviderResult(r, ResultState.PENDING)) for r in handle.request_ids
        ]

    def _ask(self, request: ModelRequest) -> ProviderResult:
        # The answer schema is sent too, so it counts as input.
        sent = request.characters + len(json.dumps(request.json_schema()))
        worst = worst_case_usd(self.model, sent, self.max_tokens)
        if self.spent_usd + worst > self.max_cost_usd:
            self.capped += 1
            return ProviderResult(request.request_id, ResultState.PENDING, error=CAPPED)
        import anthropic

        prompt = request.instructions
        if request.repair_of_error:
            prompt += f"\n\nYour previous answer was rejected: {request.repair_of_error}"
        self.calls += 1
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=prompt,
                # The imported text is data, never instructions (OPS-006).
                messages=[{"role": "user", "content": request.input_text}],
                # Picking labels from a fixed list needs no long reasoning, and
                # thinking would spend the same max_tokens as the answer.
                thinking={"type": "disabled"},
                output_config={
                    "effort": "low",
                    "format": {
                        "type": "json_schema",
                        "schema": anthropic.transform_schema(request.output_model),
                    },
                },
            )
        except (anthropic.RateLimitError, anthropic.APIConnectionError) as error:
            self.spent_usd += worst  # unknown usage: count the worst case
            return ProviderResult(
                request.request_id, ResultState.TRANSIENT, error=type(error).__name__
            )
        except anthropic.APIStatusError as error:
            self.spent_usd += worst
            response_body = RawResponse(http_status=error.status_code, error_type=None)
            return result_from_response(request, response_body)
        usage = response.usage
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
        self.spent_usd += actual_usd(self.model, usage.input_tokens, usage.output_tokens)
        if response.stop_reason == "refusal":
            # The model declined: not a provider hiccup, so not retried.
            return ProviderResult(request.request_id, ResultState.INVALID, error="refusal")
        text = next((b.text for b in response.content if b.type == "text"), None)
        stop = response.stop_reason
        raw = RawResponse(body=text, finish_reason="length" if stop == "max_tokens" else stop)
        return result_from_response(
            request, raw, served_model=response.model, session_ref=response.id
        )

    def usage(self) -> dict[str, Any]:
        """Calls, tokens and dollars so far (no text)."""
        return {
            "provider": "anthropic",
            "model": self.model,
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "spent_usd": round(self.spent_usd, 6),
            "cap_usd": self.max_cost_usd,
            "capped_requests": self.capped,
        }
