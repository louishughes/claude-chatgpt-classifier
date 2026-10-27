"""One import at a time per workspace: the single-writer import lock (IMP-004).

Each conversation group already commits under SQLite's write lock, so two
imports can never write a duplicate row. But a whole import also makes
decisions that assume it is alone: "this batch is still ``running``, so an
earlier run crashed" and "this conversation wasn't touched by *my* import,
so it's ``not_seen``". Two imports interleaving would get those wrong. So
the whole import holds an operating-system file lock on
``<workspace>/import.lock``; a second import waits for it.

The OS releases the lock when the process exits, even after a crash, so a
dead import can never leave the workspace locked.

Talking points:
    - "Two imports at once simply queue: the second waits, then finds
      everything already imported and reports it unchanged."
    - "The lock is the operating system's, so a crash can't leave it stuck."
"""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

LOCK_FILE_NAME = "import.lock"


class ImportLockTimeoutError(TimeoutError):
    """Another import held the workspace lock for longer than the timeout."""


def _try_lock(fd: int) -> bool:
    if sys.platform == "win32":
        import msvcrt

        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except OSError:
            return False
        return True
    import fcntl

    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return False
    return True


def _unlock(fd: int) -> None:
    if sys.platform == "win32":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_UN)


@contextmanager
def import_lock(workspace_root: Path, *, timeout_s: float, poll_s: float = 0.05) -> Iterator[None]:
    """Hold the workspace's import lock for the duration of the block.

    Args:
        workspace_root: The workspace folder (created if missing).
        timeout_s: How long to wait for another import to finish.
        poll_s: How often to retry while waiting.

    Yields:
        None, while the lock is held.

    Raises:
        ImportLockTimeoutError: If the lock wasn't free within ``timeout_s``.
    """
    workspace_root.mkdir(parents=True, exist_ok=True)
    fd = os.open(workspace_root / LOCK_FILE_NAME, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        deadline = time.monotonic() + timeout_s
        while not _try_lock(fd):
            if time.monotonic() >= deadline:
                raise ImportLockTimeoutError(
                    f"another import is still running after {timeout_s:g}s"
                )
            time.sleep(poll_s)
        try:
            yield
        finally:
            _unlock(fd)
    finally:
        os.close(fd)
