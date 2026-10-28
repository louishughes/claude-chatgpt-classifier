"""REL-005: related-chat suggestions from shared links and distinctive words, no labels needed."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.importer.run import run_import
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.links.store import LinkOccurrenceRow
from knowledge_engine.relationships.related import RELATED_DETECTOR, suggest_related
from knowledge_engine.relationships.store import ConversationRelationshipRow
from knowledge_engine.relationships.words import distinctive_similarity
from knowledge_engine.settings import Settings

GUIDE = "https://example.org/synthetic-shed-guide"
COMMON = "https://example.org/synthetic-everyone-reads-this"
FILLERS = (
    "kettle",
    "violin",
    "glacier",
    "lantern",
    "orchard",
    "compass",
    "harbour",
    "meadow",
    "quartz",
    "saddle",
    "tundra",
    "walnut",
)

# native ID -> (title, user words, assistant words). Every chat is synthetic.
CHATS: dict[str, tuple[str, str, str]] = {
    # Different subjects, same uncommon link: related by the link alone.
    "c-link-a": (
        "Synthetic roof",
        f"Synthetic: is this roofing advice sound? {GUIDE}",
        "Synthetic: yes, felt over boards is fine.",
    ),
    "c-link-b": (
        "Synthetic paint",
        f"Synthetic: which paint does {GUIDE} recommend?",
        "Synthetic: an exterior wood stain.",
    ),
    # Same distinctive words, no link: related by words.
    "c-word-d": (
        "Synthetic telescope collimation",
        "Synthetic: my telescope eyepiece image is blurry; does the aperture need collimation?",
        "Synthetic: collimate the telescope mirrors, then refocus the eyepiece.",
    ),
    "c-word-e": (
        "Synthetic telescope eyepiece",
        "Synthetic: choosing a telescope eyepiece for a wide aperture after collimation.",
        "Synthetic: a longer eyepiece suits a wide telescope aperture.",
    ),
    # Only common words in common: not related.
    "c-plain-f": (
        "Synthetic question",
        "Synthetic: can you tell me something about this?",
        "Synthetic: sure, here is something.",
    ),
    "c-plain-g": (
        "Synthetic request",
        "Synthetic: please explain that to me.",
        "Synthetic: here is an answer.",
    ),
}
# Twelve chats all cite one link: too common to say anything about any two.
for n, filler in enumerate(FILLERS):
    CHATS[f"c-common-{n:02}"] = (
        f"Synthetic {filler}",
        f"Synthetic: a note on the {filler}, see {COMMON}",
        f"Synthetic: noted about the {filler}.",
    )


def _export(root: Path) -> Path:
    chats = []
    for index, (cid, (title, question, answer)) in enumerate(CHATS.items()):
        created = 1704067200.0 + index * 86400
        u, a = f"{cid}-u1", f"{cid}-a1"
        mapping: dict[str, Any] = {
            "root": {"id": "root", "parent": None, "children": [u]},
            u: {"id": u, "parent": "root", "children": [a]},
            a: {"id": a, "parent": u, "children": []},
        }
        for node, role, words, offset in ((u, "user", question, 1), (a, "assistant", answer, 2)):
            mapping[node]["message"] = {
                "id": node,
                "author": {"role": role},
                "create_time": created + offset,
                "content": {"content_type": "text", "parts": [words]},
                "metadata": {},
            }
        chats.append(
            {
                "id": cid,
                "title": title,
                "create_time": created,
                "mapping": mapping,
                "current_node": a,
            }
        )
    root.mkdir(parents=True)
    (root / "conversations.json").write_text(json.dumps(chats), encoding="utf-8")
    return root


def test_links_and_distinctive_words_suggest_related_chats(tmp_path: Path) -> None:
    settings = Settings(workspace_root=tmp_path / "ws")
    run_import(_export(tmp_path / "export"), "acct", format_id=None, settings=settings)
    with Session(create_sqlite_engine(database_path(settings))) as session:
        ids = dict(
            session.execute(
                select(ConversationRow.native_conversation_id, ConversationRow.conversation_id)
            )
            .tuples()
            .all()
        )
        native = {v: k for k, v in ids.items()}
        workspace_id = session.scalars(select(ConversationRow.workspace_id)).first() or ""
        suggest_related(session, workspace_id=workspace_id, taxonomy=None, egress=settings.egress)
        session.commit()
        rows = {
            frozenset((native[r.from_conversation_id], native[r.to_conversation_id])): r
            for r in session.scalars(
                select(ConversationRelationshipRow).where(
                    ConversationRelationshipRow.detector == RELATED_DETECTOR
                )
            )
        }
        guide_occurrences = set(
            session.scalars(
                select(LinkOccurrenceRow.occurrence_id).where(
                    LinkOccurrenceRow.conversation_id.in_([ids["c-link-a"], ids["c-link-b"]])
                )
            )
        )

    link = rows[frozenset(("c-link-a", "c-link-b"))]
    assert link.kind == "related_to"
    assert link.review_state == "candidate"
    assert link.from_conversation_id == ids["c-link-b"]  # the later chat points back
    evidence = json.loads(link.evidence_json)
    assert "both chats cite the same link" in evidence["because"]
    assert set(evidence["link_occurrences"]) == guide_occurrences
    assert len(evidence["link_targets"]) == 1
    assert evidence["revisions"]["from"] and evidence["revisions"]["to"]
    assert "example.org" not in link.evidence_json  # the URL itself stays out

    words = json.loads(rows[frozenset(("c-word-d", "c-word-e"))].evidence_json)
    assert any(b.startswith("their distinctive words overlap") for b in words["because"])
    assert words["distinctive_words"] >= 0.3
    assert words["link_targets"] == []
    assert "telescope" not in json.dumps(words)

    assert frozenset(("c-plain-f", "c-plain-g")) not in rows
    for pair, row in rows.items():
        if all(c.startswith("c-common-") for c in pair):
            assert json.loads(row.evidence_json)["link_targets"] == []


def test_words_every_chat_uses_count_for_nothing() -> None:
    docs = [
        ("Synthetic", "the cat sat on the synthetic mat"),
        ("Synthetic", "the synthetic dog ran to the park"),
        ("Synthetic", "synthetic weather was cold and grey"),
    ]
    assert distinctive_similarity(docs, floor=0.0) == {}
    docs.append(("Synthetic cat", "a synthetic cat on a mat"))
    scores = distinctive_similarity(docs, floor=0.0)
    assert set(scores) == {(0, 3)}
    assert distinctive_similarity(docs, floor=1.01) == {}
