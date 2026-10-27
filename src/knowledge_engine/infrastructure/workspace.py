"""The workspace table and its repository.

A workspace is the top-level container every other record belongs to. For
now there is a single local workspace, but storing its ID on records from
the start (TECHNICAL_REQUIREMENTS TR-05) means a second workspace or user
later doesn't need a data migration. This is also the first table, so it
proves the whole database path: define, create, write, read, roll back.

Talking points:
    - "Even a single-user app gets a workspace ID on day one, because adding
      it later means migrating every row."
    - "The repository is the only code that writes SQL for its table; the
      rest of the app calls methods like get_or_create()."
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from knowledge_engine.infrastructure.db import Base


def _utc_now() -> datetime:
    return datetime.now(UTC)


class WorkspaceRow(Base):
    """One row of the ``workspaces`` table.

    Attributes:
        workspace_id: Random, permanent ID. Never derived from the name, so
            renaming a workspace can't change its identity.
        name: Short unique label chosen by the user.
        created_at: When it was created (UTC).
    """

    __tablename__ = "workspaces"

    workspace_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


class WorkspaceRepo:
    """Reads and writes workspaces inside a caller's transaction.

    The repo never commits; the caller's ``SessionFactory.transaction()``
    decides when the work is final.
    """

    def __init__(self, session: Session) -> None:
        """Bind the repo to an open session.

        Args:
            session: A session from ``SessionFactory.transaction()``.
        """
        self._session = session

    def get(self, workspace_id: str) -> WorkspaceRow | None:
        """Return the workspace with this ID, or None if there isn't one.

        Args:
            workspace_id: The permanent ID.

        Returns:
            The row, or None.
        """
        return self._session.get(WorkspaceRow, workspace_id)

    def get_by_name(self, name: str) -> WorkspaceRow | None:
        """Return the workspace with this name, or None.

        Args:
            name: The workspace label.

        Returns:
            The row, or None.
        """
        return self._session.scalars(select(WorkspaceRow).where(WorkspaceRow.name == name)).first()

    def get_or_create(self, name: str) -> WorkspaceRow:
        """Return the named workspace, creating it if needed.

        Idempotent: calling it twice with the same name returns the same row.

        Args:
            name: The workspace label.

        Returns:
            The existing or new row.

        Raises:
            ValueError: If the name is empty or longer than 100 characters.
        """
        cleaned = name.strip()
        if not cleaned or len(cleaned) > 100:
            raise ValueError("workspace name must be 1-100 characters")
        existing = self.get_by_name(cleaned)
        if existing is not None:
            return existing
        row = WorkspaceRow(workspace_id=uuid.uuid4().hex, name=cleaned)
        self._session.add(row)
        self._session.flush()  # send the INSERT now so constraint errors surface here
        return row
