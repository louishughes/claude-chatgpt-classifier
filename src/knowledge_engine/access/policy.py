"""Who may do what: roles, permissions and the service-account rule (PROD-002).

A **role** is held by one account in one workspace. Each role is a fixed set
of **permissions**, and every API endpoint needs exactly one permission.
The table is small on purpose, so it can be read in one go:

=========  ====  ======  ======  =======  ======  ======
role       read  import  export  propose  review  manage
=========  ====  ======  ======  =======  ======  ======
viewer     yes
editor     yes   yes     yes     yes
reviewer   yes                   yes      yes
owner      yes   yes     yes     yes      yes     yes
=========  ====  ======  ======  =======  ======  ======

**Service policy.** A service account is a program, not a person. It can be
a viewer or an editor only: it may read, import, export and propose, but it
can never review (confirming or rejecting knowledge is a person's call, so
automation can't promote its own output to trusted) and never manage.

Talking points:
    - "Permissions come from one small table, so I can check who can do what
      without reading every endpoint."
    - "A program's account can import and read, but only a person can
      confirm knowledge."
"""

from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    """What an account is in one workspace."""

    VIEWER = "viewer"
    EDITOR = "editor"
    REVIEWER = "reviewer"
    OWNER = "owner"


class Permission(StrEnum):
    """One kind of action; every endpoint needs exactly one."""

    READ = "read"  # sources, knowledge, taxonomy, search, documents
    IMPORT = "import"  # start an import
    EXPORT = "export"  # write a vault export
    PROPOSE = "propose"  # suggest a taxonomy change (changes nothing yet)
    REVIEW = "review"  # decide proposals and knowledge records
    MANAGE = "manage"  # membership (CLI only for now)


class AccountKind(StrEnum):
    """A person, or a program acting on its own."""

    PERSON = "person"
    SERVICE = "service"


ROLE_PERMISSIONS: dict[Role, frozenset[Permission]] = {
    Role.VIEWER: frozenset({Permission.READ}),
    Role.EDITOR: frozenset(
        {Permission.READ, Permission.IMPORT, Permission.EXPORT, Permission.PROPOSE}
    ),
    Role.REVIEWER: frozenset({Permission.READ, Permission.PROPOSE, Permission.REVIEW}),
    Role.OWNER: frozenset(Permission),
}

# The roles a service account may hold (see the module docstring).
SERVICE_ROLES = frozenset({Role.VIEWER, Role.EDITOR})


def allows(role: Role, permission: Permission) -> bool:
    """Whether ``role`` includes ``permission``."""
    return permission in ROLE_PERMISSIONS[role]


def may_hold(kind: AccountKind, role: Role) -> bool:
    """Whether an account of this kind may be given this role."""
    return kind is AccountKind.PERSON or role in SERVICE_ROLES
