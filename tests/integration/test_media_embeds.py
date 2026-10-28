"""Slice R2: images in notes (MED-004).

Acceptance (MED-004): the link checker passes for available media; a
missing asset renders a marker naming the pointer and reason; no raw/ path
leaks when copy mode is configured.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.importer import import_source
from knowledge_engine.importer.records import MessageRevisionRow
from knowledge_engine.infrastructure.db import create_sqlite_engine, database_path
from knowledge_engine.rendering.markdown import (
    DocumentModel,
    render_note,
    safe_relative_path,
    write_note,
)
from knowledge_engine.rendering.media import (
    MediaRef,
    attachment_path,
    blob_sources,
    check_embeds,
    export_attachments,
    load_media_refs,
    media_block,
    media_counts,
)
from knowledge_engine.settings import Settings, load_settings

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "chatgpt"


def _note(settings: Settings, vault: Path) -> tuple[str, dict[str, int], dict[str, int]]:
    """Render every stored revision's media into one note, as a note writer would."""
    engine = create_sqlite_engine(database_path(settings))
    try:
        with Session(engine) as session:
            revisions = session.scalars(select(MessageRevisionRow.revision_id)).all()
            refs = load_media_refs(session, revisions)
            copied = export_attachments(
                [r for uses in refs.values() for r in uses],
                vault,
                blob_sources(session, settings.workspace_root / "archive"),
            )
    finally:
        engine.dispose()
    blocks = tuple(media_block(ref) for rid in sorted(refs) for ref in refs[rid])
    text = render_note(DocumentModel("Synthetic media note", blocks=blocks))
    write_note(vault, safe_relative_path("note.md"), text)
    return text, copied, media_counts(refs)


@pytest.mark.parametrize("mode", ["reference", "copy"])
def test_available_images_embed_and_every_link_resolves(tmp_path: Path, mode: str) -> None:
    settings = load_settings(workspace_root=tmp_path / "ws", media_storage_mode=mode)
    root = FIXTURES / "repeated_image" / "export"
    import_source(root, "fixture", settings=settings)
    vault = tmp_path / "vault"

    text, copied, counts = _note(settings, vault)

    assert counts == {"available": 5}
    assert text.count("![[_attachments/") == 5
    assert check_embeds(vault, text) == []
    # Two distinct byte contents: two files in the vault, each verified.
    files = sorted((vault / "_attachments").rglob("*.png"))
    assert copied == {"copied": 2, "unchanged": 0}
    assert [hashlib.sha256(f.read_bytes()).hexdigest() + ".png" for f in files] == [
        f.name for f in files
    ]
    # The vault never points back into raw/ or the private store.
    assert str(root) not in text and str(tmp_path / "ws") not in text
    assert "images/" not in text


def test_reexporting_attachments_copies_nothing(tmp_path: Path) -> None:
    settings = load_settings(workspace_root=tmp_path / "ws")
    import_source(FIXTURES / "repeated_image" / "export", "fixture", settings=settings)
    vault = tmp_path / "vault"
    _note(settings, vault)

    _, copied, _ = _note(settings, vault)

    assert copied == {"copied": 0, "unchanged": 2}


def test_problems_render_as_markers_naming_pointer_and_reason(tmp_path: Path) -> None:
    settings = load_settings(workspace_root=tmp_path / "ws")
    import_source(FIXTURES / "asset_problems" / "export", "fixture", settings=settings)
    vault = tmp_path / "vault"

    text, copied, counts = _note(settings, vault)

    assert counts == {"ambiguous": 1, "missing": 2, "unresolved": 1}
    assert "![[" not in text
    assert copied == {"copied": 0, "unchanged": 0}
    assert (
        "> [!warning] Image missing: file-service://file-SYNMISSING "
        "(no file with this ID is in the export)"
    ) in text
    assert (
        "> [!warning] Image ambiguous: file-service://file-SYN0005 "
        "(several different files match this ID)"
    ) in text
    assert "Image unresolved: weird-scheme://abc (this kind of pointer isn't recognised)" in text
    assert "file-SYN0005-a.png" not in text


def test_link_checker_reports_broken_and_ignores_escaped_text(tmp_path: Path) -> None:
    (tmp_path / "_attachments").mkdir()
    (tmp_path / "_attachments" / "ok.png").write_bytes(b"x")
    note = (
        "![[_attachments/ok.png]]\n"
        "![[_attachments/gone.png|200]]\n"
        "![[../outside.png]]\n"
        "chat text \\!\\[\\[not an embed\\]\\]\n"
        "escaped !\\[\\[_attachments/also-not.png\\]\\]\n"
    )

    assert check_embeds(tmp_path, note) == ["_attachments/gone.png", "../outside.png"]


def test_tampered_source_never_reaches_the_vault(tmp_path: Path) -> None:
    source = tmp_path / "image.png"
    source.write_bytes(b"changed bytes")
    ref = MediaRef("file-service://file-X", 0, "available", "file_id_name", "a" * 64, "image/png")

    with pytest.raises(ValueError, match="does not match"):
        export_attachments([ref], tmp_path / "vault", lambda _sha: source)

    assert not list((tmp_path / "vault").rglob("*.png"))
    assert not list((tmp_path / "vault").rglob("*.tmp"))


def test_attachment_paths_are_vault_safe() -> None:
    sha = "ab" + "c" * 62
    assert attachment_path(sha, "image/jpeg").as_posix() == f"_attachments/ab/{sha}.jpg"
    assert attachment_path(sha, "application/x-unknown").suffix == ".bin"
    with pytest.raises(ValueError):
        attachment_path("../../etc/passwd", None)
