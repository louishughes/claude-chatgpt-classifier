"""End-to-end run and Obsidian golden: ZIP to vault, every link checked (EVAL-006).

One pinned path through the whole engine, in a scratch workspace, with no
model and no network:

1. **import** the e2e fixture (a real-shaped ChatGPT ZIP, built below);
2. **classify** every segment under a small published taxonomy (the free
   keyword classifier);
3. **extract** with the rule extractors, then **reconcile**;
4. **build the vault** (DOC-006): source transcripts, knowledge notes,
   project and topic masters, video and account notes, images;
5. **search** for a word from the fixture and follow the hit to its note.

Then the vault is checked the way Obsidian would read it:

* every note's frontmatter parses as YAML;
* every ``[[link]]``, ``[[link#^anchor]]``, ``[[#^anchor]]`` and
  ``[[link#Heading]]`` resolves to a note in the vault, and the anchor or
  heading exists in it; every ``![[embed]]`` is a file in the vault
  (escaped links and links inside code are skipped, as Obsidian skips them);
* the LLM-free source notes come first: every chat has its transcript
  note, and every knowledge note links to it (BRW-001).

The **golden** is the vault's shape, not its text: each note's path, kind
and how many links, embeds and anchors it has. It is committed and
compared, so a change to what the engine writes shows up as a diff a
person can read.

Talking points:
    - "One command runs a ZIP all the way to an Obsidian vault and then
      clicks every link in it, so a broken link fails the test."
    - "The golden file records the vault's shape, so any change in what
      gets written is visible in review."
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

E2E_VERSION = "eval-006-v1"

_FENCE = re.compile(r"^(`{3,}|~{3,}).*?^\1\s*$", re.MULTILINE | re.DOTALL)
_CODE_SPAN = re.compile(r"`[^`\n]*`")
_LINK = re.compile(r"(?<!\\)(!?)\[\[([^\[\]|]+?)(?:\|[^\[\]]*)?\]\]")
_ANCHOR = re.compile(r"(?<!\\)\^([A-Za-z0-9-]+)\s*$", re.MULTILINE)
_HEADING = re.compile(r"^#{1,6}\s+(.+?)\s*$", re.MULTILINE)


def _body(text: str) -> tuple[str | None, str]:
    """(frontmatter, body) of a note."""
    if text.startswith("---\n"):
        end = text.find("\n---\n", 4)
        if end >= 0:
            return text[4:end], text[end + 5 :]
    return None, text


def _readable(text: str) -> str:
    """The text Obsidian reads links in: without code blocks and code spans."""
    return _CODE_SPAN.sub("", _FENCE.sub("", text))


@dataclass
class NoteShape:
    """One note's shape for the golden."""

    kind: str
    links: int = 0
    embeds: int = 0
    anchors: int = 0


@dataclass
class LinkCheck:
    """Everything wrong with a vault's links (empty lists: clean)."""

    notes: int = 0
    links: int = 0
    embeds: int = 0
    broken_links: list[tuple[str, str]] = field(default_factory=list)  # (note, target)
    broken_embeds: list[tuple[str, str]] = field(default_factory=list)
    bad_frontmatter: list[str] = field(default_factory=list)
    shapes: dict[str, NoteShape] = field(default_factory=dict)

    @property
    def clean(self) -> bool:
        """No broken link, embed or frontmatter."""
        return not (self.broken_links or self.broken_embeds or self.bad_frontmatter)


