"""Core value objects for the source layer, validated when created.

These are the shapes later tickets pass between each other: a source
snapshot, one revision of a message, one place an asset is referenced, and
one piece of evidence pointing into a message. They are frozen (cannot be
changed after creation) and reject unknown fields. Where an object carries
its own ID, the model checks that the ID really is the one computed from
its key, so a hand-made or stale ID can't slip in.

The semantic-layer objects in the original ticket (Segment, KnowledgeRecord)
are deliberately left to the M3 tickets that use them, because their shape
depends on the taxonomy work still to come (SESSION_LOG, FND-005).

Talking points:
    - "Objects check their own IDs on creation: you can't build a message
      revision whose ID doesn't match its content hash."
    - "Missing information stays missing: a message without a timestamp has
      None, not a made-up date."
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from knowledge_engine.domain import ids
from knowledge_engine.domain.enums import AssetAvailability, Role


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class SourceSnapshot(_Frozen):
    """One immutable source file as it was read: same bytes, same snapshot.

    Attributes:
        snapshot_id: ``snap_`` ID derived from ``sha256``.
        sha256: Hash of the file's bytes.
        byte_size: Size of the file in bytes.
        source_format: Which adapter format it was read as.
    """

    snapshot_id: ids.SnapshotId
    sha256: ids.Sha256Hex
    byte_size: int = Field(ge=0)
    source_format: str = Field(min_length=1)

    @model_validator(mode="after")
    def _id_matches_hash(self) -> SourceSnapshot:
        if self.snapshot_id != ids.snapshot_id(self.sha256):
            raise ValueError("snapshot_id does not match sha256")
        return self


class MessageRevision(_Frozen):
    """One version of one message's content.

    Attributes:
        revision_id: ``rev_`` ID derived from ``node_id`` and the content hash.
        node_id: The logical message node this is a version of.
        canonical_content_hash: Decides whether derived work must be redone.
        raw_payload_hash: Records exactly what the export said, including
            cosmetic metadata that doesn't trigger reprocessing.
        role: Who wrote it.
        create_time: When, if the export says; never invented. Must include a
            timezone.
        content_type: The export's content type, e.g. ``"text"``.
    """

    revision_id: ids.MessageRevisionId
    node_id: ids.MessageNodeId
    canonical_content_hash: ids.Sha256Hex
    raw_payload_hash: ids.Sha256Hex
    role: Role
    create_time: datetime | None = None
    content_type: str = Field(min_length=1)

    @model_validator(mode="after")
    def _check(self) -> MessageRevision:
        if self.revision_id != ids.message_revision_id(self.node_id, self.canonical_content_hash):
            raise ValueError("revision_id does not match node_id and canonical_content_hash")
        if self.create_time is not None and self.create_time.utcoffset() is None:
            raise ValueError("create_time must include a timezone (exports use UTC epochs)")
        return self


class AssetOccurrence(_Frozen):
    """One place where a message revision refers to an asset (ADR-0004).

    Attributes:
        occurrence_id: ``occ_`` ID derived from revision, part and pointer.
        revision_id: The message revision containing the reference.
        part_index: Position of the content part in the message.
        pointer: Verbatim pointer from the export, never rewritten.
        asset_id: The resolved asset, or None if it couldn't be resolved.
        availability: Whether the bytes were found.
        evidence: Short machine-readable notes on how that was decided.
    """

    occurrence_id: ids.AssetOccurrenceId
    revision_id: ids.MessageRevisionId
    part_index: int = Field(ge=0)
    pointer: str = Field(min_length=1)
    asset_id: ids.MediaAssetId | None
    availability: AssetAvailability
    evidence: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check(self) -> AssetOccurrence:
        expected = ids.asset_occurrence_id(self.revision_id, self.part_index, self.pointer)
        if self.occurrence_id != expected:
            raise ValueError("occurrence_id does not match revision_id, part_index and pointer")
        # "available" claims we have the bytes, which requires knowing which
        # asset they belong to. The other states may or may not know it.
        if self.availability is AssetAvailability.AVAILABLE and self.asset_id is None:
            raise ValueError("an available occurrence must name its asset")
        return self


class EvidenceRef(_Frozen):
    """A pointer to the exact text that supports a claim.

    Attributes:
        revision_id: The message revision quoted.
        start: First character (inclusive) in the canonical text.
        end: Last character (exclusive). Must be greater than ``start``.
        quote_sha256: Hash of the quoted text, checked against the source.
        actor: Who *said* the quoted text (not who extracted it).
    """

    revision_id: ids.MessageRevisionId
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    quote_sha256: ids.Sha256Hex
    actor: Role

    @model_validator(mode="after")
    def _non_empty_range(self) -> EvidenceRef:
        if self.end <= self.start:
            raise ValueError("evidence offsets must form a non-empty range [start, end)")
        return self
