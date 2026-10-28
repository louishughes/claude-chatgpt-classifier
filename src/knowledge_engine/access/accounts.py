"""Accounts, their tokens, workspace membership and the authorisation log (PROD-002).

Four tables:

* ``accounts``: a person or a service (a program), by a unique name.
* ``account_tokens``: API tokens. Only a SHA-256 of each token is stored,
  so a copy of the database can't be used to log in. A token is shown once,
  when it is made.
* ``workspace_members``: one role per account per workspace.
* ``authz_events``: the authorisation log. Every refusal, every allowed
  change (anything but reading) and every membership change. Rows can't be
  edited or deleted (database triggers). It names the route, never the
  query text, because a search query can be private words.

**Turning it on.** While there are no accounts, the API works as before:
one person on their own computer. Adding the first account turns checking
on for every endpoint except ``/health``: from then on a request needs a
token, and the token's account needs a role in the workspace.

Talking points:
    - "The database keeps a fingerprint of each token, never the token, so a
      leaked backup isn't a leaked login."
    - "Every refused request and every change is in an append-only log."
"""

from __future__ import annotations

import hashlib
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Integer, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from knowledge_engine.access.policy import AccountKind, Permission, Role, allows, may_hold
from knowledge_engine.infrastructure.db import Base
from knowledge_engine.infrastructure.workspace import WorkspaceRepo, WorkspaceRow

NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
TOKEN_PREFIX = "ke_"
_ACCOUNT_ID = re.compile(r"^[0-9a-f]{32}$")


def _utc_now() -> datetime:
    return datetime.now(UTC)


class AccessError(ValueError):
    """An account or membership change that isn't allowed (the message says why)."""


class AccountRow(Base):
    """One account: a person or a service."""

    __tablename__ = "accounts"

    account_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    kind: Mapped[str] = mapped_column(String(16))  # AccountKind
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AccountTokenRow(Base):
    """One API token, stored as its SHA-256 only."""

    __tablename__ = "account_tokens"

    token_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(32), index=True)
    token_sha256: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MembershipRow(Base):
    """An account's role in one workspace."""

    __tablename__ = "workspace_members"

    workspace_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    role: Mapped[str] = mapped_column(String(16))  # Role
    granted_by: Mapped[str] = mapped_column(String(64))
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


class AuthzEventRow(Base):
    """One authorisation decision or membership change. Never edited or deleted."""

    __tablename__ = "authz_events"

    event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    # The account's random ID, never its name, so deleting the account leaves
    # the log pseudonymous (PROD-004); "" when there was no valid token.
    account: Mapped[str] = mapped_column(String(64))
    workspace_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    permission: Mapped[str] = mapped_column(String(16))
    resource: Mapped[str] = mapped_column(String(200))  # method and route, never query text
    allowed: Mapped[bool] = mapped_column(Boolean)
    reason: Mapped[str] = mapped_column(String(32))


# Created by migration 0029: the log outlives the accounts it mentions.
AUTHZ_LOG_TRIGGERS = (
    "CREATE TRIGGER IF NOT EXISTS authz_events_no_update BEFORE UPDATE ON authz_events "
    "BEGIN SELECT RAISE(ABORT, 'authz_events is an audit log'); END",
    "CREATE TRIGGER IF NOT EXISTS authz_events_no_delete BEFORE DELETE ON authz_events "
    "BEGIN SELECT RAISE(ABORT, 'authz_events is an audit log'); END",
)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def auth_enabled(session: Session) -> bool:
    """Whether checking is on: true once any account exists."""
    return session.scalar(select(AccountRow.account_id).limit(1)) is not None


def get_account(session: Session, name: str) -> AccountRow:
    """The account with this name.

    Raises:
        AccessError: There isn't one.
    """
    row = session.scalar(select(AccountRow).where(AccountRow.name == name))
    if row is None:
        raise AccessError(f"no account named {name!r}")
    return row


