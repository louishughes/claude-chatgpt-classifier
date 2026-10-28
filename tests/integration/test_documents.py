"""ING-008 + ING-009: notes, text, Word and PDF files as located blocks."""

from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from knowledge_engine.ingestion.documents import (
    BlockKind,
    ParsedDocument,
    decode_text,
    parse_markdown,
    parse_text,
)
from knowledge_engine.ingestion.structured import (
    BuiltinDocx,
    PdfWithoutConverter,
    UnsafeDocumentError,
    read_document,
)

NOTE = (
    "---\r\ntitle: Synthétique ✓\r\ntags: [a, b]\r\n---\r\n"
    "# Shed plan 🛖\r\n\r\nCedar cladding, naïve café text.\r\nSecond line.\r\n\r\n"
    "Roof\r\n----\r\n\r\n- felt\r\n- metal\r\n\r\n"
    "```\r\n# not a heading\r\n```\r\n\r\n"
    "| part | cost |\r\n|---|---|\r\n| base | 10 |\r\n\r\n"
    "## Pictures\r\n![front](img/front.png) ![[back.png|300]]\r\n"
)


def test_markdown_keeps_frontmatter_headings_and_exact_offsets() -> None:
    doc = parse_markdown(NOTE.encode("utf-8"))
    assert doc.encoding == "utf-8" and doc.warnings == ()
    assert doc.frontmatter == {"title": "Synthétique ✓", "tags": ["a", "b"]}
    for block in doc.blocks:
        assert doc.text[block.start : block.end] == block.text  # exact, CRLF and emoji kept
    kinds = [b.kind for b in doc.blocks]
    assert kinds == [
        BlockKind.FRONTMATTER,
        BlockKind.HEADING,
        BlockKind.PARAGRAPH,
        BlockKind.HEADING,  # "Roof" underlined with ----
        BlockKind.LIST,
        BlockKind.CODE,  # its "# not a heading" stays code
        BlockKind.TABLE,
        BlockKind.HEADING,
        BlockKind.PARAGRAPH,
    ]
    paragraph = doc.blocks[2]
    assert paragraph.locator == "L7-L8" and paragraph.heading_path == ("Shed plan 🛖",)
    assert "\r\n" in paragraph.text
    assert [h.heading_path for h in doc.headings()] == [
        ("Shed plan 🛖",),
        ("Shed plan 🛖", "Roof"),
        ("Shed plan 🛖", "Pictures"),
    ]
    assert [(a.target, a.style) for a in doc.assets] == [
        ("img/front.png", "markdown"),
        ("back.png", "wikilink"),
    ]


@pytest.mark.parametrize(
    ("source", "warning"),
    [
        (b"---\ntitle: [broken\n---\nbody\n", "frontmatter_invalid"),
        (b"---\n- just\n- a list\n---\nbody\n", "frontmatter_not_mapping"),
        (b"---\ntitle: x\nbody without end\n", "frontmatter_unclosed"),
        (b"```\nnever closed\n", "unclosed_code_fence"),
    ],
)
def test_odd_markdown_is_kept_and_reported(source: bytes, warning: str) -> None:
    doc = parse_markdown(source)
    assert warning in doc.warnings
    assert doc.frontmatter is None or warning == "unclosed_code_fence"
    for block in doc.blocks:
        assert doc.text[block.start : block.end] == block.text


def test_encodings_never_replace_characters() -> None:
    assert decode_text("é".encode("utf-8-sig"))[:2] == ("é", "utf-8-sig")
    assert decode_text("é ✓".encode("utf-16"))[:2] == ("é ✓", "utf-16")
    text, encoding, warnings = decode_text("café – “quoted”".encode("cp1252"))
    assert (text, encoding, warnings) == (
        "café – “quoted”",
        "cp1252",
        ("encoding_fallback_cp1252",),
    )
    text, encoding, warnings = decode_text(b"\x81\x8d")  # undefined in cp1252
    assert encoding == "latin-1" and warnings == ("encoding_fallback_latin1",)
    assert "�" not in text


def test_plain_text_is_paragraphs_with_lines() -> None:
    doc = parse_text(b"one\ntwo\n\n\nthree # not a heading\n")
    assert [(b.locator, b.kind) for b in doc.blocks] == [
        ("L1-L2", BlockKind.PARAGRAPH),
        ("L5", BlockKind.PARAGRAPH),
    ]


