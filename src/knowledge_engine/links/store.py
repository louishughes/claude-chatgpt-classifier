"""The link registry: destinations and their mentions, in the database (LNK-001).

* ``link_targets``: one row per destination (canonical URL), shared by
  every mention of it;
* ``link_occurrences``: one row per mention, keyed by the message revision
  and the exact span, so importing the same message again adds nothing and
  a changed message gets its own new mentions (the old ones stay, as
  evidence of what the old revision said).

Written in the same transaction as the messages they come from.

Talking points:
    - "Links are a registry: one destination, many mentions, each mention
      pointing at the exact characters in the exact version of a message."
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, Session, mapped_column

from knowledge_engine.domain.ids import link_occurrence_id, link_target_id
from knowledge_engine.infrastructure.db import Base
from knowledge_engine.links.extract import CITATION_METADATA, MESSAGE_TEXT, FoundLink
from knowledge_engine.links.youtube import parse_youtube, record_mention

_ORIGINS = f"'{MESSAGE_TEXT}','{CITATION_METADATA}'"


def _utc_now() -> datetime:
    return datetime.now(UTC)


class LinkTargetRow(Base):
    """One link destination, shared by all its mentions."""

    __tablename__ = "link_targets"

    target_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    canonical_url: Mapped[str] = mapped_column(Text, unique=True)
    host: Mapped[str] = mapped_column(String(255), index=True)
    # web for now; YTB-001 and SOC-001 refine it to youtube_video and
    # social_profile when they recognise a URL.
    kind: Mapped[str] = mapped_column(String(30), default="web")
    first_import_id: Mapped[str] = mapped_column(ForeignKey("import_batches.import_id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


class LinkOccurrenceRow(Base):
    """One mention of a link at an exact place in one message revision."""

    __tablename__ = "link_occurrences"
    __table_args__ = (
        UniqueConstraint("revision_id", "start", "end", "origin"),
        CheckConstraint(f"origin IN ({_ORIGINS})", name="origin_valid"),
        CheckConstraint('start >= 0 AND "end" > start', name="span_valid"),
    )

    occurrence_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    revision_id: Mapped[str] = mapped_column(
        ForeignKey("message_revisions.revision_id"), index=True
    )
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.conversation_id"), index=True
    )
    target_id: Mapped[str] = mapped_column(ForeignKey("link_targets.target_id"), index=True)
    origin: Mapped[str] = mapped_column(String(20))
    # message_text: code points in the canonical text (NRM-003);
    # citation_metadata: the citation's position in its list.
    start: Mapped[int] = mapped_column(Integer)
    end: Mapped[int] = mapped_column(Integer)
    # The URL exactly as written: the evidence. Untrusted, never fetched.
    original_text: Mapped[str] = mapped_column(Text)
    # Who wrote the message: user, assistant, tool... (None if unknown).
    actor: Mapped[str | None] = mapped_column(String(20), default=None)
    first_import_id: Mapped[str] = mapped_column(ForeignKey("import_batches.import_id"))


def ensure_target(
    session: Session, link: FoundLink, *, import_id: str, counts: Counter[str]
) -> str:
    """Return the link target for a URL, creating it the first time it's seen.

    Shared by chat messages and imported documents (ING-012), so a URL
    mentioned in both is one destination with mentions from each.

    Args:
        session: A write session.
        link: The found URL.
        import_id: The running batch.
        counts: ``new_targets`` is added to when a target is created.

    Returns:
        The ``link_`` ID.
    """
    target_key = link_target_id(link.canonical_url)
    if session.get(LinkTargetRow, target_key) is None:
        session.add(
            LinkTargetRow(
                target_id=target_key,
                canonical_url=link.canonical_url,
                host=link.host,
                first_import_id=import_id,
            )
        )
        # Flush so a second mention in this batch finds the target.
        session.flush()
        counts["new_targets"] += 1
    return target_key


def record_links(
    session: Session,
    mentions: Iterable[tuple[str, str | None, FoundLink]],
    *,
    conversation_id: str,
    import_id: str,
) -> Counter[str]:
    """Store the link mentions of one conversation's current revisions.

    Args:
        session: The batch's write session.
        mentions: ``(revision_id, actor, found link)`` triples.
        conversation_id: The ``conv_`` ID.
        import_id: The running batch.

    Returns:
        ``new_targets``, ``new_occurrences``, ``seen_occurrences`` and
        ``new_youtube_mentions`` counts.
    """
    counts: Counter[str] = Counter()
    for revision_id, actor, link in mentions:
        target_key = ensure_target(session, link, import_id=import_id, counts=counts)
        key = link_occurrence_id(revision_id, link.span.start, link.span.end, link.origin)
        counts["seen_occurrences"] += 1
        if session.get(LinkOccurrenceRow, key) is None:
            session.add(
                LinkOccurrenceRow(
                    occurrence_id=key,
                    revision_id=revision_id,
                    conversation_id=conversation_id,
                    target_id=target_key,
                    origin=link.origin,
                    start=link.span.start,
                    end=link.span.end,
                    original_text=link.original,
                    actor=actor,
                    first_import_id=import_id,
                )
            )
            session.flush()
            counts["new_occurrences"] += 1
        # Checked for old occurrences too, so a workspace imported before
        # YTB-001 gains its video records on the next import.
        video = parse_youtube(link.original)
        if video is not None:
            target = session.get(LinkTargetRow, target_key)
            if target is not None:
                target.kind = "youtube_video"
            if record_mention(session, key, video, import_id=import_id):
                counts["new_youtube_mentions"] += 1
    return counts
