"""Word and PDF files behind one converter seam (ING-009).

Structured files need a converter to become text. The plan names Docling,
a large optional library; this module puts any converter behind one small
interface, ``DocumentConverter``, so the rest of the engine sees the same
``ParsedDocument`` (blocks with references) whatever did the work:

* **Docling** is used when it is installed (it isn't by default; nothing
  is downloaded on its behalf);
* otherwise a **built-in DOCX reader** (standard library only) reads
  paragraphs, headings (from Word's Heading styles) and tables, each with
  a reference like ``p12`` or ``table2/r1c3``, and lists embedded images
  as references;
* a **PDF** without Docling is not read at all: the result has the file's
  hash, size and page count, no blocks, and the warning
  ``pdf_text_not_extracted``. Saying "nothing was read" beats guessing.

Whatever can't be extracted is reported as a warning code (footnotes,
headers and footers, comments, text boxes, images described), so a gap is
always visible. Files are only read; nothing is written next to them.

Archive safety: a DOCX is a ZIP, so the reader caps the member count and
the total unpacked size, and refuses XML that declares a DOCTYPE (the
usual way to smuggle entity bombs into XML).

Talking points:
    - "Word and PDF files go through one small converter interface, so a
      better converter can be swapped in without touching the rest."
    - "Every paragraph and table cell carries a reference back into the
      file, and anything the converter couldn't read is listed as a warning."
"""

from __future__ import annotations

import hashlib
import io
import re
import zipfile
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol
from xml.etree import ElementTree

from knowledge_engine.ingestion.documents import (
    AssetReference,
    Block,
    BlockKind,
    ParsedDocument,
    TextBuilder,
    parse_markdown,
    parse_text,
)

STRUCTURED_PARSER_VERSION = "ing-009-v1"
MAX_DOCX_ENTRIES = 2_000
MAX_DOCX_UNPACKED = 200 * 1024 * 1024
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_HEADING_STYLE = re.compile(r"^(?:heading|titre|überschrift)\s*([1-6])$", re.IGNORECASE)
_PDF_PAGE = re.compile(rb"/Type\s*/Page(?![a-zA-Z])")


class UnsafeDocumentError(ValueError):
    """A file breaks the archive or XML safety limits."""


class DocumentConverter(Protocol):
    """Turns a file's bytes into a ``ParsedDocument``."""

    name: str

    def accepts(self, suffix: str) -> bool:
        """Whether this converter reads files with this suffix (``.docx``...)."""
        ...

    def convert(self, data: bytes, suffix: str) -> ParsedDocument:
        """Convert, or raise ``UnsafeDocumentError``."""
        ...


def _xml(data: bytes) -> ElementTree.Element:
    if b"<!DOCTYPE" in data[:4096].upper():
        raise UnsafeDocumentError("xml_doctype_refused")
    return ElementTree.fromstring(data)  # noqa: S314 - DOCTYPE refused above; expat limits amplification


