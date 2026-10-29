"""The conversation digest contract (NOTE-002).

A *digest* is what a model writes about one whole chat so the knowledge
note can be read by a person: a short summary, what the chat was for, how
it ended, its topics, and the generated parts Louis asked to see (insights,
tensions, next steps; decision D3). It lives apart from knowledge records
(decision D5): a generated insight must never sit next to a confirmed
decision as if it were the same kind of thing.

Two shapes, like the model extractor:

* ``DigestAnswer`` is what the model returns. ``extra="forbid"`` refuses
  any field we did not ask for, and every item must cite at least one
  message with a short exact quote, so an uncited sentence can't even be
  parsed.
* ``ConversationDigest`` is what we keep, built by ``resolve_digest``. Each
  quote is looked up in the real message text (NRM-003 / LEG-004
  matching) and becomes exact, fingerprinted evidence. If **any** quote of
  an item cites a message that is not in the chat, or words that are not
  in that message, the whole item is dropped and the drop is recorded in
  ``flags``. A digest item is either fully backed by the chat or not shown.

Each field's provenance is fixed here (``FIELD_PROVENANCE``), never chosen
by the model, so the note's "From the chat" / "Generated" labels can't be
talked into something else.

Talking points:
    - "The model can only fill the boxes we drew. An extra box, or a
      sentence with no citation, is refused before we read it."
    - "One bad quote sinks the whole sentence it was meant to support."
    - "Whether a section counts as 'from the chat' or 'generated' is our
      rule, not the model's opinion."
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from knowledge_engine.domain.models import EvidenceRef
from knowledge_engine.extraction.text import ExtractionMessage, quote
from knowledge_engine.graph.offsets import find_quote
from knowledge_engine.providers.base import MessageRef

DIGEST_SCHEMA_VERSION = "note-002-v1"

# Short quotes keep the model honest and the note readable: long enough
# for a clause, too short to paste a paragraph.
MAX_QUOTE_CHARS = 300
MAX_QUOTES_PER_ITEM = 5


class Provenance(StrEnum):
    """Where a section's content comes from, as the note labels it."""

    FROM_CHAT = "from_chat"  # said in the chat; the model only picked it out
    GENERATED = "generated"  # the model's own words, cited; check before relying on it


class ChatStatus(StrEnum):
    """How the chat ended (the note's ``status`` property)."""

    OPEN = "open"  # still going, or left with things unresolved
    SETTLED = "settled"  # reached an answer or a result
    ABANDONED = "abandoned"  # dropped without one


class Intent(StrEnum):
    """What the user wanted from the chat, at the coarsest level."""

    LEARN = "learn"
    BUILD = "build"
    DECIDE = "decide"
    CREATE = "create"
    FIX = "fix"
    PLAN = "plan"
    EXPLORE = "explore"
    OTHER = "other"


# Fixed per field. Only open questions are things literally said in the
# chat; everything else is the model's wording, so it is labelled generated.
FIELD_PROVENANCE: Mapping[str, Provenance] = {
    "summary": Provenance.GENERATED,
    "purpose": Provenance.GENERATED,
    "outcome": Provenance.GENERATED,
    "status": Provenance.GENERATED,
    "intent": Provenance.GENERATED,
    "topics": Provenance.GENERATED,
    "insights": Provenance.GENERATED,
    "tensions": Provenance.GENERATED,
    "open_questions": Provenance.FROM_CHAT,
    "next_steps": Provenance.GENERATED,
}


class DigestQuote(BaseModel):
    """A short exact quote from one message."""

    model_config = ConfigDict(extra="forbid")

    message_id: MessageRef = Field(min_length=1)
    text: str = Field(min_length=1, max_length=MAX_QUOTE_CHARS)


class DigestItemAnswer(BaseModel):
    """One sentence or phrase, with what it rests on."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=500)
    quotes: list[DigestQuote] = Field(min_length=1, max_length=MAX_QUOTES_PER_ITEM)


class StatusAnswer(BaseModel):
    """The chat's status and why."""

    model_config = ConfigDict(extra="forbid")

    value: ChatStatus
    quotes: list[DigestQuote] = Field(min_length=1, max_length=MAX_QUOTES_PER_ITEM)


class IntentAnswer(BaseModel):
    """The user's intent, a one-line description, and why."""

    model_config = ConfigDict(extra="forbid")

    value: Intent
    text: str = Field(min_length=1, max_length=300)
    quotes: list[DigestQuote] = Field(min_length=1, max_length=MAX_QUOTES_PER_ITEM)


class DigestAnswer(BaseModel):
    """A model's whole digest of one chat."""

    model_config = ConfigDict(extra="forbid")

    summary: list[DigestItemAnswer] = Field(min_length=1, max_length=4)
    purpose: DigestItemAnswer | None = None
    outcome: DigestItemAnswer | None = None
    status: StatusAnswer
    intent: IntentAnswer
    topics: list[DigestItemAnswer] = Field(default_factory=list, max_length=8)
    insights: list[DigestItemAnswer] = Field(default_factory=list, max_length=5)
    tensions: list[DigestItemAnswer] = Field(default_factory=list, max_length=5)
    open_questions: list[DigestItemAnswer] = Field(default_factory=list, max_length=8)
    next_steps: list[DigestItemAnswer] = Field(default_factory=list, max_length=5)


