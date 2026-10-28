"""Separate workspaces for separate people, one folder each (PROD-003, ADR-0011).

With ``tenants_root`` set, the API serves several workspaces. Each one is a
complete, ordinary workspace in its own folder::

    <tenants_root>/
        workspaces/<name>/   its database, archive, search indexes, exports
        inbox/<name>/        export files waiting to be imported into it

Isolation comes from the folder, not from filters: a request for workspace
``a`` only ever opens ``workspaces/a``, so its SQL, word index, meaning
index, caches, answers, documents, exports, jobs and purges can't see
``b``'s, because they are different files. Nothing has to remember to add
``WHERE workspace = ...`` to every query.

Accounts live inside each workspace's own database (PROD-002), so a token
made in ``b`` isn't even known in ``a``.

Talking points:
    - "Each workspace is its own folder with its own database, so one
      person's chats can't leak into another's search: they are different
      files, not rows behind a filter."
    - "Deleting a workspace's data never touches another's folder."
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path

from knowledge_engine.access.accounts import add_account, grant, issue_token
from knowledge_engine.access.policy import AccountKind, Role
from knowledge_engine.infrastructure.db import SessionFactory, database_path
from knowledge_engine.infrastructure.migrations import upgrade_to_head
from knowledge_engine.settings import Settings

NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
# The workspace every tenant's own records belong to (as for a single user).
HOME = "default"


class TenantError(ValueError):
    """A workspace name or layout that isn't allowed (the message says why)."""


def _root(settings: Settings) -> Path:
    if settings.tenants_root is None:
        raise TenantError("tenants_root isn't set: this engine serves one workspace")
    return settings.tenants_root.resolve()


def _checked(name: str) -> str:
    # Names become folder names, so only plain characters: no "..", no "/".
    if not NAME_RE.fullmatch(name):
        raise TenantError("workspace names use letters, digits, '-' and '_' (1-64)")
    return name


def tenant_settings(settings: Settings, name: str) -> Settings:
    """The settings for one tenant: the same switches, its own folder."""
    folder = _root(settings) / "workspaces" / _checked(name)
    return settings.model_copy(update={"workspace_root": folder, "tenants_root": None})


def tenant_inbox(settings: Settings, name: str) -> Path:
    """Where export files for this tenant wait; the only place it may import from."""
    return _root(settings) / "inbox" / _checked(name)


def tenant_exists(settings: Settings, name: str) -> bool:
    """Whether the tenant has been created (it has a database)."""
    try:
        return database_path(tenant_settings(settings, name)).exists()
    except TenantError:
        return False


def list_tenants(settings: Settings) -> list[str]:
    """Every created tenant, by name."""
    folder = _root(settings) / "workspaces"
    if not folder.is_dir():
        return []
    return sorted(
        p.name
        for p in folder.iterdir()
        if NAME_RE.fullmatch(p.name) and tenant_exists(settings, p.name)
    )


def create_tenant(settings: Settings, name: str, owner: str) -> str:
    """Make a new workspace with one owner account; return the owner's token.

    Raises:
        TenantError: Bad name, no ``tenants_root``, or it already exists.
        AccessError: The owner's name isn't allowed.
    """
    if tenant_exists(settings, name):
        raise TenantError(f"workspace {name!r} already exists")
    tenant = tenant_settings(settings, name)
    tenant.workspace_root.mkdir(parents=True, exist_ok=True)
    tenant_inbox(settings, name).mkdir(parents=True, exist_ok=True)
    sessions = SessionFactory.from_settings(tenant)
    try:
        upgrade_to_head(sessions.engine)
        with sessions.transaction() as session:
            add_account(session, owner, AccountKind.PERSON)
            grant(session, owner, HOME, Role.OWNER, by="tenant-setup")
            return issue_token(session, owner)
    finally:
        sessions.dispose()


def delete_tenant(settings: Settings, name: str, confirm: str) -> list[str]:
    """Delete a whole workspace: its folder and its inbox (PROD-004).

    This is the erasure of everything one tenant stored. No other folder is
    opened. Backups taken earlier are separate copies and are not touched;
    the operator deletes those by the backup policy.

    Args:
        settings: The engine's settings (with ``tenants_root``).
        name: The workspace.
        confirm: The same name again, so a slip of the keyboard can't do it.

    Returns:
        The folders removed, relative to ``tenants_root``.

    Raises:
        TenantError: Unknown workspace, or ``confirm`` doesn't match.
    """
    if confirm != name:
        raise TenantError("to delete a workspace, repeat its name exactly to confirm")
    if not tenant_exists(settings, name):
        raise TenantError(f"no workspace named {name!r}")
    root = _root(settings)
    removed = []
    for folder in (root / "workspaces" / name, root / "inbox" / name):
        # Never follow a link out of tenants_root: check where it really is.
        if folder.is_symlink() or not folder.resolve().is_relative_to(root):
            raise TenantError("a workspace folder points outside tenants_root; delete it by hand")
        if folder.exists():
            shutil.rmtree(folder)
            removed.append(str(folder.relative_to(root)))
    return removed
