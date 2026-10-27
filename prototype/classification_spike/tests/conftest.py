"""Shared test helpers: build synthetic ChatGPT files. No real data is used."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def node(node_id, parent, role=None, text=None, content_type="text", hidden=False, image=False):
    message = None
    if role:
        parts = [text] if text is not None else []
        if image:
            parts.append({"content_type": "image_asset_pointer", "asset_pointer": "file-service://file-FAKE"})
            content_type = "multimodal_text"
        message = {
            "id": node_id,
            "author": {"role": role},
            "content": {"content_type": content_type, "parts": parts},
            "metadata": {"is_visually_hidden_from_conversation": True} if hidden else {},
        }
    return {"id": node_id, "parent": parent, "message": message}


def make_conversation(conv_id: str, n_exchanges: int = 2, branch: bool = False) -> dict:
    """A split-wrapper style file: wrapper fields + native object under 'conversation'."""
    nodes = [node("root", None), node("sys", "root", "system", "system prompt"),
             node("ctx", "sys", "user", "hidden custom instructions", hidden=True)]
    parent = "ctx"
    for i in range(n_exchanges):
        u, a = f"u{i}", f"a{i}"
        nodes.append(node(u, parent, "user", f"{conv_id} question {i}: I decided to use Python", image=(i == 0)))
        nodes.append(node(f"t{i}", u, "assistant", "secret reasoning", content_type="thoughts"))
        nodes.append(node(a, f"t{i}", "assistant", f"answer {i} for {conv_id}"))
        parent = a
    if branch:
        # A regenerated alternative answer to the last question, not selected.
        nodes.append(node("alt", f"t{n_exchanges - 1}", "assistant", "ALTERNATIVE BRANCH TEXT"))
    native = {
        "conversation_id": conv_id,
        "current_node": parent,
        "mapping": {n["id"]: n for n in nodes},
    }
    return {"title": "synthetic", "message_count": len(nodes), "conversation": native}


@pytest.fixture
def raw_dir(tmp_path):
    """Builds a raw/ folder factory: raw_dir(n) -> Path with n synthetic chats."""

    def build(n: int = 10) -> Path:
        root = tmp_path / "raw"
        conv_dir = root / "conversations"
        conv_dir.mkdir(parents=True)
        for i in range(n):
            data = make_conversation(f"conv-{i:03d}", n_exchanges=1 + i % 3, branch=(i % 4 == 0))
            (conv_dir / f"chat-{i:03d}.json").write_text(json.dumps(data))
        # A derived file from an old attempt: must be skipped, not crash.
        (conv_dir / "classification_output.json").write_text(json.dumps({"results": []}))
        return root

    return build
