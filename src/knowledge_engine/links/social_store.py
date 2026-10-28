"""The social account registry: accounts, aliases and mentions (SOC-002).

* ``social_accounts``: one row per account, keyed by platform and the
  platform's permanent ID when a URL gives one, otherwise by the handle
  (case-insensitive);
* ``account_aliases``: every way the account was written (a profile URL,
  a handle), so "github.com/Octo" and "GitHub: @octo" are visibly the same;
* ``account_mentions``: every mention, keyed by message revision and span.
  A bare @handle is stored with ``resolution='ambiguous'`` and no account:
  it is never linked automatically, even if an account with that handle
  exists.

Identity status starts at ``probable``: the engine only ever has text, so
it never claims ``confirmed``. A person (or a review step) can change it.

Talking points:
    - "One account, however it was written, with every mention listed; and
      an unqualified @name stays a question, not an identity."
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

from knowledge_engine.domain.ids import account_mention_id, social_account_id
from knowledge_engine.infrastructure.db import Base
from knowledge_engine.links.extract import CITATION_METADATA, MESSAGE_TEXT
from knowledge_engine.links.social import AMBIGUOUS, RESOLVED, FoundAccount

_STATUSES = "'confirmed','probable','ambiguous','rejected'"


def _utc_now() -> datetime:
    return datetime.now(UTC)


class SocialAccountRow(Base):
    """One social account, however many ways it was written."""

    __tablename__ = "social_accounts"
    __table_args__ = (
        UniqueConstraint("platform", "stable_platform_id"),
        UniqueConstraint("platform", "canonical_handle"),
        CheckConstraint(f"identity_status IN ({_STATUSES})", name="identity_status_valid"),
    )

    account_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    platform: Mapped[str] = mapped_column(String(20), index=True)
    stable_platform_id: Mapped[str | None] = mapped_column(String(100), default=None)
    # Lower-case, no "@": handles are case-insensitive on these platforms.
    canonical_handle: Mapped[str | None] = mapped_column(String(300), default=None)
    profile_url: Mapped[str | None] = mapped_column(Text, default=None)
    identity_status: Mapped[str] = mapped_column(String(12), default="probable")
    first_import_id: Mapped[str] = mapped_column(ForeignKey("import_batches.import_id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


class AccountAliasRow(Base):
    """One way an account was written: a URL or a handle, as seen."""

    __tablename__ = "account_aliases"
    __table_args__ = (UniqueConstraint("account_id", "kind", "alias"),)

    alias_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    account_id: Mapped[str] = mapped_column(ForeignKey("social_accounts.account_id"), index=True)
    alias: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(String(12))  # handle | url


class AccountMentionRow(Base):
    """One mention of a (possible) account at an exact place in a revision."""

    __tablename__ = "account_mentions"
    __table_args__ = (
        UniqueConstraint("revision_id", "start", "end", "origin"),
        CheckConstraint(
            f"resolution IN ('{RESOLVED}','{AMBIGUOUS}','rejected')", name="resolution_valid"
        ),
        CheckConstraint(f"origin IN ('{MESSAGE_TEXT}','{CITATION_METADATA}')", name="origin_valid"),
        CheckConstraint(
            f"resolution != '{RESOLVED}' OR account_id IS NOT NULL", name="resolved_has_account"
        ),
    )

    mention_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    revision_id: Mapped[str] = mapped_column(
        ForeignKey("message_revisions.revision_id"), index=True
    )
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.conversation_id"), index=True
    )
    origin: Mapped[str] = mapped_column(String(20))
    start: Mapped[int] = mapped_column(Integer)
    end: Mapped[int] = mapped_column(Integer)
    raw_text: Mapped[str] = mapped_column(Text)
    platform: Mapped[str | None] = mapped_column(String(20), default=None)
    # The handle as written (for an ambiguous mention, the only clue).
    handle: Mapped[str | None] = mapped_column(String(300), default=None)
    account_id: Mapped[str | None] = mapped_column(
        ForeignKey("social_accounts.account_id"), default=None, index=True
    )
    resolution: Mapped[str] = mapped_column(String(12))
    actor: Mapped[str | None] = mapped_column(String(20), default=None)
    first_import_id: Mapped[str] = mapped_column(ForeignKey("import_batches.import_id"))


def record_accounts(
    session: Session,
    mentions: Iterable[tuple[str, str | None, FoundAccount]],
    *,
    conversation_id: str,
    import_id: str,
) -> Counter[str]:
    """Store the account mentions of one conversation's current revisions.

    Args:
        session: The batch's write session.
        mentions: ``(revision_id, actor, found account)`` triples.
        conversation_id: The ``conv_`` ID.
        import_id: The running batch.

    Returns:
        ``new_accounts``, ``new_mentions`` and ``ambiguous_mentions`` counts.
    """
    counts: Counter[str] = Counter()
    for revision_id, actor, found in mentions:
        key = account_mention_id(revision_id, found.span.start, found.span.end, found.origin)
        account_id = None
        if found.resolution == RESOLVED and found.platform is not None:
            account_id = _account(session, found, import_id, counts)
        if session.get(AccountMentionRow, key) is not None:
            continue
        session.add(
            AccountMentionRow(
                mention_id=key,
                revision_id=revision_id,
                conversation_id=conversation_id,
                origin=found.origin,
                start=found.span.start,
                end=found.span.end,
                raw_text=found.raw,
                platform=found.platform,
                handle=found.handle,
                account_id=account_id,
                resolution=found.resolution,
                actor=actor,
                first_import_id=import_id,
            )
        )
        session.flush()
        counts["new_mentions"] += 1
        if found.resolution == AMBIGUOUS:
            counts["ambiguous_mentions"] += 1
    return counts


def _account(session: Session, found: FoundAccount, import_id: str, counts: Counter[str]) -> str:
    assert found.platform is not None  # checked by the caller
    handle = found.handle.lower() if found.handle else None
    account_id = social_account_id(
        found.platform,
        stable_platform_id=found.stable_id,
        handle=None if found.stable_id else handle,
    )
    if session.get(SocialAccountRow, account_id) is None:
        session.add(
            SocialAccountRow(
                account_id=account_id,
                platform=found.platform,
                stable_platform_id=found.stable_id,
                canonical_handle=None if found.stable_id else handle,
                profile_url=found.profile_url,
                first_import_id=import_id,
            )
        )
        session.flush()
        counts["new_accounts"] += 1
    kind = "url" if found.raw.lower().startswith(("http://", "https://")) else "handle"
    alias = found.raw if kind == "url" else f"@{found.handle}"
    exists = (
        session.query(AccountAliasRow)
        .filter_by(account_id=account_id, kind=kind, alias=alias)
        .one_or_none()
    )
    if exists is None:
        session.add(AccountAliasRow(account_id=account_id, alias=alias, kind=kind))
        session.flush()
    return account_id