def add_account(session: Session, name: str, kind: AccountKind) -> AccountRow:
    """Create an account (it can do nothing until it is given a role).

    Raises:
        AccessError: The name is taken or has characters other than letters,
            digits, ``.``, ``-`` and ``_``.
    """
    if not NAME_RE.fullmatch(name):
        raise AccessError("account names use letters, digits, '.', '-' and '_' (1-64)")
    if session.scalar(select(AccountRow.account_id).where(AccountRow.name == name)):
        raise AccessError(f"an account named {name!r} already exists")
    row = AccountRow(account_id=uuid.uuid4().hex, name=name, kind=kind.value)
    session.add(row)
    session.flush()
    return row


def issue_token(session: Session, name: str) -> str:
    """Make a new API token for an account and return it (shown only now).

    Raises:
        AccessError: No such account, or it is disabled.
    """
    account = get_account(session, name)
    if account.disabled_at is not None:
        raise AccessError(f"{name!r} is disabled")
    token = TOKEN_PREFIX + secrets.token_urlsafe(32)
    session.add(
        AccountTokenRow(
            token_id=uuid.uuid4().hex, account_id=account.account_id, token_sha256=_hash(token)
        )
    )
    session.flush()
    return token


def revoke_tokens(session: Session, name: str) -> int:
    """Revoke every live token of an account; returns how many."""
    account = get_account(session, name)
    live = session.scalars(
        select(AccountTokenRow).where(
            AccountTokenRow.account_id == account.account_id,
            AccountTokenRow.revoked_at.is_(None),
        )
    ).all()
    for row in live:
        row.revoked_at = _utc_now()
    session.flush()
    return len(live)


def disable_account(session: Session, name: str) -> None:
    """Stop an account from logging in at all (its tokens are revoked too)."""
    account = get_account(session, name)
    revoke_tokens(session, name)
    account.disabled_at = account.disabled_at or _utc_now()
    session.flush()


def authenticate(session: Session, token: str) -> AccountRow | None:
    """The live account a token belongs to, or None (unknown, revoked or disabled)."""
    if not token.startswith(TOKEN_PREFIX):
        return None
    row = session.scalar(
        select(AccountRow)
        .join(AccountTokenRow, AccountTokenRow.account_id == AccountRow.account_id)
        .where(AccountTokenRow.token_sha256 == _hash(token), AccountTokenRow.revoked_at.is_(None))
    )
    if row is None or row.disabled_at is not None:
        return None
    return row


def role_in(session: Session, account_id: str, workspace_id: str) -> Role | None:
    """The account's role in a workspace, or None when it isn't a member."""
    value = session.scalar(
        select(MembershipRow.role).where(
            MembershipRow.account_id == account_id, MembershipRow.workspace_id == workspace_id
        )
    )
    return Role(value) if value else None


def _log(
    session: Session,
    account: str,
    workspace_id: str | None,
    permission: Permission,
    resource: str,
    allowed: bool,
    reason: str,
) -> None:
    session.add(
        AuthzEventRow(
            account=account,
            workspace_id=workspace_id,
            permission=permission.value,
            resource=resource[:200],
            allowed=allowed,
            reason=reason,
        )
    )
    session.flush()


def grant(session: Session, name: str, workspace: str, role: Role, by: str) -> MembershipRow:
    """Give an account a role in a workspace (replacing any role it had).

    Raises:
        AccessError: No such account, or a service account asked for a role
            it may not hold (reviewer or owner).
    """
    account = get_account(session, name)
    if not may_hold(AccountKind(account.kind), role):
        raise AccessError(f"a service account can't be a {role.value}: only viewer or editor")
    workspace_id = WorkspaceRepo(session).get_or_create(workspace).workspace_id
    row = session.get(MembershipRow, (workspace_id, account.account_id))
    if row is None:
        row = MembershipRow(workspace_id=workspace_id, account_id=account.account_id)
        session.add(row)
    row.role, row.granted_by, row.granted_at = role.value, by, _utc_now()
    resource = f"grant {account.account_id} {role.value}"
    _log(session, by, workspace_id, Permission.MANAGE, resource, True, "ok")
    return row


