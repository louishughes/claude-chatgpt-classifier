"""API-003: taxonomy, review and knowledge endpoints.

The acceptance check: an unauthorised or invalid transition is rejected,
and a rejected request changes nothing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from knowledge_engine.api.app import PREFIX, create_app
from knowledge_engine.extraction.decisions import extract_decisions
from knowledge_engine.extraction.preferences import extract_preferences
from knowledge_engine.extraction.records import (
    Acceptance,
    CandidateRecord,
    Provenance,
    RecordType,
    Trust,
)
from knowledge_engine.extraction.store import add_candidates, gate
from knowledge_engine.extraction.text import segment_extraction_messages
from knowledge_engine.importer import import_source
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.infrastructure.db import SessionFactory
from knowledge_engine.rendering.transcript import load_conversation
from knowledge_engine.segmentation.segmenter import segment_conversation
from knowledge_engine.settings import Settings
from knowledge_engine.taxonomy.registry import TaxonomyRegistry

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt"
PROVENANCE = Provenance(
    stage_id="extract.test.v1", stage_key="stg_" + "b" * 64, extractor_version="test-v1"
)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    settings = Settings(workspace_root=tmp_path / "ws")
    import_source(FIXTURES / "extraction_rules" / "export", "fixture", settings=settings)
    return settings


@pytest.fixture
def client(settings: Settings) -> TestClient:
    return TestClient(
        create_app(settings), base_url="http://127.0.0.1:8766", raise_server_exceptions=False
    )


def _candidates(settings: Settings) -> list[CandidateRecord]:
    sessions = SessionFactory.from_settings(settings)
    found: list[CandidateRecord] = []
    with sessions.transaction(write=False) as session:
        for conversation_id in session.query(ConversationRow.conversation_id).all():
            conv = load_conversation(session, conversation_id[0])
            for seg in segment_conversation(conv):
                messages = segment_extraction_messages(conv, seg)
                found += extract_decisions(messages, segment_id=seg.segment_id)
                found += extract_preferences(messages, segment_id=seg.segment_id)
    sessions.dispose()
    return found


def _store(settings: Settings, candidates: list[CandidateRecord], *, gated: bool) -> list[Any]:
    sessions = SessionFactory.from_settings(settings)
    with sessions.transaction() as session:
        records = add_candidates(session, candidates, PROVENANCE)
        if gated:
            records = [gate(session, r.record_id) for r in records]
    sessions.dispose()
    return records


def _error(response: Any) -> str:
    code: str = response.json()["error"]["code"]
    return code


# ------------------------------------------------------------------ taxonomy


def _propose(client: TestClient, label: str, proposer: str = "alice") -> dict[str, Any]:
    response = client.post(
        f"{PREFIX}/taxonomy/proposals",
        json={
            "operation": "add",
            "payload": {"label": label, "dimension": "topic"},
            "proposer": proposer,
        },
    )
    assert response.status_code == 201, response.text
    body: dict[str, Any] = response.json()
    return body


def test_a_proposal_goes_through_review_once(client: TestClient) -> None:
    proposal = _propose(client, "Rust")
    pid = proposal["proposal_id"]
    assert proposal["status"] == "open"
    assert client.get(f"{PREFIX}/taxonomy").json()["terms"] == []  # nothing changed yet
    assert [p["proposal_id"] for p in client.get(f"{PREFIX}/review").json()["proposals"]] == [pid]

    review = f"{PREFIX}/taxonomy/proposals/{pid}/review"
    own = client.post(review, json={"decision": "approve", "reviewer": "Alice "})
    assert own.status_code == 403 and _error(own) == "reviewer_not_allowed"
    assert client.get(f"{PREFIX}/taxonomy").json()["terms"] == []

    approved = client.post(review, json={"decision": "approve", "reviewer": "bob"}).json()
    assert approved["status"] == "approved" and approved["reviewer"] == "bob"
    [term] = client.get(f"{PREFIX}/taxonomy").json()["terms"]
    assert term["term_id"] == approved["result_id"] and term["status"] == "approved"

    again = client.post(review, json={"decision": "reject", "reviewer": "carol", "note": "no"})
    assert again.status_code == 409 and _error(again) == "invalid_transition"
    listed = client.get(f"{PREFIX}/taxonomy/proposals", params={"status": "all"}).json()
    assert [p["status"] for p in listed["items"]] == ["approved"]


def test_a_failed_approval_changes_nothing(client: TestClient) -> None:
    first = _propose(client, "Rust")
    client.post(
        f"{PREFIX}/taxonomy/proposals/{first['proposal_id']}/review",
        json={"decision": "approve", "reviewer": "bob"},
    )
    clash = _propose(client, "rust")  # the same spelling once normalised
    refused = client.post(
        f"{PREFIX}/taxonomy/proposals/{clash['proposal_id']}/review",
        json={"decision": "approve", "reviewer": "bob"},
    )
    assert refused.status_code == 409 and _error(refused) == "invalid_transition"
    assert len(client.get(f"{PREFIX}/taxonomy").json()["terms"]) == 1
    assert client.get(f"{PREFIX}/taxonomy/proposals").json()["items"][0]["status"] == "open"


def test_bad_proposals_and_decisions_are_refused(client: TestClient) -> None:
    missing = client.post(
        f"{PREFIX}/taxonomy/proposals",
        json={"operation": "add", "payload": {"dimension": "topic"}, "proposer": "alice"},
    )
    assert missing.status_code == 400 and _error(missing) == "invalid_proposal"
    unknown_op = client.post(
        f"{PREFIX}/taxonomy/proposals",
        json={"operation": "delete", "payload": {}, "proposer": "alice"},
    )
    assert _error(unknown_op) == "invalid_request"
    pid = _propose(client, "Go")["proposal_id"]
    review = f"{PREFIX}/taxonomy/proposals/{pid}/review"
    assert _error(client.post(review, json={"decision": "maybe", "reviewer": "bob"})) == (
        "invalid_request"
    )
    no_reason = client.post(review, json={"decision": "reject", "reviewer": "bob"})
    assert _error(no_reason) == "invalid_transition"
    assert _error(client.post(review, json={"decision": "approve", "reviewer": ""})) == (
        "invalid_request"
    )
    nowhere = client.post(
        f"{PREFIX}/taxonomy/proposals/prop_nope/review",
        json={"decision": "approve", "reviewer": "bob"},
    )
    assert nowhere.status_code == 404


def test_published_versions_and_governance(client: TestClient, settings: Settings) -> None:
    pid = _propose(client, "Python")["proposal_id"]
    client.post(
        f"{PREFIX}/taxonomy/proposals/{pid}/review",
        json={"decision": "approve", "reviewer": "bob"},
    )
    sessions = SessionFactory.from_settings(settings)
    with sessions.transaction() as session:
        TaxonomyRegistry(session).publish("tax-1", author="bob")
    sessions.dispose()
    assert client.get(f"{PREFIX}/taxonomy").json()["versions"] == ["tax-1"]
    snapshot = client.get(f"{PREFIX}/taxonomy/versions/tax-1").json()
    assert [t["label"] for t in snapshot["terms"]] == ["Python"]
    assert client.get(f"{PREFIX}/taxonomy/versions/tax-9").status_code == 404
    report = client.get(f"{PREFIX}/taxonomy/governance").json()
    assert report["terms"] == {"approved": 1}


# ----------------------------------------------------------------- knowledge


def test_knowledge_lists_only_checked_records(client: TestClient, settings: Settings) -> None:
    records = _store(settings, _candidates(settings), gated=True)
    supported = {r.record_id for r in records if r.trust is Trust.SUPPORTED}
    waiting = {r.record_id for r in records if r.trust is Trust.REVIEW_REQUIRED}
    assert supported and waiting
    knowledge = client.get(f"{PREFIX}/knowledge").json()["items"]
    assert {r["record_id"] for r in knowledge} == supported
    queue = client.get(f"{PREFIX}/review").json()["records"]
    assert {r["record_id"] for r in queue} == waiting
    decisions = client.get(f"{PREFIX}/knowledge", params={"type": "decision"}).json()["items"]
    assert all(r["record_type"] == "decision" for r in decisions)
    one = client.get(f"{PREFIX}/knowledge/{sorted(waiting)[0]}").json()
    assert one["record"]["evidence"]  # the anchors a reviewer checks
    assert [e["to"] for e in one["history"]] == ["candidate", "review_required"]


def test_record_decisions_follow_the_lifecycle(client: TestClient, settings: Settings) -> None:
    records = _store(settings, _candidates(settings), gated=True)
    target = next(r for r in records if r.trust is Trust.SUPPORTED).record_id
    review = f"{PREFIX}/knowledge/{target}/review"

    as_validator = client.post(review, json={"decision": "confirm", "reviewer": "validator"})
    assert as_validator.status_code == 403 and _error(as_validator) == "reviewer_not_allowed"

    confirmed = client.post(review, json={"decision": "confirm", "reviewer": "bob", "note": "ok"})
    assert confirmed.json()["trust"] == "confirmed"
    history = client.get(f"{PREFIX}/knowledge/{target}").json()["history"]
    assert history[-1] == {**history[-1], "to": "confirmed", "actor": "bob", "note": "ok"}

    # Confirmed can only be superseded, never rejected or confirmed again.
    for decision in ("reject", "confirm", "support"):
        refused = client.post(review, json={"decision": decision, "reviewer": "bob"})
        assert refused.status_code == 409 and _error(refused) == "invalid_transition", decision
    assert client.get(f"{PREFIX}/knowledge/{target}").json()["record"]["trust"] == "confirmed"


def test_a_suggestion_cannot_become_the_users_decision(
    client: TestClient, settings: Settings
) -> None:
    decision = next(r for r in _candidates(settings) if r.record_type is RecordType.DECISION)
    unaccepted = decision.model_copy(
        update={"acceptance": Acceptance.ABSENT, "review_reason": None}
    )
    [record] = _store(settings, [unaccepted], gated=True)
    assert record.trust is Trust.REVIEW_REQUIRED
    refused = client.post(
        f"{PREFIX}/knowledge/{record.record_id}/review",
        json={"decision": "support", "reviewer": "bob"},
    )
    assert refused.status_code == 409
    assert "acceptance" in refused.json()["error"]["message"]
    after = client.get(f"{PREFIX}/knowledge/{record.record_id}").json()
    assert after["record"]["trust"] == "review_required"  # rolled back, nothing logged
    assert [e["to"] for e in after["history"]] == ["candidate", "review_required"]


def test_ungated_and_unknown_records(client: TestClient, settings: Settings) -> None:
    [record] = _store(settings, _candidates(settings)[:1], gated=False)
    early = client.post(
        f"{PREFIX}/knowledge/{record.record_id}/review",
        json={"decision": "confirm", "reviewer": "bob"},
    )
    assert early.status_code == 409 and "gate first" in early.json()["error"]["message"]
    assert client.get(f"{PREFIX}/knowledge/krec_nope").status_code == 404
    unknown = client.post(
        f"{PREFIX}/knowledge/krec_nope/review", json={"decision": "reject", "reviewer": "bob"}
    )
    assert unknown.status_code == 404