def check_vault(vault: Path) -> LinkCheck:
    """Resolve every link and embed in every note, as Obsidian would. Reads only."""
    notes = {
        p.relative_to(vault).as_posix(): p
        for p in sorted(vault.rglob("*.md"))
        if ".ke" not in p.relative_to(vault).parts
    }
    texts = {key: path.read_text(encoding="utf-8") for key, path in notes.items()}
    # A link may name a note by its file name or by its path in the vault.
    by_stem: dict[str, set[str]] = {}
    for key in notes:
        by_stem.setdefault(Path(key).stem, set()).add(key)
        by_stem.setdefault(key.removesuffix(".md"), set()).add(key)
    anchors: dict[str, set[str]] = {}
    headings: dict[str, set[str]] = {}
    for key, text in texts.items():
        body = _readable(_body(text)[1])
        anchors[key] = set(_ANCHOR.findall(body))
        headings[key] = {h.strip() for h in _HEADING.findall(body)}
    report = LinkCheck(notes=len(notes))
    for key, text in texts.items():
        front, body = _body(text)
        kind = "note"
        if front is not None:
            try:
                properties = yaml.safe_load(front)
            except yaml.YAMLError:
                report.bad_frontmatter.append(key)
                properties = None
            if isinstance(properties, dict):
                kind = str(properties.get("ke_type", kind))
        shape = NoteShape(kind, anchors=len(anchors[key]))
        for bang, raw in _LINK.findall(_readable(body)):
            target = raw.strip()
            if bang:
                report.embeds += 1
                shape.embeds += 1
                if not (vault / target).is_file():
                    report.broken_embeds.append((key, target))
                continue
            report.links += 1
            shape.links += 1
            if not _resolves(key, target, by_stem, anchors, headings):
                report.broken_links.append((key, target))
        report.shapes[key] = shape
    return report


def _resolves(
    here: str,
    target: str,
    by_stem: dict[str, set[str]],
    anchors: dict[str, set[str]],
    headings: dict[str, set[str]],
) -> bool:
    name, _, fragment = target.partition("#")
    found = {here} if not name else by_stem.get(name.removesuffix(".md"), set())
    if len(found) != 1:
        return False  # missing, or ambiguous: Obsidian would guess
    (note,) = found
    if not fragment:
        return True
    if fragment.startswith("^"):
        return fragment[1:] in anchors[note]
    return fragment.strip() in headings[note]


_WORKSPACE_ID = re.compile(r"\((conv|acct)-[0-9a-f]+\)")


def golden_key(path: str) -> str:
    """A note path without the ids that change with every new workspace.

    Conversation and account ids are random per workspace (so two workspaces
    never share ids), which is why ``(conv-1a2b3c4d)`` becomes ``(conv-*)``.
    """
    return _WORKSPACE_ID.sub(r"(\1-*)", path)


def vault_golden(check: LinkCheck) -> dict[str, Any]:
    """The committed golden: each note's kind and counts, plus totals."""
    return {
        "version": E2E_VERSION,
        "notes": {
            golden_key(key): {
                "kind": s.kind,
                "links": s.links,
                "embeds": s.embeds,
                "anchors": s.anchors,
            }
            for key, s in sorted(check.shapes.items())
        },
        "kinds": dict(sorted(Counter(s.kind for s in check.shapes.values()).items())),
    }


def golden_diff(actual: dict[str, Any], expected: dict[str, Any]) -> list[str]:
    """Plain-English differences between two goldens (empty: they match)."""
    diffs: list[str] = []
    have, want = actual.get("notes", {}), expected.get("notes", {})
    for key in sorted(set(want) - set(have)):
        diffs.append(f"missing note: {key}")
    for key in sorted(set(have) - set(want)):
        diffs.append(f"new note: {key}")
    for key in sorted(set(have) & set(want)):
        for field_name in ("kind", "links", "embeds", "anchors"):
            if have[key].get(field_name) != want[key].get(field_name):
                diffs.append(
                    f"{key}: {field_name} {want[key].get(field_name)} -> "
                    f"{have[key].get(field_name)}"
                )
    return diffs


@dataclass(frozen=True)
class EndToEndReport:
    """What the run did and what the checks found."""

    conversations: int
    segments: int
    classified: int
    records: int
    vault_counts: dict[str, int]
    search_hit_in_vault: bool
    sources_first: bool
    check: LinkCheck

    @property
    def passed(self) -> bool:
        """The vault is clean, sources come first and search lands on a note."""
        return self.check.clean and self.sources_first and self.search_hit_in_vault


