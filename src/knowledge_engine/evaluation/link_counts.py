"""Link, YouTube and social-account counts for a batch of imported chats (EVAL-010c).

Gate G2 asks for the M2 registries to be looked at on 100 real
conversations: how many links, videos and account mentions the import
found, and how many account candidates were left ambiguous rather than
guessed. This module only counts what the import already stored. It reads,
never writes, calls no model and prints no URL, handle or text, so its
report is safe to paste from the owner's PC.

The batch is the first N conversations by native ID, the same choice
``ke eval semantic --limit`` makes.

Talking points:
    - "It counts what the registries hold for a sample of chats; it never
      shows a link or a handle."
    - "Ambiguous @names are counted as ambiguous, which is the point: the
      import didn't guess an account for them."
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from sqlalchemy import Select, distinct, func, select
from sqlalchemy.orm import Session

from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.links.social_store import AccountMentionRow, SocialAccountRow
from knowledge_engine.links.store import LinkOccurrenceRow, LinkTargetRow
from knowledge_engine.links.youtube import YouTubeMentionRow, YouTubeVideoRow


def _batch(limit: int | None) -> Select[tuple[str]]:
    query = select(ConversationRow.conversation_id).order_by(ConversationRow.native_conversation_id)
    return query.limit(limit) if limit is not None else query


def _counter(rows: Any) -> dict[str, int]:
    return dict(sorted(Counter({str(k): int(n) for k, n in rows}).items()))


def link_counts(session: Session, limit: int | None = None) -> dict[str, Any]:
    """Counts only, for the first ``limit`` conversations (all when None).

    Returns:
        ``conversations``, then ``links``, ``youtube`` and ``social`` blocks
        of plain integers and small ``{kind: count}`` maps.
    """
    batch = _batch(limit).subquery()
    in_batch = LinkOccurrenceRow.conversation_id.in_(select(batch.c.conversation_id))
    conversations = session.scalar(select(func.count()).select_from(batch)) or 0

    occurrences = select(LinkOccurrenceRow).where(in_batch).subquery()
    targets = (
        select(LinkTargetRow.target_id, LinkTargetRow.kind)
        .where(LinkTargetRow.target_id.in_(select(occurrences.c.target_id)))
        .subquery()
    )
    links = {
        "occurrences": session.scalar(select(func.count()).select_from(occurrences)) or 0,
        "conversations_with_links": session.scalar(
            select(func.count(distinct(occurrences.c.conversation_id)))
        )
        or 0,
        "distinct_targets": session.scalar(select(func.count()).select_from(targets)) or 0,
        "targets_by_kind": _counter(
            session.execute(select(targets.c.kind, func.count()).group_by(targets.c.kind))
        ),
        "occurrences_by_origin": _counter(
            session.execute(
                select(occurrences.c.origin, func.count()).group_by(occurrences.c.origin)
            )
        ),
    }

    mentions = (
        select(YouTubeMentionRow)
        .where(YouTubeMentionRow.mention_id.in_(select(occurrences.c.occurrence_id)))
        .subquery()
    )
    videos = select(mentions.c.video_id).distinct().subquery()
    youtube = {
        "mentions": session.scalar(select(func.count()).select_from(mentions)) or 0,
        "distinct_videos": session.scalar(select(func.count()).select_from(videos)) or 0,
        "with_timestamp": session.scalar(
            select(func.count()).where(mentions.c.t_seconds.is_not(None))
        )
        or 0,
        "with_playlist": session.scalar(
            select(func.count()).where(mentions.c.playlist_id.is_not(None))
        )
        or 0,
        "transcript_status": _counter(
            session.execute(
                select(YouTubeVideoRow.transcript_status, func.count())
                .where(YouTubeVideoRow.video_id.in_(select(videos.c.video_id)))
                .group_by(YouTubeVideoRow.transcript_status)
            )
        ),
    }

    account_mentions = (
        select(AccountMentionRow)
        .where(AccountMentionRow.conversation_id.in_(select(batch.c.conversation_id)))
        .subquery()
    )
    accounts = (
        select(SocialAccountRow.platform, SocialAccountRow.identity_status)
        .where(
            SocialAccountRow.account_id.in_(
                select(account_mentions.c.account_id).where(
                    account_mentions.c.account_id.is_not(None)
                )
            )
        )
        .subquery()
    )
    social = {
        "mentions": session.scalar(select(func.count()).select_from(account_mentions)) or 0,
        "mentions_by_resolution": _counter(
            session.execute(
                select(account_mentions.c.resolution, func.count()).group_by(
                    account_mentions.c.resolution
                )
            )
        ),
        "distinct_accounts": session.scalar(select(func.count()).select_from(accounts)) or 0,
        "accounts_by_platform": _counter(
            session.execute(select(accounts.c.platform, func.count()).group_by(accounts.c.platform))
        ),
        "accounts_by_status": _counter(
            session.execute(
                select(accounts.c.identity_status, func.count()).group_by(
                    accounts.c.identity_status
                )
            )
        ),
        # Bare @names: kept as ambiguous candidates, never turned into accounts.
        "ambiguous_handles": session.scalar(
            select(func.count(distinct(func.lower(account_mentions.c.handle)))).where(
                account_mentions.c.resolution == "ambiguous"
            )
        )
        or 0,
    }
    return {"conversations": conversations, "links": links, "youtube": youtube, "social": social}
