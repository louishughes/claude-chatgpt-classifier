"""Imports started from the browser, run in the background (UI-002).

An import can take minutes, longer than a browser waits for one page. So the
Import button starts a job on a background thread and sends you to a page
that refreshes itself until the job is done, then links to its report.

The job calls the same ``import_source`` as ``ke import``; the workspace
lock (IMP-004) still guarantees only one import runs at a time.

Talking points:
    - "Clicking Import starts the real importer in the background; the page
      checks back every couple of seconds and shows the report when done."
"""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass, field
from pathlib import Path

from knowledge_engine.importer import import_source
from knowledge_engine.importer.failures import describe_failure
from knowledge_engine.settings import Settings


@dataclass
class ImportJob:
    """One browser-started import and how it's going.

    Attributes:
        job_id: Random ID used in the progress page's address.
        state: ``running``, ``done`` or ``failed``.
        import_id: The ledger ID once finished.
        status: The import's own status (``succeeded``, ``partial``...).
        error: A plain reason when it failed (never a path).
    """

    job_id: str
    state: str = "running"
    import_id: str | None = None
    status: str | None = None
    error: str | None = None
    done: threading.Event = field(default_factory=threading.Event, repr=False)


class ImportJobs:
    """Starts imports in the background and remembers them while the app runs."""

    def __init__(self, settings: Settings) -> None:
        """Create the job list for one workspace.

        Args:
            settings: The workspace's settings.
        """
        self._settings = settings
        self._jobs: dict[str, ImportJob] = {}
        self._guard = threading.Lock()

    def start(self, source: Path, account: str, *, partial: bool) -> ImportJob:
        """Start importing ``source`` in the background and return its job."""
        job = ImportJob(job_id=secrets.token_hex(8))
        with self._guard:
            self._jobs[job.job_id] = job
        thread = threading.Thread(
            target=self._run, args=(job, source, account, partial), daemon=True
        )
        thread.start()
        return job

    def get(self, job_id: str) -> ImportJob | None:
        """Return a job by ID, or None."""
        with self._guard:
            return self._jobs.get(job_id)

    def _run(self, job: ImportJob, source: Path, account: str, partial: bool) -> None:
        try:
            report = import_source(
                source, account, settings=self._settings, full_export=not partial
            )
        except Exception as error:  # noqa: BLE001 - a failed job must still finish
            failure = describe_failure(error)
            # Only the error's type for unknown errors: its text can hold a path.
            job.error = (
                failure.message
                if failure
                else f"The import stopped with an unexpected error ({type(error).__name__})."
            )
            job.state = "failed"
        else:
            job.import_id = report.import_id
            job.status = report.status.value
            job.state = "done"
        finally:
            job.done.set()