def run_end_to_end(export_zip: Path, scratch: Path, *, query: str) -> EndToEndReport:
    """Run the whole pinned path in ``scratch`` (never your workspace).

    Args:
        export_zip: The ZIP to import (only read).
        scratch: An empty folder for the workspace and the vault.
        query: A word known to be in the export, for the search step.
    """
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from knowledge_engine.classification.classifier import SegmentClassifier
    from knowledge_engine.classification.store import save
    from knowledge_engine.documents.vault import sync_vault
    from knowledge_engine.evaluation.semantic_smoke import (
        _extraction_segments,
        _rule_extractors,
    )
    from knowledge_engine.extraction.runner import run
    from knowledge_engine.extraction.store import KnowledgeRecordRow
    from knowledge_engine.importer import import_source
    from knowledge_engine.importer.records import ConversationRow
    from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
    from knowledge_engine.infrastructure.workspace import WorkspaceRow
    from knowledge_engine.reconciliation.supersession import reconcile
    from knowledge_engine.rendering.transcript import load_conversation, transcript_path
    from knowledge_engine.retrieval.lexical import LexicalIndex, search_index_path, sync_index
    from knowledge_engine.segmentation.overrides import load_segments
    from knowledge_engine.settings import Settings
    from knowledge_engine.taxonomy.registry import Dimension, TaxonomyRegistry, TermStatus

    settings = Settings(workspace_root=scratch / "ws")
    import_source(export_zip, "e2e", settings=settings)
    vault = scratch / "vault"
    engine = create_sqlite_engine(database_path(settings))
    try:
        with Session(engine) as session:
            registry = TaxonomyRegistry(session)
            for label, aliases in (("Code", ("python",)), ("Images", ("image",))):
                term = registry.add_term(Dimension.TOPIC, label, status=TermStatus.APPROVED)
                for alias in aliases:
                    registry.add_alias(term, alias)
            taxonomy = registry.publish("e2e-tax-1", author="eval-006")
            conversations = [
                load_conversation(session, c)
                for c in session.scalars(
                    select(ConversationRow.conversation_id).order_by(
                        ConversationRow.native_conversation_id
                    )
                ).all()
            ]
            items = [(c, s) for c in conversations for s in load_segments(session, c)]
            classified = save(session, SegmentClassifier(taxonomy).classify(items))
            run(
                session,
                _extraction_segments(session, conversations),
                _rule_extractors(session, conversations),
            )
            session.commit()
            reconcile(session)
            session.commit()
            records = len(session.scalars(select(KnowledgeRecordRow.record_id)).all())
            report = sync_vault(
                session, vault, settings.workspace_root / "archive", taxonomy=taxonomy
            )
            transcripts = {
                transcript_path(c.conversation_id, c.title).as_posix() for c in conversations
            }
            with LexicalIndex(search_index_path(settings)) as index:
                sync_index(session, index)
                hits = [
                    hit
                    for workspace_id in session.scalars(select(WorkspaceRow.workspace_id))
                    for hit in index.search(query, workspace_id=workspace_id, limit=5)
                ]
            hit_notes = {
                transcript_path(h.conversation_id, _title(conversations, h.conversation_id))
                for h in hits
            }
    finally:
        engine.dispose()
    check = check_vault(vault)
    knowledge = [k for k, s in check.shapes.items() if s.kind == "conversation_knowledge"]
    sources_first = transcripts <= set(check.shapes) and all(
        any(f"[[{Path(t).stem}]]" in (vault / k).read_text(encoding="utf-8") for t in transcripts)
        for k in knowledge
    )
    return EndToEndReport(
        conversations=len(conversations),
        segments=len(items),
        classified=len(classified),
        records=records,
        vault_counts=report.counts(),
        search_hit_in_vault=bool(hit_notes)
        and all((vault / p.as_posix()).is_file() for p in hit_notes),
        sources_first=sources_first,
        check=check,
    )


def _title(conversations: list[Any], conversation_id: str) -> str | None:
    for chat in conversations:
        if chat.conversation_id == conversation_id:
            return str(chat.title) if chat.title else None
    return None


def to_dict(report: EndToEndReport) -> dict[str, Any]:
    """JSON-ready summary (counts and note paths of synthetic fixtures only)."""
    return {
        "version": E2E_VERSION,
        "passed": report.passed,
        "conversations": report.conversations,
        "segments": report.segments,
        "classified": report.classified,
        "records": report.records,
        "vault": report.vault_counts,
        "notes": report.check.notes,
        "links": report.check.links,
        "embeds": report.check.embeds,
        "broken_links": [list(b) for b in report.check.broken_links],
        "broken_embeds": [list(b) for b in report.check.broken_embeds],
        "bad_frontmatter": report.check.bad_frontmatter,
        "sources_first": report.sources_first,
        "search_hit_in_vault": report.search_hit_in_vault,
    }