class BuiltinDocx:
    """Reads DOCX with the standard library: paragraphs, headings, tables, image references."""

    name = "builtin-docx"

    def accepts(self, suffix: str) -> bool:
        """Only ``.docx``."""
        return suffix == ".docx"

    def convert(self, data: bytes, suffix: str) -> ParsedDocument:
        """Read the main document part; report what isn't read."""
        try:
            archive = zipfile.ZipFile(io.BytesIO(data))
        except zipfile.BadZipFile as error:
            raise UnsafeDocumentError("docx_not_a_zip") from error
        with archive:
            infos = archive.infolist()
            if len(infos) > MAX_DOCX_ENTRIES:
                raise UnsafeDocumentError("docx_too_many_entries")
            if sum(i.file_size for i in infos) > MAX_DOCX_UNPACKED:
                raise UnsafeDocumentError("docx_too_large_unpacked")
            names = {i.filename for i in infos}
            if "word/document.xml" not in names:
                raise UnsafeDocumentError("docx_missing_document")
            body = _xml(archive.read("word/document.xml")).find(f"{_W}body")
            targets = _relationships(archive, names)
            warnings = [
                code
                for prefix, code in (
                    ("word/footnotes.xml", "docx_footnotes_not_extracted"),
                    ("word/endnotes.xml", "docx_endnotes_not_extracted"),
                    ("word/comments.xml", "docx_comments_not_extracted"),
                    ("word/header", "docx_headers_not_extracted"),
                    ("word/footer", "docx_footers_not_extracted"),
                )
                if any(n.startswith(prefix) for n in names)
            ]
        builder = TextBuilder()
        blocks: list[Block] = []
        assets: list[AssetReference] = []
        heads: list[tuple[int, str]] = []
        paragraphs = tables = 0
        for element in list(body) if body is not None else []:
            if element.tag == f"{_W}p":
                paragraphs += 1
                text = _paragraph_text(element)
                images = [
                    targets.get(blip.get(f"{_R}embed", ""), "")
                    for blip in element.iter(f"{_A}blip")
                ]
                if element.find(f".//{_W}txbxContent") is not None:
                    warnings.append("docx_text_boxes_not_extracted")
                if not text.strip() and not images:
                    continue
                level = _heading_level(element)
                if level is not None:
                    while heads and heads[-1][0] >= level:
                        heads.pop()
                    heads.append((level, text.strip()))
                start, end = builder.add(text)
                index = len(blocks)
                blocks.append(
                    Block(
                        index=index,
                        kind=BlockKind.HEADING if level is not None else BlockKind.PARAGRAPH,
                        text=text,
                        start=start,
                        end=end,
                        line_start=None,
                        line_end=None,
                        heading_path=tuple(t for _, t in heads),
                        level=level,
                        locator=f"p{paragraphs}",
                    )
                )
                for target in images:
                    assets.append(AssetReference(target or "(unresolved)", index, "docx"))
                if images:
                    warnings.append("docx_images_not_described")
            elif element.tag == f"{_W}tbl":
                tables += 1
                rows = [
                    [_paragraphs_text(cell) for cell in row.iter(f"{_W}tc")]
                    for row in element.iter(f"{_W}tr")
                ]
                text = "\n".join(" | ".join(cells) for cells in rows)
                start, end = builder.add(text)
                blocks.append(
                    Block(
                        index=len(blocks),
                        kind=BlockKind.TABLE,
                        text=text,
                        start=start,
                        end=end,
                        line_start=None,
                        line_end=None,
                        heading_path=tuple(t for _, t in heads),
                        locator=f"table{tables}/r1c1-r{len(rows)}c{max(map(len, rows), default=0)}",
                    )
                )
        return ParsedDocument(
            format="docx",
            sha256=hashlib.sha256(data).hexdigest(),
            size=len(data),
            encoding=None,
            text=builder.text(),
            frontmatter=None,
            frontmatter_raw=None,
            blocks=tuple(blocks),
            assets=tuple(assets),
            warnings=tuple(dict.fromkeys(warnings)),
            parser=f"{STRUCTURED_PARSER_VERSION}+{self.name}",
        )


def _relationships(archive: zipfile.ZipFile, names: set[str]) -> dict[str, str]:
    rels = "word/_rels/document.xml.rels"
    if rels not in names:
        return {}
    return {
        r.get("Id", ""): r.get("Target", "")
        for r in _xml(archive.read(rels)).iter(f"{_PKG_REL}Relationship")
    }


def _paragraph_text(paragraph: ElementTree.Element) -> str:
    parts = []
    for node in paragraph.iter():
        if node.tag == f"{_W}t" and node.text:
            parts.append(node.text)
        elif node.tag == f"{_W}tab":
            parts.append("\t")
        elif node.tag in (f"{_W}br", f"{_W}cr"):
            parts.append("\n")
    return "".join(parts)


def _paragraphs_text(cell: ElementTree.Element) -> str:
    return " ".join(_paragraph_text(p) for p in cell.iter(f"{_W}p")).strip()


def _heading_level(paragraph: ElementTree.Element) -> int | None:
    style = paragraph.find(f"{_W}pPr/{_W}pStyle")
    value = (style.get(f"{_W}val", "") if style is not None else "").replace(" ", "")
    match = _HEADING_STYLE.match(value)
    if match:
        return int(match.group(1))
    return 1 if value.lower() == "title" else None


