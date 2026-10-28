"""Keep text that isn't the conversation out of extraction (NOTE-016).

The first real score of rich notes (``docs/evaluation/NOTE-011_REAL.md``)
found two kinds of text being read as if the user had said it in the chat:

* **pasted profiles**: the same custom-instruction paragraph ("I prefer
  British spelling. Answers must be short...") at the top of many chats
  became a requirement in 10 of 15 notes;
* **assistant drafts**: a letter or email the assistant wrote *for* the
  user ("I will send the invoice on Friday") became suggestions, actions
  and requirements, often twice.

A ``Cleaner`` hides three things from the extractors:

1. a paragraph that appears in many chats (the rule the taxonomy pack
   uses, counted in chats here): boilerplate, not this chat's subject;
2. a user message that is a pasted setup prompt ("You are...", "Act as...");
3. inside an assistant message, drafted content: a letter or email (from
   "Dear ..." or "Subject: ..." to the sign-off), or a fenced block of
   prose (a fence with no language, or ``text``/``markdown``). Fences with
   a programming language stay: code is an artefact, not a draft.

**How it hides them, and why:** the hidden characters are replaced with
spaces, keeping line breaks, so the text keeps its exact length. Every
sentence the extractors still see sits at the same position in the stored
message, so its evidence (start, end and fingerprint) still checks out
against the archive. Nothing stored is changed; the cleaner only changes
what an extractor is shown.

Talking points:
    - "A profile pasted into 50 chats is one paragraph of setup, not 50
      requirements."
    - "I blank the text out with spaces instead of deleting it, so every
      quote still points at the right characters in the original."
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.domain.enums import Role
from knowledge_engine.extraction.model_knowledge import is_preamble
from knowledge_engine.extraction.text import ExtractionMessage

CLEAN_VERSION = "note-016-v1"

# A paragraph in more chats than this is boilerplate; the same floor the
# taxonomy pack uses (BOILERPLATE_MIN_SEGMENTS), and at least 1% of chats.
REPEATED_MIN_CHATS = 5
# A paragraph this short ("Thanks!", "Yes.") repeats for innocent reasons.
REPEATED_MIN_CHARS = 40

_PARAGRAPH = re.compile(r"[^\n]+(?:\n(?!\s*\n)[^\n]*)*")
# A letter or email the assistant drafted: from its greeting or subject line
# to the sign-off and the name under it.
_DRAFT = re.compile(
    r"^[ \t>*_]*(?:dear\b|subject\s*:|to whom it may concern\b)[\s\S]*?"
    r"^[ \t>*_]*(?:best(?: regards| wishes)?|kind regards|warm regards|regards|sincerely|"
    r"yours (?:sincerely|faithfully|truly)|many thanks|thanks(?: again)?|cheers)\b[^\n]*"
    r"(?:\n[ \t]*[^\n]+)?",
    re.IGNORECASE | re.MULTILINE,
)
# A fenced block of prose: no language, or a prose one.
_PROSE_FENCE = re.compile(
    r"^(`{3,}|~{3,})[ \t]*(?:text|txt|markdown|md|plain|plaintext)?[ \t]*\n[\s\S]*?^\1[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)


def normalise(paragraph: str) -> str:
    """A paragraph with its spacing evened out, as it is compared."""
    return " ".join(paragraph.split())


def repeated_paragraphs(chats: Iterable[Sequence[ExtractionMessage]]) -> frozenset[str]:
    """Paragraphs that appear in many chats (see ``REPEATED_MIN_CHATS``).

    Args:
        chats: Each chat's messages (all of them, not one segment).

    Returns:
        The normalised paragraphs to hide.
    """
    seen: Counter[str] = Counter()
    total = 0
    for messages in chats:
        total += 1
        here = {
            normalise(m.group())
            for message in messages
            for m in _PARAGRAPH.finditer(message.text)
            if len(normalise(m.group())) >= REPEATED_MIN_CHARS
        }
        seen.update(here)
    floor = max(REPEATED_MIN_CHATS, total // 100)
    return frozenset(p for p, n in seen.items() if n > floor)


def drafted_spans(text: str) -> list[tuple[int, int]]:
    """Where an assistant message holds drafted content (letters, prose fences)."""
    spans = [(m.start(), m.end()) for m in _DRAFT.finditer(text)]
    spans += [(m.start(), m.end()) for m in _PROSE_FENCE.finditer(text)]
    return sorted(spans)


def _blank(text: str, spans: Iterable[tuple[int, int]]) -> str:
    """The text with each span's characters turned to spaces (line breaks kept)."""
    chars = list(text)
    for start, end in spans:
        for i in range(start, end):
            if chars[i] != "\n":
                chars[i] = " "
    return "".join(chars)


@dataclass(frozen=True)
class Cleaner:
    """What to hide from extractors, for one workspace's chats.

    Attributes:
        repeated: Boilerplate paragraphs (``repeated_paragraphs``).
        version: Part of each extraction run's key, through the text it changes.
    """

    repeated: frozenset[str] = field(default_factory=frozenset)
    version: str = CLEAN_VERSION

    def hidden(self, message: ExtractionMessage) -> list[tuple[int, int]]:
        """The character ranges of one message that extractors shouldn't read."""
        # The same setup-prompt rule the model extractor uses (NOTE-005).
        if is_preamble(message):
            return [(0, len(message.text))]
        spans = [
            (m.start(), m.end())
            for m in _PARAGRAPH.finditer(message.text)
            if normalise(m.group()) in self.repeated
        ]
        if message.role is Role.ASSISTANT:
            spans += drafted_spans(message.text)
        return spans

    def clean(self, messages: Sequence[ExtractionMessage]) -> list[ExtractionMessage]:
        """The messages as extractors should see them: same lengths, hidden parts blank."""
        out = []
        for message in messages:
            spans = self.hidden(message)
            if spans:
                message = ExtractionMessage(
                    message.native_id,
                    message.revision_id,
                    message.role,
                    _blank(message.text, spans),
                )
            out.append(message)
        return out


def workspace_cleaner(session: Session) -> Cleaner:
    """A cleaner for every chat in the workspace: boilerplate counted across all of them.

    Every message of each chat counts, branches included, so a profile
    pasted into an edited question is still seen as the same paragraph.
    """
    from knowledge_engine.importer.records import ConversationRow
    from knowledge_engine.rendering.transcript import load_conversation

    def chats() -> Iterable[list[ExtractionMessage]]:
        for conversation_id in session.scalars(select(ConversationRow.conversation_id)):
            chat = load_conversation(session, conversation_id)
            yield [
                ExtractionMessage(native, chat.revisions.get(native, ""), Role.UNKNOWN, node.text)
                for native, node in chat.messages.items()
                if node.text
            ]

    return Cleaner(repeated_paragraphs(chats()))
