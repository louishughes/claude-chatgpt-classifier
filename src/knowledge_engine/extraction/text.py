"""Shared pieces for the rule-based extractors: messages, sentences, quotes.

Every extractor reads a segment as a list of ``ExtractionMessage`` (who
said it, which exact revision, the canonical text) and cites whole
sentences, so every candidate's evidence is an exact, fingerprinted quote
(NRM-003) that the EXT-002 validator can check.

Talking points:
    - "Extractors cite whole sentences by position and fingerprint, never a
      paraphrase."
"""

from __future__ import annotations

import re
from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from knowledge_engine.domain.enums import Role
from knowledge_engine.domain.models import EvidenceRef
from knowledge_engine.graph.offsets import Span, cite
from knowledge_engine.rendering.transcript import StoredConversation
from knowledge_engine.segmentation.segmenter import Segment

# A sentence ends at . ! ? or a line break; the end mark stays with it.
_SENTENCE = re.compile(r"[^.!?\n]+[.!?]*")


@dataclass(frozen=True)
class ExtractionMessage:
    """One message as an extractor sees it.

    Attributes:
        native_id: The export's node ID.
        revision_id: The exact message version (``rev_``) evidence cites.
        role: Who wrote it.
        text: Canonical text (private).
    """

    native_id: str
    revision_id: str
    role: Role
    text: str


def segment_extraction_messages(
    conversation: StoredConversation, segment: Segment
) -> list[ExtractionMessage]:
    """The segment's messages, in order, with their revision IDs."""
    found = []
    for native in segment.messages:
        node = conversation.messages.get(native)
        revision = conversation.revisions.get(native)
        if node is None or revision is None:
            continue
        try:
            role = Role(node.role) if node.role else Role.UNKNOWN
        except ValueError:
            role = Role.UNKNOWN
        found.append(ExtractionMessage(native, revision, role, node.text))
    return found


def exchanges_of(messages: Sequence[ExtractionMessage]) -> list[list[ExtractionMessage]]:
    """Group messages into exchanges: each user message starts a new one.

    The unit model stages split on (LEG-005), like the segmenter: a
    question always stays with its answer.
    """
    groups: list[list[ExtractionMessage]] = []
    for message in messages:
        if not groups or message.role is Role.USER:
            groups.append([])
        groups[-1].append(message)
    return groups


def sentences(text: str) -> Iterator[Span]:
    """Each sentence's span, with surrounding spaces trimmed off."""
    for match in _SENTENCE.finditer(text):
        raw = match.group()
        start = match.start() + (len(raw) - len(raw.lstrip()))
        end = match.end() - (len(raw) - len(raw.rstrip()))
        if end > start:
            yield Span(start, end)


def quote(message: ExtractionMessage, span: Span) -> EvidenceRef:
    """Evidence for one sentence of one message."""
    _, digest = cite(message.text, span)
    return EvidenceRef(
        revision_id=message.revision_id,
        start=span.start,
        end=span.end,
        quote_sha256=digest,
        actor=message.role,
    )
