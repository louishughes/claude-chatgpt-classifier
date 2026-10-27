"""Synthetic ChatGPT exports: fixed test cases plus a seeded batch generator.

The importer has to cope with real exports: branching chats, repeated
images, missing files, re-exports that change a little each time. Testing
that on the owner's private data in a public repository is not an option.
This module builds fake exports with the same *shape* as the real ones, in
every layout the importer must read (official single file, numbered shards,
ZIP, and the per-conversation "split-wrapper" folders produced by the
earlier Hermes extraction). Each fixed case comes with a ``manifest.json``
answer key that states, by hand, what an importer should find.

Everything is deterministic. The same seed gives byte-identical files on any
machine, so a fixture can be regenerated and compared with the committed
copy. Images are tiny uncompressed PNGs, because compressed bytes can differ
between zlib versions.

Assumption to check on real data (EVAL-010b): the split-wrapper field names
other than ``conversation`` and ``title`` are inferred from the audit's
description, not copied from a real file. ING-011 must confirm them with a
metadata-only key listing before relying on them.

Talking points:
    - "My test data is generated, not copied: same seed, same bytes,
      everywhere."
    - "Every fixture ships with an answer key written by hand, so the
      importer is scored against expectations, not against itself."
    - "The fixtures cover the awkward cases on purpose: edits, regenerations,
      a missing image, a chat that vanishes from the next export."
"""

from __future__ import annotations

import io
import json
import random
import struct
import sys
import uuid
import zipfile
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

FIXTURE_FORMAT_VERSION = 1
SYNTHETIC_MARKER = "SYNTHETIC"
# 2024-01-01T00:00:00Z. All synthetic timestamps count up from here.
BASE_EPOCH = 1_704_067_200.0
_ZIP_DATE = (2024, 1, 1, 0, 0, 0)

JsonDict = dict[str, Any]


# ---------------------------------------------------------------- images


def tiny_png(rgb: tuple[int, int, int], width: int = 4, height: int = 4) -> bytes:
    """Return a valid PNG of one solid colour, built byte by byte.

    Compression level 0 ("stored") keeps the bytes identical across zlib
    versions, which matters because committed fixtures are compared with
    freshly generated ones.

    Args:
        rgb: The colour, three values 0-255.
        width: Width in pixels.
        height: Height in pixels.

    Returns:
        The PNG file's bytes.
    """

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    row = b"\x00" + bytes(rgb) * width  # filter byte 0, then RGB pixels
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(row * height, 0))
        + chunk(b"IEND", b"")
    )


@dataclass(frozen=True)
class SyntheticImage:
    """An image file that exists on disk in the fixture.

    Attributes:
        file_id: The export's file ID, e.g. ``file-SYN0001``.
        filename: The file name on disk; starts with the file ID, because the
            real flattened image folder names files by ID prefix.
        rgb: Colour, which decides the bytes. Two images with the same colour
            and size have identical bytes (one blob, two assets).
    """

    file_id: str
    filename: str
    rgb: tuple[int, int, int]

    def data(self) -> bytes:
        """Return the PNG bytes."""
        return tiny_png(self.rgb)


def image_part(pointer: str, *, kind: str = "image_asset_pointer") -> JsonDict:
    """Return a message content part that points at an asset.

    Args:
        pointer: e.g. ``file-service://file-SYN0001``.
        kind: The part's ``content_type``.

    Returns:
        The part as a dict, shaped like the official export.
    """
    return {
        "content_type": kind,
        "asset_pointer": pointer,
        "size_bytes": 0,
        "width": 4,
        "height": 4,
        "fovea": None,
        "metadata": None,
    }


# ---------------------------------------------------------------- conversations


