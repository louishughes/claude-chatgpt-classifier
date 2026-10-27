"""Fixed lists of states and kinds used across the engine.

Each list is a ``StrEnum``: a set of allowed values that are also plain
strings, so they read naturally in the database and in reports. Using an
enum instead of free text means a typo such as ``"unchaged"`` is caught
when the code runs, not discovered weeks later in a report. Values match
DATA_MODEL_AND_CONTRACTS §10 and must never be renamed once stored.

Talking points:
    - "Every status in the system comes from a closed list. Free-text
      statuses are how reports quietly go wrong."
    - "State changes are checked against an allowed-transitions table, so an
      import can't go from 'failed' back to 'running'."
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class SourceSystem(StrEnum):
    """Where a conversation came from. Only ChatGPT for the MVP."""

    CHATGPT = "chatgpt"


class Role(StrEnum):
    """Who wrote a message. ``unknown`` is used rather than guessing."""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
    TOOL = "tool"
    UNKNOWN = "unknown"


class DeltaCategory(StrEnum):
    """What a re-import found for a conversation or message (ADR-0003)."""

    NEW = "new"
    UNCHANGED = "unchanged"
    REVISED = "revised"
    NEW_BRANCH = "new_branch"
    NOT_SEEN = "not_seen"  # absent from this export: unknown, never "deleted"
    CANDIDATE_DUPLICATE = "candidate_duplicate"
    FAILED = "failed"


class PresenceState(StrEnum):
    """Whether a message node appeared in the latest full export."""

    PRESENT = "present"
    NOT_SEEN = "not_seen"


class ImportBatchStatus(StrEnum):
    """Lifecycle of one import attempt (DATA_MODEL §10.2)."""

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"
    ABANDONED = "abandoned"


class AssetAvailability(StrEnum):
    """Whether the bytes behind an asset reference were found (ADR-0004)."""

    AVAILABLE = "available"
    MISSING = "missing"  # known reference, no bytes
    UNRESOLVED = "unresolved"  # pointer scheme or ID not matched
    AMBIGUOUS = "ambiguous"  # several candidate files
    UNSUPPORTED = "unsupported"


class BranchKind(StrEnum):
    """Why a message has more than one child (REL-001)."""

    EDIT = "edit"  # the user edited their message
    REGENERATION = "regeneration"  # the assistant answer was regenerated
    OTHER = "other"


class ReviewState(StrEnum):
    """Review lifecycle for proposed links and candidate matches."""

    CANDIDATE = "candidate"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class JobState(StrEnum):
    """Lifecycle of one processing job (TECHNICAL_REQUIREMENTS TR-03)."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REVIEW_REQUIRED = "review_required"  # a person must look; never retried automatically
    SKIPPED = "skipped"


# Allowed state changes. Anything not listed is refused. Kept as data, not
# if-statements, so the whole lifecycle can be read (and tested) at a glance.
_IMPORT_TRANSITIONS: dict[ImportBatchStatus, frozenset[ImportBatchStatus]] = {
    ImportBatchStatus.RUNNING: frozenset(
        {
            ImportBatchStatus.SUCCEEDED,
            ImportBatchStatus.PARTIAL,
            ImportBatchStatus.FAILED,
            ImportBatchStatus.ABANDONED,
        }
    ),
    ImportBatchStatus.SUCCEEDED: frozenset(),
    ImportBatchStatus.PARTIAL: frozenset(),
    ImportBatchStatus.FAILED: frozenset(),
    ImportBatchStatus.ABANDONED: frozenset(),
}

_PRESENCE_TRANSITIONS: dict[PresenceState, frozenset[PresenceState]] = {
    PresenceState.PRESENT: frozenset({PresenceState.NOT_SEEN}),
    PresenceState.NOT_SEEN: frozenset({PresenceState.PRESENT}),
}

_REVIEW_TRANSITIONS: dict[ReviewState, frozenset[ReviewState]] = {
    ReviewState.CANDIDATE: frozenset({ReviewState.ACCEPTED, ReviewState.REJECTED}),
    ReviewState.ACCEPTED: frozenset({ReviewState.SUPERSEDED}),
    ReviewState.REJECTED: frozenset(),
    ReviewState.SUPERSEDED: frozenset(),
}


_JOB_TRANSITIONS: dict[JobState, frozenset[JobState]] = {
    JobState.PENDING: frozenset({JobState.RUNNING, JobState.SKIPPED}),
    # RUNNING -> PENDING is a transient failure with attempts left, or a
    # crashed run being resumed.
    JobState.RUNNING: frozenset(
        {JobState.SUCCEEDED, JobState.FAILED, JobState.REVIEW_REQUIRED, JobState.PENDING}
    ),
    JobState.SUCCEEDED: frozenset(),
    JobState.FAILED: frozenset(),
    JobState.REVIEW_REQUIRED: frozenset(),
    JobState.SKIPPED: frozenset(),
}


class InvalidTransitionError(ValueError):
    """Raised when a state change is not in the allowed-transitions table."""


def check_transition(
    current: ImportBatchStatus | PresenceState | ReviewState | JobState,
    new: ImportBatchStatus | PresenceState | ReviewState | JobState,
) -> None:
    """Refuse a state change that the lifecycle doesn't allow.

    Args:
        current: The state now.
        new: The requested next state (same enum type).

    Raises:
        InvalidTransitionError: If the change is not allowed, including
            mixing two different enums.
    """
    # StrEnum members compare equal to plain strings, so the type check comes
    # first: ReviewState "accepted" must never pass for another enum's value.
    if type(new) is not type(current):
        raise InvalidTransitionError(f"cannot go from {current.value!r} to {new.value!r}")
    allowed: frozenset[Any]
    if isinstance(current, ImportBatchStatus):
        allowed = _IMPORT_TRANSITIONS[current]
    elif isinstance(current, PresenceState):
        allowed = _PRESENCE_TRANSITIONS[current]
    elif isinstance(current, JobState):
        allowed = _JOB_TRANSITIONS[current]
    else:
        allowed = _REVIEW_TRANSITIONS[current]
    if new not in allowed:
        raise InvalidTransitionError(f"cannot go from {current.value!r} to {new.value!r}")