class PdfWithoutConverter:
    """A PDF with no converter installed: provenance only, and a warning."""

    name = "pdf-unread"

    def accepts(self, suffix: str) -> bool:
        """Only ``.pdf``."""
        return suffix == ".pdf"

    def convert(self, data: bytes, suffix: str) -> ParsedDocument:
        """Count pages, read no text."""
        warnings = ["pdf_text_not_extracted"]
        if not data.startswith(b"%PDF-"):
            warnings.append("pdf_header_missing")
        if b"/Encrypt" in data:
            warnings.append("pdf_encrypted")
        pages = len(_PDF_PAGE.findall(data)) or None
        return ParsedDocument(
            format="pdf",
            sha256=hashlib.sha256(data).hexdigest(),
            size=len(data),
            encoding=None,
            text="",
            frontmatter=None,
            frontmatter_raw=None,
            blocks=(),
            warnings=tuple(warnings),
            parser=f"{STRUCTURED_PARSER_VERSION}+{self.name}",
            pages=pages,
        )


class DoclingConverter:
    """Docling, when installed: converts to Markdown, then reads that with ING-008.

    Not installed by default and not exercised by the test suite (the
    library and its models are large). Blocks get ``docling:`` locators;
    page-level positions are not carried over yet, which the warning
    ``docling_positions_not_kept`` says.
    """

    name = "docling"

    def __init__(self) -> None:
        """Fail early if Docling isn't importable."""
        from docling.document_converter import (  # type: ignore[import-not-found]
            DocumentConverter as Docling,
        )

        self._docling = Docling()

    def accepts(self, suffix: str) -> bool:
        """Word and PDF."""
        return suffix in (".docx", ".pdf")

    def convert(self, data: bytes, suffix: str) -> ParsedDocument:
        """Convert through a temporary copy (Docling reads paths)."""
        import tempfile

        with tempfile.TemporaryDirectory(prefix="ke-docling-") as folder:
            path = Path(folder) / f"input{suffix}"
            path.write_bytes(data)
            markdown = self._docling.convert(path).document.export_to_markdown()
        parsed = parse_markdown(markdown.encode("utf-8"))
        blocks = tuple(
            Block(
                index=b.index,
                kind=b.kind,
                text=b.text,
                start=b.start,
                end=b.end,
                line_start=None,
                line_end=None,
                heading_path=b.heading_path,
                level=b.level,
                locator=f"docling:{b.index}",
            )
            for b in parsed.blocks
        )
        return ParsedDocument(
            format=suffix.lstrip("."),
            sha256=hashlib.sha256(data).hexdigest(),
            size=len(data),
            encoding=None,
            text=parsed.text,
            frontmatter=None,
            frontmatter_raw=None,
            blocks=blocks,
            assets=parsed.assets,
            warnings=(*parsed.warnings, "docling_positions_not_kept"),
            parser=f"{STRUCTURED_PARSER_VERSION}+{self.name}",
        )


def default_converters() -> list[DocumentConverter]:
    """Docling first when it can be imported, then the built-in readers."""
    found: list[DocumentConverter] = []
    try:
        found.append(DoclingConverter())
    except ImportError:
        pass
    found += [BuiltinDocx(), PdfWithoutConverter()]
    return found


TEXT_SUFFIXES = {".md": parse_markdown, ".markdown": parse_markdown, ".txt": parse_text}


def read_document(
    path: Path,
    *,
    max_bytes: int,
    converters: Sequence[DocumentConverter] | None = None,
) -> ParsedDocument:
    """Read any supported file into a ``ParsedDocument``. Only reads ``path``.

    Raises:
        ValueError: Unsupported suffix, or the file is over ``max_bytes``.
        UnsafeDocumentError: The file breaks a safety limit.
    """
    suffix = path.suffix.lower()
    if path.stat().st_size > max_bytes:
        raise ValueError("file_too_large")
    if suffix in TEXT_SUFFIXES:
        return TEXT_SUFFIXES[suffix](path.read_bytes())
    for converter in converters if converters is not None else default_converters():
        if converter.accepts(suffix):
            return converter.convert(path.read_bytes(), suffix)
    raise ValueError(f"unsupported_suffix:{suffix}")
