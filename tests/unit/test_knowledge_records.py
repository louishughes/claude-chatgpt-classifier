"""EXT-001: the record schema forbids unsupported trusted records and unknown types."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from knowledge_engine.domain.enums import Role
from knowledge_engine.domain.models import EvidenceRef
from knowledge_engine.extraction.records import (
    CandidateRecord,
    KnowledgeRecord,
    Trust,
    TrustTransitionError,
    advance,
)
from knowledge_engine.graph.offsets import quote_hash

EVIDENCE = EvidenceRef(
    revision_id="rev_" + "1" * 32,
    start=0,
    end=9,
    quote_sha256=quote_hash("Synthetic"),
    actor=Role.USER,
)
PROVENANCE = {
    "stage_id": "extract.decisions.v1",
    "stage_key": "stg_" + "2" * 64,
    "extractor_version": "ext-003-v1",
}


def _record(**overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "record_id": "krec_" + "3" * 32,
        "record_type": "decision",
        "assertion": "Synthetic: use Godot",
        "actor": "user",
        "acceptance": "explicit",
        "scope": "segment",
        "scope_id": "seg_1",
        "evidence": [EVIDENCE.model_dump()],
        "provenance": PROVENANCE,
    }
    data.update(overrides)
    return data


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"record_type": "rumour"}, "record_type"),
        ({"trust": "certain"}, "trust"),
        ({"colour": "blue"}, "Extra inputs"),
        ({"evidence": []}, "needs source evidence"),
        ({"provenance": None}, "needs provenance"),
        ({"scope_id": None}, "needs scope_id"),
        ({"trust": "supported"}, "passed validation"),
        ({"trust": "confirmed", "evidence_checked_by": "ext-002-v1"}, "named reviewer"),
        (
            {
                "trust": "confirmed",
                "origin": "inferred",
                "evidence_checked_by": "v",
                "reviewer": "r",
            },
            "inferred record",
        ),
        # A user decision with no acceptance can't be trusted, however good the quote.
        ({"trust": "supported", "evidence_checked_by": "v", "acceptance": "absent"}, "acceptance"),
        (
            {"trust": "supported", "evidence_checked_by": "v", "acceptance": "inferred"},
            "acceptance",
        ),
    ],
)
def test_schema_forbids_unsupported_trusted_records_and_unknown_types(
    overrides: dict[str, Any], message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        KnowledgeRecord.model_validate(_record(**overrides))


def test_trusted_records_that_follow_the_rules() -> None:
    supported = KnowledgeRecord.model_validate(
        _record(trust="supported", evidence_checked_by="ext-002-v1")
    )
    assert supported.trust is Trust.SUPPORTED
    # An assistant's proposal can be supported without user acceptance: it is
    # recorded as the assistant's proposal, not as the user's decision.
    proposal = _record(
        record_type="proposal",
        actor="assistant",
        acceptance="absent",
        trust="supported",
        evidence_checked_by="v",
        evidence=[EVIDENCE.model_copy(update={"actor": Role.ASSISTANT})],
    )
    assert KnowledgeRecord.model_validate(proposal).actor is Role.ASSISTANT
    # A reviewer's own entry needs no machine provenance or quotes.
    own = _record(
        origin="reviewer",
        evidence=[],
        provenance=None,
        trust="confirmed",
        reviewer="reviewer-a",
        scope="global",
        scope_id=None,
    )
    assert KnowledgeRecord.model_validate(own).trust is Trust.CONFIRMED


def test_extractor_output_has_no_trust_field() -> None:
    data = {k: v for k, v in _record().items() if k not in ("record_id", "provenance")}
    candidate = CandidateRecord.model_validate(data)
    assert not hasattr(candidate, "trust")
    with pytest.raises(ValidationError, match="Extra inputs"):
        CandidateRecord.model_validate({**data, "trust": "confirmed"})
    with pytest.raises(ValidationError, match="reviewer"):
        CandidateRecord.model_validate({**data, "origin": "reviewer"})


def test_trust_moves_only_along_the_table() -> None:
    record = KnowledgeRecord.model_validate(_record())
    with pytest.raises(TrustTransitionError):
        advance(record, Trust.CONFIRMED)  # candidate can't jump to confirmed
    with pytest.raises(ValidationError, match="passed validation"):
        advance(record, Trust.SUPPORTED)  # the move is allowed, the record isn't ready
    supported = advance(record, Trust.SUPPORTED, evidence_checked_by="ext-002-v1")
    confirmed = advance(supported, Trust.CONFIRMED, reviewer="reviewer-a")
    assert (record.trust, confirmed.trust) == (Trust.CANDIDATE, Trust.CONFIRMED)
    rejected = advance(record, Trust.REJECTED, reviewer="reviewer-a")
    with pytest.raises(TrustTransitionError):
        advance(rejected, Trust.SUPPORTED)  # rejected is final
