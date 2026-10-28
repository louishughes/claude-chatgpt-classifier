"""Data for the links, videos, accounts and search pages (UI-004).

Every list here is a registry the importer already keeps: one row per URL,
video or account, and every mention pointing back to the exact message it
came from. These functions only read; the pages link each mention to its
message on the chat page (``/chats/<id>#<anchor>``).

Talking points:
    - "Every link, video and account page is a view over a registry, and
      every row on it is one click from the message that mentioned it."
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from knowledge_engine.importer.records import ConversationRow, MessageNodeRow, MessageRevisionRow
from knowledge_engine.links.social_store import SocialAccountRow, account_mentions
from knowledge_engine.links.store import LinkOccurrenceRow, LinkTargetRow
from knowledge_engine.links.youtube import YouTubeMentionRow, YouTubeVideoRow
from knowledge_engine.rendering.transcript import message_anchor


@dataclass(frozen=True)
class Place:
    """Where a mention is: a message in a chat, ready to link to."""

    conversation_id: str
    title: str
    anchor: str
    role: str | None
    when: datetime | None


def places(session: Session, revision_ids: Iterable[str]) -> dict[str, Place]:
    """Return revision ID -> the chat message it belongs to."""
    wanted = sorted(set(revision_ids))
    found: dict[str, Place] = {}
    for start in range(0, len(wanted), 500):  # stay under SQLite's variable limit
        rows = session.execute(
            select(
                MessageRevisionRow.revision_id,
                MessageRevisionRow.role,
                MessageRevisionRow.create_time,
                MessageNodeRow.node_key,
                ConversationRow.conversation_id,
                ConversationRow.title,
            )
            .join(MessageNodeRow, MessageNodeRow.node_key == MessageRevisionRow.node_key)
            .join(
                ConversationRow, ConversationRow.conversation_id == MessageNodeRow.conversation_id
            )
            .where(MessageRevisionRow.revision_id.in_(wanted[start : start + 500]))
        )
        for revision, role, created, node_key, conversation, title in rows:
            found[revision] = Place(
                conversation,
                title or "Untitled conversation",
                message_anchor(node_key),
                role,
                datetime.fromtimestamp(created, UTC) if created else None,
            )
    return found


def list_links(
    session: Session, query: str = "", offset: int = 0, limit: int = 100
) -> tuple[list[dict[str, Any]], int]:
    """Return one page of link targets, most mentioned first.

    Args:
        session: A read session.
        query: Text to look for in the URL (case-insensitive); empty for all.
        offset: How many to skip.
        limit: Page size.

    Returns:
        The page and the total number of matching targets.
    """
    where = []
    if query.strip():
        pattern = query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        where.append(LinkTargetRow.canonical_url.ilike(f"%{pattern}%", escape="\\"))
    total = session.scalar(select(func.count()).select_from(LinkTargetRow).where(*where))
    mentions = func.count(LinkOccurrenceRow.occurrence_id)
    rows = session.execute(
        select(
            LinkTargetRow,
            mentions,
            func.count(func.distinct(LinkOccurrenceRow.conversation_id)),
        )
        .join(LinkOccurrenceRow, LinkOccurrenceRow.target_id == LinkTargetRow.target_id)
        .where(*where)
        .group_by(LinkTargetRow.target_id)
        .order_by(mentions.desc(), LinkTargetRow.canonical_url)
        .offset(offset)
        .limit(limit)
    ).all()
    page = [
        {
            "target_id": target.target_id,
            "url": target.canonical_url,
            "host": target.host,
            "kind": target.kind,
            "mentions": int(m),
            "conversations": int(c),
        }
        for target, m, c in rows
    ]
    return page, int(total or 0)


def link_page(session: Session, target_id: str) -> dict[str, Any] | None:
    """Return one link target and every mention of it, or None."""
    target = session.get(LinkTargetRow, target_id)
    if target is None:
        return None
    occurrences = session.scalars(
        select(LinkOccurrenceRow)
        .where(LinkOccurrenceRow.target_id == target_id)
        .order_by(LinkOccurrenceRow.revision_id, LinkOccurrenceRow.start)
    ).all()
    where = places(session, (o.revision_id for o in occurrences))
    return {
        "target_id": target.target_id,
        "url": target.canonical_url,
        "host": target.host,
        "kind": target.kind,
        "mentions": [
            {"place": where.get(o.revision_id), "written": o.original_text, "origin": o.origin}
            for o in occurrences
        ],
    }


def list_videos(session: Session) -> list[dict[str, Any]]:
    """Return every YouTube video, most mentioned first, with transcript status."""
    mentions = func.count(YouTubeMentionRow.mention_id)
    rows = session.execute(
        select(
            YouTubeVideoRow,
            mentions,
            func.count(func.distinct(LinkOccurrenceRow.conversation_id)),
        )
        .join(YouTubeMentionRow, YouTubeMentionRow.video_id == YouTubeVideoRow.video_id)
        .join(LinkOccurrenceRow, LinkOccurrenceRow.occurrence_id == YouTubeMentionRow.mention_id)
        .group_by(YouTubeVideoRow.video_id)
        .order_by(mentions.desc(), YouTubeVideoRow.video_id)
    ).all()
    return [
        {
            "video_id": video.video_id,
            "transcript_status": video.transcript_status,
            "mentions": int(m),
            "conversations": int(c),
        }
        for video, m, c in rows
    ]


def video_page(session: Session, video_id: str) -> dict[str, Any] | None:
    """Return one video and every mention of it, or None."""
    from knowledge_engine.links.video_transcripts import TranscriptSnapshotRow

    video = session.get(YouTubeVideoRow, video_id)
    if video is None:
        return None
    rows = session.execute(
        select(YouTubeMentionRow, LinkOccurrenceRow)
        .join(LinkOccurrenceRow, LinkOccurrenceRow.occurrence_id == YouTubeMentionRow.mention_id)
        .where(YouTubeMentionRow.video_id == video_id)
        .order_by(LinkOccurrenceRow.revision_id, LinkOccurrenceRow.start)
    ).all()
    where = places(session, (occurrence.revision_id for _, occurrence in rows))
    transcripts = session.scalar(
        select(func.count())
        .select_from(TranscriptSnapshotRow)
        .where(TranscriptSnapshotRow.video_id == video_id)
    )
    return {
        "video_id": video.video_id,
        "transcript_status": video.transcript_status,
        "transcripts": int(transcripts or 0),
        "mentions": [
            {
                "place": where.get(occurrence.revision_id),
                "written": occurrence.original_text,
                "t_seconds": mention.t_seconds,
                "playlist_id": mention.playlist_id,
            }
            for mention, occurrence in rows
        ],
    }


def account_page(session: Session, account_id: str) -> dict[str, Any] | None:
    """Return one registry account, its aliases and every mention, or None."""
    from knowledge_engine.links.social_store import AccountAliasRow

    account = session.get(SocialAccountRow, account_id)
    if account is None:
        return None
    mentions = account_mentions(session, account_id)
    where = places(session, (m.revision_id for m in mentions))
    aliases = session.scalars(
        select(AccountAliasRow)
        .where(AccountAliasRow.account_id == account_id)
        .order_by(AccountAliasRow.kind, AccountAliasRow.alias)
    ).all()
    return {
        "account_id": account.account_id,
        "platform": account.platform,
        "handle": account.canonical_handle,
        "stable_id": account.stable_platform_id,
        "profile_url": account.profile_url,
        "identity_status": account.identity_status,
        "aliases": [(a.kind, a.alias) for a in aliases],
        "mentions": [{"place": where.get(m.revision_id), "written": m.raw_text} for m in mentions],
    }
