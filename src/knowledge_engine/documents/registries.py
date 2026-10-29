"""Video notes, transcript cue search and account registry notes (YTB-003, SOC-003).

**Videos.** One note per YouTube video (``Videos/``). It says, in words,
where getting its transcript stands (never blank: "none attached and none
requested" is an answer too), lists every message that links to it with
the link's own timestamp, and backlinks each of those chats. If a
transcript is attached, its timed cues follow, each with a block anchor
and a link that opens the video at that moment.

**Cue search.** ``find_cues`` finds cues containing every word asked for.
Each hit resolves to the video, the moment (``&t=``) and **every** chat
that links to the video, so a line in a talk leads back to the
conversations about it. Cue text only ever comes from a transcript file
(YTB-002); nothing here writes or guesses words.

**Accounts.** A registry note (``Accounts/Account registry.md``) lists
every registry account with mention counts and backlinks, by platform.
Bare ``@handles`` are never linked to an account (SOC-002), so they get a
separate "Needs review" section rather than being guessed at; rejected
accounts are listed apart too. Each account has its own note with its
aliases, every mention and the chats they are in.

Handles, aliases and cue text are imported text: they are escaped or put
in code spans so nothing in them acts as a link or a tag.

Talking points:
    - "A video note always says whether there's a transcript and why not,
      and links to every chat that mentioned the video."
    - "Searching transcript lines takes me to the exact second of the
      video and to the chats that cited it."
    - "An unqualified @name is listed as a question, never filed under an
      account."
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import PurePosixPath

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from knowledge_engine.documents.render import source_links, transcript_stem
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.importer.text_documents import video_document_mentions
from knowledge_engine.links.social_store import (
    AccountAliasRow,
    SocialAccountRow,
    account_history,
    account_mentions,
    account_summaries,
    ambiguous_handles,
)
from knowledge_engine.links.store import LinkOccurrenceRow
from knowledge_engine.links.video_transcripts import (
    TranscriptCueRow,
    TranscriptSnapshotRow,
)
from knowledge_engine.links.youtube import YouTubeMentionRow, YouTubeVideoRow
from knowledge_engine.rendering.markdown import (
    Block,
    BulletList,
    DocumentModel,
    Heading,
    Paragraph,
    PropertyValue,
    block_anchor,
    escape_text,
    safe_filename,
    safe_relative_path,
)

REGISTRY_NOTES_VERSION = "ytb-003+soc-004-v2"
VIDEOS_DIR = "Videos"
ACCOUNTS_DIR = "Accounts"
REGISTRY_TITLE = "Account registry"

# The transcript status in words, so a note never leaves it to be guessed.
STATUS_WORDS = {
    "not_requested": "No transcript: none attached and none requested.",
    "queued": "A transcript has been requested and is waiting its turn.",
    "succeeded": "A transcript is attached.",
    "unavailable": "No transcript: the source says none is available.",
    "permission_required": (
        "No transcript: fetching one needs the transcript network switch, which is off."
    ),
    "rate_limited": "No transcript yet: the source asked us to slow down; it can be retried.",
    "failed": "No transcript yet: the last attempt failed; it can be retried.",
}


def watch_url(video_id: str, seconds: int | None = None) -> str:
    """The canonical address of a video, optionally at a moment (built, never fetched)."""
    at = f"&t={seconds}s" if seconds else ""
    return f"https://www.youtube.com/watch?v={video_id}{at}"


def _clock(seconds: int) -> str:
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02}:{secs:02}" if hours else f"{minutes}:{secs:02}"


def _one_line(text: str) -> str:
    return " ".join(escape_text(text).split())


def _code(text: str) -> str:
    return " ".join(text.replace("`", "'").split())


def cue_anchor(ordinal: int) -> str:
    """The block anchor of a cue's line in its video note."""
    return block_anchor(f"cue-{ordinal}")


# ---- videos ---------------------------------------------------------------


def video_path(video_id: str) -> PurePosixPath:
    """Where a video's note lives in the vault (``Videos/…``)."""
    return safe_relative_path(VIDEOS_DIR, safe_filename(f"YouTube {video_id}", "video"))


@dataclass(frozen=True)
class VideoMention:
    """One message linking to a video."""

    revision_id: str
    conversation_id: str
    t_seconds: int | None
    playlist_id: str | None
    actor: str | None


