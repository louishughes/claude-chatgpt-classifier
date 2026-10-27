"""FND-006 acceptance: same inputs produce a cache hit; a changed version creates a new key."""

from collections.abc import Iterator
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st
from sqlalchemy.exc import IntegrityError

from knowledge_engine.domain.enums import InvalidTransitionError, JobState
from knowledge_engine.domain.ids import sha256_hex
from knowledge_engine.infrastructure.db import SessionFactory, create_sqlite_engine
from knowledge_engine.infrastructure.jobs import (
    AttemptsExhaustedError,
    ClaimResult,
    JobRepository,
    JobRow,
)
from knowledge_engine.infrastructure.migrations import upgrade_to_head
from knowledge_engine.orchestration.stage_keys import stage_key

INPUT = sha256_hex(b"synthetic input")
VERSIONS = {"code": "1.0.0", "parser": "split-v1"}


@pytest.fixture
def factory(tmp_path: Path) -> Iterator[SessionFactory]:
    engine = create_sqlite_engine(tmp_path / "jobs.db")
    upgrade_to_head(engine)  # use the real migration, not create_all
    sessions = SessionFactory(engine)
    yield sessions
    sessions.dispose()


def _claim(
    repo: JobRepository, versions: dict[str, str] = VERSIONS, max_attempts: int = 3
) -> ClaimResult:
    key = stage_key("import.parse.v1", INPUT, versions)
    return repo.claim("import.parse.v1", key, INPUT, versions, max_attempts=max_attempts)


# ---------------------------------------------------------------- stage keys


def test_same_inputs_give_the_same_key() -> None:
    assert stage_key("s.v1", INPUT, {"code": "1", "x": "2"}) == stage_key(
        "s.v1", INPUT, {"x": "2", "code": "1"}
    )


@given(st.text(min_size=1, max_size=20), st.text(min_size=1, max_size=20))
def test_any_version_change_gives_a_new_key(old: str, new: str) -> None:
    keys_equal = stage_key("s.v1", INPUT, {"code": old}) == stage_key("s.v1", INPUT, {"code": new})
    assert keys_equal == (old == new)


def test_input_stage_and_extra_versions_all_matter() -> None:
    base = stage_key("s.v1", INPUT, {"code": "1"})
    assert base != stage_key("s.v2", INPUT, {"code": "1"})
    assert base != stage_key("s.v1", sha256_hex(b"other"), {"code": "1"})
    assert base != stage_key("s.v1", INPUT, {"code": "1", "prompt": "p1"})
    assert base.startswith("stg_") and len(base) == 68


@pytest.mark.parametrize(
    ("stage", "input_hash", "versions"),
    [
        ("", INPUT, {"code": "1"}),
        ("Bad Stage", INPUT, {"code": "1"}),
        ("s.v1", "nothex", {"code": "1"}),
        ("s.v1", INPUT, {}),
        ("s.v1", INPUT, {"code": ""}),
        ("s.v1", INPUT, {"code": "1", "Bad-Name": "x"}),
    ],
)
def test_malformed_key_parts_are_rejected(
    stage: str, input_hash: str, versions: dict[str, str]
) -> None:
    with pytest.raises(ValueError):
        stage_key(stage, input_hash, versions)


# ---------------------------------------------------------------- cache hits


def test_second_claim_after_success_is_a_cache_hit(factory: SessionFactory) -> None:
    with factory.transaction() as session:
        repo = JobRepository(session)
        first = _claim(repo)
        assert not first.cache_hit
        repo.start(first.job)
        repo.succeed(first.job, {"conversations": 3})
    with factory.transaction() as session:
        again = _claim(JobRepository(session))
        assert again.cache_hit
        assert again.job.job_id == first.job.job_id
        assert again.job.result_json == '{"conversations": 3}'
        assert again.job.attempts == 1  # nothing ran the second time


def test_changed_version_creates_a_new_job(factory: SessionFactory) -> None:
    with factory.transaction() as session:
        repo = JobRepository(session)
        old = _claim(repo)
        repo.start(old.job)
        repo.succeed(old.job, {})
        new = _claim(repo, {"code": "1.0.1", "parser": "split-v1"})
        assert not new.cache_hit
        assert new.job.job_id != old.job.job_id
        assert session.query(JobRow).count() == 2


