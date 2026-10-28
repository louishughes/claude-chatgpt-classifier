"""REC-001: the same claim twice is proposed, never merged; near misses stay distinct."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DatabaseError
from sqlalchemy.orm import Session

from knowledge_engine.domain.enums import Role
from knowledge_engine.domain.models import EvidenceRef
from knowledge_engine.extraction.records import (
    Acceptance,
    CandidateRecord,
    KnowledgeRecord,
    Provenance,
    RecordType,
    Trust,
)
from knowledge_engine.extraction.store import KnowledgeRecordRow, add_candidates, gate
from knowledge_engine.infrastructure.db import create_sqlite_engine
from knowledge_engine.infrastructure.migrations import upgrade_to_head
from knowledge_engine.reconciliation.equivalence import (
    Basis,
    EquivalenceError,
    State,
    compare,
    equivalence_groups,
    find_candidates,
    pair_id,
    pairs,
    propose_equivalences,
    review,
)

# Each claim is said in two chats (two stage keys).
CLAIMS = {
    "exact": ("Use SQLite for storage.", "use sqlite for storage"),
    "similar": (
        "Store everything locally in SQLite",
        "Store everything locally in a SQLite database",
    ),
    "numbers": ("Run the server on port 8080", "Run the server on port 8081"),
    "negation": ("Deploy with Docker", "Don't deploy with Docker"),
    "unrelated": ("Write the docs in Markdown", "Paint the shed door red"),
}


def _evidence() -> EvidenceRef:
    return EvidenceRef(
        revision_id="rev_" + "0" * 32,
        start=0,
        end=9,
        quote_sha256=hashlib.sha256(b"Synthetic").hexdigest(),
        actor=Role.USER,
    )


def _candidate(assertion: str, **extra: Any) -> CandidateRecord:
    fields: dict[str, Any] = {
        "record_type": RecordType.DECISION,
        "assertion": assertion,
        "actor": Role.USER,
        "acceptance": Acceptance.EXPLICIT,
        "evidence": (_evidence(),),
        "scope_id": "seg_synthetic",
        **extra,
    }
    return CandidateRecord(**fields)


def _provenance(chat: int) -> Provenance:
    return Provenance(
        stage_id="extract.test.v1", stage_key="stg_" + str(chat) * 64, extractor_version="t"
    )


@pytest.fixture
def session(tmp_path: Path) -> Iterator[Session]:
    engine = create_sqlite_engine(tmp_path / "ke.db")
    upgrade_to_head(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def _store(session: Session) -> dict[str, tuple[KnowledgeRecord, KnowledgeRecord]]:
    stored = {}
    for name, (first, second) in CLAIMS.items():
        [a] = add_candidates(session, [_candidate(first)], _provenance(1))
        [b] = add_candidates(session, [_candidate(second)], _provenance(2))
        stored[name] = (a, b)
    return stored


def test_candidates_by_basis(session: Session) -> None:
    stored = _store(session)
    found = {c.pair_id: c for c in find_candidates([r for p in stored.values() for r in p])}
    basis = {
        name: found[pair_id(a.record_id, b.record_id)].basis
        for name, (a, b) in stored.items()
        if pair_id(a.record_id, b.record_id) in found
    }
    assert basis == {
        "exact": Basis.EXACT,
        "similar": Basis.SIMILAR,
        "numbers": Basis.NEAR_MISS,
        "negation": Basis.NEAR_MISS,
    }
    a, b = stored["numbers"]
    assert found[pair_id(a.record_id, b.record_id)].differences == ("numbers",)
    a, b = stored["negation"]
    assert found[pair_id(a.record_id, b.record_id)].differences == ("negation",)
    assert len(found) == 4  # nothing across different claims


def test_different_scope_person_or_kind_never_pairs(session: Session) -> None:
    [base] = add_candidates(session, [_candidate("Use SQLite for storage")], _provenance(1))
    variants = {
        "project": {"project_ids": ("proj_synthetic_a",)},
        "reported": {"attributed_to": "external", "review_reason": "reported view"},
        "kind": {"record_type": RecordType.REQUIREMENT, "strength": "hard"},
    }
    for chat, (name, extra) in enumerate(variants.items(), start=2):
        [other] = add_candidates(
            session, [_candidate("Use SQLite for storage", **extra)], _provenance(chat)
        )
        assert compare(base, other) is None, name
    rejected = base.model_copy(update={"trust": Trust.REJECTED})
    [twin] = add_candidates(session, [_candidate("use sqlite for storage")], _provenance(9))
    assert compare(rejected, twin) is None
    assert compare(base, twin) is not None


def test_proposals_wait_for_a_reviewer_and_records_never_change(session: Session) -> None:
    stored = _store(session)
    before = {r.record_id: r.record_json for r in session.scalars(select(KnowledgeRecordRow))}
    report = propose_equivalences(session)
    assert len(report.added) == 4 and report.known == ()
    assert {row.state for row in pairs(session)} == {"proposed"}
    assert equivalence_groups(session) == []  # even the exact repeat waits
    again = propose_equivalences(session)
    assert again.added == () and sorted(again.known) == sorted(report.added)
    exact = pair_id(*(r.record_id for r in stored["exact"]))
    review(session, exact, State.CONFIRMED, reviewer="review-session-3")
    assert equivalence_groups(session) == [tuple(sorted(r.record_id for r in stored["exact"]))]
    # A re-run neither re-opens nor changes a reviewed pair.
    propose_equivalences(session)
    assert session.get_one(type(pairs(session)[0]), exact).state == "confirmed"
    after = {r.record_id: r.record_json for r in session.scalars(select(KnowledgeRecordRow))}
    assert after == before


def test_near_miss_needs_a_reason_and_rejected_records_cannot_join(session: Session) -> None:
    stored = _store(session)
    propose_equivalences(session)
    near = pair_id(*(r.record_id for r in stored["numbers"]))
    with pytest.raises(EquivalenceError, match="near miss"):
        review(session, near, State.CONFIRMED, reviewer="r")
    review(session, near, State.REJECTED, reviewer="r", note="different ports")
    with pytest.raises(EquivalenceError, match="already rejected"):
        review(session, near, State.REJECTED, reviewer="r")
    with pytest.raises(EquivalenceError, match="named reviewer"):
        review(session, near, State.CONFIRMED, reviewer=" ", note="x")
    with pytest.raises(KeyError):
        review(session, "req_missing", State.CONFIRMED, reviewer="r")
    similar = stored["similar"]
    gate(session, similar[0].record_id)  # the dummy quote fails: rejected
    with pytest.raises(EquivalenceError, match="rejected record"):
        review(session, pair_id(*(r.record_id for r in similar)), State.CONFIRMED, reviewer="r")
    session.commit()
    for statement in (
        "UPDATE record_equivalence_reviews SET reviewer = 'x'",
        "DELETE FROM record_equivalence_reviews",
    ):
        with pytest.raises(DatabaseError, match="append-only"):
            session.execute(text(statement))
        session.rollback()


def test_cli_detect_review_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from knowledge_engine.cli.main import main
    from knowledge_engine.infrastructure.db import database_path
    from knowledge_engine.settings import Settings

    settings = Settings(workspace_root=tmp_path / "ws")
    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(settings.workspace_root))
    assert main(["--json", "duplicates", "list"]) != 0  # no database yet
    capsys.readouterr()
    database_path(settings).parent.mkdir(parents=True, exist_ok=True)
    engine = create_sqlite_engine(database_path(settings))
    upgrade_to_head(engine)
    with Session(engine) as session:
        stored = _store(session)
        session.commit()
    engine.dispose()
    assert main(["--json", "duplicates", "detect"]) == 0
    assert len(json.loads(capsys.readouterr().out)["data"]["added"]) == 4
    exact = pair_id(*(r.record_id for r in stored["exact"]))
    assert main(["--json", "duplicates", "review", exact, "confirmed", "--reviewer", "r"]) == 0
    data = json.loads(capsys.readouterr().out)["data"]
    assert len(data["groups"]) == 1
    assert "sqlite" not in json.dumps(data).lower()  # no record text
    assert main(["--json", "duplicates", "list", "--state", "proposed"]) == 0
    assert len(json.loads(capsys.readouterr().out)["data"]["pairs"]) == 3
