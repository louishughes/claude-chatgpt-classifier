r"""Deterministic Markdown notes with YAML frontmatter, written atomically.

A note is described as data (``DocumentModel``: properties, a title and a list
of blocks) and turned into text by ``render_note``. Four rules make the
output safe and repeatable:

- **Deterministic:** the same model gives byte-identical text, with ``\n``
  line endings and one final newline.
- **Valid frontmatter:** properties are written by PyYAML's safe emitter and
  checked by parsing them back, so Obsidian always reads them.
- **Untrusted text stays text:** chat content may contain ``[[links]]``,
  ``![[embeds]]``, ``%%comments%%`` or HTML that Obsidian would act on.
  ``escape_text`` neutralises those, so a message can't create links or hide
  content in the vault (treating imported text as data, CLAUDE.md §2E).
- **Safe files:** note file names work on Windows and macOS/Linux, can't
  escape the vault folder, and are written via a temporary file and an atomic
  rename, so a crash never leaves a half-written note. An unchanged note is
  not rewritten.

Talking points:
    - "A note is data first and text second, so the same data always renders
      to the same bytes."
    - "Text from chats is escaped before it reaches Obsidian. A message
      containing [[something]] can't create a link in my vault."
    - "Files are written to a temp file and renamed, so a crash can't leave a
      half-written note."
"""

from __future__ import annotations

import os
import re
import tempfile
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from typing import Literal

import yaml

Scalar = str | int | float | bool | None | date | datetime
PropertyValue = Scalar | Sequence[Scalar]

_ANCHOR_RE = re.compile(r"^[A-Za-z0-9-]{1,64}$")
_WINDOWS_RESERVED = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}  # fmt: skip
_UNSAFE_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f#^\[\]]')
MAX_STEM_CHARS = 80


# ---------------------------------------------------------------- the note model


@dataclass(frozen=True)
class Heading:
    """A heading line. ``level`` is 2-6; level 1 is reserved for the title."""

    text: str
    level: int = 2


@dataclass(frozen=True)
class Paragraph:
    """A paragraph of text.

    Attributes:
        text: The words. Escaped unless ``trusted``.
        trusted: True only for text the engine wrote itself (labels, counts),
            never for imported chat content.
        anchor: Optional Obsidian block ID (``^anchor``) so other notes can
            cite this exact paragraph.
    """

    text: str
    trusted: bool = False
    anchor: str | None = None


@dataclass(frozen=True)
class BulletList:
    """A bulleted list; items follow the same trust rule as paragraphs."""

    items: tuple[str, ...]
    trusted: bool = False


@dataclass(frozen=True)
class CodeBlock:
    """Verbatim text in a fenced block. Nothing inside is interpreted."""

    text: str
    language: str = ""


Block = Heading | Paragraph | BulletList | CodeBlock


@dataclass(frozen=True)
class DocumentModel:
    """Everything needed to render one note.

    Attributes:
        title: Shown as the level-1 heading. Escaped (titles come from chats).
        properties: Frontmatter, in the order given.
        blocks: The body, in order.
    """

    title: str
    properties: Mapping[str, PropertyValue] = field(default_factory=dict)
    blocks: tuple[Block, ...] = ()


# ---------------------------------------------------------------- text helpers


def escape_text(text: str) -> str:
    """Neutralise Obsidian and HTML syntax in untrusted text.

    Keeps the words readable while stopping wikilinks, embeds, comments,
    block references, tags at line start and HTML from taking effect.

    Args:
        text: Text from an imported source.

    Returns:
        The escaped text.
    """
    text = text.replace("\\", "\\\\")
    text = re.sub(r"#(?=[^\s#])", r"\\#", text)  # #tags, anywhere in a line
    text = text.replace("[[", "\\[\\[").replace("]]", "\\]\\]")
    text = text.replace("%%", "\\%\\%")
    text = text.replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"(?m)(\s)\^(?=[A-Za-z0-9-]+\s*$)", r"\1\\^", text)  # block refs
    text = re.sub(r"(?m)^(\s*)([#>|-]|\d+\.)", r"\1\\\2", text)  # headings, quotes, tables, lists
    return text


def block_anchor(name: str) -> str:
    """Validate an Obsidian block ID and return it.

    Args:
        name: Letters, digits and hyphens, 1-64 characters.

    Returns:
        The same name.

    Raises:
        ValueError: If it contains anything else.
    """
    if not _ANCHOR_RE.fullmatch(name):
        raise ValueError("anchors are 1-64 letters, digits or hyphens")
    return name


def safe_filename(title: str, unique_suffix: str, extension: str = ".md") -> str:
    """Build a file name that is safe on Windows, macOS and Linux.

    The title is only decoration. ``unique_suffix`` (a short stable ID) keeps
    two chats with the same title from colliding, so identity never depends
    on the title.

    Args:
        title: Human title (may be empty or contain anything).
        unique_suffix: Short stable ID, letters/digits/hyphens only.
        extension: File extension including the dot.

    Returns:
        A name like ``"Synthetic plain chat (conv-1a2b3c4d).md"``.

    Raises:
        ValueError: If ``unique_suffix`` or ``extension`` is unsafe.
    """
    block_anchor(unique_suffix)
    if not re.fullmatch(r"\.[a-z0-9]{1,10}", extension):
        raise ValueError("extension must look like '.md'")
    stem = unicodedata.normalize("NFC", title)
    stem = _UNSAFE_FILENAME_CHARS.sub(" ", stem)
    stem = re.sub(r"\s+", " ", stem).strip(" .")
    if len(stem) > MAX_STEM_CHARS:
        stem = stem[:MAX_STEM_CHARS].rstrip(" .")
    if not stem or stem.split(".")[0].upper() in _WINDOWS_RESERVED:
        stem = f"untitled {stem}".strip()
    return f"{stem} ({unique_suffix}){extension}"


