"""The chat's status, decided once for the whole chat (NOTE-034).

The NOTE-013 pass 1 score found status right in only 3 of 10 notes, wrong
in both directions. Before this, two checks ran one after the other: one
set the status from the ending (NOTE-019), then another could flip it back
because of an open question (NOTE-028). Each looked at less than the whole
picture, and a long chat could get two contradicting flags. Now the status
is decided **once**, after the parts are merged and their open questions
reconciled (NOTE-032), from two things only:

* the **ending**: how the chat's last turns read (``digest/ending.py``);
* the **open questions still open after reconciling**, from every part,
  before the merge cuts the list to its maximum. Only a question that
  **cites the last exchange** (the user's last message or anything after
  it) counts. A question from earlier in the chat may have been answered
  later, so on its own it says nothing about how the chat ended.

Rule table (first matching row wins):

====  ===================================  ==========================  ==============
Row   Ending                               Open question in the last   Status
                                           exchange?
====  ===================================  ==========================  ==============
1     user_done ("thanks, that's done")    ignored                     settled
2     user_question, unsent_draft,         ignored                     open
      report_back, put_off
3     assistant_offer (a result, then      yes, citing more than the   open
      "Want me to...?")                    closing offer
4     assistant_offer                      no (or only the offer)      settled
5     other, and the model said settled    yes                         open
6     other, anything else                 any                         the model's
                                                                       reading
====  ===================================  ==========================  ==============

Row 3 and row 4 look at each question on its own: a question that cites
only the closing offer is the offer itself ("Want me to do another?"),
which is not unfinished business, and an unrelated earlier question can't
change that. Row 6 leaves "open", "abandoned" and a missing status alone:
with no rule, the model's reading of the whole chat is the best we have.

When the decision differs from what the model said, the new status cites
the message that decided it and one flag says what changed and why. The
model's answer is never re-requested: the rule runs on stored answers.

Talking points:
    - "Status is decided once, from how the whole chat ends, after the
      parts' questions are reconciled. Not part by part."
    - "A question from early in the chat can't keep a finished chat open.
      Only a question in the last exchange can."
"""

from __future__ import annotations

from collections.abc import Sequence

from knowledge_engine.digest.contract import ChatStatus, ConversationDigest, DigestFlag, DigestItem
from knowledge_engine.digest.ending import (
    ENDING_VERSION,
    STATUS_FOR,
    Ending,
    chat_ending,
    status_item,
)
from knowledge_engine.domain.enums import Role
from knowledge_engine.extraction.text import ExtractionMessage
from knowledge_engine.rendering.transcript import StoredConversation

# The status rules' version is the ending rules' version: the two are one rule set.
STATUS_VERSION = ENDING_VERSION


def _last_exchange_cite(
    questions: Sequence[DigestItem],
    messages: Sequence[ExtractionMessage],
    ignore: str | None,
) -> ExtractionMessage | None:
    """The latest last-exchange message an open question cites, or None.

    ``ignore`` is the closing offer's ID: a question counts only for the
    last-exchange messages it cites besides that one.
    """
    order = {m.native_id: n for n, m in enumerate(messages)}
    users = [n for n, m in enumerate(messages) if m.role is Role.USER]
    start = users[-1] if users else 0
    late = [
        order[i]
        for q in questions
        for i in q.message_ids
        if i != ignore and order.get(i, -1) >= start
    ]
    return messages[max(late)] if late else None


def decide_status(
    digest: ConversationDigest,
    messages: list[ExtractionMessage],
    conversation: StoredConversation,
    still_open: Sequence[DigestItem] = (),
) -> ConversationDigest:
    """The digest with its status decided by the rule table above.

    Args:
        digest: The merged, checked digest. Its ``status`` is the model's
            reading (from the last part, for a long chat).
        messages: The chat's active-path messages, in order.
        conversation: The stored chat (for the images a message carries).
        still_open: Every open question still open after reconciling, from
            all parts and before the merge's cap. The digest's own open
            questions are always counted too.

    Returns:
        The digest unchanged when the rules agree with the model or don't
        apply; otherwise with the new status, its citation and one flag.
    """
    found = chat_ending(messages, conversation)
    said = digest.status
    questions = [*digest.open_questions, *still_open]
    wanted: ChatStatus | None = None
    by: ExtractionMessage | None = None
    why = ""
    if found.ending in STATUS_FOR:  # rows 1, 2 and 4
        wanted, by = STATUS_FOR[found.ending], found.message
        why = f"the chat ends with {found.ending.value}"
    if found.ending in (Ending.ASSISTANT_OFFER, Ending.OTHER):  # rows 3 and 5
        offer = found.message if found.ending is Ending.ASSISTANT_OFFER else None
        late = _last_exchange_cite(questions, messages, offer.native_id if offer else None)
        if late is not None and (offer is not None or said is ChatStatus.SETTLED):
            wanted, by = ChatStatus.OPEN, late
            why = "an open question cites the last exchange"
    if wanted is None or by is None or wanted is said:
        return digest
    item = status_item(wanted, by)
    if item is None:
        return digest
    before = said.value if said else "no status"
    flag = DigestFlag(
        field="status",
        index=0,
        reason=f"changed from {before} to {wanted.value}: {why} ({STATUS_VERSION})",
    )
    return digest.model_copy(
        update={"status": wanted, "status_item": item, "flags": (*digest.flags, flag)}
    )
