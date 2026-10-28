"""The provider contract, output validation, and the fake and replay providers (FND-007).

A *request* asks for one structured answer: instructions, the input text,
and a Pydantic model the answer must fit. Its ``request_id`` is the stage
key (FND-006), so the same input under the same versions is the same
request everywhere: in a cache, a request file or a response file.

A provider never decides whether an answer is good. ``validate_output``
does, in code, for every provider alike: the answer must be JSON, must fit
the model exactly (unknown fields are refused), and anything else comes back
``invalid`` with the reason. Nothing here stores anything.

Talking points:
    - "Every provider, fake or real, goes through the same validator. A
      model's answer is a claim until code has checked its shape."
    - "Submit now, collect later: the same contract fits an API that answers
      in seconds and a session that answers tomorrow."
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Protocol

from pydantic import BaseModel, BeforeValidator, ValidationError

from knowledge_engine.settings import Capability

_STAGE_KEY_PREFIX = "stg_"


_LINE_START_BRACKET = re.compile(r"(?m)^(\s*)\[")


def quote_untrusted(text: str) -> str:
    """Imported text, ready to go inside a request's ``input_text`` (OPS-006).

    Requests mark each message with a line such as ``[m:ID] user:`` (or
    ``[3] user:`` for numbered evidence). A message containing a line like
    that could pose as a different message, or as the user. A backslash
    before every line-start ``[`` keeps such a line as plain text. Text
    without one is returned unchanged, so ordinary stage keys don't move.

    Args:
        text: One message's or passage's text.

    Returns:
        The same text with line-start brackets escaped.
    """
    return _LINE_START_BRACKET.sub(r"\1\\[", text)


_MESSAGE_TAG = re.compile(r"^\[?\s*m:\s*(?P<id>[^\]\s]+)\s*\]?$")


def bare_message_id(value: object) -> object:
    """A cited message ID without the ``[m:...]`` tag the request showed it in.

    Requests show each message as ``[m:ID] user:``, and models often cite
    it back in that same form. The ID inside is what the evidence checks
    compare with, so ``[m:abc]`` and ``m:abc`` become ``abc``; anything
    else is left exactly as it was. Before this, every such citation
    counted as "outside the segment" (#255: 53 of the 67 answers in the
    one paid run).
    """
    if isinstance(value, str):
        found = _MESSAGE_TAG.match(value.strip())
        if found:
            return found.group("id")
    return value


# A message ID a model cites; validation strips the [m:...] tag.
MessageRef = Annotated[str, BeforeValidator(bare_message_id)]


class ResultState(StrEnum):
    """Where one request's answer stands."""

    OK = "ok"  # arrived and validated
    INVALID = "invalid"  # arrived, failed validation (never stored)
    PENDING = "pending"  # no answer yet
    # The provider failed, not the model (an error envelope, a rate limit,
    # an overload): there is no answer to judge, so it is asked again
    # without using up the one repair (LEG-003).
    TRANSIENT = "transient"


@dataclass(frozen=True)
class ProviderIdentity:
    """Who answers, so every stored answer can say where it came from.

    Attributes:
        provider_id: e.g. ``fake``, ``replay``, ``file_batch``.
        capability: The egress switch this provider needs (ADR-0007).
        version: The adapter's own version.
        sends_data: False only for providers that never send anything off
            the machine (replaying stored answers); the egress switch is
            checked for every other provider before it is given a request.
    """

    provider_id: str
    capability: Capability
    version: str
    sends_data: bool = True


@dataclass(frozen=True)
class ModelRequest:
    """One structured question for a model.

    Attributes:
        request_id: The stage key (``stg_...``) for this exact work.
        stage_id: Which stage asks, e.g. ``classify.segment.v1``.
        instructions: What to do. Never contains imported text.
        input_text: The data to work on: untrusted, never instructions.
        output_model: The Pydantic model the answer must fit.
        prompt_version: Version of ``instructions``.
        schema_version: Version of ``output_model``.
        attempt: 1 for a first ask, 2 for the one allowed repair.
        repair_of_error: For a repair, the validation error being fixed.
    """

    request_id: str
    stage_id: str
    instructions: str
    input_text: str
    output_model: type[BaseModel]
    prompt_version: str
    schema_version: str
    attempt: int = 1
    repair_of_error: str | None = None

    def __post_init__(self) -> None:
        """Refuse a request that isn't keyed by a stage key."""
        if not self.request_id.startswith(_STAGE_KEY_PREFIX):
            raise ValueError("request_id must be a stage key (stg_...)")
        if self.attempt not in (1, 2):
            raise ValueError("attempt is 1, or 2 for the single repair")
        # An answer with fields nobody asked for is refused, not trimmed
        # silently, so every output model must say so.
        if self.output_model.model_config.get("extra") != "forbid":
            raise ValueError("output_model must set extra='forbid'")

    @property
    def characters(self) -> int:
        """Size of the text sent, for batching and the usage ledger."""
        return len(self.instructions) + len(self.input_text)

    def json_schema(self) -> dict[str, Any]:
        """Return the JSON Schema of the expected answer."""
        return self.output_model.model_json_schema()


@dataclass(frozen=True)
class ProviderResult:
    """One request's answer as collected.

    Attributes:
        request_id: The request it answers.
        state: ``ok``, ``invalid`` or ``pending``.
        output: The validated answer, only when ``ok``.
        error: Why it was refused, only when ``invalid``.
        served_model: The model that answered, as reported (may be None).
        session_ref: The session or batch that produced it, as reported.
        trimmed: Lists cut back to their schema maximum (LEG-003), as
            ``field.path`` strings; logged, never retried.
    """

    request_id: str
    state: ResultState
    output: BaseModel | None = None
    error: str | None = None
    served_model: str | None = None
    session_ref: str | None = None
    trimmed: tuple[str, ...] = ()


@dataclass(frozen=True)
class RawResponse:
    """What an HTTP-style provider got back for one request, before any checks.

    Real providers can report a failure in several ways that older runs
    mistook for a model answer (LEG-003). An adapter fills this in and
    ``result_from_response`` sorts it out in one place.

    Attributes:
        http_status: The HTTP status (200 even for some provider errors).
        body: The model's text (JSON expected), if any.
        error_type: A provider error envelope's type, e.g. ``overloaded``
            or ``rate_limit``, even when the status was 200.
        finish_reason: Why generation stopped: ``stop``, ``length``...
    """

    http_status: int = 200
    body: str | Mapping[str, Any] | None = None
    error_type: str | None = None
    finish_reason: str | None = None


TRUNCATED = "truncated: the answer hit the output length limit (finish_reason=length)"


@dataclass(frozen=True)
class BatchHandle:
    """What ``submit`` returns: enough to ``collect`` later.

    Attributes:
        batch_ids: The batches the requests went into.
        request_ids: Every request submitted, in order.
    """

    batch_ids: tuple[str, ...]
    request_ids: tuple[str, ...]


class StructuredModelProvider(Protocol):
    """Anything that can answer structured requests, now or later."""

    @property
    def identity(self) -> ProviderIdentity:
        """Who answers."""
        ...

    def submit(self, requests: Sequence[ModelRequest]) -> BatchHandle:
        """Hand over requests; return at once."""
        ...

    def collect(
        self, handle: BatchHandle, requests: Mapping[str, ModelRequest]
    ) -> list[ProviderResult]:
        """Return one result per request in ``handle``, in order.

        ``requests`` maps request IDs to the requests, so answers can be
        validated even after a restart (the provider keeps no memory).
        """
        ...


def validate_output(raw: str | Mapping[str, Any], model: type[BaseModel]) -> BaseModel | str:
    """Check one raw answer against the expected model.

    Args:
        raw: The answer as JSON text or an already-parsed object.
        model: The Pydantic model it must fit.

    Returns:
        The validated model, or a short error message (never the raw text,
        which may contain private content).
    """
    checked = _validate(raw, model)
    return checked if isinstance(checked, str) else checked[0]


def _validate(
    raw: str | Mapping[str, Any], model: type[BaseModel]
) -> tuple[BaseModel, tuple[str, ...]] | str:
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError as error:
        return f"not JSON (line {error.lineno}, column {error.colno})"
    if not isinstance(data, Mapping):
        return "answer must be a JSON object"
    try:
        return model.model_validate(data, strict=False), ()
    except ValidationError as error:
        errors = error.errors(include_input=False, include_url=False)
    # A list longer than the schema allows is cut back to the maximum, once,
    # instead of spending the repair on it (LEG-003): the extra items are
    # the model's lowest-ranked, and a retry tends to overflow again.
    if errors and all(e["type"] == "too_long" for e in errors):
        trimmed_data = json.loads(json.dumps(data))
        trimmed = []
        for item in errors:
            if _trim(trimmed_data, item["loc"], int((item.get("ctx") or {}).get("max_length", 0))):
                trimmed.append(".".join(str(p) for p in item["loc"]))
        if trimmed:
            try:
                return model.model_validate(trimmed_data, strict=False), tuple(trimmed)
            except ValidationError as again:
                errors = again.errors(include_input=False, include_url=False)
    problems = [
        f"{'.'.join(str(p) for p in item['loc']) or '(root)'}: {item['type']}" for item in errors
    ]
    return "does not fit the schema: " + "; ".join(problems[:10])


def _trim(data: Any, loc: tuple[int | str, ...], max_length: int) -> bool:
    for part in loc[:-1]:
        try:
            data = data[part]
        except (KeyError, IndexError, TypeError):
            return False
    last = loc[-1] if loc else None
    target = data.get(last) if isinstance(data, dict) else None
    if not isinstance(target, list) or max_length <= 0:
        return False
    data[last] = target[:max_length]
    return True


def result_from_raw(
    request: ModelRequest,
    raw: str | Mapping[str, Any],
    *,
    served_model: str | None = None,
    session_ref: str | None = None,
) -> ProviderResult:
    """Validate a raw answer and wrap it as an ``ok`` or ``invalid`` result."""
    checked = _validate(raw, request.output_model)
    if isinstance(checked, str):
        return ProviderResult(request.request_id, ResultState.INVALID, error=checked)
    output, trimmed = checked
    return ProviderResult(
        request.request_id,
        ResultState.OK,
        output=output,
        served_model=served_model,
        session_ref=session_ref,
        trimmed=trimmed,
    )


def result_from_response(
    request: ModelRequest,
    response: RawResponse,
    *,
    served_model: str | None = None,
    session_ref: str | None = None,
) -> ProviderResult:
    """Sort out one HTTP-style response (LEG-003).

    * An error envelope, a rate limit (429) or a server error (5xx) is
      ``transient``, even inside HTTP 200: the provider failed, so there is
      no model answer to judge.
    * ``finish_reason=length`` is a format error (``invalid``, recorded),
      even if the cut-off text happens to parse.
    * Anything else is validated like any answer.
    """
    status = response.http_status
    if response.error_type or status == 429 or status >= 500:
        kind = response.error_type or ("rate_limit" if status == 429 else f"http_{status}")
        return ProviderResult(request.request_id, ResultState.TRANSIENT, error=kind)
    if response.finish_reason == "length":
        return ProviderResult(request.request_id, ResultState.INVALID, error=TRUNCATED)
    if response.body is None or status != 200:
        return ProviderResult(
            request.request_id, ResultState.INVALID, error=f"no answer ({status})"
        )
    return result_from_raw(
        request, response.body, served_model=served_model, session_ref=session_ref
    )


@dataclass
class FakeProvider:
    """A provider for tests: canned answers, failures on demand, no network.

    ``answer`` maps a request to its raw answer (JSON text or a dict), or
    None to leave it pending. ``submitted`` records every request it was
    given, so a test can prove a cache hit made zero provider calls.
    """

    answer: Callable[[ModelRequest], str | Mapping[str, Any] | RawResponse | None]
    served_model: str = "fake-model"
    submitted: list[ModelRequest] = field(default_factory=list)

    @property
    def identity(self) -> ProviderIdentity:
        """A fake text model."""
        return ProviderIdentity("fake", Capability.TEXT_LLM, "fake-v1")

    def submit(self, requests: Sequence[ModelRequest]) -> BatchHandle:
        """Remember the requests; answers are produced on ``collect``."""
        self.submitted.extend(requests)
        batch = f"fake-{len(self.submitted)}"
        return BatchHandle((batch,), tuple(r.request_id for r in requests))

    def collect(
        self, handle: BatchHandle, requests: Mapping[str, ModelRequest]
    ) -> list[ProviderResult]:
        """Answer each request with ``answer``, validated."""
        results = []
        for request_id in handle.request_ids:
            request = requests[request_id]
            raw = self.answer(request)
            if raw is None:
                results.append(ProviderResult(request_id, ResultState.PENDING))
            elif isinstance(raw, RawResponse):
                results.append(result_from_response(request, raw, served_model=self.served_model))
            else:
                results.append(result_from_raw(request, raw, served_model=self.served_model))
        return results


@dataclass
class ReplayProvider:
    """Answers from stored response files, so re-runs and tests are deterministic.

    Reads every ``*.response.jsonl`` under ``root``; the first valid line
    for a request ID wins. Never makes a call; anything not on file is
    ``pending``.
    """

    root: Path

    @property
    def identity(self) -> ProviderIdentity:
        """Replays need no egress, but stay classed as a text model."""
        return ProviderIdentity("replay", Capability.TEXT_LLM, "replay-v1", sends_data=False)

    def submit(self, requests: Sequence[ModelRequest]) -> BatchHandle:
        """Nothing to send: answers are already on file."""
        return BatchHandle(("replay",), tuple(r.request_id for r in requests))

    def collect(
        self, handle: BatchHandle, requests: Mapping[str, ModelRequest]
    ) -> list[ProviderResult]:
        """Look each request up in the stored responses."""
        lines = read_response_lines(sorted(self.root.rglob("*.response.jsonl")))
        results = []
        for request_id in handle.request_ids:
            line = lines.get(request_id)
            if line is None:
                results.append(ProviderResult(request_id, ResultState.PENDING))
                continue
            results.append(
                result_from_raw(
                    requests[request_id],
                    line.get("output", {}),
                    served_model=_text(line.get("served_model")),
                    session_ref=_text(line.get("session_ref")),
                )
            )
        return results


def read_response_lines(files: Iterable[Path]) -> dict[str, dict[str, Any]]:
    """Read response JSONL files: request ID -> its first complete line.

    A line that isn't a JSON object with a ``request_id`` (for example a
    last line cut off when a session stopped) is skipped, never guessed at.
    A later line for the same request never replaces the first.
    """
    found: dict[str, dict[str, Any]] = {}
    for path in files:
        for text in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                line = json.loads(text)
            except json.JSONDecodeError:
                continue
            if isinstance(line, dict) and isinstance(line.get("request_id"), str):
                found.setdefault(line["request_id"], line)
    return found


def _text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None