def _docx(*, doctype: bool = False) -> bytes:
    w = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    r = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    a = "http://schemas.openxmlformats.org/drawingml/2006/main"
    body = (
        f'<w:document xmlns:w="{w}" xmlns:r="{r}" xmlns:a="{a}"><w:body>'
        '<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Shed plan</w:t></w:r></w:p>'
        "<w:p><w:r><w:t>Cedar </w:t></w:r><w:r><w:t>cladding.</w:t></w:r></w:p>"
        '<w:p><w:pPr><w:pStyle w:val="Heading2"/></w:pPr><w:r><w:t>Costs</w:t></w:r></w:p>'
        "<w:tbl><w:tr><w:tc><w:p><w:r><w:t>part</w:t></w:r></w:p></w:tc>"
        "<w:tc><w:p><w:r><w:t>cost</w:t></w:r></w:p></w:tc></w:tr>"
        "<w:tr><w:tc><w:p><w:r><w:t>base</w:t></w:r></w:p></w:tc>"
        "<w:tc><w:p><w:r><w:t>10</w:t></w:r></w:p></w:tc></w:tr></w:tbl>"
        '<w:p><w:r><w:drawing><a:blip r:embed="rId5"/></w:drawing></w:r></w:p>'
        "<w:p/>"
        "</w:body></w:document>"
    )
    if doctype:
        body = '<!DOCTYPE x [<!ENTITY a "aaaa">]>' + body
    rels = (
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId5" Target="media/image1.png"/></Relationships>'
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", body)
        archive.writestr("word/_rels/document.xml.rels", rels)
        archive.writestr("word/footnotes.xml", "<x/>")
        archive.writestr("word/media/image1.png", b"synthetic")
    return buffer.getvalue()


def test_docx_blocks_have_references_and_report_what_was_skipped() -> None:
    doc = BuiltinDocx().convert(_docx(), ".docx")
    assert [(b.kind, b.locator) for b in doc.blocks] == [
        (BlockKind.HEADING, "p1"),
        (BlockKind.PARAGRAPH, "p2"),
        (BlockKind.HEADING, "p3"),
        (BlockKind.TABLE, "table1/r1c1-r2c2"),
        (BlockKind.PARAGRAPH, "p4"),  # the image paragraph; the empty one is skipped
    ]
    assert doc.blocks[1].text == "Cedar cladding." and doc.blocks[1].heading_path == ("Shed plan",)
    assert doc.blocks[3].text == "part | cost\nbase | 10"
    assert doc.blocks[3].heading_path == ("Shed plan", "Costs")
    for block in doc.blocks:
        assert doc.text[block.start : block.end] == block.text
    assert [(a.target, a.block_index) for a in doc.assets] == [("media/image1.png", 4)]
    assert set(doc.warnings) == {"docx_footnotes_not_extracted", "docx_images_not_described"}
    assert doc.parser.endswith("builtin-docx") and len(doc.sha256) == 64


def test_docx_safety_limits() -> None:
    with pytest.raises(UnsafeDocumentError, match="xml_doctype_refused"):
        BuiltinDocx().convert(_docx(doctype=True), ".docx")
    with pytest.raises(UnsafeDocumentError, match="docx_not_a_zip"):
        BuiltinDocx().convert(b"not a zip", ".docx")


def test_pdf_without_a_converter_gives_provenance_and_says_nothing_was_read() -> None:
    pdf = (
        b"%PDF-1.4\n1 0 obj << /Type /Pages /Kids [2 0 R 3 0 R] >>\n"
        b"2 0 obj << /Type /Page >>\n3 0 obj << /Type /Page >>\n%%EOF\n"
    )
    doc = PdfWithoutConverter().convert(pdf, ".pdf")
    assert doc.blocks == () and doc.pages == 2 and doc.size == len(pdf)
    assert doc.warnings == ("pdf_text_not_extracted",)


def test_the_converter_seam_takes_any_converter(tmp_path: Path) -> None:
    class Fake:
        name = "fake"

        def accepts(self, suffix: str) -> bool:
            return suffix == ".pdf"

        def convert(self, data: bytes, suffix: str) -> ParsedDocument:
            return parse_markdown(b"# Converted\n\nbody\n")

    path = tmp_path / "file.pdf"
    path.write_bytes(b"%PDF-1.4\n")
    assert (
        read_document(path, max_bytes=10_000, converters=[Fake()]).headings()[0].text
        == "# Converted"
    )
    with pytest.raises(ValueError, match="file_too_large"):
        read_document(path, max_bytes=3, converters=[Fake()])
    other = tmp_path / "file.xyz"
    other.write_bytes(b"x")
    with pytest.raises(ValueError, match="unsupported_suffix"):
        read_document(other, max_bytes=10, converters=[])


def test_cli_file_read(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from knowledge_engine.cli.main import main

    monkeypatch.setenv("KE_WORKSPACE_ROOT", str(tmp_path / "ws"))
    note = tmp_path / "note.md"
    note.write_bytes(NOTE.encode("utf-8"))
    before = note.read_bytes()
    assert main(["--json", "file", "read", str(note), "--blocks"]) == 0
    data = json.loads(capsys.readouterr().out)["data"]
    assert data["format"] == "markdown" and data["frontmatter_keys"] == ["tags", "title"]
    assert [h["at"] for h in data["outline"]] == ["L5", "L10-L11", "L24"]
    assert len(data["located"]) == data["blocks"] == 9
    assert note.read_bytes() == before  # read only
    docx = tmp_path / "plan.docx"
    docx.write_bytes(_docx())
    assert main(["--json", "file", "read", str(docx)]) == 0
    assert json.loads(capsys.readouterr().out)["data"]["kinds"]["table"] == 1
    assert main(["--json", "file", "read", str(tmp_path / "missing.md")]) == 2
