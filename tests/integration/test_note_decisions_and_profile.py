"""NOTE-035: Decisions holds the user's own choices; NOTE-036: the profile is never a keyword.

Every chat and record here is synthetic and written by the test.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.orm import Session

from knowledge_engine.documents.keywords import ChatInput, keyword_candidates, workspace_keywords
from knowledge_engine.documents.model import DocItem
from knowledge_engine.documents.rich_note import _Item, _sort
from knowledge_engine.domain.enums import Role
from knowledge_engine.extraction.records import (
    Acceptance,
    KnowledgeRecord,
    RecordType,
    Scope,
    Trust,
)
from knowledge_engine.extraction.text import ExtractionMessage, quote, sentences
from knowledge_engine.importer import import_source
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.settings import Settings

# --- NOTE-035 ---------------------------------------------------------------


def _item(
    n: int,
    kind: RecordType,
    actor: Role,
    text: str,
    acceptance: Acceptance = Acceptance.EXPLICIT,
) -> _Item:
    message = ExtractionMessage(f"m{n}", f"rev_{n:032d}", actor, text)
    span = next(iter(sentences(text)))
    record = KnowledgeRecord.model_validate(
        {
            "record_id": f"krec_{n:032d}",
            "trust": Trust.CANDIDATE,
            "record_type": kind,
            "assertion": span.of(text),
            "actor": actor,
            "acceptance": acceptance,
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
    doc = DocItem(
        record.record_id, str(kind), "open", record.assertion, str(actor), (message.revision_id,)
    )
    return _Item(doc, record)


def test_a_user_choice_filed_as_a_preference_is_a_decision_shown_once() -> None:
    choice = _item(1, RecordType.PREFERENCE, Role.USER, "Synthetic: I'll go with the oak shelf.")
    plain = _item(2, RecordType.PREFERENCE, Role.USER, "Synthetic: I like light colours.")
    sorted_ = _sort([choice, plain])
    assert sorted_.decisions == [choice]
    assert sorted_.stated == [plain]  # not listed twice


def test_a_user_requirement_that_commits_to_a_course_is_a_decision() -> None:
    need = _item(3, RecordType.REQUIREMENT, Role.USER, "Synthetic: let's use the coast road.")
    assert _sort([need]).decisions == [need]


def test_an_assistant_suggestion_is_never_a_decision_however_it_is_worded() -> None:
    worded = _item(4, RecordType.PREFERENCE, Role.ASSISTANT, "Synthetic: let's use the coast road.")
    proposal = _item(5, RecordType.PROPOSAL, Role.ASSISTANT, "Synthetic: let's use the oak shelf.")
    sorted_ = _sort([worded, proposal])
    assert sorted_.decisions == []
    assert proposal in sorted_.suggestions


def test_an_accepted_suggestion_is_decided_by_the_users_own_accepting_message() -> None:
    # Acceptance is recorded as the user's decision record (the reconciliation timeline only lets a
    # decision ACCEPT an offer), so Decisions cites the user's message, and the
    # suggestion itself stays under Suggestions.
    offer = _item(7, RecordType.PROPOSAL, Role.ASSISTANT, "Synthetic: take the coast road.")
    accept = _item(8, RecordType.DECISION, Role.USER, "Synthetic: yes, the coast road it is.")
    sorted_ = _sort([offer, accept])
    assert sorted_.decisions == [accept]
    assert sorted_.suggestions == [offer]
    assert {e.actor for e in accept.record.evidence} == {Role.USER}


def test_a_choice_the_user_only_hedged_stays_a_preference() -> None:
    hedged = _item(
        6,
        RecordType.PREFERENCE,
        Role.USER,
        "Synthetic: I'll go with the oak shelf if it fits.",
        Acceptance.CONDITIONAL,
    )
    sorted_ = _sort([hedged])
    assert sorted_.decisions == [] and sorted_.stated == [hedged]


# --- NOTE-036 ---------------------------------------------------------------

PROFILE = "Synthetic Person lives in Exampleville.\n\nSynthetic Person works as a Zephyrwright."


def _msg(n: int, role: Role, text: str) -> ExtractionMessage:
    return ExtractionMessage(f"k{n}", f"rev_{n:032x}", role, text)


def _terms(found: Any) -> set[str]:
    return {k.term.casefold() for k in found.keywords}


def _corpus(*chats: ChatInput) -> list[ChatInput]:
    filler = [
        ChatInput(
            f"conv_filler{i}",
            f"Synthetic filler {i}",
            (_msg(900 + i, Role.USER, f"Synthetic filler about topic number {i} and teapots."),),
        )
        for i in range(4)
    ]
    return [*chats, *filler]


def test_profile_text_is_never_a_keyword() -> None:
    chat = ChatInput(
        "conv_bread",
        "Synthetic bread",
        (
            _msg(1, Role.USER, "How do I feed a sourdough starter? My sourdough starter is slow."),
            _msg(2, Role.ASSISTANT, "Feed the sourdough starter flour and water daily."),
        ),
        profile=(PROFILE,),
    )
    found = keyword_candidates(_corpus(chat))["conv_bread"]
    assert "sourdough starter" in _terms(found) or "sourdough" in _terms(found)
    assert not {"exampleville", "zephyrwright", "synthetic person"} & _terms(found)


def test_a_profile_pasted_into_a_user_turn_is_skipped_but_real_mentions_count() -> None:
    pasted = ChatInput(
        "conv_pasted",
        "Synthetic pasted profile",
        (
            _msg(3, Role.USER, PROFILE.upper() + "\n\nHow should I prune a fig tree?"),
            _msg(4, Role.ASSISTANT, "Prune the fig tree in late winter."),
        ),
        profile=(PROFILE,),
    )
    spoken = ChatInput(
        "conv_spoken",
        "Synthetic trip",
        (
            _msg(5, Role.USER, "I am driving to Exampleville. Is the Exampleville bridge open?"),
            _msg(6, Role.ASSISTANT, "The Exampleville bridge reopened last spring."),
        ),
    )
    found = keyword_candidates(_corpus(pasted, spoken))
    assert not {"exampleville", "zephyrwright"} & _terms(found["conv_pasted"])
    assert "exampleville" in _terms(found["conv_spoken"]) or any(
        "exampleville" in t for t in _terms(found["conv_spoken"])
    )


def _node(cid: str, n: int, role: str, content: dict[str, Any], parent: str) -> dict[str, Any]:
    return {
        "id": f"{cid}-{n}",
        "message": {
            "id": f"{cid}-{n}",
            "author": {"role": role, "name": None, "metadata": {}},
            "create_time": 1704067200.0 + n,
            "content": content,
            "status": "finished_successfully",
            "metadata": {},
        },
        "parent": parent,
        "children": [],
    }


def _chat(cid: str, title: str, contents: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    root = f"{cid}-root"
    mapping: dict[str, Any] = {root: {"id": root, "message": None, "parent": None, "children": []}}
    parent = root
    for n, (role, content) in enumerate(contents):
        node = _node(cid, n, role, content, parent)
        mapping[parent]["children"].append(node["id"])
        mapping[node["id"]] = node
        parent = node["id"]
    return {
        "id": cid,
        "conversation_id": cid,
        "title": title,
        "create_time": 1704067200.0,
        "update_time": 1704067300.0,
        "mapping": mapping,
        "current_node": parent,
    }


def _text(text: str) -> dict[str, Any]:
    return {"content_type": "text", "parts": [text]}


@pytest.fixture
def workspace(tmp_path: Path) -> Iterator[Session]:
    context = {
        "content_type": "user_editable_context",
        "user_profile": PROFILE,
        "user_instructions": "Answer briefly.",
    }
    chats = [
        _chat(
            "c0360000-0000-4000-8000-000000000001",
            "Synthetic kiln",
            [
                ("user", context),
                ("user", _text("What temperature should my pottery kiln reach?")),
                ("assistant", _text("A pottery kiln for stoneware reaches about 1200 C.")),
            ],
        ),
        *[
            _chat(
                f"c0360000-0000-4000-8000-00000000001{i}",
                f"Synthetic other {i}",
                [("user", _text(f"Synthetic question {i} about teapots and kettles."))],
            )
            for i in range(4)
        ],
    ]
    export = tmp_path / "export"
    export.mkdir()
    (export / "conversations.json").write_text(json.dumps(chats), encoding="utf-8")
    settings = Settings(workspace_root=tmp_path / "ws")
    import_source(export, "fixture", settings=settings)
    engine = create_sqlite_engine(database_path(settings))
    with Session(engine) as session:
        yield session
    engine.dispose()


def test_workspace_keywords_leave_out_the_custom_instruction_profile(workspace: Session) -> None:
    found = workspace_keywords(workspace)
    kiln = next(v for v in found.values() if "kiln" in " ".join(_terms(v)))
    assert not {"exampleville", "zephyrwright", "synthetic person"} & _terms(kiln)