def safe_relative_path(*parts: str) -> PurePosixPath:
    """Join path parts into a relative path that cannot leave the vault.

    Args:
        *parts: Folder names and a file name, each already safe.

    Returns:
        A POSIX-style relative path.

    Raises:
        ValueError: For empty, absolute, ``.``/``..`` or separator-containing parts.
    """
    if not parts:
        raise ValueError("at least one path part is required")
    for part in parts:
        if part in ("", ".", "..") or "/" in part or "\\" in part or ":" in part:
            raise ValueError(f"unsafe path part {part!r}")
    return PurePosixPath(*parts)


# ---------------------------------------------------------------- rendering


def _normalise_property(value: PropertyValue) -> object:
    if isinstance(value, datetime):
        if value.utcoffset() is None:
            raise ValueError("datetime properties must include a timezone")
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str | int | float | bool) or value is None:
        if isinstance(value, float) and value != value:  # NaN never equals itself
            raise ValueError("NaN is not a valid property value")
        return value
    if isinstance(value, Sequence):
        return [_normalise_property(item) for item in value]
    raise TypeError(f"unsupported property type {type(value).__name__}")


def render_frontmatter(properties: Mapping[str, PropertyValue]) -> str:
    r"""Render properties as an Obsidian frontmatter block.

    Args:
        properties: Property names (letters, digits, ``_``, ``-``) to values.

    Returns:
        ``---\n...\n---\n``, or an empty string when there are none.

    Raises:
        ValueError: For unsafe names or values.
        TypeError: For unsupported value types.
    """
    if not properties:
        return ""
    data: dict[str, object] = {}
    for name, value in properties.items():
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", name):
            raise ValueError(f"bad property name {name!r}")
        data[name] = _normalise_property(value)
    # Readable Unicode first. A few characters (such as U+0085, which YAML
    # treats as a line break) don't survive that, so fall back to escaped
    # ASCII. Both paths are deterministic for a given input.
    for allow_unicode in (True, False):
        body = yaml.safe_dump(
            data,
            sort_keys=False,
            allow_unicode=allow_unicode,
            default_flow_style=False,
            width=10_000,
        )
        # Belt and braces: what we wrote must read back as the same data.
        if yaml.safe_load(body) == data:
            break
    else:
        raise ValueError("frontmatter did not round-trip")
    return f"---\n{body}---\n"


def _one_line(text: str) -> str:
    # Headings must stay on one line, or the rest would become body text.
    return escape_text(" ".join(text.split()))


def _fence_for(text: str) -> str:
    # Use a fence longer than any run of backticks inside the text, so the
    # block can't be closed early by its own content.
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    return "`" * max(3, longest + 1)


def _render_block(block: Block) -> str:
    if isinstance(block, Heading):
        if not 2 <= block.level <= 6:
            raise ValueError("heading level must be 2-6")
        return f"{'#' * block.level} {_one_line(block.text)}"
    if isinstance(block, Paragraph):
        text = block.text if block.trusted else escape_text(block.text)
        if block.anchor is not None:
            text = f"{text} ^{block_anchor(block.anchor)}"
        return text
    if isinstance(block, BulletList):
        items = block.items if block.trusted else tuple(escape_text(i) for i in block.items)
        return "\n".join(f"- {item}" for item in items)
    fence = _fence_for(block.text)
    language = re.sub(r"[^A-Za-z0-9_+-]", "", block.language)
    return f"{fence}{language}\n{block.text}\n{fence}"


def render_note(model: DocumentModel) -> str:
    r"""Render a note: frontmatter, title, then blocks separated by blank lines.

    Args:
        model: The note to render.

    Returns:
        The full Markdown text, ``\n`` line endings, ending in one newline.
    """
    parts = [f"# {_one_line(model.title)}"]
    parts += [_render_block(block) for block in model.blocks]
    body = "\n\n".join(parts).replace("\r\n", "\n").replace("\r", "\n")
    return render_frontmatter(model.properties) + body + "\n"


# ---------------------------------------------------------------- writing


def write_note(
    vault_root: Path, relative: PurePosixPath, content: str
) -> Literal["written", "unchanged"]:
    """Write a note atomically inside ``vault_root``; skip identical content.

    Args:
        vault_root: The vault folder (created if missing).
        relative: Path from ``safe_relative_path``.
        content: The rendered note.

    Returns:
        ``"unchanged"`` if the file already had exactly this content
        (nothing is touched), otherwise ``"written"``.

    Raises:
        ValueError: If the path would land outside ``vault_root``.
    """
    root = vault_root.resolve()
    target = (root / Path(*relative.parts)).resolve()
    if not target.is_relative_to(root) or target == root:
        raise ValueError("note path must stay inside the vault")
    data = content.encode("utf-8")
    if target.is_file() and target.read_bytes() == data:
        return "unchanged"
    target.parent.mkdir(parents=True, exist_ok=True)
    # Temp file in the same folder, so os.replace is an atomic rename on the
    # same disk (and never a slow, interruptible copy across disks).
    handle, temp_name = tempfile.mkstemp(dir=target.parent, prefix=".ke-", suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as temp_file:
            temp_file.write(data)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.replace(temp_name, target)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise
    return "written"