def remove_member(session: Session, name: str, workspace: str, by: str) -> bool:
    """Take an account out of a workspace; False when it wasn't a member."""
    account = get_account(session, name)
    found = WorkspaceRepo(session).get_by_name(workspace)
    row = session.get(MembershipRow, (found.workspace_id, account.account_id)) if found else None
    if row is None or found is None:
        return False
    session.delete(row)
    resource = f"remove {account.account_id}"
    _log(session, by, found.workspace_id, Permission.MANAGE, resource, True, "ok")
    return True


def rotate_token(session: Session, name: str) -> str:
    """Revoke every token of an account and issue one new one (key rotation)."""
    revoke_tokens(session, name)
    return issue_token(session, name)


def delete_account(session: Session, name: str, by: str) -> str:
    """Erase an account: its row, its tokens and its roles (PROD-004).

    The authorisation log keeps its rows (it is append-only), but they only
    ever held the account's random ID, which nothing links to a name once
    the account row is gone. Returns that ID, shortened, for the record.
    """
    account = get_account(session, name)
    for model in (AccountTokenRow, MembershipRow):
        for row in session.scalars(select(model).where(model.account_id == account.account_id)):
            session.delete(row)
    session.delete(account)
    _log(session, by, None, Permission.MANAGE, f"delete {account.account_id}", True, "ok")
    return account.account_id[:8]


@dataclass(frozen=True)
class Decision:
    """The answer to "may this account do this here?"."""

    allowed: bool
    reason: str  # ok, no_token, not_a_member, forbidden
    role: Role | None = None


def authorize(
    session: Session,
    account: AccountRow | None,
    workspace_id: str | None,
    permission: Permission,
    resource: str,
) -> Decision:
    """Decide one request and log it (refusals and changes; plain reads aren't logged).

    Args:
        session: An open session; the caller commits so the log row is kept
            even when the request is refused.
        account: The authenticated account, or None (no or bad token).
        workspace_id: The workspace the request is about; None when it
            doesn't exist yet (then only a refusal is possible).
        permission: What the endpoint needs.
        resource: Method and route template, e.g. ``GET /api/v1/sources``.
    """
    if account is None:
        decision = Decision(False, "no_token")
    else:
        role = role_in(session, account.account_id, workspace_id) if workspace_id else None
        if role is None:
            decision = Decision(False, "not_a_member")
        elif not allows(role, permission):
            decision = Decision(False, "forbidden", role)
        else:
            decision = Decision(True, "ok", role)
    if not decision.allowed or permission is not Permission.READ:
        who = account.account_id if account else ""
        _log(session, who, workspace_id, permission, resource, decision.allowed, decision.reason)
    return decision


def members(session: Session) -> list[dict[str, str | None]]:
    """Every account with its kind, state and roles (no tokens)."""
    workspaces = {row.workspace_id: row.name for row in session.scalars(select(WorkspaceRow))}
    rows = []
    for account in session.scalars(select(AccountRow).order_by(AccountRow.name)):
        roles = session.scalars(
            select(MembershipRow).where(MembershipRow.account_id == account.account_id)
        ).all()
        rows.append(
            {
                "name": account.name,
                "kind": account.kind,
                "disabled": "yes" if account.disabled_at else None,
                "roles": ", ".join(
                    f"{workspaces.get(m.workspace_id, m.workspace_id)}:{m.role}" for m in roles
                )
                or None,
            }
        )
    return rows


def authz_log(session: Session, limit: int = 50) -> list[dict[str, object]]:
    """The newest authorisation events, newest first."""
    rows = session.scalars(
        select(AuthzEventRow).order_by(AuthzEventRow.event_id.desc()).limit(limit)
    ).all()
    names = {a.account_id: a.name for a in session.scalars(select(AccountRow))}

    def shown(value: str) -> str:
        # Account IDs read as names while the account exists; a deleted one
        # stays an anonymous, shortened ID. Anything else ("", "cli") as is.
        if value in names:
            return names[value]
        return f"deleted-{value[:8]}" if _ACCOUNT_ID.fullmatch(value) else value

    return [
        {
            "at": row.at.isoformat(),
            "account": shown(row.account),
            "workspace_id": row.workspace_id,
            "permission": row.permission,
            "resource": " ".join(shown(word) for word in row.resource.split(" ")),
            "allowed": row.allowed,
            "reason": row.reason,
        }
        for row in rows
    ]