def video_mentions(session: Session, video_id: str) -> list[VideoMention]:
    """Every message that links to the video, in archive order."""
    rows = session.execute(
        select(YouTubeMentionRow, LinkOccurrenceRow)
        .join(LinkOccurrenceRow, LinkOccurrenceRow.occurrence_id == YouTubeMentionRow.mention_id)
        .where(YouTubeMentionRow.video_id == video_id)
        .order_by(LinkOccurrenceRow.revision_id, LinkOccurrenceRow.start)
    ).all()
    return [
        VideoMention(
            occurrence.revision_id,
            occurrence.conversation_id,
            mention.t_seconds,
            mention.playlist_id,
            occurrence.actor,
        )
        for mention, occurrence in rows
    ]


def _latest_snapshot(session: Session, video_id: str) -> TranscriptSnapshotRow | None:
    return session.scalar(
        select(TranscriptSnapshotRow)
        .where(TranscriptSnapshotRow.video_id == video_id)
        .order_by(TranscriptSnapshotRow.created_at.desc(), TranscriptSnapshotRow.transcript_id)
    )


def _chat_links(session: Session, conversation_ids: set[str]) -> list[str]:
    titles = dict(
        session.execute(
            select(ConversationRow.conversation_id, ConversationRow.title).where(
                ConversationRow.conversation_id.in_(sorted(conversation_ids))
            )
        )
        .tuples()
        .all()
    )
    return [f"[[{transcript_stem(c, titles.get(c))}]] (`{c}`)" for c in sorted(conversation_ids)]


def video_note(session: Session, video_id: str) -> DocumentModel:
    """Build one video's note. Reads only.

    Raises:
        KeyError: If the video isn't in the registry.
    """
    video = session.get(YouTubeVideoRow, video_id)
    if video is None:
        raise KeyError("no such video")
    mentions = video_mentions(session, video_id)
    cited = source_links(session, [m.revision_id for m in mentions])
    snapshots = list(
        session.scalars(
            select(TranscriptSnapshotRow)
            .where(TranscriptSnapshotRow.video_id == video_id)
            .order_by(TranscriptSnapshotRow.created_at, TranscriptSnapshotRow.transcript_id)
        )
    )
    blocks: list[Block] = [
        Paragraph(f"Watch: <{watch_url(video_id)}> (opens YouTube; nothing is fetched).", True),
        Heading("Transcript", 2),
        Paragraph(STATUS_WORDS.get(video.transcript_status, video.transcript_status), True),
    ]
    if snapshots:
        cue_counts = _cue_counts(session, [s.transcript_id for s in snapshots])
        blocks.append(
            BulletList(
                tuple(
                    f"`{s.transcript_id}` ({s.format}, {s.language or 'language unknown'}, "
                    f"{cue_counts.get(s.transcript_id, 0)} cue(s))"
                    for s in snapshots
                ),
                trusted=True,
            )
        )
    lines = []
    for m in mentions:
        place = cited[m.revision_id].wikilink if m.revision_id in cited else f"`{m.revision_id}`"
        extra = ""
        if m.t_seconds is not None:
            extra = f" at [{_clock(m.t_seconds)}]({watch_url(video_id, m.t_seconds)})"
        extra += f", playlist `{_code(m.playlist_id)}`" if m.playlist_id else ""
        lines.append(f"{place}{extra} (by {m.actor or 'unknown'}, `{m.conversation_id}`)")
    blocks += [Heading("Mentioned in", 2), BulletList(tuple(lines or ["no mentions"]), True)]
    # ING-012: imported notes that link to it. File names are the person's
    # own text, so they go in code spans like every other imported string.
    in_notes = video_document_mentions(session, video_id)
    if in_notes:
        blocks += [
            Heading("In your notes", 2),
            BulletList(tuple(f"`{_code(d['name'])}` at `{d['locator']}`" for d in in_notes), True),
        ]
    chats = {m.conversation_id for m in mentions}
    blocks += [
        Heading("Conversations", 2),
        BulletList(tuple(_chat_links(session, chats) or ["none"]), True),
    ]
    latest = snapshots[-1] if snapshots else None
    if latest is not None:
        cues = session.scalars(
            select(TranscriptCueRow)
            .where(TranscriptCueRow.transcript_id == latest.transcript_id)
            .order_by(TranscriptCueRow.ordinal)
        )
        cue_lines = []
        for cue in cues:
            seconds = (cue.start_ms or 0) // 1000
            moment = (
                f"[{_clock(seconds)}]({watch_url(video_id, seconds)}) "
                if cue.start_ms is not None
                else ""
            )
            speaker = f"{_one_line(cue.speaker)}: " if cue.speaker else ""
            cue_lines.append(f"{moment}{speaker}{_one_line(cue.text)} ^{cue_anchor(cue.ordinal)}")
        blocks += [Heading("Cues", 2), BulletList(tuple(cue_lines or ["no cues"]), True)]
    properties: dict[str, PropertyValue] = {
        "ke_type": "video",
        "video_id": video_id,
        "url": watch_url(video_id),
        "transcript_status": video.transcript_status,
        "transcripts": len(snapshots),
        "mentions": len(mentions),
        "conversations": len(chats),
        "generator": REGISTRY_NOTES_VERSION,
    }
    return DocumentModel(f"YouTube {video_id}", properties, tuple(blocks))


