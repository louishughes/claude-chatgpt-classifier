"""EXT-009 and EXT-010: action status and dependencies from the user's own words.

Every message is synthetic.
"""

from __future__ import annotations

from knowledge_engine.domain.enums import Role
from knowledge_engine.extraction.action_status import (
    ActionStatus,
    action_status,
    propose_dependencies,
)
from knowledge_engine.extraction.records import (
    Acceptance,
    KnowledgeRecord,
    RecordType,
    Scope,
    Trust,
)
from knowledge_engine.extraction.text import ExtractionMessage, quote, sentences


def _message(n: int, role: Role, text: str) -> ExtractionMessage:
    return ExtractionMessage(f"m{n}", f"rev_{n:032d}", role, text)


def _action(record_id: str, message: ExtractionMessage, sentence: int = 0) -> KnowledgeRecord:
    span = list(sentences(message.text))[sentence]
    return KnowledgeRecord.model_validate(
        {
            "record_id": record_id,
            "trust": Trust.CANDIDATE,
            "record_type": RecordType.ACTION,
            "assertion": span.of(message.text),
            "actor": Role.USER,
            "acceptance": Acceptance.EXPLICIT,
            "scope": Scope.SEGMENT,
            "scope_id": "seg_synthetic",
            "evidence": [quote(message, span)],
            "provenance": {
                "stage_id": "extract.test.v1",
                "stage_key": "stg_" + "e" * 64,
                "extractor_version": "t",
            },
        }
    )


ASK = _message(1, Role.USER, "Synthetic: I'll fix the shed roof this weekend.")
ROOF = _action("krec_" + "0" * 32, ASK)


def test_no_later_words_leaves_an_action_open() -> None:
    found = action_status(ROOF, [])
    assert found.status is ActionStatus.OPEN and found.evidence is None


def test_the_user_reporting_it_done_marks_it_reported_done() -> None:
    later = [_message(2, Role.USER, "Update: the shed roof is fixed now.")]
    found = action_status(ROOF, later)
    assert found.status is ActionStatus.REPORTED_DONE
    assert found.evidence is not None and found.evidence.revision_id == later[0].revision_id


def test_not_done_yet_stays_open() -> None:
    later = [_message(2, Role.USER, "The shed roof is not done yet.")]
    assert action_status(ROOF, later).status is ActionStatus.OPEN
    later = [_message(2, Role.USER, "I haven't finished the roof.")]
    assert action_status(ROOF, later).status is ActionStatus.OPEN


def test_an_assistant_saying_done_changes_nothing() -> None:
    later = [_message(2, Role.ASSISTANT, "Done: the shed roof is fixed.")]
    assert action_status(ROOF, later).status is ActionStatus.OPEN


def test_done_about_something_else_stays_open() -> None:
    later = [_message(2, Role.USER, "The fence painting is finished.")]
    assert action_status(ROOF, later).status is ActionStatus.OPEN


def test_explicit_words_drop_it() -> None:
    later = [_message(2, Role.USER, "Actually, skip it, the roof can wait for the builder.")]
    assert action_status(ROOF, later).status is ActionStatus.DROPPED
    # Bare "forget it" counts only as the next thing the user says.
    assert action_status(ROOF, [_message(2, Role.USER, "Forget it.")]).status is (
        ActionStatus.DROPPED
    )
    later = [_message(2, Role.USER, "Thanks."), _message(4, Role.USER, "Forget it.")]
    assert action_status(ROOF, later).status is ActionStatus.OPEN


def test_the_last_deciding_words_win() -> None:
    later = [
        _message(2, Role.USER, "Forget about the roof."),
        _message(4, Role.USER, "Change of plan: the roof is sorted after all."),
    ]
    assert action_status(ROOF, later).status is ActionStatus.REPORTED_DONE


PLAN = _message(
    1,
    Role.USER,
    "Synthetic: I'll fix the shed roof. I'll paint the shed walls. I'll order new gutters.",
)
FIX, PAINT, GUTTERS = (_action("krec_" + c * 32, PLAN, i) for i, c in enumerate("abc"))
F, P, G = (a.record_id for a in (FIX, PAINT, GUTTERS))
ACTIONS = [FIX, PAINT, GUTTERS]


def _deps(text: str, role: Role = Role.USER) -> set[tuple[str, str, str]]:
    found = propose_dependencies(ACTIONS, [PLAN, _message(3, role, text)])
    return {(p.dependent, p.prerequisite, p.cue) for p in found}


def test_each_cue_sets_the_direction() -> None:
    assert _deps("Paint the walls after the roof is fixed.") == {(P, F, "after")}
    assert _deps("Once the roof is fixed, paint the walls.") == {(P, F, "after")}
    assert _deps("Fix the roof before painting the walls.") == {(P, F, "before")}
    assert _deps("Before the walls get painted, fix the roof.") == {(P, F, "before")}
    assert _deps("First the roof, then the gutters.") == {(G, F, "then")}


def test_the_evidence_is_the_sentence_that_names_both() -> None:
    later = _message(3, Role.USER, "Thanks. Paint the walls after the roof is fixed.")
    [found] = propose_dependencies(ACTIONS, [PLAN, later])
    assert found.evidence.revision_id == later.revision_id
    assert later.text[found.evidence.start : found.evidence.end].startswith("Paint the walls")


def test_no_link_from_an_assistant_sentence_or_an_idiom() -> None:
    assert _deps("Paint the walls after the roof is fixed.", Role.ASSISTANT) == set()
    assert _deps("Once again, the roof and the walls need work.") == set()
    assert _deps("Paint everything after lunch.") == set()  # names one action at most


def test_a_report_counts_for_the_action_it_is_most_about() -> None:
    later = [_message(3, Role.USER, "Update: the shed roof is fixed now.")]
    others = [FIX, PAINT, GUTTERS]
    assert action_status(FIX, later, others=others).status is ActionStatus.REPORTED_DONE
    assert action_status(PAINT, later, others=others).status is ActionStatus.OPEN
