"""Who is calling, and may they? Applied to every API endpoint (PROD-002).

``check_access`` runs before every endpoint. It looks the endpoint up in
``ROUTE_PERMISSIONS`` (one line per endpoint, so the whole policy is in one
place) and then:

* **No accounts yet** (or a database from before accounts existed): the
  API works as it always has, for the one person on this computer.
* **Accounts exist**: the request needs ``Authorization: Bearer ke_...``.
  No or bad token: 401 ``unauthenticated``. The account isn't a member of
  the workspace: 403 ``not_a_member``. Its role lacks the permission: 403
  ``forbidden``. Each refusal is written to the authorisation log.
* Once accounts exist, an endpoint missing from the table is refused
  (403), so a new endpoint can't be open by accident; a test checks every
  route is listed.

Where a request body names a person (``reviewer``, ``proposer``), that name
must be the caller's own account (403 ``identity_mismatch``), so nobody can
review under someone else's name, and "you can't review your own proposal"
can't be dodged by typing another name.

The API serves one workspace, the one imports write to (``default``).
Choosing among several workspaces in one database is PROD-003.

Talking points:
    - "Once I add an account, every endpoint needs a token, and the whole
      permission policy is one table I can read."
    - "A request can only act under its own name, so reviews can't be
      forged."
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from knowledge_engine.access.accounts import AccountRow, auth_enabled, authenticate, authorize
from knowledge_engine.access.policy import ROLE_PERMISSIONS, Permission, Role
from knowledge_engine.api.deps import ApiError, SettingsDep
from knowledge_engine.importer.run import DEFAULT_WORKSPACE_NAME
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.infrastructure.upgrade import schema_status
from knowledge_engine.infrastructure.workspace import WorkspaceRepo

P = "/api/v1"
R, IMP, EXP, PRO, REV = (
    Permission.READ,
    Permission.IMPORT,
    Permission.EXPORT,
    Permission.PROPOSE,
    Permission.REVIEW,
)

# (method, route) -> what it needs. None: open to anyone (health only).
ROUTE_PERMISSIONS: dict[tuple[str, str], Permission | None] = {
    ("GET", f"{P}/health"): None,
    ("GET", f"{P}/status"): R,
    ("GET", f"{P}/counts"): R,
    ("GET", f"{P}/access/me"): R,
    # sources and imports
    ("POST", f"{P}/imports"): IMP,
    ("GET", f"{P}/jobs/{{job_id}}"): R,
    ("GET", f"{P}/imports"): R,
    ("GET", f"{P}/imports/{{import_id}}"): R,
    ("GET", f"{P}/sources"): R,
    ("GET", f"{P}/sources/{{conversation_id}}"): R,
    ("GET", f"{P}/sources/{{conversation_id}}/nodes"): R,
    # taxonomy and knowledge
    ("GET", f"{P}/taxonomy"): R,
    ("GET", f"{P}/taxonomy/versions/{{version}}"): R,
    ("GET", f"{P}/taxonomy/governance"): R,
    ("GET", f"{P}/taxonomy/proposals"): R,
    ("POST", f"{P}/taxonomy/proposals"): PRO,
    ("POST", f"{P}/taxonomy/proposals/{{proposal_id}}/review"): REV,
    ("GET", f"{P}/knowledge"): R,
    ("GET", f"{P}/review"): R,
    ("GET", f"{P}/knowledge/{{record_id}}"): R,
    ("POST", f"{P}/knowledge/{{record_id}}/review"): REV,
    # retrieval
    ("GET", f"{P}/search"): R,
    ("GET", f"{P}/find"): R,
    ("POST", f"{P}/answers"): R,
    ("GET", f"{P}/decisions/{{record_id}}/history"): R,
    # documents and exports
    ("GET", f"{P}/documents"): R,
    ("GET", f"{P}/documents/preview"): R,
    ("GET", f"{P}/exports"): R,
    ("POST", f"{P}/exports"): EXP,
    ("GET", f"{P}/exports/jobs/{{job_id}}"): R,
}


@dataclass(frozen=True)
class Access:
    """The caller, as ``check_access`` found it.

    Attributes:
        enabled: False while there are no accounts (single-user mode).
        account: The account's name, or None in single-user mode.
        role: Its role in the workspace, or None in single-user mode.
    """

    enabled: bool
    account: str | None = None
    role: Role | None = None

    def require_identity(self, name: str) -> None:
        """Refuse a body that names someone other than the caller.

        Raises:
            ApiError: 403 ``identity_mismatch``.
        """
        if self.enabled and name.strip() != self.account:
            raise ApiError(
                403, "identity_mismatch", "act under your own account name, not someone else's"
            )


_OPEN = Access(enabled=False)


def _bearer(request: Request) -> str:
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    return token.strip() if scheme.lower() == "bearer" else ""


def check_access(request: Request, settings: SettingsDep) -> None:
    """Authenticate and authorise one request (see the module docstring).

    Raises:
        ApiError: 401 ``unauthenticated``, 403 ``not_a_member``,
            ``forbidden`` or ``identity_mismatch``, or 503
            ``schema_mismatch`` for a database newer than the code.
    """
    # An included router's route knows only its own path ("/sources"); every
    # router is included under P, so P is put back for the table lookup.
    path = getattr(request.scope.get("route"), "path", "")
    key = (request.method, path if path.startswith(P) else P + path)
    listed = key in ROUTE_PERMISSIONS
    # Unlisted routes need MANAGE, which no API endpoint grants: refused below.
    permission = ROUTE_PERMISSIONS.get(key, Permission.MANAGE)
    request.state.access = _OPEN
    if permission is None or not database_path(settings).exists():
        return
    engine = create_sqlite_engine(database_path(settings))
    try:
        status = schema_status(engine)
        if status == "ahead":
            # Accounts may exist in a schema this code can't read: fail closed.
            raise ApiError(503, "schema_mismatch", "the database is newer than this version")
        if status != "current":
            return  # older than accounts: nothing to check yet (endpoints refuse anyway)
        with Session(engine) as session:
            if not auth_enabled(session):
                return
            if not listed:
                raise ApiError(403, "forbidden", "this endpoint has no access rule")
            access = _decide(session, request, permission, " ".join(key))
            session.commit()  # keep the log row, refused or not
    finally:
        engine.dispose()
    if isinstance(access, ApiError):
        raise access
    request.state.access = access


def _decide(
    session: Session, request: Request, permission: Permission, resource: str
) -> Access | ApiError:
    account: AccountRow | None = authenticate(session, _bearer(request))
    workspace = WorkspaceRepo(session).get_by_name(DEFAULT_WORKSPACE_NAME)
    decision = authorize(
        session, account, workspace.workspace_id if workspace else None, permission, resource
    )
    if decision.allowed:
        return Access(enabled=True, account=account.name if account else None, role=decision.role)
    if decision.reason == "no_token":
        return ApiError(401, "unauthenticated", "send Authorization: Bearer <your API token>")
    if decision.reason == "not_a_member":
        return ApiError(403, "not_a_member", "this account has no role in this workspace")
    return ApiError(403, "forbidden", f"this account's role can't {permission.value} here")


def get_access(request: Request) -> Access:
    """The caller ``check_access`` found (single-user mode if it didn't run)."""
    found: Access = getattr(request.state, "access", _OPEN)
    return found


AccessDep = Annotated[Access, Depends(get_access)]

router = APIRouter()


@router.get("/access/me", tags=["access"])
def me(access: AccessDep) -> dict[str, Any]:
    """Who the API thinks you are, your role and what it lets you do."""
    allowed = sorted(p.value for p in ROLE_PERMISSIONS[access.role]) if access.role else []
    return {
        "checking": access.enabled,
        "account": access.account,
        "workspace": DEFAULT_WORKSPACE_NAME,
        "role": access.role.value if access.role else None,
        "permissions": allowed if access.enabled else [p.value for p in Permission],
    }
