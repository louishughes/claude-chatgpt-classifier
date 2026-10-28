"""A chat's knowledge note in the browser, and every chat's note by category (NOTE-012).

The vault gets each chat's rich note as Markdown (NOTE-001). The dashboard
shows the same note beside the transcript, so a reader can check a claim
against the message it cites with one click. Nothing is written: the note
is built in memory from stored facts, exactly as ``ke docs rubric`` does.

Turning the note into HTML is deliberately narrow. The note is produced by
our own renderer, so only its handful of shapes are understood (headings,
bullets, callouts, the knowledge-card table, bold and italics, wikilinks).
Every piece of text is HTML-escaped, so chat text can never become markup
here, and a citation ``[[transcript#^node-x|m12]]`` becomes a link to
``#node-x``, the same message's ``id`` on the transcript side of the page.
A link to another chat's note goes to that chat's page; anything else is
shown as plain words.

Talking points:
    - "The page shows the note and the chat side by side, and every m-number
      in the note jumps to the message it quotes."
    - "The converter only knows the shapes our own notes use, and it escapes
      every character of chat text, so a chat can't inject HTML."
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.digest.stage import stored_digest
from knowledge_engine.documents.categories import suggested_category
from knowledge_engine.documents.notes import knowledge_path
from knowledge_engine.documents.render import transcript_stem
from knowledge_engine.documents.rich_note import body_of, chat_labels, rich_conversation_note
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.relationships.view import related_links
from knowledge_engine.rendering.markdown import render_note
from knowledge_engine.rendering.transcript import load_conversation
from knowledge_engine.taxonomy.registry import TaxonomyRegistry, TaxonomySnapshot

# ``[[target#^anchor|label]]`` or an embed ``![[...]]``; inside a table cell
# the pipe is escaped as ``\|``.
_WIKILINK = re.compile(r"(!?)\[\[([^\]#|\\]+)(?:#\^?([^|\]\\]+))?(?:\\?\|([^\]]+))?\]\]")
_ESCAPED = re.compile(r"\\(.)")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITALIC = re.compile(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])")
_CELL_SPLIT = re.compile(r"(?<!\\)\|")
_CALLOUT = re.compile(r"^> \[!(\w+)\](-?)\s*(.*)$")
_LIST, _TABLE, _DETAILS, _ASIDE = "</ul>", "</table></div>", "</details>", "</aside>"


@dataclass(frozen=True)
class NoteView:
    """What the chat page shows in its note column."""

    html: str
    taxonomy_version: str | None
    digest: str


def newest_taxonomy(session: Session) -> TaxonomySnapshot | None:
    """The most recently published taxonomy, or None before the first publish."""
    registry = TaxonomyRegistry(session)
    versions = registry.versions()
    return registry.snapshot(versions[-1]) if versions else None


def _text(words: str) -> str:
    """Escape one run of note text to HTML, honouring bold, italics and backslash escapes."""
    kept: list[str] = []

    def keep(match: re.Match[str]) -> str:
        kept.append(match.group(1))
        return f"\x00{len(kept) - 1}\x00"

    # The note escapes chat text for Obsidian (``\[``, ``&lt;``...). Undo that
    # first, set the escaped characters aside so they can't start bold or
    # italics, then escape everything for HTML.
    safe = html.escape(html.unescape(_ESCAPED.sub(keep, words)), quote=False)
    safe = _BOLD.sub(r"<strong>\1</strong>", safe)
    safe = _ITALIC.sub(r"<em>\1</em>", safe)
    return re.sub(r"\x00(\d+)\x00", lambda m: html.escape(kept[int(m.group(1))]), safe)


def _inline(line: str, here: str, notes: dict[str, str]) -> str:
    """One line of the note as HTML, with its wikilinks turned into page links."""
    out, last = [], 0
    for match in _WIKILINK.finditer(line):
        out.append(_text(line[last : match.start()]))
        last = match.end()
        embed, target, anchor, label = match.groups()
        target = target.strip()
        shown = html.escape(label or ("image" if embed else "message" if anchor else target))
        if target == here and anchor:
            out.append(f'<a class="cite" href="#{html.escape(anchor)}">{shown}</a>')
        elif target == here:
            out.append(f'<a href="#transcript">{shown}</a>')  # the whole transcript
        elif target in notes:
            out.append(f'<a href="{html.escape(notes[target])}">{html.escape(target)}</a>')
        else:
            out.append(shown)
    out.append(_text(line[last:]))
    return "".join(out)


def note_html(markdown: str, here: str, notes: dict[str, str]) -> str:
    """Turn a rendered rich note (front matter removed) into safe HTML.

    Args:
        markdown: The note's body.
        here: This chat's transcript stem: links to it become ``#anchor``.
        notes: Other chats' knowledge-note stems -> their page addresses.
    """
    out: list[str] = []
    closing: str | None = None  # how to close the list, table or callout we're in

    def close() -> None:
        nonlocal closing
        if closing:
            out.append(closing)
        closing = None

    for line in markdown.splitlines():
        callout = _CALLOUT.match(line)
        if callout:
            close()
            kind, folded, title = callout.groups()
            title_html = _inline(title, here, notes) or html.escape(kind.title())
            if folded:
                out.append(
                    f'<details class="callout {html.escape(kind)}"><summary>{title_html}</summary>'
                )
                closing = _DETAILS
            else:
                out.append(f'<aside class="callout {html.escape(kind)}">')
                out.append(f'<p class="callout-title">{title_html}</p>')
                closing = _ASIDE
        elif line.startswith("> ") and closing in (_DETAILS, _ASIDE):
            out.append(f"<p>{_inline(line[2:], here, notes)}</p>")
        elif line.startswith("# "):
            close()  # the page already shows the title
        elif line.startswith("## "):
            close()
            out.append(f"<h3>{_text(line[3:])}</h3>")
        elif line.startswith("### "):
            close()
            out.append(f"<h4>{_text(line[4:])}</h4>")
        elif line.startswith("- "):
            if closing != _LIST:
                close()
                out.append("<ul>")
                closing = _LIST
            out.append(f"<li>{_inline(line[2:], here, notes)}</li>")
        elif line.startswith("|"):
            cells = [c.strip() for c in _CELL_SPLIT.split(line.strip())[1:-1]]
            if all(re.fullmatch(r":?-+:?", c) for c in cells):
                continue  # the header separator
            if closing != _TABLE:
                close()
                out.append('<div class="table-wrap"><table class="note-card">')
                closing = _TABLE
            if not any(cells):
                continue  # the card's blank header row
            row = "".join(f"<td>{_inline(c, here, notes)}</td>" for c in cells)
            out.append(f"<tr>{row}</tr>")
        elif not line.strip():
            if closing in (_LIST, _TABLE):
                close()
        else:
            if closing in (_LIST, _TABLE):
                close()
            out.append(f"<p>{_inline(line, here, notes)}</p>")
    close()
    return "\n".join(out)


def _other_notes(session: Session, conversation_id: str) -> dict[str, str]:
    """Knowledge-note stem -> page address, for the chats this one links to."""
    others = {link.other(conversation_id) for link in related_links(session, [conversation_id])}
    rows = session.execute(
        select(ConversationRow.conversation_id, ConversationRow.title).where(
            ConversationRow.conversation_id.in_(sorted(others))
        )
    )
    return {knowledge_path(cid, title).stem: f"/chats/{cid}" for cid, title in rows}


def note_view(session: Session, conversation_id: str) -> NoteView:
    """Build one chat's rich note in memory and return it as page HTML."""
    chat = load_conversation(session, conversation_id)
    taxonomy = newest_taxonomy(session)
    digest = stored_digest(session, chat)
    note = rich_conversation_note(session, conversation_id, taxonomy=taxonomy, digest=digest)
    body = body_of(render_note(note.model))
    here = transcript_stem(conversation_id, chat.title)
    notes = _other_notes(session, conversation_id)
    return NoteView(
        html=note_html(body, here, notes),
        taxonomy_version=taxonomy.version if taxonomy else None,
        digest="not written yet" if digest is None else "generated, not scored",
    )