def _cue_counts(session: Session, transcript_ids: list[str]) -> dict[str, int]:
    counts: dict[str, int] = defaultdict(int)
    for transcript_id in session.scalars(
        select(TranscriptCueRow.transcript_id).where(
            TranscriptCueRow.transcript_id.in_(transcript_ids)
        )
    ):
        counts[transcript_id] += 1
    return dict(counts)


@dataclass(frozen=True)
class CueHit:
    """One transcript line that matched, resolved to the video and the chats citing it.

    Attributes:
        video_id: The video.
        transcript_id: The transcript snapshot it is from.
        ordinal: Its position in that transcript (also its note anchor).
        start_seconds: When it starts, if the transcript is timed.
        url: The video, opened at that moment.
        text: The cue's words, as the transcript file has them.
        conversations: Every chat linking to the video.
        revisions: Every message revision linking to it.
    """

    video_id: str
    transcript_id: str
    ordinal: int
    start_seconds: int | None
    url: str
    text: str
    conversations: tuple[str, ...]
    revisions: tuple[str, ...]


_WORD = re.compile(r"[^\W_]+", re.UNICODE)


def _like(word: str) -> str:
    escaped = word.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def find_cues(session: Session, words: str, *, limit: int = 20) -> list[CueHit]:
    """Cues containing every word asked for (any case), newest transcript of each video only.

    An older transcript of a video stays in the archive but is not searched,
    so a corrected transcript doesn't show its superseded lines too.
    """
    wanted = [w.lower() for w in _WORD.findall(words)]
    if not wanted:
        return []
    latest = {
        video_id: snapshot.transcript_id
        for video_id in session.scalars(select(TranscriptSnapshotRow.video_id).distinct())
        if (snapshot := _latest_snapshot(session, video_id)) is not None
    }
    if not latest:
        return []
    matches = [
        TranscriptCueRow.text.ilike(_like(word), escape="\\") for word in sorted(set(wanted))
    ]
    rows = session.execute(
        select(TranscriptCueRow, TranscriptSnapshotRow.video_id)
        .join(
            TranscriptSnapshotRow,
            TranscriptSnapshotRow.transcript_id == TranscriptCueRow.transcript_id,
        )
        .where(TranscriptCueRow.transcript_id.in_(sorted(latest.values())), and_(*matches))
        .order_by(TranscriptSnapshotRow.video_id, TranscriptCueRow.ordinal)
        .limit(limit)
    ).all()
    mentions: dict[str, list[VideoMention]] = {}
    hits = []
    for cue, video_id in rows:
        if video_id not in mentions:
            mentions[video_id] = video_mentions(session, video_id)
        found = mentions[video_id]
        seconds = cue.start_ms // 1000 if cue.start_ms is not None else None
        hits.append(
            CueHit(
                video_id,
                cue.transcript_id,
                cue.ordinal,
                seconds,
                watch_url(video_id, seconds),
                cue.text,
                tuple(sorted({m.conversation_id for m in found})),
                tuple(dict.fromkeys(m.revision_id for m in found)),
            )
        )
    return hits


# ---- accounts -------------------------------------------------------------


def registry_path() -> PurePosixPath:
    """Where the account registry note lives in the vault."""
    return safe_relative_path(ACCOUNTS_DIR, f"{REGISTRY_TITLE}.md")


def account_path(account_id: str) -> PurePosixPath:
    """Where one account's note lives (named by ID: handles are private text)."""
    suffix = account_id.replace("_", "-", 1)[:16]
    return safe_relative_path(ACCOUNTS_DIR, safe_filename("Account", suffix))


def _account_link(account_id: str) -> str:
    return f"[[{account_path(account_id).stem}]]"


