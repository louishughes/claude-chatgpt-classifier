"""Spotting a pasted setup prompt: custom instructions or a role-play opening.

People often paste the same "You are a senior editor..." or "Act as..."
text at the top of many chats. It is an instruction to ChatGPT, not part
of the conversation's subject, so:

* the knowledge extractor (NOTE-005) never takes a decision from it;
* the keyword step (NOTE-007) lists its words as excluded;
* the relationship detectors (NOTE-009) never call two chats related, or
  one a quote of the other, because they share it.

This module has no dependencies beyond ``re`` so any of those can import it.

Talking points:
    - "'You are an expert chef' at the top of two chats doesn't make them
      the same conversation."
"""

from __future__ import annotations

import re

# Opening words of a pasted setup prompt (custom instructions, role-play).
_PREAMBLE = re.compile(
    r"^\s*(?:#+\s*)?(?:you are\b|you're\b|act as\b|pretend\b|from now on\b|"
    r"system\s*:|role\s*:|instructions?\s*:|custom instructions\b|"
    r"i want you to act\b|your role\b)",
    re.IGNORECASE,
)
# A setup prompt is long; "you are right" in a short reply is not one.
PREAMBLE_MIN_CHARS = 200


def looks_like_preamble(role: str | None, text: str) -> bool:
    """True for a user message that reads as a pasted setup prompt."""
    return role == "user" and len(text) >= PREAMBLE_MIN_CHARS and _PREAMBLE.match(text) is not None