def notes_index(session: Session, *, offset: int, limit: int) -> dict[str, Any]:
    """One page of chats, grouped by category, with status and open questions.

    Categories come from the newest published taxonomy; with none published
    every chat is "unclassified". An unclassified chat whose answers wait
    for review shows the classifier's suggestion (NOTE-018). Status and open questions come from the
    chat's stored digest, or say it hasn't been written.
    """
    taxonomy = newest_taxonomy(session)
    total = session.query(ConversationRow).count()
    rows = session.execute(
        select(ConversationRow.conversation_id, ConversationRow.title)
        .order_by(ConversationRow.title, ConversationRow.conversation_id)
        .offset(offset)
        .limit(limit)
    ).all()
    groups: dict[str, list[dict[str, Any]]] = {}
    for conversation_id, title in rows:
        chat = load_conversation(session, conversation_id)
        labels = chat_labels(session, chat, taxonomy)
        digest = stored_digest(session, chat)
        category = labels.category or "unclassified"
        # NOTE-018: an unsettled chat stays under "unclassified", with the
        # classifier's best candidate shown beside it, never as its group.
        suggestion = (
            suggested_category(session, chat, taxonomy)
            if taxonomy is not None and labels.category is None
            else None
        )
        groups.setdefault(category, []).append(
            {
                "conversation_id": conversation_id,
                "title": title or "Untitled conversation",
                "subcategory": labels.subcategory,
                "suggested": suggestion.label if suggestion else None,
                "status": (digest.status.value if digest and digest.status else None),
                "digest": digest is not None,
                "open_questions": len(digest.open_questions) if digest else None,
            }
        )
    ordered = sorted(groups.items(), key=lambda kv: (kv[0] == "unclassified", kv[0].casefold()))
    return {
        "categories": [{"name": name, "chats": chats} for name, chats in ordered],
        "total": total,
        "taxonomy_version": taxonomy.version if taxonomy else None,
    }
