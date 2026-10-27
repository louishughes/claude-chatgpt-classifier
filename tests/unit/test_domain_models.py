"""FND-005 acceptance: Pydantic validation of the core value objects."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from knowledge_engine.domain import ids
from knowledge_engine.domain.enums import (
    AssetAvailability,
    DeltaCategory,
    ImportBatchStatus,
    InvalidTransitionError,
    PresenceState,
    ReviewState,
    Role,
    check_transition,
)
from knowledge_engine.domain.models import (
    AssetOccurrence,
    EvidenceRef,
    MessageRevision,
    SourceSnapshot,
)

CONV = ids.conversation_id("ws0", "chatgpt", "fixture", "c1")
NODE = ids.message_node_id(CONV, "n1")
CONTENT = "1" * 64
REV = ids.message_revision_id(NODE, CONTENT)


def _revision(**changes: object) -> MessageRevision:
    data: dict[str, object] = {
        "revision_id": REV,
        "node_id": NODE,
        "canonical_content_hash": CONTENT,
        "raw_payload_hash": "2" * 64,
        "role": "user",
        "create_time": datetime(2025, 1, 2, 3, 4, 5, tzinfo=UTC),
        "content_type": "text",
    }
    data.update(changes)
    return MessageRevision.model_validate(data)


# ---------------------------------------------------------------- SourceSnapshot


def test_snapshot_round_trips_through_json() -> None:
    sha = ids.sha256_hex(b"synthetic export bytes")
    snap = SourceSnapshot(
        snapshot_id=ids.snapshot_id(sha), sha256=sha, byte_size=22, source_format="chatgpt-split-v1"
    )
    assert SourceSnapshot.model_validate_json(snap.model_dump_json()) == snap


def test_snapshot_with_wrong_id_is_rejected() -> None:
    with pytest.raises(ValidationError, match="does not match"):
        SourceSnapshot(
            snapshot_id=ids.snapshot_id("0" * 64), sha256="1" * 64, byte_size=1, source_format="x"
        )


# ---------------------------------------------------------------- MessageRevision


def test_revision_is_valid_and_frozen() -> None:
    revision = _revision()
    assert revision.role is Role.USER
    with pytest.raises(ValidationError):
        revision.role = Role.ASSISTANT


def test_revision_id_must_match_content_hash() -> None:
    with pytest.raises(ValidationError, match="does not match"):
        _revision(canonical_content_hash="3" * 64)


def test_missing_timestamp_stays_missing() -> None:
    assert _revision(create_time=None).create_time is None


def test_naive_timestamp_is_rejected() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        _revision(create_time=datetime(2025, 1, 2, 3, 4, 5))


@pytest.mark.parametrize(
    "changes",
    [
        {"role": "boss"},
        {"node_id": CONV},
        {"raw_payload_hash": "short"},
        {"content_type": ""},
        {"surprise": 1},
    ],
)
def test_bad_revision_fields_are_rejected(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _revision(**changes)


# ---------------------------------------------------------------- AssetOccurrence


def _occurrence(**changes: object) -> AssetOccurrence:
    pointer = changes.pop("pointer", "file-service://file-SYNTHETIC1")
    part = changes.pop("part_index", 0)
    data: dict[str, object] = {
        "occurrence_id": ids.asset_occurrence_id(REV, part, pointer),  # type: ignore[arg-type]
        "revision_id": REV,
        "part_index": part,
        "pointer": pointer,
        "asset_id": ids.media_asset_id("ws0", "chatgpt", native_file_id="file-SYNTHETIC1"),
        "availability": "available",
    }
    data.update(changes)
    return AssetOccurrence.model_validate(data)


def test_available_occurrence_is_valid() -> None:
    assert _occurrence().availability is AssetAvailability.AVAILABLE


def test_available_occurrence_needs_an_asset() -> None:
    with pytest.raises(ValidationError, match="must name its asset"):
        _occurrence(asset_id=None)


@pytest.mark.parametrize("state", ["missing", "unresolved", "ambiguous", "unsupported"])
def test_unavailable_occurrence_may_lack_an_asset(state: str) -> None:
    occurrence = _occurrence(asset_id=None, availability=state, evidence={"disk": "absent"})
    assert occurrence.asset_id is None


def test_occurrence_id_must_match_its_key() -> None:
    with pytest.raises(ValidationError, match="does not match"):
        _occurrence(occurrence_id=ids.asset_occurrence_id(REV, 9, "other"))


# ---------------------------------------------------------------- EvidenceRef


def test_evidence_range_must_be_non_empty() -> None:
    EvidenceRef(revision_id=REV, start=0, end=1, quote_sha256="4" * 64, actor=Role.USER)
    with pytest.raises(ValidationError):
        EvidenceRef(revision_id=REV, start=3, end=3, quote_sha256="4" * 64, actor=Role.USER)
    with pytest.raises(ValidationError):
        EvidenceRef(revision_id=REV, start=-1, end=3, quote_sha256="4" * 64, actor=Role.USER)


# ---------------------------------------------------------------- enums and transitions


def test_enum_values_match_the_data_model() -> None:
    assert {c.value for c in DeltaCategory} == {
        "new",
        "unchanged",
        "revised",
        "new_branch",
        "not_seen",
        "candidate_duplicate",
        "failed",
    }
    assert {a.value for a in AssetAvailability} == {
        "available",
        "missing",
        "unresolved",
        "ambiguous",
        "unsupported",
    }


def test_import_batch_never_returns_to_running() -> None:
    check_transition(ImportBatchStatus.RUNNING, ImportBatchStatus.PARTIAL)
    for final in (ImportBatchStatus.SUCCEEDED, ImportBatchStatus.FAILED, ImportBatchStatus.PARTIAL):
        with pytest.raises(InvalidTransitionError):
            check_transition(final, ImportBatchStatus.RUNNING)


def test_not_seen_can_become_present_again() -> None:
    check_transition(PresenceState.PRESENT, PresenceState.NOT_SEEN)
    check_transition(PresenceState.NOT_SEEN, PresenceState.PRESENT)


def test_review_lifecycle() -> None:
    check_transition(ReviewState.CANDIDATE, ReviewState.ACCEPTED)
    check_transition(ReviewState.ACCEPTED, ReviewState.SUPERSEDED)
    with pytest.raises(InvalidTransitionError):
        check_transition(ReviewState.REJECTED, ReviewState.ACCEPTED)
    with pytest.raises(InvalidTransitionError):
        check_transition(ReviewState.CANDIDATE, ReviewState.SUPERSEDED)


def test_mixing_enums_is_refused() -> None:
    with pytest.raises(InvalidTransitionError):
        check_transition(PresenceState.PRESENT, ImportBatchStatus.FAILED)
