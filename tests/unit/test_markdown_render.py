"""DOC-002 acceptance: Obsidian YAML parses, and the same inputs yield a byte-identical note."""

from datetime import UTC, date, datetime
from pathlib import Path, PurePosixPath

import pytest
import yaml
from hypothesis import given
from hypothesis import strategies as st

from knowledge_engine.rendering.markdown import (
    BulletList,
    CodeBlock,
    DocumentModel,
    Heading,
    Paragraph,
    block_anchor,
    escape_text,
    render_frontmatter,
    render_note,
    safe_filename,
    safe_relative_path,
    write_note,
)


def _model(**changes: object) -> DocumentModel:
    data: dict[str, object] = {
        "title": "Synthetic chat",
        "properties": {
            "ke_id": "conv_0bfffaf4519e5747672b77cac126e764",
            "created": datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC),
            "day": date(2024, 1, 2),
            "tags": ["synthetic", "chatgpt"],
            "messages": 5,
            "archived": False,
            "score": 0.5,
            "summary": None,
        },
        "blocks": (
            Heading("Messages"),
            Paragraph("**user**: Synthetic question?", anchor="m-1"),
            BulletList(("Synthetic one", "Synthetic two")),
            CodeBlock("print('synthetic')", "python"),
        ),
    }
    data.update(changes)
    return DocumentModel(**data)  # type: ignore[arg-type]


def _frontmatter(note: str) -> dict[str, object]:
    assert note.startswith("---\n")
    end = note.index("\n---\n", 4)
    loaded: dict[str, object] = yaml.safe_load(note[4:end])
    return loaded


# ---------------------------------------------------------------- determinism and YAML


def test_same_model_gives_identical_bytes() -> None:
    assert render_note(_model()) == render_note(_model())


def test_frontmatter_parses_and_keeps_order_and_types() -> None:
    props = _frontmatter(render_note(_model()))
    assert list(props) == [
        "ke_id",
        "created",
        "day",
        "tags",
        "messages",
        "archived",
        "score",
        "summary",
    ]
    assert props["created"] == "2024-01-02T03:04:05+00:00"
    assert props["day"] == "2024-01-02"
    assert props["tags"] == ["synthetic", "chatgpt"]
    assert props["messages"] == 5 and props["archived"] is False and props["summary"] is None


@given(
    st.dictionaries(
        st.from_regex(r"[A-Za-z][A-Za-z0-9_-]{0,20}", fullmatch=True),
        st.one_of(
            st.text(max_size=50),
            st.integers(),
            st.booleans(),
            st.none(),
            st.lists(st.text(max_size=20), max_size=4),
        ),
        max_size=6,
    )
)
def test_any_string_properties_round_trip(props: dict[str, object]) -> None:
    rendered = render_frontmatter(props)  # type: ignore[arg-type]
    if props:
        assert yaml.safe_load(rendered[4:-4]) == props
    else:
        assert rendered == ""


