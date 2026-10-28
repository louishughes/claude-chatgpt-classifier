"""Preferences and requirements, by rule (EXT-004).

Only the **user's** sentences are read: an assistant saying "I prefer
spaces" is not the user's preference. Each matching sentence becomes one
candidate:

* **requirement**: a constraint on the work.
  - *hard*: "must", "has to", "needs to", "no more than", "at least"...
  - *soft*: "ideally", "preferably", "would be nice", "if possible"...

  A hard cue wins over a soft one in the same sentence.
* **preference**: a taste.
  - *for*: "I prefer", "I like", "I'd rather", "my favourite"...
  - *against*: "I hate", "I don't like", "I can't stand"...

  "Really", "love", "hate", "always", "never" make it *hard* (strong); the
  rest are *soft*.

Questions are skipped ("must it be Python?" constrains nothing).

**Someone else's view is kept apart.** A sentence inside quotation marks
or a ``>`` line, or one that reports someone ("my client said they want a
light theme"), is recorded with ``attributed_to="external"`` and flagged
for review. It is not the user's own preference.

Talking points:
    - "'Must' and 'ideally' are different promises, so a requirement says
      whether it's hard or soft."
    - "'My client wants X' is the client's preference, not mine, and the
      record says so."
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from knowledge_engine.domain.enums import Role
from knowledge_engine.extraction.evidence import quoted_at
from knowledge_engine.extraction.records import (
    Acceptance,
    CandidateRecord,
    Polarity,
    RecordType,
    Scope,
    Strength,
)
from knowledge_engine.extraction.text import ExtractionMessage, quote, sentences

EXTRACTOR_VERSION = "ext-004-rules-v1"
EXTERNAL = "external"
_HARD = re.compile(
    r"\b(?:must|mustn'?t|has to|have to|needs? to|is required|are required|no more than|"
    r"at most|at least|mandatory|under no circumstances)\b",
    re.IGNORECASE,
)
_SOFT = re.compile(
    r"\b(?:ideally|preferably|would be nice|if possible|nice to have|should)\b", re.IGNORECASE
)
_LIKE = re.compile(
    r"\bi (?:really |do )?(?:prefer|like|love|enjoy|favou?r)\b|\bi'?d rather\b|"
    r"\bmy favou?rite\b",
    re.IGNORECASE,
)
_DISLIKE = re.compile(
    r"\bi (?:really )?(?:dislike|hate|can'?t stand|detest)\b|\bi (?:really )?don'?t "
    r"(?:like|enjoy|want)\b",
    re.IGNORECASE,
)
_STRONG = re.compile(r"\b(?:really|love|hate|always|never|can'?t stand|detest)\b", re.I)
_REPORTED = re.compile(
    r"\b(?:my|our|the) (?:boss|client|manager|friend|teacher|team|customer|partner|colleague|"
    r"wife|husband|users?)\b[^.!?]{0,20}\b(?:said|says|wants?|thinks?|prefers?|insists?)\b|"
    r"\b(?:he|she|they) (?:said|says|wants?|prefers?|insists?)\b",
    re.IGNORECASE,
)


def extract_preferences(
    messages: Sequence[ExtractionMessage], *, segment_id: str
) -> list[CandidateRecord]:
    """Preferences and requirements stated in user messages of one segment."""
    found = []
    for message in messages:
        if message.role is not Role.USER:
            continue
        for span in sentences(message.text):
            said = span.of(message.text)
            if said.rstrip().endswith("?"):
                continue
            ref = quote(message, span)
            cue = (
                _HARD.search(said)
                or _SOFT.search(said)
                or _LIKE.search(said)
                or _DISLIKE.search(said)
            )
            reported = _REPORTED.search(said)
            # Quoted if the cue itself sits inside quotation marks, wherever
            # the sentence starts.
            quoted = cue is not None and quoted_at(message.text, span.start + cue.start())
            external = quoted or reported is not None
            fields: dict[str, object]
            if _HARD.search(said) or _SOFT.search(said):
                hard = bool(_HARD.search(said))
                fields = {
                    "record_type": RecordType.REQUIREMENT,
                    "strength": Strength.HARD if hard else Strength.SOFT,
                }
            elif _LIKE.search(said) or _DISLIKE.search(said):
                against = bool(_DISLIKE.search(said))
                fields = {
                    "record_type": RecordType.PREFERENCE,
                    "polarity": Polarity.AGAINST if against else Polarity.FOR,
                    "strength": Strength.HARD if _STRONG.search(said) else Strength.SOFT,
                }
            elif reported is not None:
                # "my client said they want a light theme": a view, not a constraint.
                fields = {
                    "record_type": RecordType.PREFERENCE,
                    "polarity": Polarity.FOR,
                    "strength": Strength.SOFT,
                }
            else:
                continue
            if external:
                fields["attributed_to"] = EXTERNAL
                fields["review_reason"] = "someone else's view, reported by the user"
            found.append(
                CandidateRecord.model_validate(
                    {
                        **fields,
                        "assertion": said[:300],
                        "actor": Role.USER,
                        # Stated by the user in their own words: that is the
                        # acceptance. A reported view gets none.
                        "acceptance": Acceptance.ABSENT if external else Acceptance.EXPLICIT,
                        "scope": Scope.SEGMENT,
                        "scope_id": segment_id,
                        "evidence": [ref],
                    }
                )
            )
    return found
