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

Some endings leave something open even though nothing is asked (NOTE-023,
from the re-score, which found 0 of 9 open questions):

* the assistant's **last message holds a draft** (a letter, an email, a
  block of text to send) and the user never said it went out: **open**;
* the user's last message **promises to report back** ("I'll let you
  know") or **puts a choice off** ("I'll decide later"): **open**.

Each of these, and an unanswered question, also becomes an open question
in the digest, citing the closing message, when the model didn't list one.

The status itself is decided once, for the whole chat, in
``digest/status.py`` (NOTE-034): that module holds the rule table, which
combines the ending read here with the open questions still open after
the parts are reconciled (NOTE-028's "keep open" rule lives there too).

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
from knowledge_engine.extraction.clean import drafted_spans
from knowledge_engine.extraction.text import ExtractionMessage, quote
from knowledge_engine.graph.offsets import find_quote
from knowledge_engine.rendering.transcript import StoredConversation

# note-023-v1: drafts, report-backs; note-028-v1: open questions keep a chat open;
# note-034-v1: the status is decided once, for the whole chat (digest/status.py).
ENDING_VERSION = "note-034-v1"

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
# The user will come back with news, or hasn't chosen yet.
_REPORT_BACK = re.compile(
    r"\b(i'?ll|i will)\b[^.!?\n]*?\b"
    r"(let you know|report back|get back to you|update you|keep you posted)\b",
    re.IGNORECASE,
)
_PUT_OFF = re.compile(
    r"\b(i'?ll|i will|let me) (think (about|it over)|decide later|sleep on it|"
    r"come back to (this|it|you)|decide (tomorrow|next week|after))\b|\bdecide later\b",
    re.IGNORECASE,
)
_SENTENCES = re.compile(r"(?<=[.!?])\s+")
_WORD_START = re.compile(r"(?<!\S)\S")
_DONE_MAX_CHARS = 80  # a thank-you longer than this is probably a new request


class Ending(StrEnum):
    """How the chat's last turns read."""

    USER_DONE = "user_done"  # the user said thanks or done
    ASSISTANT_OFFER = "assistant_offer"  # a result, then an offer of more
    USER_QUESTION = "user_question"  # the user asked and no one answered
    UNSENT_DRAFT = "unsent_draft"  # the assistant drafted something to send
    REPORT_BACK = "report_back"  # the user will come back with news
    PUT_OFF = "put_off"  # the user left a choice for later
    OTHER = "other"  # no rule applies: the model's reading stands


STATUS_FOR = {
    Ending.USER_DONE: ChatStatus.SETTLED,
    Ending.ASSISTANT_OFFER: ChatStatus.SETTLED,
    Ending.USER_QUESTION: ChatStatus.OPEN,
    Ending.UNSENT_DRAFT: ChatStatus.OPEN,
    Ending.REPORT_BACK: ChatStatus.OPEN,
    Ending.PUT_OFF: ChatStatus.OPEN,
}

# The open question an ending leaves, in plain words ({} is the user's question).
OPEN_QUESTION_FOR = {
    Ending.USER_QUESTION: "{}",
    Ending.UNSENT_DRAFT: "The draft in the last message isn't confirmed as sent.",
    Ending.REPORT_BACK: "The user said they would report back; the chat has no follow-up.",
    Ending.PUT_OFF: "The user left the choice for later; the chat doesn't record it.",
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
        # "Thanks. And how many coats...?" is a new question, not a sign-off.
        and "?" not in last_user.text
        and messages.index(last_user) >= len(messages) - 2
    ):
        return ChatEnding(Ending.USER_DONE, last_user)
    # A draft to send, with nothing after it: the sending is still to come.
    if last.role is Role.ASSISTANT and drafted_spans(last.text):
        return ChatEnding(Ending.UNSENT_DRAFT, last)
    if last_user is not None and messages.index(last_user) >= len(messages) - 2:
        if _REPORT_BACK.search(last_user.text):
            return ChatEnding(Ending.REPORT_BACK, last_user)
        if _PUT_OFF.search(last_user.text):
            return ChatEnding(Ending.PUT_OFF, last_user)
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


def status_item(status: ChatStatus, message: ExtractionMessage) -> DigestItem | None:
    """The status as an item citing ``message``'s last words; None if they aren't found."""
    # Cite the deciding message by its last words (where the ending is), as
    # written: a letter's last words run over line breaks ("regards,\nSam").
    starts = [m.start() for m in _WORD_START.finditer(message.text)]
    tail = message.text[starts[-8] if len(starts) >= 8 else 0 :].rstrip() if starts else ""
    spans = find_quote(message.text, tail) if tail else []
    if not spans:
        return None
    return DigestItem(
        text=status.value,
        provenance=FIELD_PROVENANCE["status"],
        message_ids=(message.native_id,),
        evidence=(quote(message, spans[0]),),
    )


def _question_text(message: ExtractionMessage) -> str:
    # The user's last sentence with a question mark, in their own words.
    sentences = [x for x in _SENTENCES.split(message.text.strip()) if "?" in x]
    return " ".join((sentences[-1] if sentences else message.text).split())


def ending_questions(
    digest: ConversationDigest,
    messages: list[ExtractionMessage],
    conversation: StoredConversation,
) -> ConversationDigest:
    """The digest with the open question its ending leaves, if the model missed it (NOTE-023).

    Nothing is added when an open question already cites the closing
    message. An added one cites that message and is flagged for review.
    """
    found = chat_ending(messages, conversation)
    wording = OPEN_QUESTION_FOR.get(found.ending)
    if wording is None or found.message is None:
        return digest
    if any(found.message.native_id in q.message_ids for q in digest.open_questions):
        return digest
    cited = status_item(ChatStatus.OPEN, found.message)
    if cited is None:
        return digest
    item = DigestItem(
        text=wording.format(_question_text(found.message)),
        provenance=FIELD_PROVENANCE["open_questions"],
        message_ids=cited.message_ids,
        evidence=cited.evidence,
    )
    flag = DigestFlag(
        field="open_questions",
        index=len(digest.open_questions),
        reason=f"added: the chat ends with {found.ending.value} ({ENDING_VERSION})",
    )
    return digest.model_copy(
        update={
            "open_questions": (*digest.open_questions, item),
            "flags": (*digest.flags, flag),
        }
    )