def account_registry_note(session: Session) -> DocumentModel:
    """The registry: every account by platform, then the questions left to review."""
    summaries = account_summaries(session)
    kept = [s for s in summaries if s["identity_status"] != "rejected"]
    rejected = [s for s in summaries if s["identity_status"] == "rejected"]
    blocks: list[Block] = [
        Paragraph(
            "Every social account named in the chats, however it was written. "
            "Nothing here was looked up online; identities come from the text alone.",
            True,
        )
    ]
    by_platform: dict[str, list[str]] = defaultdict(list)
    for s in kept:
        by_platform[s["platform"]].append(_summary_line(s))
    blocks.append(Heading("Accounts", 2))
    if not by_platform:
        blocks.append(Paragraph("No accounts yet.", True))
    for platform in sorted(by_platform):
        blocks += [Heading(platform, 3), BulletList(tuple(by_platform[platform]), True)]
    ambiguous = ambiguous_handles(session)
    blocks += [
        Heading("Needs review", 2),
        Paragraph(
            "Bare @names with no platform. They are never filed under an account "
            "automatically, even when one has the same handle.",
            True,
        ),
        BulletList(
            tuple(
                f"`{_code(a['handle'])}`: {a['mentions']} mention(s) in "
                f"{a['conversations']} chat(s), {a['first_seen'] or '?'} to "
                f"{a['last_seen'] or '?'}"
                for a in ambiguous
            )
            or ("nothing to review",),
            True,
        ),
    ]
    if rejected:
        # SOC-004: a rejected account drops out of the registry. Each one's
        # own note keeps its mentions and review history.
        blocks += [
            Heading("Rejected", 2),
            Paragraph(
                f"{len(rejected)} account(s) a person rejected are left out. "
                "`ke accounts --all` lists them.",
                True,
            ),
        ]
    properties: dict[str, PropertyValue] = {
        "ke_type": "account_registry",
        "accounts": len(kept),
        "needs_review": len(ambiguous),
        "rejected": len(rejected),
        "generator": REGISTRY_NOTES_VERSION,
    }
    return DocumentModel(REGISTRY_TITLE, properties, tuple(blocks))


def _summary_line(s: dict[str, object]) -> str:
    handle = f"`{_code(str(s['handle']))}`" if s["handle"] else "(no handle)"
    return (
        f"{_account_link(str(s['account_id']))} {handle} ({s['identity_status']}): "
        f"{s['mentions']} mention(s) in {s['conversations']} chat(s), "
        f"{s['first_seen'] or '?'} to {s['last_seen'] or '?'}"
    )


def account_note(session: Session, account_id: str) -> DocumentModel:
    """One account's note: aliases, every mention, the chats. Reads only.

    Raises:
        KeyError: If there is no such account.
    """
    account = session.get(SocialAccountRow, account_id)
    if account is None:
        raise KeyError("no such account")
    aliases = session.scalars(
        select(AccountAliasRow)
        .where(AccountAliasRow.account_id == account_id)
        .order_by(AccountAliasRow.kind, AccountAliasRow.alias)
    ).all()
    mentions = account_mentions(session, account_id)
    cited = source_links(session, [m.revision_id for m in mentions])
    blocks: list[Block] = [
        Paragraph(f"Back to the [[{REGISTRY_TITLE}]].", True),
        Heading("Written as", 2),
        BulletList(
            tuple(f"`{_code(a.alias)}` ({a.kind})" for a in aliases) or ("no aliases",), True
        ),
        Heading("Mentions", 2),
        BulletList(
            tuple(
                f"{cited[m.revision_id].wikilink if m.revision_id in cited else m.revision_id}: "
                f"`{_code(m.raw_text)}` (by {m.actor or 'unknown'}, `{m.conversation_id}`)"
                for m in mentions
            )
            or ("no mentions",),
            True,
        ),
        Heading("Conversations", 2),
        BulletList(
            tuple(_chat_links(session, {m.conversation_id for m in mentions}) or ["none"]), True
        ),
    ]
    history = account_history(session, account_id)
    if history:
        blocks += [
            Heading("Review history", 2),
            BulletList(
                tuple(
                    # Reviewer and note are typed by a person: code spans keep
                    # them from turning into Markdown links or headings.
                    f"{r.at.isoformat(timespec='seconds')}: `{_code(r.reviewer)}` {r.action} "
                    f"({r.from_state} to {r.to_state})" + (f": `{_code(r.note)}`" if r.note else "")
                    for r in history
                ),
                True,
            ),
        ]
    properties: dict[str, PropertyValue] = {
        "ke_type": "social_account",
        "account_id": account_id,
        "platform": account.platform,
        "identity_status": account.identity_status,
        "mentions": len(mentions),
        "generator": REGISTRY_NOTES_VERSION,
    }
    return DocumentModel(f"Account {account_id}", properties, tuple(blocks))
