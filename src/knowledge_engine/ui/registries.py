"""Data for the links, videos, accounts and search pages (UI-004).

Every list here is a registry the importer already keeps: one row per URL,
video, account or image (UI-010), and every mention pointing back to the exact message it
came from. These functions only read; the pages link each mention to its
message on the chat page (``/chats/<id>#<anchor>``).

Talking points:
    - "Every link, video and account page is a view over a registry, and
      every row on it is one click from the message that mentioned it."
"""

from __future__ import annotations

import json
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
    """Return every YouTube video, most mentioned first, with transcript status.

    ``mentions`` counts chat mentions plus links from imported notes'
    current versions (ING-014); ``conversations`` counts chats only.
    """
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
    ).all()
    in_notes = _note_mentions(session)
    videos = [
        {
            "video_id": video.video_id,
            "transcript_status": video.transcript_status,
            "mentions": int(m) + in_notes.pop(video.video_id, 0),
            "conversations": int(c),
        }
        for video, m, c in rows
    ]
    # What is left in ``in_notes`` is linked only from notes.
    for video_id, count in in_notes.items():
        video = session.get(YouTubeVideoRow, video_id)
        if video is not None:
            videos.append(
                {
                    "video_id": video_id,
                    "transcript_status": video.transcript_status,
                    "mentions": count,
                    "conversations": 0,
                }
            )
    return sorted(videos, key=lambda v: (-v["mentions"], v["video_id"]))


def _note_mentions(session: Session) -> dict[str, int]:
    # ING-012/014: links to each video from imported notes. Only a note's
    # *current* version counts, the same rule as the video page, so a link
    # removed from a note no longer keeps the video in the list. Old
    # versions keep their link rows as history.
    from knowledge_engine.importer.text_documents import DocumentLinkRow, DocumentRow

    rows = session.execute(
        select(DocumentLinkRow.video_id, func.count(DocumentLinkRow.link_id))
        .join(DocumentRow, DocumentRow.current_revision_id == DocumentLinkRow.revision_id)
        .where(DocumentLinkRow.video_id.is_not(None))
        .group_by(DocumentLinkRow.video_id)
    ).tuples()
    return {video_id: int(count) for video_id, count in rows if video_id is not None}


def video_page(session: Session, video_id: str) -> dict[str, Any] | None:
    """Return one video and every mention of it, or None."""
    from knowledge_engine.importer.text_documents import video_document_mentions
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
        # ING-012: links to it from imported notes (current versions only).
        "documents": video_document_mentions(session, video_id),
    }


def account_page(session: Session, account_id: str) -> dict[str, Any] | None:
    """Return one registry account, its aliases and every mention, or None."""
    from knowledge_engine.links.social_store import AccountAliasRow, account_history

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
        "history": [
            {
                "action": r.action,
                "from_state": r.from_state,
                "to_state": r.to_state,
                "reviewer": r.reviewer,
                "note": r.note,
                "at": r.at.isoformat(timespec="seconds"),
            }
            for r in account_history(session, account_id)
        ],
    }


def asset_page(session: Session, asset_id: str) -> dict[str, Any] | None:
    """Return one image or file and every message that uses it, or None (UI-010).

    An asset is the export's logical file; each use of it in a message is a
    separate occurrence (CLAUDE.md §2A). The same picture sent in three
    messages is one asset with three rows here, and every row links to its
    message. Each occurrence keeps its own availability, because a later
    export may supply bytes that an earlier one lacked.
    """
    from knowledge_engine.importer.media import AssetOccurrenceRow, MediaAssetRow, MediaBlobRow
    from knowledge_engine.rendering.media import REASONS

    asset = session.get(MediaAssetRow, asset_id)
    if asset is None:
        return None
    blob = session.get(MediaBlobRow, asset.blob_sha256) if asset.blob_sha256 else None
    rows = session.scalars(
        select(AssetOccurrenceRow)
        .where(AssetOccurrenceRow.asset_id == asset_id)
        .order_by(AssetOccurrenceRow.revision_id, AssetOccurrenceRow.part_index)
    ).all()
    # One row per *message*, not per stored revision. Re-importing a chat
    # whose message was edited adds a new revision of the same message; the
    # chat page shows the newest one (``load_conversation``), so this page
    # counts only uses in each message's newest revision. Uses that exist
    # only in an older version are counted separately, never dropped.
    node_of = dict(
        session.execute(
            select(MessageRevisionRow.revision_id, MessageRevisionRow.node_key).where(
                MessageRevisionRow.revision_id.in_({row.revision_id for row in rows})
            )
        )
        .tuples()
        .all()
    )
    newest: dict[str, str] = {}
    for revision_id, node_key in session.execute(
        select(MessageRevisionRow.revision_id, MessageRevisionRow.node_key)
        .where(MessageRevisionRow.node_key.in_(set(node_of.values())))
        .order_by(MessageRevisionRow.created_at, MessageRevisionRow.revision_id)
    ).tuples():
        newest[node_key] = revision_id  # later rows win, as on the chat page
    # A revision with no stored message can't be placed; it is kept (shown as
    # "message not found") rather than silently dropped.
    current = [
        row
        for row in rows
        if row.revision_id not in node_of or newest.get(node_of[row.revision_id]) == row.revision_id
    ]
    earlier = len(
        {node_of[row.revision_id] for row in rows if row.revision_id in node_of}
        - {node_of[r.revision_id] for r in current if r.revision_id in node_of}
    )
    rows = current
    where = places(session, (row.revision_id for row in rows))

    def oldest_first(row: AssetOccurrenceRow) -> tuple[bool, datetime]:
        # A message with no time (or not found) goes last.
        place = where.get(row.revision_id)
        when = place.when if place is not None else None
        return (when is None, when or datetime.min.replace(tzinfo=UTC))

    occurrences = []
    chats = set()
    for row in sorted(rows, key=oldest_first):
        place = where.get(row.revision_id)
        if place is not None:
            chats.add(place.conversation_id)
        evidence = json.loads(row.evidence_json) if row.evidence_json else {}
        occurrences.append(
            {
                "occurrence_id": row.occurrence_id,
                "revision_id": row.revision_id,
                "place": place,
                "availability": row.availability,
                "reason": REASONS.get(evidence.get("rule") or "", "no reason recorded"),
            }
        )
    shared = 0
    if blob is not None:
        # Other logical files with identical bytes (a re-upload under a new
        # file ID): the same picture, kept as its own asset, never merged.
        shared = int(
            session.scalar(
                select(func.count())
                .select_from(MediaAssetRow)
                .where(
                    MediaAssetRow.blob_sha256 == blob.blob_sha256,
                    MediaAssetRow.asset_id != asset_id,
                )
            )
            or 0
        )
    return {
        "asset_id": asset.asset_id,
        "blob_sha256": blob.blob_sha256 if blob else None,
        "media_type": blob.media_type if blob else None,
        "width": blob.width if blob else None,
        "height": blob.height if blob else None,
        "chats": len(chats),
        "same_bytes_elsewhere": shared,
        "only_in_earlier_versions": earlier,
        "occurrences": occurrences,
    }