@dataclass
class ConversationBuilder:
    """Builds one native conversation object, node by node.

    The result has the official export's shape: a ``mapping`` of node ID to
    ``{id, message, parent, children}``, a ``current_node`` (the leaf the
    user last saw) and the usual top-level fields.
    """

    conversation_id: str | None
    title: str
    start: float
    nodes: dict[str, JsonDict] = field(default_factory=dict)
    current_node: str | None = None
    extra: JsonDict = field(default_factory=dict)
    _clock: int = 0

    def __post_init__(self) -> None:
        """Add the empty root node every real export starts with."""
        root = f"{self.conversation_id or 'noid'}-root"
        self.nodes[root] = {"id": root, "message": None, "parent": None, "children": []}
        self.root = root

    def add(
        self,
        node_id: str,
        parent: str,
        role: str,
        parts: list[Any],
        *,
        content_type: str = "text",
        metadata: JsonDict | None = None,
        timestamp: float | None = None,
    ) -> str:
        """Add a message node under ``parent`` and make it the current node.

        Args:
            node_id: Native node ID (also used as the message ID).
            parent: The parent node ID.
            role: ``user``, ``assistant``, ``system`` or ``tool``.
            parts: Content parts: strings and/or asset pointer dicts.
            content_type: ``text``, ``multimodal_text``, ``code``...
            metadata: Message metadata; defaults to ``{}``.
            timestamp: Explicit create time; otherwise the next tick.

        Returns:
            ``node_id``, so calls can be chained.
        """
        self._clock += 1
        created = timestamp if timestamp is not None else self.start + 60 * self._clock
        content: JsonDict = {"content_type": content_type}
        if content_type == "code":
            content.update({"language": "python", "text": parts[0] if parts else ""})
        else:
            content["parts"] = parts
        message = {
            "id": node_id,
            "author": {"role": role, "name": None, "metadata": {}},
            "create_time": created,
            "update_time": None,
            "content": content,
            "status": "finished_successfully",
            "end_turn": role == "assistant" or None,
            "weight": 1.0,
            "metadata": metadata if metadata is not None else {},
            "recipient": "all",
            "channel": None,
        }
        self.nodes[node_id] = {"id": node_id, "message": message, "parent": parent, "children": []}
        self.nodes[parent]["children"].append(node_id)
        self.current_node = node_id
        return node_id

    def native(self, *, include_children: bool = True) -> JsonDict:
        """Return the conversation as an official-export dict.

        Args:
            include_children: False drops ``children`` lists, like the split
                files, so parsers must rebuild them from ``parent``.

        Returns:
            The native conversation object.
        """
        mapping: JsonDict = {}
        for node_id, node in self.nodes.items():
            copy = json.loads(json.dumps(node))
            if not include_children:
                del copy["children"]
            mapping[node_id] = copy
        native: JsonDict = {
            "title": self.title,
            "create_time": self.start,
            "update_time": self.start + 60 * (self._clock + 1),
            "mapping": mapping,
            "moderation_results": [],
            "current_node": self.current_node,
            "plugin_ids": None,
            "conversation_id": self.conversation_id,
            "conversation_template_id": None,
            "gizmo_id": None,
            "is_archived": False,
            "safe_urls": [],
            "default_model_slug": "synthetic-model",
            "id": self.conversation_id,
        }
        if self.conversation_id is None:
            del native["conversation_id"]
            del native["id"]
        native.update(self.extra)
        return native


def _chat(
    conv_id: str | None, title: str, day: int, exchanges: list[tuple[str, str]]
) -> ConversationBuilder:
    """A linear chat: system root message, then user/assistant pairs."""
    builder = ConversationBuilder(conv_id, title, BASE_EPOCH + 86_400 * day)
    prefix = conv_id or "noid"
    parent = builder.add(f"{prefix}-sys", builder.root, "system", [""])
    for index, (question, answer) in enumerate(exchanges):
        parent = builder.add(f"{prefix}-u{index}", parent, "user", [question])
        parent = builder.add(f"{prefix}-a{index}", parent, "assistant", [answer])
    return builder


# ---------------------------------------------------------------- layouts


