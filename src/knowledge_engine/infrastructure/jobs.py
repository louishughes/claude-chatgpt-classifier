"""Processing jobs: one row per unit of work, keyed by its stage key.

Every stage (parse a file, compute a delta, later classify a segment) runs
as a job. The job row records its stage key, state, attempts, result and a
checkpoint, so a crashed run can resume where it stopped and a finished one
is never repeated. The retry rules from the owner's guardrails live here:
transient errors (timeouts, malformed output) retry up to ``max_attempts``
in total, semantic problems go to a person (``review_required``) and are
never retried, and permanent errors fail at once.

Talking points:
    - "A job knows if it's already done: asking for the same stage key twice
      returns the saved result instead of running again."
    - "Retries are bounded and only for errors that might go away. A wrong
      answer isn't retried, it's flagged for review."
    - "Checkpoints are saved inside the same transaction as the work, so a
      crash can't leave them out of step."
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import CheckConstraint, DateTime, Integer, String, Text, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from knowledge_engine.domain.enums import JobState, check_transition
from knowledge_engine.infrastructure.db import Base

ErrorKind = Literal["transient", "permanent", "semantic"]
DEFAULT_MAX_ATTEMPTS = 3  # owner guardrail: 3 attempts in total for transient errors


def _utc_now() -> datetime:
    return datetime.now(UTC)


class JobRow(Base):
    """One row of the ``jobs`` table.

    Attributes:
        job_id: Random permanent ID.
        stage_id: Stage name and contract version.
        stage_key: Fingerprint of input and versions; unique.
        input_hash: SHA-256 of the input, kept for diagnostics.
        versions_json: The versions that went into the key, as JSON.
        state: A ``JobState`` value.
        attempts: How many times it has started.
        max_attempts: Limit on starts.
        result_json: The saved output summary, once succeeded.
        last_error: Short error text from the latest failure. Never contains
            source content; callers pass a code and a short message.
        checkpoint_json: Progress marker for resuming long jobs.
    """

    __tablename__ = "jobs"
    __table_args__ = (
        CheckConstraint(
            "state IN ('pending','running','succeeded','failed','review_required','skipped')",
            name="state_valid",
        ),
        CheckConstraint("attempts >= 0 AND attempts <= max_attempts", name="attempts_bounded"),
    )

    job_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    stage_id: Mapped[str] = mapped_column(String(100), index=True)
    stage_key: Mapped[str] = mapped_column(String(68), unique=True)
    input_hash: Mapped[str] = mapped_column(String(64))
    versions_json: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(20), default=JobState.PENDING.value)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=DEFAULT_MAX_ATTEMPTS)
    result_json: Mapped[str | None] = mapped_column(Text, default=None)
    last_error: Mapped[str | None] = mapped_column(String(500), default=None)
    checkpoint_json: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utc_now, onupdate=_utc_now
    )


@dataclass(frozen=True)
class ClaimResult:
    """What ``JobRepository.claim`` found.

    Attributes:
        job: The job row.
        cache_hit: True if this exact work already succeeded, so the caller
            should reuse ``job.result_json`` and not run anything.
    """

    job: JobRow
    cache_hit: bool


class AttemptsExhaustedError(RuntimeError):
    """Raised when starting a job that has used all of its attempts."""


class JobRepository:
    """Creates, claims and updates jobs inside the caller's transaction."""

    def __init__(self, session: Session) -> None:
        """Bind the repository to an open session.

        Args:
            session: A session from ``SessionFactory.transaction()``.
        """
        self._session = session

    def by_key(self, key: str) -> JobRow | None:
        """Return the job with this stage key, or None.

        Args:
            key: A ``stg_`` stage key.

        Returns:
            The row, or None.
        """
        return self._session.scalars(select(JobRow).where(JobRow.stage_key == key)).first()

    def claim(
        self,
        stage_id: str,
        key: str,
        input_hash: str,
        versions: dict[str, str],
        *,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> ClaimResult:
        """Find or create the job for a stage key.

        Idempotent: claiming the same key twice returns the same job. A job
        that already succeeded is reported as a cache hit.

        Args:
            stage_id: Stage name and contract version.
            key: The stage key from ``stage_keys.stage_key``.
            input_hash: SHA-256 of the input.
            versions: Versions used to compute the key.
            max_attempts: Attempt limit for a new job (1 or more).

        Returns:
            The job and whether it is a cache hit.

        Raises:
            ValueError: If ``max_attempts`` is below 1.
        """
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        existing = self.by_key(key)
        if existing is not None:
            return ClaimResult(existing, existing.state == JobState.SUCCEEDED.value)
        job = JobRow(
            job_id=uuid.uuid4().hex,
            stage_id=stage_id,
            stage_key=key,
            input_hash=input_hash,
            versions_json=json.dumps(versions, sort_keys=True),
            state=JobState.PENDING.value,
            attempts=0,
            max_attempts=max_attempts,
        )
        self._session.add(job)
        self._session.flush()
        return ClaimResult(job, False)

    def start(self, job: JobRow) -> None:
        """Move a pending job to running and count the attempt.

        Args:
            job: A pending job.

        Raises:
            AttemptsExhaustedError: If no attempts are left.
            InvalidTransitionError: If the job is not pending.
        """
        # Check the state first, so a finished job reports "not pending"
        # rather than a misleading "out of attempts".
        check_transition(JobState(job.state), JobState.RUNNING)
        if job.attempts >= job.max_attempts:
            raise AttemptsExhaustedError(f"job {job.job_id} has used {job.attempts} attempts")
        self._move(job, JobState.RUNNING)
        job.attempts += 1

    def succeed(self, job: JobRow, result: dict[str, Any]) -> None:
        """Mark a running job as done and store its result summary.

        Args:
            job: A running job.
            result: JSON-serialisable summary (IDs and counts, not content).
        """
        self._move(job, JobState.SUCCEEDED)
        job.result_json = json.dumps(result, sort_keys=True)
        job.last_error = None

    def fail(self, job: JobRow, kind: ErrorKind, message: str) -> JobState:
        """Record a failure and decide what happens next.

        - ``transient`` (timeout, invalid JSON): back to pending if attempts
          remain, otherwise failed.
        - ``semantic`` (a well-formed but doubtful answer): review_required,
          never retried.
        - ``permanent`` (bad input, bug): failed.

        Args:
            job: A running job.
            kind: The error kind.
            message: Short, content-free description (truncated to 500).

        Returns:
            The job's new state.
        """
        if kind == "transient" and job.attempts < job.max_attempts:
            new = JobState.PENDING
        elif kind == "semantic":
            new = JobState.REVIEW_REQUIRED
        else:
            new = JobState.FAILED
        self._move(job, new)
        job.last_error = f"{kind}: {message}"[:500]
        return new

    def skip(self, job: JobRow, reason: str) -> None:
        """Mark a pending job as deliberately not run.

        Args:
            job: A pending job.
            reason: Short explanation, stored in ``last_error``.
        """
        self._move(job, JobState.SKIPPED)
        job.last_error = f"skipped: {reason}"[:500]

    def save_checkpoint(self, job: JobRow, checkpoint: dict[str, Any]) -> None:
        """Store progress so an interrupted job can resume.

        Saved in the caller's transaction, so it commits together with the
        work it describes.

        Args:
            job: A running job.
            checkpoint: JSON-serialisable progress marker.

        Raises:
            ValueError: If the job isn't running.
        """
        if job.state != JobState.RUNNING.value:
            raise ValueError("only a running job can save a checkpoint")
        job.checkpoint_json = json.dumps(checkpoint, sort_keys=True)

    def checkpoint(self, job: JobRow) -> dict[str, Any] | None:
        """Return the last saved checkpoint, or None.

        Args:
            job: Any job.

        Returns:
            The checkpoint dict, or None.
        """
        if job.checkpoint_json is None:
            return None
        data: dict[str, Any] = json.loads(job.checkpoint_json)
        return data

    def recover_interrupted(self) -> int:
        """Return jobs left ``running`` by a crash to ``pending``.

        Call once at start-up, before any work runs, while holding the write
        lock. Checkpoints are kept, so resumed jobs continue from them.

        Returns:
            How many jobs were recovered.
        """
        stuck = self._session.scalars(select(JobRow).where(JobRow.state == JobState.RUNNING.value))
        count = 0
        for job in stuck:
            self._move(job, JobState.PENDING)
            count += 1
        return count

    def _move(self, job: JobRow, new: JobState) -> None:
        check_transition(JobState(job.state), new)
        job.state = new.value
        self._session.flush()
