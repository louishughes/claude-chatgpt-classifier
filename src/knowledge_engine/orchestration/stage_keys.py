"""Stage keys: a fingerprint that says whether a piece of work is already done.

TECHNICAL_REQUIREMENTS TR-03: a stage's key is the hash of the stage name,
the hash of its exact input, and every version that could change its output
(code, prompt, taxonomy, configuration, model policy). Same key means the
saved result can be reused (a "cache hit"). Change any part, for example
bump the parser version, and the key changes, so the work runs again. This
is what makes re-importing an unchanged export free, and it's how a future
AI stage avoids paying twice for the same answer.

Talking points:
    - "Whether to redo work is a lookup, not a judgement call: same
      fingerprint, same answer."
    - "Bumping a version number is enough to invalidate exactly the work that
      version affects."
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping

_STAGE_ID_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,99}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_VERSION_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,49}$")


def stage_key(stage_id: str, input_hash: str, versions: Mapping[str, str]) -> str:
    """Return the stage key for one unit of work.

    Args:
        stage_id: The stage name and contract version, e.g. ``"import.parse.v1"``.
        input_hash: SHA-256 of the exact input (64 lowercase hex characters).
        versions: Everything else that can change the output, by name, e.g.
            ``{"code": "1.0.0", "prompt": "cls-001"}``. Must include
            ``"code"``. Order doesn't matter; names are sorted.

    Returns:
        ``stg_`` followed by 64 hex characters (full SHA-256; stage keys are
        never shown to people, so there's no reason to shorten them).

    Raises:
        ValueError: If any part is missing or malformed.
    """
    if not _STAGE_ID_RE.fullmatch(stage_id):
        raise ValueError("stage_id must look like 'import.parse.v1'")
    if not _SHA256_RE.fullmatch(input_hash):
        raise ValueError("input_hash must be 64 lowercase hex characters")
    if "code" not in versions:
        raise ValueError("versions must include 'code'")
    for name, value in versions.items():
        if not _VERSION_NAME_RE.fullmatch(name):
            raise ValueError(f"bad version name {name!r}")
        if not isinstance(value, str) or not value:
            raise ValueError(f"version {name!r} must be a non-empty string")
    key = ["ke-stage-v1", stage_id, input_hash, sorted(versions.items())]
    encoded = json.dumps(key, separators=(",", ":"), ensure_ascii=False)
    return "stg_" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()