@pytest.mark.parametrize(
    "props",
    [
        {"bad name": 1},
        {"1abc": 1},
        {"t": datetime(2024, 1, 1)},  # no timezone
        {"x": float("nan")},
    ],
)
def test_bad_properties_are_rejected(props: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        render_frontmatter(props)  # type: ignore[arg-type]


def test_unsupported_property_type_is_rejected() -> None:
    with pytest.raises(TypeError):
        render_frontmatter({"x": object()})  # type: ignore[dict-item]


def test_note_shape() -> None:
    note = render_note(_model())
    assert note.endswith("\n") and not note.endswith("\n\n")
    assert "\r" not in note
    assert "\n# Synthetic chat\n\n## Messages\n\n" in note
    assert "Synthetic question? ^m-1\n" in note
    assert "- Synthetic one\n- Synthetic two\n" in note
    assert "```python\nprint('synthetic')\n```\n" in note


def test_empty_properties_give_no_frontmatter() -> None:
    assert render_note(_model(properties={})).startswith("# Synthetic chat\n")


# ---------------------------------------------------------------- untrusted text


@pytest.mark.parametrize(
    ("raw", "must_not_contain"),
    [
        ("see [[Secret note]]", "[[Secret"),
        ("![[image.png]]", "![["),
        ("hidden %%comment%%", "%%"),
        ("<script>alert(1)</script>", "<script>"),
        ("# not a heading", "\n# not"),
        ("> not a quote", "\n> not"),
        ("text ^fake-anchor", " ^fake-anchor"),
        ("a #private-tag here", " #private-tag"),
    ],
)
def test_untrusted_text_cannot_become_obsidian_syntax(raw: str, must_not_contain: str) -> None:
    note = render_note(_model(blocks=(Paragraph(raw),)))
    body = note.split("\n# Synthetic chat\n", 1)[1]
    assert must_not_contain not in "\n" + body


def test_backslash_before_a_tag_cannot_unescape_it() -> None:
    # Source "\\#tag": the backslash is kept as a literal backslash and the
    # hash is escaped separately, so no tag appears.
    assert escape_text("a \\#sneaky") == "a \\\\\\#sneaky"


def test_trusted_text_is_left_alone() -> None:
    note = render_note(_model(blocks=(Paragraph("[[Index]]", trusted=True),)))
    assert "[[Index]]" in note


def test_title_with_newlines_stays_one_heading() -> None:
    note = render_note(_model(title="Synthetic\n# injected heading", properties={}))
    lines = note.splitlines()
    assert lines[0].startswith("# Synthetic ")
    assert not any(line.startswith("# injected") for line in lines)


def test_code_block_cannot_be_closed_by_its_content() -> None:
    sneaky = "```\n# escaped?\n```"
    note = render_note(_model(blocks=(CodeBlock(sneaky),), properties={}))
    assert "````\n" + sneaky + "\n````" in note


def test_escape_text_keeps_plain_words() -> None:
    assert escape_text("Synthetic plain words, 100% fine.") == "Synthetic plain words, 100% fine."


def test_heading_level_is_checked() -> None:
    with pytest.raises(ValueError):
        render_note(_model(blocks=(Heading("x", level=1),)))


# ---------------------------------------------------------------- names and paths


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Synthetic plain chat", "Synthetic plain chat (c1).md"),
        ('a<b>c:d"e/f\\g|h?i*j', "a b c d e f g h i j (c1).md"),
        ("  trailing dots...  ", "trailing dots (c1).md"),
        ("", "untitled (c1).md"),
        ("CON", "untitled CON (c1).md"),
        ("com1.txt", "untitled com1.txt (c1).md"),
        ("[[link]] #tag ^ref", "link tag ref (c1).md"),
        ("x" * 200, "x" * 80 + " (c1).md"),
    ],
)
def test_safe_filename(title: str, expected: str) -> None:
    assert safe_filename(title, "c1") == expected


def test_same_title_different_ids_never_collide() -> None:
    assert safe_filename("Same", "a1") != safe_filename("Same", "b2")


@pytest.mark.parametrize("suffix", ["", "a b", "../x", "a" * 65])
def test_bad_suffix_is_rejected(suffix: str) -> None:
    with pytest.raises(ValueError):
        safe_filename("t", suffix)


@pytest.mark.parametrize("parts", [(), ("..",), ("a", "../b"), ("C:", "x"), ("a/b",), ("",)])
def test_unsafe_relative_paths_are_rejected(parts: tuple[str, ...]) -> None:
    with pytest.raises(ValueError):
        safe_relative_path(*parts)


def test_block_anchor_validation() -> None:
    assert block_anchor("m-12") == "m-12"
    with pytest.raises(ValueError):
        block_anchor("bad anchor")


# ---------------------------------------------------------------- writing


def test_write_then_rewrite_identical_is_unchanged(tmp_path: Path) -> None:
    relative = safe_relative_path("sources", safe_filename("Synthetic", "c1"))
    content = render_note(_model())
    assert write_note(tmp_path, relative, content) == "written"
    target = tmp_path / "sources" / "Synthetic (c1).md"
    before = target.stat().st_mtime_ns
    assert write_note(tmp_path, relative, content) == "unchanged"
    assert target.stat().st_mtime_ns == before
    assert target.read_bytes() == content.encode("utf-8")
    assert write_note(tmp_path, relative, content + "x") == "written"
    assert list(tmp_path.rglob(".ke-*.tmp")) == []


def test_write_refuses_to_leave_the_vault(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        write_note(tmp_path / "vault", PurePosixPath("../outside.md"), "x\n")
    assert not (tmp_path / "outside.md").exists()


def test_failed_write_leaves_no_temp_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(src: str, dst: str) -> None:
        raise OSError("disk full (simulated)")

    monkeypatch.setattr("knowledge_engine.rendering.markdown.os.replace", boom)
    with pytest.raises(OSError):
        write_note(tmp_path, PurePosixPath("n.md"), "content\n")
    assert list(tmp_path.iterdir()) == []
