"""How a chat ended, read from its last turns, to decide the digest's status (NOTE-019).

The first real score (``docs/evaluation/NOTE-011_REAL.md``) found the model
calling chats "open" when the user had got what they asked for and the
assistant simply ended on an offer: "Want me to make another version?".
Nothing is unresolved there; the assistant always offers more.

So the status is checked against the chat's ending, by rules a person can
read:

* the user's **last message is a thank-you or "done"** (whatever short
  reply the assistant gave after it): **settled**;
* the **last message is the assistant's**, it **delivered something**
  (text before its closing offer, or an image) and it **ends on an offer**
  ("Want me to…?", "Would you like…", "Let me know if…"): **settled**;
* the **last message is the user's and asks something** no one answered:
  **open**;
* anything else: the model's reading stands.

When a rule applies and the model said otherwise, the rule wins, and a flag
records the change for a reviewer, so the correction is never silent. The
new status cites the message that decided it.

Talking points:
    - "'Want me to do another?' isn't an open question. It's the assistant
      being polite after the job was done, and a short rule says so."
    - "The rule never hides what the model said: every correction is
      flagged for review."
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from knowledge_engine.digest.contract import (
    FIELD_PROVENANCE,
    ChatStatus,
    ConversationDigest,
    DigestFlag,
    DigestItem,
)
from knowledge_engine.domain.enums import Role
from knowledge_engine.extraction.text import ExtractionMessage, quote
from knowledge_engine.graph.offsets import find_quote
from knowledge_engine.rendering.transcript import StoredConversation

ENDING_VERSION = "note-019-v1"

# An offer of more help. Matched only in the assistant's closing sentence.
_OFFER = re.compile(
    r"\b(want me to|would you like( me)? to|would you like|do you want me to|shall i|"
    r"should i (also|go ahead)|if you('d| would)? like|if you want|let me know if|"
    r"happy to (help|make|adjust|create)|i can also)\b",
    re.IGNORECASE,
)
# A thank-you or sign-off from the user, as the whole of a short message.
_DONE = re.compile(
    r"^\W*(ok(ay)?[, ]+)?(thanks?( you)?( so much| a lot)?|thank you|cheers|perfect|great|"
    r"that'?s (all|it|great|perfect)|all done|done|sorted|that works|got it)\b[\s\S]{0,60}$",
    re.IGNORECASE,
)
_SENTENCES = re.compile(r"(?<=[.!?])\s+")
_DONE_MAX_CHARS = 80  # a thank-you longer than this is probably a new request


class Ending(StrEnum):
    """How the chat's last turns read."""

    USER_DONE = "user_done"  # the user said thanks or done
    ASSISTANT_OFFER = "assistant_offer"  # a result, then an offer of more
    USER_QUESTION = "user_question"  # the user asked and no one answered
    OTHER = "other"  # no rule applies: the model's reading stands


STATUS_FOR = {
    Ending.USER_DONE: ChatStatus.SETTLED,
    Ending.ASSISTANT_OFFER: ChatStatus.SETTLED,
    Ending.USER_QUESTION: ChatStatus.OPEN,
}


@dataclass(frozen=True)
class ChatEnding:
    """The ending and the message that shows it (None for ``OTHER``)."""

    ending: Ending
    message: ExtractionMessage | None = None


def _ends_on_offer(text: str) -> bool:
    sentences = [s for s in _SENTENCES.split(text.strip()) if s.strip()]
    return bool(sentences) and _OFFER.search(sentences[-1]) is not None


def _delivered(message: ExtractionMessage, conversation: StoredConversation) -> bool:
    # Something besides the offer: an earlier sentence, or an image or file.
    if conversation.media.get(message.revision_id):
        return True
    sentences = [s for s in _SENTENCES.split(message.text.strip()) if s.strip()]
    return len(sentences) > 1


def chat_ending(messages: list[ExtractionMessage], conversation: StoredConversation) -> ChatEnding:
    """Read the chat's ending from its active path (``chat_messages``).

    Args:
        messages: The active path's messages with text, in order.
        conversation: The stored chat (for the images a message carries).
    """
    if not messages:
        return ChatEnding(Ending.OTHER)
    last = messages[-1]
    users = [m for m in messages if m.role is Role.USER]
    last_user = users[-1] if users else None
    # "Thanks!" then the assistant's "You're welcome" still ends on the thanks.
    if (
        last_user is not None
        and len(last_user.text.strip()) <= _DONE_MAX_CHARS
        and _DONE.match(last_user.text.strip())
        and messages.index(last_user) >= len(messages) - 2
    ):
        return ChatEnding(Ending.USER_DONE, last_user)
    if last.role is Role.ASSISTANT and _ends_on_offer(last.text):
        previous = messages[-2] if len(messages) > 1 else None
        if _delivered(last, conversation) or (
            previous is not None
            and previous.role is Role.ASSISTANT
            and _delivered(previous, conversation)
        ):
            return ChatEnding(Ending.ASSISTANT_OFFER, last)
    if last.role is Role.USER and "?" in last.text:
        return ChatEnding(Ending.USER_QUESTION, last)
    return ChatEnding(Ending.OTHER)


def _status_item(status: ChatStatus, message: ExtractionMessage) -> DigestItem | None:
    # Cite the deciding message by its last words (where the ending is).
    words = message.text.split()
    tail = " ".join(words[-8:])
    spans = find_quote(message.text, tail) if tail else []
    if not spans:
        return None
    return DigestItem(
        text=status.value,
        provenance=FIELD_PROVENANCE["status"],
        message_ids=(message.native_id,),
        evidence=(quote(message, spans[0]),),
    )


def settle_status(
    digest: ConversationDigest,
    messages: list[ExtractionMessage],
    conversation: StoredConversation,
) -> ConversationDigest:
    """The digest with its status checked against how the chat ended.

    A rule that applies and disagrees with the model replaces the status,
    with a flag saying what the model had said and why it changed.
    """
    found = chat_ending(messages, conversation)
    wanted = STATUS_FOR.get(found.ending)
    if wanted is None or found.message is None or digest.status is wanted:
        return digest
    item = _status_item(wanted, found.message)
    if item is None:
        return digest
    said = digest.status.value if digest.status else "no status"
    flag = DigestFlag(
        field="status",
        index=0,
        reason=f"changed from {said} to {wanted.value}: the chat ends with {found.ending.value} "
        f"({ENDING_VERSION})",
    )
    return digest.model_copy(
        update={"status": wanted, "status_item": item, "flags": (*digest.flags, flag)}
    )