# --- The pinned input -------------------------------------------------------
#
# The e2e export is the ``export_zip`` fixture plus two more synthetic chats
# that give every later stage something to find: a decision, a preference, a
# requirement, a YouTube link, a profile link, the same image used again, and
# a follow-up chat that changes the earlier decision. It is built by code
# (below) so it can be re-made byte for byte, and committed so the run never
# depends on the builder being right.

BASE_FIXTURE = Path("tests/fixtures/chatgpt/export_zip/export/export.zip")
E2E_FIXTURE = Path("tests/fixtures/e2e/export.zip")
E2E_GOLDEN = Path("tests/fixtures/e2e/vault_golden.json")
E2E_QUERY = "cedar"
_ZIP_TIME = (2024, 1, 1, 0, 0, 0)
_IMAGE_PART = {
    "content_type": "image_asset_pointer",
    "asset_pointer": "file-service://file-SYN0001",
    "size_bytes": 0,
    "width": 4,
    "height": 4,
}
_EXTRA_CHATS: tuple[tuple[str, str, float, tuple[tuple[str, Any], ...]], ...] = (
    (
        "e2e00000-0000-4000-8000-00000000000a",
        "Synthetic garden shed plan",
        1704240000.0,
        (
            (
                "user",
                "Synthetic: I am planning a garden shed and the parts list is a Python script. "
                "Watch https://www.youtube.com/watch?v=aBcDeFgHiJk&t=75 and the code is at "
                "https://github.com/Synth-Octo for reference.",
            ),
            ("assistant", "Synthetic: I'd suggest a timber frame with a felt roof."),
            (
                "user",
                "Sounds good, let's do that. The base must be level. I prefer cedar cladding.",
            ),
            ("assistant", "Synthetic: noted, cedar cladding on a level base."),
        ),
    ),
    (
        "e2e00000-0000-4000-8000-00000000000b",
        "Synthetic garden shed follow-up",
        1704326400.0,
        (
            (
                "user",
                [
                    _IMAGE_PART,
                    "Synthetic: back to the garden shed. I've decided to use a metal roof "
                    "instead of felt. See https://youtu.be/aBcDeFgHiJk again.",
                ],
            ),
            ("assistant", "Synthetic: understood, a metal roof on the cedar shed."),
        ),
    ),
)


def _chat(cid: str, title: str, start: float, turns: tuple[tuple[str, Any], ...]) -> dict[str, Any]:
    ids = [f"{cid}-root"] + [f"{cid}-m{i}" for i in range(len(turns))]
    mapping: dict[str, Any] = {}
    for i, node in enumerate(ids):
        message = None
        if i:
            role, parts = turns[i - 1]
            multimodal = isinstance(parts, list)
            message = {
                "id": node,
                "author": {"role": role, "name": None, "metadata": {}},
                "create_time": start + 60 * i,
                "content": {
                    "content_type": "multimodal_text" if multimodal else "text",
                    "parts": parts if multimodal else [parts],
                },
                "status": "finished_successfully",
                "metadata": {},
                "recipient": "all",
            }
        mapping[node] = {
            "id": node,
            "message": message,
            "parent": ids[i - 1] if i else None,
            "children": [ids[i + 1]] if i + 1 < len(ids) else [],
        }
    return {
        "title": title,
        "create_time": start,
        "update_time": start + 60 * len(turns),
        "mapping": mapping,
        "current_node": ids[-1],
        "conversation_id": cid,
        "id": cid,
    }


def build_fixture(base: Path, out: Path) -> bytes:
    """Write the e2e export ZIP (same bytes every time) and return them."""
    import io
    import json
    import zipfile

    with zipfile.ZipFile(base) as source:
        chats = json.loads(source.read("conversations.json"))
        others = {n: source.read(n) for n in sorted(source.namelist()) if n != "conversations.json"}
    chats += [_chat(*extra) for extra in _EXTRA_CHATS]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as target:
        files = {"conversations.json": json.dumps(chats, indent=1).encode("utf-8"), **others}
        for name, data in files.items():
            info = zipfile.ZipInfo(name, date_time=_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            target.writestr(info, data)
    data = buffer.getvalue()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    return data