# ---- What we keep -----------------------------------------------------------


class DigestItem(BaseModel):
    """A digest item whose every quote was found in the chat."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str = Field(min_length=1)
    provenance: Provenance
    message_ids: tuple[str, ...] = Field(min_length=1)
    evidence: tuple[EvidenceRef, ...] = Field(min_length=1)


class DigestFlag(BaseModel):
    """Why an item was left out (shown to a reviewer, never in the note body)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    field: str
    index: int = Field(ge=0)
    reason: str


class ResolvedQuestion(BaseModel):
    """An open question a later user message answered (NOTE-032).

    Kept, not deleted, so a reviewer can see why the note no longer lists it.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    question: DigestItem
    resolved_by: EvidenceRef


class ConversationDigest(BaseModel):
    """The checked digest of one chat.

    ``status`` and ``intent`` are ``None`` when their quotes failed: the
    note then says it doesn't know rather than guessing. ``summary`` may
    end up empty for the same reason, and the digest is then not usable
    (``usable`` is False) and goes to review.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    summary: tuple[DigestItem, ...]
    purpose: DigestItem | None
    outcome: DigestItem | None
    status: ChatStatus | None
    status_item: DigestItem | None
    intent: Intent | None
    intent_item: DigestItem | None
    topics: tuple[DigestItem, ...]
    insights: tuple[DigestItem, ...]
    tensions: tuple[DigestItem, ...]
    open_questions: tuple[DigestItem, ...]
    next_steps: tuple[DigestItem, ...]
    flags: tuple[DigestFlag, ...]
    schema_version: str = DIGEST_SCHEMA_VERSION
    # NOTE-032: open questions a later user message answered, with that answer.
    resolved_questions: tuple[ResolvedQuestion, ...] = ()
    # NOTE-033: the part number of a long chat's last part when no summary
    # sentence from it survived, so the note can say the ending isn't summarised.
    ending_unsummarised: int | None = None

    @property
    def usable(self) -> bool:
        """At least one summary sentence survived the quote check."""
        return bool(self.summary)


@dataclass(frozen=True)
class _Resolved:
    item: DigestItem | None
    reason: str | None


def _resolve_item(
    field: str,
    text: str,
    quotes: Sequence[DigestQuote],
    by_id: Mapping[str, ExtractionMessage],
) -> _Resolved:
    evidence: list[EvidenceRef] = []
    message_ids: list[str] = []
    for cited in quotes:
        message = by_id.get(cited.message_id)
        if message is None:
            return _Resolved(None, "cites a message that is not in the chat")
        spans = find_quote(message.text, cited.text)
        if not spans:
            return _Resolved(None, "quote not found in the cited message")
        evidence.append(quote(message, spans[0]))
        if message.native_id not in message_ids:
            message_ids.append(message.native_id)
    item = DigestItem(
        text=text,
        provenance=FIELD_PROVENANCE[field],
        message_ids=tuple(message_ids),
        evidence=tuple(evidence),
    )
    return _Resolved(item, None)


def resolve_digest(
    answer: DigestAnswer, messages: Sequence[ExtractionMessage]
) -> ConversationDigest:
    """Check every quote against the chat and keep only fully backed items.

    Args:
        answer: The model's validated answer.
        messages: The chat's messages the model was shown (exact revisions).

    Returns:
        The digest, with a flag for every dropped item.
    """
    by_id = {m.native_id: m for m in messages}
    flags: list[DigestFlag] = []

    def one(field: str, index: int, text: str, quotes: Sequence[DigestQuote]) -> DigestItem | None:
        resolved = _resolve_item(field, text, quotes, by_id)
        if resolved.reason is not None:
            flags.append(DigestFlag(field=field, index=index, reason=resolved.reason))
        return resolved.item

    def many(field: str, items: Sequence[DigestItemAnswer]) -> tuple[DigestItem, ...]:
        kept = (one(field, i, item.text, item.quotes) for i, item in enumerate(items))
        return tuple(item for item in kept if item is not None)

    purpose = (
        one("purpose", 0, answer.purpose.text, answer.purpose.quotes) if answer.purpose else None
    )
    outcome = (
        one("outcome", 0, answer.outcome.text, answer.outcome.quotes) if answer.outcome else None
    )
    status_item = one("status", 0, answer.status.value.value, answer.status.quotes)
    intent_item = one("intent", 0, answer.intent.text, answer.intent.quotes)
    return ConversationDigest(
        summary=many("summary", answer.summary),
        purpose=purpose,
        outcome=outcome,
        status=answer.status.value if status_item else None,
        status_item=status_item,
        intent=answer.intent.value if intent_item else None,
        intent_item=intent_item,
        topics=many("topics", answer.topics),
        insights=many("insights", answer.insights),
        tensions=many("tensions", answer.tensions),
        open_questions=many("open_questions", answer.open_questions),
        next_steps=many("next_steps", answer.next_steps),
        flags=tuple(flags),
    )