def _dumps(data: Any) -> bytes:
    # Fixed formatting and "\n" line endings, so output is byte-identical.
    return (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _slug(title: str) -> str:
    cleaned = "".join(ch if ch.isalnum() else "-" for ch in title.lower())
    return "-".join(part for part in cleaned.split("-") if part) or "untitled"


def split_wrapper(native: JsonDict, filename: str) -> JsonDict:
    """Wrap a native conversation the way the split-wrapper files do.

    The wrapper key names match the real files (checked on the owner's PC,
    names only, 2026-10-27, REV-007): ``conversation_id``, ``title``,
    ``create_time``, ``date``, ``filename``, ``message_count``,
    ``user_message_count``, ``assistant_message_count``,
    ``image_references`` and ``conversation``. How the real tool counted is
    not known, so importers must treat the counts as hints only.

    Args:
        native: The native conversation object (children already removed).
        filename: The wrapper file's own name.

    Returns:
        The wrapper dict. Counts are hints the importer cross-checks.
    """
    messages = [node["message"] for node in native["mapping"].values() if node.get("message")]
    images = sum(
        1
        for node in native["mapping"].values()
        if node.get("message")
        for part in node["message"]["content"].get("parts", [])
        if isinstance(part, dict)
    )
    created = native.get("create_time")
    return {
        "conversation_id": native.get("conversation_id"),
        "title": native.get("title"),
        "create_time": created,
        "date": _iso_date(created),
        "filename": filename,
        "message_count": len(messages),
        "user_message_count": sum(1 for m in messages if m["author"]["role"] == "user"),
        "assistant_message_count": sum(1 for m in messages if m["author"]["role"] == "assistant"),
        "image_references": images,
        "conversation": native,
    }


def _iso_date(epoch: float | None) -> str | None:
    if epoch is None:
        return None
    days = int((epoch - BASE_EPOCH) // 86_400)
    # Synthetic dates stay within 2024, so a simple day count is enough.
    month_lengths = [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    month = 0
    while days >= month_lengths[month]:
        days -= month_lengths[month]
        month += 1
    return f"2024-{month + 1:02d}-{days + 1:02d}"


def write_layout(
    out_dir: Path,
    layout: str,
    conversations: list[JsonDict],
    images: list[SyntheticImage],
    *,
    extra_files: dict[str, bytes] | None = None,
    wrapper_overrides: dict[int, JsonDict] | None = None,
) -> None:
    """Write conversations and images to ``out_dir`` in one export layout.

    Args:
        out_dir: Folder to create (must not exist yet or be empty).
        layout: ``official``, ``official_sharded``, ``official_zip`` or ``split``.
        conversations: Native conversation objects.
        images: Image files to place next to them.
        extra_files: Additional files, path relative to ``out_dir``.
        wrapper_overrides: For ``split`` only: index of a conversation ->
            wrapper fields to overwrite (to create mismatches on purpose).

    Raises:
        ValueError: For an unknown layout.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    files: dict[str, bytes] = {}
    if layout == "official":
        files["conversations.json"] = _dumps(conversations)
        files.update({image.filename: image.data() for image in images})
    elif layout == "official_sharded":
        # Two conversations per shard, mirroring conversations-000.json, -001...
        for shard, start in enumerate(range(0, len(conversations), 2)):
            files[f"conversations-{shard:03d}.json"] = _dumps(conversations[start : start + 2])
        files.update({image.filename: image.data() for image in images})
    elif layout == "official_zip":
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
            members = {"conversations.json": _dumps(conversations)}
            members.update({image.filename: image.data() for image in images})
            for name in sorted(members):
                info = zipfile.ZipInfo(name, date_time=_ZIP_DATE)
                info.external_attr = 0o644 << 16
                # Python records the OS that built the ZIP (0 on Windows,
                # 3 on Unix). Pin it so the bytes match on every machine.
                info.create_system = 3
                archive.writestr(info, members[name])
        files["export.zip"] = buffer.getvalue()
    elif layout == "split":
        used: set[str] = set()
        for index, native in enumerate(conversations):
            date = _iso_date(native.get("create_time")) or "undated"
            name = f"{date}.{_slug(str(native.get('title') or ''))}.json"
            suffix = 2
            while name in used:  # the real files add -2 when titles collide
                name = f"{date}.{_slug(str(native.get('title') or ''))}-{suffix}.json"
                suffix += 1
            used.add(name)
            stripped = json.loads(json.dumps(native))
            for node in stripped["mapping"].values():
                node.pop("children", None)
            wrapper = split_wrapper(stripped, name)
            wrapper.update((wrapper_overrides or {}).get(index, {}))
            files[f"conversations/{name}"] = _dumps(wrapper)
        files.update({f"images/{image.filename}": image.data() for image in images})
    else:
        raise ValueError(f"unknown layout {layout!r}")
    files.update(extra_files or {})
    for relative, data in sorted(files.items()):
        target = out_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


# ---------------------------------------------------------------- fixed cases


@dataclass
class Case:
    """One fixture case: what to write and the hand-written answer key."""

    name: str
    proves: str
    layout: str
    conversations: list[JsonDict]
    images: list[SyntheticImage] = field(default_factory=list)
    expected: JsonDict = field(default_factory=dict)
    extra_files: dict[str, bytes] = field(default_factory=dict)
    wrapper_overrides: dict[int, JsonDict] = field(default_factory=dict)


IMG_RED = SyntheticImage("file-SYN0001", "file-SYN0001-synthetic.png", (200, 30, 30))
IMG_BLUE = SyntheticImage("file-SYN0002", "file-SYN0002-synthetic.png", (30, 30, 200))
# Same colour as IMG_RED: identical bytes under a different file ID.
IMG_RED_COPY = SyntheticImage("file-SYN0003", "file-SYN0003-synthetic.png", (200, 30, 30))
IMG_SEDIMENT = SyntheticImage(
    "file_00000000synthetic0004", "file_00000000synthetic0004-synthetic.png", (30, 200, 30)
)
IMG_AMBIGUOUS_A = SyntheticImage("file-SYN0005", "file-SYN0005-a.png", (90, 90, 90))
IMG_AMBIGUOUS_B = SyntheticImage("file-SYN0005", "file-SYN0005-b.png", (91, 91, 91))


def _core_set() -> tuple[list[JsonDict], list[SyntheticImage]]:
    """Three chats shared by the format-equivalence cases.

    One plain chat, one with an image, one with a regenerated answer.
    """
    plain = _chat(
        "c0000001-0000-4000-8000-000000000001",
        "Synthetic plain chat",
        0,
        [
            ("Synthetic question one?", "Synthetic answer one."),
            ("Synthetic question two?", "Synthetic answer two."),
        ],
    )
    with_image = _chat("c0000001-0000-4000-8000-000000000002", "Synthetic image chat", 1, [])
    parent = with_image.add(
        "c2-u0",
        f"{with_image.conversation_id}-sys",
        "user",
        [image_part("file-service://file-SYN0001"), "Synthetic: what colour is this?"],
        content_type="multimodal_text",
    )
    with_image.add("c2-a0", parent, "assistant", ["Synthetic: it is red."])
    branched = _chat(
        "c0000001-0000-4000-8000-000000000003",
        "Synthetic branched chat",
        2,
        [
            ("Synthetic question?", "Synthetic first answer."),
        ],
    )
    # Regenerate: a second assistant reply to the same user message, now active.
    branched.add(
        "c0000001-0000-4000-8000-000000000003-a0-regen",
        "c0000001-0000-4000-8000-000000000003-u0",
        "assistant",
        ["Synthetic regenerated answer."],
    )
    return [plain.native(), with_image.native(), branched.native()], [IMG_RED]


_CORE_EXPECTED: JsonDict = {
    "conversations": 3,
    "mapping_nodes": 15,  # 6 + 4 + 5, each chat including its empty root
    "messages": 12,  # every node except the three roots
    "branch_points": {"edit": 0, "regeneration": 1},
    "active_path_messages": {
        "c0000001-0000-4000-8000-000000000001": 5,
        "c0000001-0000-4000-8000-000000000002": 3,
        "c0000001-0000-4000-8000-000000000003": 3,
    },
    "asset_occurrences": {"available": 1},
    "assets": 1,
    "image_files": 1,
    "derived_artifacts": 0,
    "warnings": [],
}


def _branch_cases() -> list[Case]:
    edit = _chat(
        "c0000002-0000-4000-8000-000000000001",
        "Synthetic edited question",
        3,
        [
            ("Synthetic original question?", "Synthetic answer to original."),
        ],
    )
    sys_node = f"{edit.conversation_id}-sys"
    # The user edited their first message: a sibling user node under the same
    # parent, with its own answer. The edited branch is the active one.
    edited = edit.add("edit-u0b", sys_node, "user", ["Synthetic edited question?"])
    edit.add("edit-a0b", edited, "assistant", ["Synthetic answer to edit."])

    regen = _chat(
        "c0000002-0000-4000-8000-000000000002",
        "Synthetic regenerated answer",
        4,
        [
            ("Synthetic question?", "Synthetic answer v1."),
        ],
    )
    user_node = f"{regen.conversation_id}-u0"
    regen.add("regen-a0b", user_node, "assistant", ["Synthetic answer v2."])
    regen.add("regen-a0c", user_node, "assistant", ["Synthetic answer v3."])
    # The user went back and picked v2: current_node is not the newest node.
    regen.current_node = "regen-a0b"
    return [
        Case(
            "branches_edit",
            "A user edit creates sibling user nodes; the edited branch is active; no splicing.",
            "official",
            [edit.native()],
            expected={
                "conversations": 1,
                "branch_points": {"edit": 1, "regeneration": 0},
                "active_path_node_ids": [
                    sys_node,
                    "edit-u0b",
                    "edit-a0b",
                ],
                "inactive_node_ids": [f"{edit.conversation_id}-u0", f"{edit.conversation_id}-a0"],
            },
        ),
        Case(
            "branches_regen",
            "Regenerated replies are assistant siblings; current_node picks the active one.",
            "official",
            [regen.native()],
            expected={
                "conversations": 1,
                "branch_points": {"edit": 0, "regeneration": 1},
                "branch_children": 3,
                "active_path_node_ids": [f"{regen.conversation_id}-sys", user_node, "regen-a0b"],
                "inactive_node_ids": [f"{regen.conversation_id}-a0", "regen-a0c"],
            },
        ),
    ]


def _media_cases() -> list[Case]:
    repeated = _chat("c0000003-0000-4000-8000-000000000001", "Synthetic repeated image A", 5, [])
    parent = repeated.add(
        "rep-u0",
        f"{repeated.conversation_id}-sys",
        "user",
        [image_part("file-service://file-SYN0001"), "Synthetic: first look."],
        content_type="multimodal_text",
    )
    parent = repeated.add("rep-a0", parent, "assistant", ["Synthetic reply."])
    repeated.add(
        "rep-u1",
        parent,
        "user",
        [image_part("file-service://file-SYN0001"), "Synthetic: same image again."],
        content_type="multimodal_text",
    )
    other = _chat("c0000003-0000-4000-8000-000000000002", "Synthetic repeated image B", 6, [])
    parent = other.add(
        "rep2-u0",
        f"{other.conversation_id}-sys",
        "user",
        [
            image_part("file-service://file-SYN0001"),
            image_part("file-service://file-SYN0003"),
            image_part("sediment://file_00000000synthetic0004"),
            "Synthetic: three images.",
        ],
        content_type="multimodal_text",
    )

    missing = _chat("c0000004-0000-4000-8000-000000000001", "Synthetic asset problems", 7, [])
    missing.add(
        "miss-u0",
        f"{missing.conversation_id}-sys",
        "user",
        [
            image_part("file-service://file-SYNMISSING"),  # well-formed, no file on disk
            image_part("weird-scheme://abc"),  # scheme not recognised
            image_part("file-service://file-SYN0005"),  # two files share this ID
            image_part("sediment://file_00000000synthaudio", kind="audio_asset_pointer"),
            "Synthetic: four broken references.",
        ],
        content_type="multimodal_text",
    )
    return [
        Case(
            "repeated_image",
            "One file used in three messages across two chats is one asset with three occurrences; "
            "a different file ID with identical bytes is a second asset sharing one blob.",
            "split",
            [repeated.native(), other.native()],
            [IMG_RED, IMG_RED_COPY, IMG_SEDIMENT],
            expected={
                "conversations": 2,
                "image_files": 3,
                "asset_occurrences": {"available": 5},
                "assets": 3,
                "blobs": 2,
                "occurrences_per_asset": {
                    "file-SYN0001": 3,
                    "file-SYN0003": 1,
                    "file_00000000synthetic0004": 1,
                },
            },
        ),
        Case(
            "asset_problems",
            "Each non-available state appears once, with evidence and no invented path.",
            "split",
            [missing.native()],
            [IMG_AMBIGUOUS_A, IMG_AMBIGUOUS_B],
            expected={
                "conversations": 1,
                "image_files": 2,
                "asset_occurrences": {"missing": 2, "unresolved": 1, "ambiguous": 1},
                "occurrence_states_by_pointer": {
                    "file-service://file-SYNMISSING": "missing",
                    "weird-scheme://abc": "unresolved",
                    "file-service://file-SYN0005": "ambiguous",
                    "sediment://file_00000000synthaudio": "missing",
                },
                "note": "The audio pointer is 'missing': audio is not in raw/ (OD-10).",
            },
        ),
    ]


def _reexport_cases() -> list[Case]:
    def v1_chats() -> dict[str, ConversationBuilder]:
        return {
            "A": _chat(
                "c0000005-0000-4000-8000-00000000000a",
                "Synthetic unchanged chat",
                8,
                [
                    ("Synthetic A question?", "Synthetic A answer."),
                ],
            ),
            "B": _chat(
                "c0000005-0000-4000-8000-00000000000b",
                "Synthetic growing chat",
                9,
                [
                    ("Synthetic B question?", "Synthetic B answer."),
                ],
            ),
            "C": _chat(
                "c0000005-0000-4000-8000-00000000000c",
                "Synthetic edited chat",
                10,
                [
                    ("Synthetic C question?", "Synthetic C answer."),
                ],
            ),
            "D": _chat(
                "c0000005-0000-4000-8000-00000000000d",
                "Synthetic vanishing chat",
                11,
                [
                    ("Synthetic D question?", "Synthetic D answer."),
                ],
            ),
        }

    v1 = v1_chats()
    v2 = v1_chats()
    # B: two new messages at the end.
    b = v2["B"]
    parent = b.add(
        f"{b.conversation_id}-u1", f"{b.conversation_id}-a0", "user", ["Synthetic B follow-up?"]
    )
    b.add(f"{b.conversation_id}-a1", parent, "assistant", ["Synthetic B follow-up answer."])
    # C: the same node now has different content, and a regenerated reply exists.
    c = v2["C"]
    c.nodes[f"{c.conversation_id}-a0"]["message"]["content"]["parts"] = [
        "Synthetic C answer, revised."
    ]
    c.add("c-regen", f"{c.conversation_id}-u0", "assistant", ["Synthetic C regenerated."])
    # D is absent from v2. E is new and brings an image.
    del v2["D"]
    e = _chat("c0000005-0000-4000-8000-00000000000e", "Synthetic new chat", 12, [])
    e.add(
        "e-u0",
        f"{e.conversation_id}-sys",
        "user",
        [image_part("file-service://file-SYN0002"), "Synthetic E with image."],
        content_type="multimodal_text",
    )
    v2["E"] = e

    # Metadata drift: same content as v1's A, only cosmetic metadata changed.
    drift = v1_chats()["A"]
    drift.extra = {"update_time": BASE_EPOCH + 999_999, "default_model_slug": "synthetic-model-2"}
    for node in drift.nodes.values():
        if node["message"]:
            node["message"]["metadata"] = {"model_slug": "synthetic-model-2", "finish_details": {}}

    return [
        Case(
            "reexport_v1",
            "Baseline export: four chats.",
            "official",
            [chat.native() for chat in v1.values()],
            expected={"conversations": 4, "messages": 12},
        ),
        Case(
            "reexport_v2",
            "Imported after reexport_v1: exact delta categories, nothing deleted.",
            "official",
            [chat.native() for chat in v2.values()],
            [IMG_BLUE],
            expected={
                "conversations": 4,
                "delta_vs": "reexport_v1",
                "conversation_delta": {
                    "new": 1,
                    "unchanged": 1,
                    "revised": 2,
                    "not_seen": 1,
                },
                "conversation_delta_by_id": {
                    "c0000005-0000-4000-8000-00000000000a": "unchanged",
                    "c0000005-0000-4000-8000-00000000000b": "revised",
                    "c0000005-0000-4000-8000-00000000000c": "revised",
                    "c0000005-0000-4000-8000-00000000000d": "not_seen",
                    "c0000005-0000-4000-8000-00000000000e": "new",
                },
                # B +2, C +1 regenerated, E +2 / C's answer / A 3, B 3, C 2 / D 3
                "message_delta": {"new": 5, "revised": 1, "unchanged": 8, "not_seen": 3},
                "new_branches": 1,
                "new_media": 1,
                "model_calls_triggered": 0,
            },
        ),
        Case(
            "metadata_drift",
            "Imported after reexport_v1: only cosmetic metadata changed, so the content is "
            "unchanged and nothing is reprocessed (OD-13).",
            "official",
            [drift.native()],
            expected={
                "conversations": 1,
                "delta_vs": "reexport_v1",
                "conversation_delta_by_id": {"c0000005-0000-4000-8000-00000000000a": "unchanged"},
                "message_delta": {"unchanged": 3},
                "new_raw_observations": True,
                "model_calls_triggered": 0,
            },
        ),
    ]


def _identity_cases() -> list[Case]:
    first = _chat(
        "c0000006-0000-4000-8000-000000000001",
        "Synthetic collision",
        13,
        [
            ("Synthetic first chat?", "Synthetic first reply."),
        ],
    )
    second = _chat(
        "c0000006-0000-4000-8000-000000000001",
        "Synthetic collision",
        14,
        [
            ("Synthetic different chat?", "Synthetic different reply."),
        ],
    )
    no_id = _chat(None, "Synthetic chat without an ID", 15, [("Synthetic?", "Synthetic.")])
    twin_a = _chat(
        "c0000007-0000-4000-8000-000000000001",
        "Synthetic same title",
        16,
        [
            ("Synthetic twin question A?", "Synthetic twin answer A."),
        ],
    )
    twin_b = _chat(
        "c0000007-0000-4000-8000-000000000002",
        "Synthetic same title",
        16,
        [
            ("Synthetic twin question B?", "Synthetic twin answer B."),
        ],
    )
    return [
        Case(
            "id_collision",
            "Two different chats share a conversation ID; a third has none. Candidates for "
            "review, never an automatic merge.",
            "official",
            [first.native(), second.native(), no_id.native()],
            expected={
                "conversations_in_file": 3,
                "candidate_matches": {"id_collision": 1, "missing_native_id": 1},
                "merged": 0,
            },
        ),
        Case(
            "same_title_different_chat",
            "Same title and day, different IDs: two separate conversations. In the split "
            "layout the second file gets a -2 suffix, like the real files.",
            "split",
            [twin_a.native(), twin_b.native()],
            expected={"conversations": 2, "files": 2, "merged": 0},
        ),
    ]


def _format_cases() -> list[Case]:
    conversations, images = _core_set()
    derived = {
        "conversations/classification_output.json": _dumps({"results": [], "synthetic": True})
    }
    return [
        Case(
            "export_single",
            "Official export, one conversations.json.",
            "official",
            conversations,
            images,
            expected=dict(_CORE_EXPECTED),
        ),
        Case(
            "export_sharded",
            "Official export split into numbered shards.",
            "official_sharded",
            conversations,
            images,
            expected=dict(_CORE_EXPECTED),
        ),
        Case(
            "export_zip",
            "Official export as a ZIP file.",
            "official_zip",
            conversations,
            images,
            expected=dict(_CORE_EXPECTED),
        ),
        Case(
            "split_wrapper",
            "Same chats in the split-wrapper layout: identical logical records to the official "
            "cases; a derived file is reported, not parsed; a wrong wrapper count warns.",
            "split",
            conversations,
            images,
            expected={
                **_CORE_EXPECTED,
                "derived_artifacts": 1,
                "warnings": ["wrapper_message_count_mismatch"],
                "equivalent_to": "export_single",
            },
            extra_files=derived,
            wrapper_overrides={0: {"message_count": 99}},
        ),
        Case(
            "no_children",
            "Official layout without children lists: children are rebuilt from parent links.",
            "official",
            [without_children(conversations[2])],
            expected={"conversations": 1, "branch_points": {"edit": 0, "regeneration": 1}},
        ),
    ]


def without_children(native: JsonDict) -> JsonDict:
    """Return a copy of a native conversation with every ``children`` list removed."""
    copy: JsonDict = json.loads(json.dumps(native))
    for node in copy["mapping"].values():
        node.pop("children", None)
    return copy


def all_cases() -> list[Case]:
    """Return every fixed fixture case, in a stable order."""
    return [
        *_format_cases(),
        *_branch_cases(),
        *_media_cases(),
        *_reexport_cases(),
        *_identity_cases(),
    ]


def write_case(case: Case, root: Path) -> Path:
    """Write one case under ``root/<case.name>/`` with its marker and manifest.

    Args:
        case: The case to write.
        root: The fixtures folder.

    Returns:
        The case folder.
    """
    folder = root / case.name
    write_layout(
        folder / "export",
        case.layout,
        case.conversations,
        case.images,
        extra_files=case.extra_files,
        wrapper_overrides=case.wrapper_overrides,
    )
    (folder / SYNTHETIC_MARKER).write_bytes(b"Synthetic test data generated by knowledge_engine.\n")
    manifest = {
        "fixture_format_version": FIXTURE_FORMAT_VERSION,
        "case": case.name,
        "synthetic": True,
        "layout": case.layout,
        "proves": case.proves,
        "expected": case.expected,
    }
    (folder / "manifest.json").write_bytes(_dumps(manifest))
    return folder


def build_fixtures(root: Path) -> list[Path]:
    """Write all fixed cases under ``root``.

    Args:
        root: Destination folder, e.g. ``tests/fixtures/chatgpt``.

    Returns:
        The case folders written.
    """
    return [write_case(case, root) for case in all_cases()]


# ---------------------------------------------------------------- seeded batch generator


def generate_conversations(count: int, seed: int) -> tuple[list[JsonDict], list[SyntheticImage]]:
    """Generate ``count`` random-but-reproducible conversations.

    Shapes vary like real data: 1-8 exchanges, some edits and
    regenerations, some images (a few reused, a few missing), occasional
    code messages.

    Args:
        count: How many conversations (e.g. 50, 100, 1000).
        seed: Same seed, same output.

    Returns:
        The native conversations and the image files that exist.

    Raises:
        ValueError: If ``count`` is negative.
    """
    if count < 0:
        raise ValueError("count must be zero or positive")
    rng = random.Random(seed)
    pool = [
        SyntheticImage(
            f"file-GEN{seed:04d}{i:04d}",
            f"file-GEN{seed:04d}{i:04d}-synthetic.png",
            (rng.randrange(256), rng.randrange(256), rng.randrange(256)),
        )
        for i in range(max(1, count // 5))
    ]
    used_images: dict[str, SyntheticImage] = {}
    conversations: list[JsonDict] = []
    for index in range(count):
        conv_id = str(uuid.UUID(int=rng.getrandbits(128), version=4))
        builder = ConversationBuilder(
            conv_id, f"Synthetic generated chat {index}", BASE_EPOCH + 3_600 * index
        )
        parent = builder.add(f"{conv_id}-sys", builder.root, "system", [""])
        for turn in range(rng.randint(1, 8)):
            parts: list[Any] = [f"Synthetic question {index}.{turn}?"]
            content_type = "text"
            if rng.random() < 0.15:
                if rng.random() < 0.1:
                    parts.insert(0, image_part(f"file-service://file-GENMISSING{index:05d}"))
                else:
                    image = rng.choice(pool)
                    used_images[image.file_id] = image
                    parts.insert(0, image_part(f"file-service://{image.file_id}"))
                content_type = "multimodal_text"
            user = builder.add(
                f"{conv_id}-u{turn}", parent, "user", parts, content_type=content_type
            )
            if rng.random() < 0.05:
                answer = builder.add(
                    f"{conv_id}-c{turn}",
                    user,
                    "assistant",
                    [f"print('synthetic {index}.{turn}')"],
                    content_type="code",
                )
            else:
                answer = builder.add(
                    f"{conv_id}-a{turn}", user, "assistant", [f"Synthetic answer {index}.{turn}."]
                )
            roll = rng.random()
            if roll < 0.08:
                regen = builder.add(
                    f"{conv_id}-a{turn}r", user, "assistant", ["Synthetic regenerated."]
                )
                answer = regen if rng.random() < 0.5 else answer
            elif roll < 0.12:
                edit = builder.add(
                    f"{conv_id}-u{turn}e", parent, "user", ["Synthetic edited question?"]
                )
                answer = builder.add(
                    f"{conv_id}-a{turn}e", edit, "assistant", ["Synthetic answer to edit."]
                )
            builder.current_node = answer
            parent = answer
        conversations.append(builder.native())
    images = [used_images[key] for key in sorted(used_images)]
    return conversations, images


def write_generated(out_dir: Path, count: int, seed: int, layout: str = "split") -> Path:
    """Generate a batch and write it in one layout, with a marker and summary.

    Args:
        out_dir: Destination folder.
        count: Number of conversations.
        seed: Random seed.
        layout: Any layout accepted by ``write_layout``.

    Returns:
        ``out_dir``.
    """
    conversations, images = generate_conversations(count, seed)
    write_layout(out_dir / "export", layout, conversations, images)
    (out_dir / SYNTHETIC_MARKER).write_bytes(
        b"Synthetic test data generated by knowledge_engine.\n"
    )
    summary = {
        "synthetic": True,
        "count": count,
        "seed": seed,
        "layout": layout,
        "image_files": len(images),
    }
    (out_dir / "manifest.json").write_bytes(_dumps(summary))
    return out_dir


def main(argv: list[str] | None = None) -> int:
    """Rebuild the committed fixtures: ``python -m knowledge_engine.evaluation.synthetic DIR``.

    Args:
        argv: Command-line arguments (defaults to ``sys.argv[1:]``).

    Returns:
        Process exit code.
    """
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print(
            "usage: python -m knowledge_engine.evaluation.synthetic <fixtures-dir>", file=sys.stderr
        )
        return 2
    for folder in build_fixtures(Path(args[0])):
        print(folder)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
