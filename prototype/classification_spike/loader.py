"""Load ChatGPT conversations from a raw folder, read-only, and turn each one
into plain text for the model.

What this does
--------------
1. Finds conversation JSON files (official native objects, or the Hermes
   "split-wrapper" files that hold the native object under ``conversation``).
2. Follows the *active branch*: start at ``current_node`` and walk ``parent``
   links back to the root. Regenerated or edited alternatives are skipped,
   because the spike only needs what the user actually saw.
3. Keeps user and assistant text only. Thinking, tool output, system and
   hidden context messages are dropped.

Why
---
The real importer (M1) will keep *everything*. The spike is throwaway: it only
has to feed the model a fair, repeatable piece of text so we can measure
whether the AI step is consistent.

Talking points
--------------
- "The spike reads the data exactly the way the real importer will, but only
  keeps the parts the experiment needs."
- Files are opened read-only. Nothing in raw/ is ever written.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path

# Message roles we send to the model. Everything else (system, tool, ...) is
# left out because it is either hidden context or machine output.
KEPT_ROLES = {"user", "assistant"}

# Content types that carry readable chat text. "thoughts" and
# "reasoning_recap" are the model's hidden reasoning, not the conversation.
TEXT_CONTENT_TYPES = {"text", "multimodal_text"}


@dataclass
class Turn:
    role: str
    text: str
    image_refs: int = 0  # how many images were attached (we never send them)


@dataclass
class Conversation:
    """One conversation, flattened to its active branch."""

    conversation_id: str
    source_file: str  # file name only, used for resume and debugging
    title: str = ""  # only ever written to the private output folder
    turns: list[Turn] = field(default_factory=list)
    branch_points: int = 0  # nodes with more than one child (edits/regens)

    def full_text(self) -> str:
        return "\n\n".join(f"[{t.role}]: {t.text}" for t in self.turns)


def native_object(data: object) -> dict | None:
    """Return the native conversation object, or None for non-conversation JSON.

    The Hermes split files wrap the native object under ``conversation``; an
    official export entry has ``mapping`` at the top level. Anything else
    (such as an old classifier's output file) is skipped, not treated as an
    error.
    """
    if isinstance(data, dict):
        inner = data.get("conversation")
        if isinstance(inner, dict) and isinstance(inner.get("mapping"), dict):
            return inner
        if isinstance(data.get("mapping"), dict):
            return data
    return None


def active_path(mapping: dict, current_node: str | None) -> list[dict]:
    """Walk from ``current_node`` up through ``parent`` links, then reverse.

    The split files have no ``children`` lists, so walking *up* from the leaf
    is the reliable way to get the branch the user last saw. A ``seen`` set
    stops us looping forever if a file is ever corrupt.
    """
    if not current_node or current_node not in mapping:
        return []
    path, seen, node_id = [], set(), current_node
    while node_id and node_id in mapping and node_id not in seen:
        seen.add(node_id)
        node = mapping[node_id]
        path.append(node)
        node_id = node.get("parent")
    path.reverse()
    return path


def count_branch_points(mapping: dict) -> int:
    """Count nodes that have more than one child (derived from parent links)."""
    children: dict[str, int] = {}
    for node in mapping.values():
        parent = node.get("parent")
        if parent:
            children[parent] = children.get(parent, 0) + 1
    return sum(1 for n in children.values() if n > 1)


def turn_from_node(node: dict) -> Turn | None:
    msg = node.get("message")
    if not isinstance(msg, dict):
        return None
    role = (msg.get("author") or {}).get("role")
    content = msg.get("content") or {}
    if role not in KEPT_ROLES or content.get("content_type") not in TEXT_CONTENT_TYPES:
        return None
    # Hidden context the user never typed in this chat (custom instructions).
    if (msg.get("metadata") or {}).get("is_visually_hidden_from_conversation"):
        return None
    texts, images = [], 0
    for part in content.get("parts") or []:
        if isinstance(part, str):
            if part.strip():
                texts.append(part)
        elif isinstance(part, dict):
            # Image or file pointers. Counted, never sent to the model.
            images += 1
    if not texts and not images:
        return None
    return Turn(role=role, text="\n".join(texts), image_refs=images)


def load_conversation(path: Path) -> Conversation | None:
    with path.open("rb") as fh:  # read-only, binary: we never write to raw/
        data = json.load(fh)
    native = native_object(data)
    if native is None:
        return None
    mapping = native["mapping"]
    turns = [t for t in (turn_from_node(n) for n in active_path(mapping, native.get("current_node"))) if t]
    conv_id = native.get("conversation_id") or native.get("id") or path.stem
    title = native.get("title") or (data.get("title") if isinstance(data, dict) else "") or ""
    return Conversation(
        conversation_id=str(conv_id),
        source_file=path.name,
        title=str(title),
        turns=turns,
        branch_points=count_branch_points(mapping),
    )


def candidate_files(raw_dir: Path) -> list[Path]:
    """All JSON files in the conversations folder, in a stable order."""
    folder = raw_dir / "conversations" if (raw_dir / "conversations").is_dir() else raw_dir
    return sorted(p for p in folder.glob("*.json") if p.is_file())


def sample_conversations(raw_dir: Path, size: int, seed: int) -> tuple[list[Conversation], dict]:
    """Pick ``size`` conversations reproducibly.

    We shuffle *all* files once with a fixed seed and take the first N. That
    means the 100-chat sample always contains the 50-chat sample, so results
    from the two runs can be compared directly.
    """
    files = candidate_files(raw_dir)
    rng = random.Random(seed)
    rng.shuffle(files)
    picked: list[Conversation] = []
    skipped = {"not_a_conversation": 0, "no_text": 0, "unreadable": 0}
    for path in files:
        if len(picked) >= size:
            break
        try:
            conv = load_conversation(path)
        except (OSError, ValueError, UnicodeDecodeError):
            skipped["unreadable"] += 1
            continue
        if conv is None:
            skipped["not_a_conversation"] += 1
        elif not any(t.text for t in conv.turns):
            skipped["no_text"] += 1
        else:
            picked.append(conv)
    return picked, skipped


def clip_text(text: str, budget_chars: int) -> tuple[str, bool]:
    """Keep the start and end of very long chats, cut the middle.

    Openings usually state the goal and endings hold the outcome, so those are
    the parts worth paying for. Returns (text, was_clipped).
    """
    if len(text) <= budget_chars:
        return text, False
    head = int(budget_chars * 0.65)
    tail = budget_chars - head
    marker = "\n\n[... middle of conversation omitted for length ...]\n\n"
    return text[:head] + marker + text[-tail:], True
