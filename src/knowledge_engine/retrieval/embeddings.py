"""Turning text into vectors, with the model's identity always attached (RET-002).

An embedding is a list of numbers standing for a text's meaning, so texts
about the same thing end up close together. Search can then find a message
that says "painted the shed" for the query "shed painting".

Vectors from two different models (or two sizes of one model) can't be
compared: mixing them gives nonsense scores silently. So every embedder
declares an ``EmbeddingIdentity`` (provider, model, dimension, version and
whether it sends data off the machine), and every vector index stores the
identity's **fingerprint**. An index opened with a different identity is
refused (``StaleIndexError``) until it is explicitly rebuilt; it is never
half-reused. That is TR: "a model change triggers a reindex, not silent
reuse".

Two embedders ship:

* ``LocalHashEmbedder``: deterministic, local, free, no model download.
  Each word is reduced to a rough stem ("painting", "painted" -> "paint")
  and also split into three-letter pieces (which tolerates typos); every
  feature is hashed into one of ``dimension`` slots with a +1/-1 sign,
  and the vector is scaled to length 1. It finds re-worded, re-ordered,
  inflected or misspelt versions of the same words. It does **not** know
  synonyms ("car" and "automobile" share nothing); a real embedding model
  behind the same interface is needed for that, and stays off until the
  owner enables the ``embedding`` egress switch or installs a local model.
* ``FakeEmbedder``: answers from a table, for tests.

An embedder that sends data must pass ``EgressPolicy.require(EMBEDDING)``
first; ``embed`` does that check.

Talking points:
    - "Every vector carries the fingerprint of the model that made it, and
      an index built with another model is refused, not mixed in."
    - "The built-in embedder is local and free. It handles rewording and
      typos, but not synonyms; a real model can be plugged in later."
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from knowledge_engine.settings import Capability, EgressPolicy

_WORD = re.compile(r"[^\W_]+", re.UNICODE)
# Longest first, so "edly" goes before "ed".
_SUFFIXES = (
    "ations",
    "ation",
    "ments",
    "ment",
    "ness",
    "edly",
    "ing",
    "ies",
    "ers",
    "est",
    "ed",
    "er",
    "es",
    "ly",
    "s",
)


@dataclass(frozen=True)
class EmbeddingIdentity:
    """Who makes the vectors, and their shape.

    Attributes:
        provider_id: e.g. ``local-hash``.
        model: The model name or local method.
        dimension: How many numbers per vector.
        version: The method's own version (tokeniser, normalisation).
        sends_data: True if texts leave this machine.
    """

    provider_id: str
    model: str
    dimension: int
    version: str
    sends_data: bool

    @property
    def fingerprint(self) -> str:
        """SHA-256 of everything that changes what a vector means."""
        key = "\x00".join((self.provider_id, self.model, str(self.dimension), self.version))
        return hashlib.sha256(key.encode("utf-8")).hexdigest()


class Embedder(Protocol):
    """Anything that turns texts into vectors of one fixed identity."""

    @property
    def identity(self) -> EmbeddingIdentity:
        """What makes the vectors."""
        ...

    def vectors(self, texts: Sequence[str]) -> list[list[float]]:
        """One vector per text, in order."""
        ...


class EmbeddingShapeError(ValueError):
    """An embedder returned the wrong number of vectors or numbers."""


def embed(embedder: Embedder, texts: Sequence[str], egress: EgressPolicy) -> list[list[float]]:
    """Embed texts after the egress check, and check what comes back.

    Raises:
        EgressDisabledError: The embedder sends data and ``embedding`` is off.
        EmbeddingShapeError: Wrong count or dimension.
    """
    if embedder.identity.sends_data:
        egress.require(Capability.EMBEDDING)
    if not texts:
        return []
    found = embedder.vectors(texts)
    if len(found) != len(texts):
        raise EmbeddingShapeError("one vector per text expected")
    if any(len(v) != embedder.identity.dimension for v in found):
        raise EmbeddingShapeError("vector size differs from the declared dimension")
    return found


def stem(word: str) -> str:
    """A rough English stem: strips one common ending, keeping at least 3 letters."""
    for suffix in _SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


def _features(text: str) -> list[tuple[str, float]]:
    found: list[tuple[str, float]] = []
    for word in _WORD.findall(text.lower()):
        root = stem(word)
        found.append(("w:" + root, 1.0))
        padded = f"<{root}>"
        found += [("c:" + padded[i : i + 3], 0.25) for i in range(len(padded) - 2)]
    return found


def normalise(vector: list[float]) -> list[float]:
    """Scale to length 1 (a zero vector stays zero)."""
    length = math.sqrt(sum(x * x for x in vector))
    return [x / length for x in vector] if length else vector


class LocalHashEmbedder:
    """Hashed stems and letter triples; local and deterministic (see the module text)."""

    def __init__(self, dimension: int = 512) -> None:
        """Choose the vector size (a new size is a new identity)."""
        self._identity = EmbeddingIdentity(
            "local-hash", "stems+trigrams", dimension, "ret-002-v1", sends_data=False
        )

    @property
    def identity(self) -> EmbeddingIdentity:
        """Local, never sends anything."""
        return self._identity

    def vectors(self, texts: Sequence[str]) -> list[list[float]]:
        """Hash each text's features into a fixed-size vector."""
        size = self._identity.dimension
        result = []
        for text in texts:
            vector = [0.0] * size
            for feature, weight in _features(text):
                digest = hashlib.blake2b(feature.encode("utf-8"), digest_size=8).digest()
                slot = int.from_bytes(digest[:4], "big") % size
                sign = 1.0 if digest[4] & 1 else -1.0
                vector[slot] += sign * weight
            result.append(normalise(vector))
        return result


class FakeEmbedder:
    """Answers from a table; unknown texts get a zero vector. For tests."""

    def __init__(
        self,
        table: Mapping[str, Sequence[float]],
        *,
        dimension: int,
        model: str = "fake",
        sends_data: bool = False,
    ) -> None:
        """Set the answers and the identity."""
        self._table = {k: list(v) for k, v in table.items()}
        self._identity = EmbeddingIdentity("fake", model, dimension, "test", sends_data)
        self.calls: list[int] = []

    @property
    def identity(self) -> EmbeddingIdentity:
        """The declared identity."""
        return self._identity

    def vectors(self, texts: Sequence[str]) -> list[list[float]]:
        """Look each text up; records how many texts each call had."""
        self.calls.append(len(texts))
        return [self._table.get(t, [0.0] * self._identity.dimension) for t in texts]


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity of two vectors (0 when either is all zeros)."""
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    size = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / size if size else 0.0