def test_stage_key_is_unique_in_the_database(factory: SessionFactory) -> None:
    key = stage_key("s.v1", INPUT, {"code": "1"})
    with pytest.raises(IntegrityError):
        with factory.transaction() as session:
            for job_id in ("a" * 32, "b" * 32):
                session.add(
                    JobRow(
                        job_id=job_id,
                        stage_id="s.v1",
                        stage_key=key,
                        input_hash=INPUT,
                        versions_json="{}",
                        state="pending",
                        attempts=0,
                        max_attempts=3,
                    )
                )


# ---------------------------------------------------------------- retries and states


def test_transient_errors_retry_until_three_attempts(factory: SessionFactory) -> None:
    with factory.transaction() as session:
        repo = JobRepository(session)
        job = _claim(repo).job
        for attempt in (1, 2):
            repo.start(job)
            assert repo.fail(job, "transient", f"timeout {attempt}") is JobState.PENDING
        repo.start(job)
        assert repo.fail(job, "transient", "timeout 3") is JobState.FAILED
        assert job.attempts == 3
        with pytest.raises(InvalidTransitionError):
            repo.start(job)


def test_cannot_start_when_attempts_are_used_up(factory: SessionFactory) -> None:
    with factory.transaction() as session:
        repo = JobRepository(session)
        job = _claim(repo, max_attempts=1).job
        repo.start(job)
        job.state = JobState.PENDING.value  # simulate a crash recovery
        with pytest.raises(AttemptsExhaustedError):
            repo.start(job)


def test_semantic_problem_goes_to_review_and_is_never_retried(factory: SessionFactory) -> None:
    with factory.transaction() as session:
        repo = JobRepository(session)
        job = _claim(repo).job
        repo.start(job)
        assert repo.fail(job, "semantic", "doubtful answer") is JobState.REVIEW_REQUIRED
        assert job.attempts == 1
        with pytest.raises(InvalidTransitionError):
            repo.start(job)


def test_permanent_error_fails_at_once(factory: SessionFactory) -> None:
    with factory.transaction() as session:
        repo = JobRepository(session)
        job = _claim(repo).job
        repo.start(job)
        assert repo.fail(job, "permanent", "bad input") is JobState.FAILED
        assert job.last_error == "permanent: bad input"


def test_skip_and_finished_jobs_cannot_restart(factory: SessionFactory) -> None:
    with factory.transaction() as session:
        repo = JobRepository(session)
        job = _claim(repo).job
        repo.skip(job, "not needed")
        assert job.state == "skipped"
        with pytest.raises(InvalidTransitionError):
            repo.start(job)


def test_invalid_max_attempts_is_rejected(factory: SessionFactory) -> None:
    with factory.transaction() as session, pytest.raises(ValueError):
        _claim(JobRepository(session), max_attempts=0)


def test_database_refuses_an_unknown_state(factory: SessionFactory) -> None:
    with pytest.raises(IntegrityError, match="CHECK"):
        with factory.transaction() as session:
            job = _claim(JobRepository(session)).job
            job.state = "exploded"
            session.flush()


# ---------------------------------------------------------------- checkpoints and resume


def test_checkpoint_rolls_back_with_the_work(factory: SessionFactory) -> None:
    with factory.transaction() as session:
        repo = JobRepository(session)
        job = _claim(repo).job
        repo.start(job)
        repo.save_checkpoint(job, {"group": 1})
    with pytest.raises(RuntimeError):
        with factory.transaction() as session:
            repo = JobRepository(session)
            job = _claim(repo).job
            repo.save_checkpoint(job, {"group": 2})
            raise RuntimeError("crash while committing group 2")
    with factory.transaction() as session:
        repo = JobRepository(session)
        assert repo.checkpoint(_claim(repo).job) == {"group": 1}


def test_interrupted_jobs_resume_from_their_checkpoint(factory: SessionFactory) -> None:
    with factory.transaction() as session:
        repo = JobRepository(session)
        job = _claim(repo).job
        repo.start(job)
        repo.save_checkpoint(job, {"group": 4})
    # The process "dies" here, leaving the job running.
    with factory.transaction() as session:
        repo = JobRepository(session)
        assert repo.recover_interrupted() == 1
        job = _claim(repo).job
        assert job.state == "pending"
        repo.start(job)
        assert repo.checkpoint(job) == {"group": 4}
        assert job.attempts == 2


def test_checkpoint_requires_a_running_job(factory: SessionFactory) -> None:
    with factory.transaction() as session:
        repo = JobRepository(session)
        job = _claim(repo).job
        assert repo.checkpoint(job) is None
        with pytest.raises(ValueError):
            repo.save_checkpoint(job, {"group": 1})
