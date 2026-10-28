"""Typed knowledge records and their review lifecycle (EXT-001).

A *knowledge record* is one thing worth remembering from the chats: a
decision, a rejected idea, a preference, a task, a question, a reference...
Each record says **who** holds it (``actor``), **how** we know (``origin``,
``acceptance``), **where** it applies (``scope``), **what it rests on**
(``evidence``: exact quotes, NRM-003), **what produced it**
(``provenance``) and **how far it is trusted** (``trust``).

The rules the schema enforces, so a bad record can't even be built:

* Unknown record types, trust states or fields are refused (enums,
  ``extra="forbid"``).
* An ``extracted`` record must cite evidence. Only a reviewer's own entry
  (``origin="reviewer"``) may have none.
* ``supported`` needs evidence that the EXT-002 validator checked
  (``evidence_checked_by``); ``confirmed`` additionally needs a named
  reviewer. ``inferred`` records can't be confirmed.
* A decision, preference, requirement or task held by the **user** can't be
  ``supported`` or ``confirmed`` unless the acceptance was ``explicit`` or
  ``conditional``. An assistant suggestion the user never took up stays a
  candidate or a ``proposal``: it is never turned into the user's decision.

What an extractor (or a model) returns is a ``CandidateRecord``: it has no
trust field at all, so no extractor can promote its own output. Trust only
moves through ``advance`` and the transition table below (EXT-007 stores it).

Talking points:
    - "An extractor can only propose. There is no field in its output that
      says 'trusted'."
    - "A suggestion stays a suggestion until the user's own words accept it."
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from knowledge_engine.domain.enums import Role
from knowledge_engine.domain.models import EvidenceRef

# v2 (EXT-004): optional strength, polarity and attributed_to.
RECORD_SCHEMA_VERSION = "ext-001-v2"


class RecordType(StrEnum):
    """What kind of knowledge (DATA_MODEL_AND_CONTRACTS §4)."""

    FACT = "fact"
    PROPOSAL = "proposal"
    DECISION = "decision"
    REJECTION = "rejection"
    PREFERENCE = "preference"
    REQUIREMENT = "requirement"
    IDEA = "idea"
    QUESTION = "question"
    ACTION = "action"
    ARTEFACT = "artefact"
    REFERENCE = "reference"
    RECOMMENDATION = "recommendation"


class Origin(StrEnum):
    """How the record came about."""

    EXTRACTED = "extracted"  # read from quoted source text
    INFERRED = "inferred"  # reasoned from several sources; never confirmed
    REVIEWER = "reviewer"  # entered by a person directly


class Acceptance(StrEnum):
    """Did the actor accept it, and how do we know (TR-04)?"""

    EXPLICIT = "explicit"  # "yes, let's do that"
    CONDITIONAL = "conditional"  # "yes, if it runs on Linux"
    INFERRED = "inferred"  # they went on as if accepted; not enough alone
    ABSENT = "absent"  # no sign of acceptance
    NOT_APPLICABLE = "not_applicable"  # facts, questions, references


class Scope(StrEnum):
    """Where a record applies."""

    GLOBAL = "global"
    PROJECT = "project"
    CONVERSATION = "conversation"
    SEGMENT = "segment"


class Strength(StrEnum):
    """How firm a preference or requirement is (EXT-004)."""

    SOFT = "soft"  # "ideally", "would be nice", "I'd rather"
    HARD = "hard"  # "must", "has to", "never"


class Polarity(StrEnum):
    """For or against."""

    FOR = "for"
    AGAINST = "against"


class Trust(StrEnum):
    """How far a record is trusted.

    Only ``supported`` and ``confirmed`` may feed current-truth views (EXT-007).
    """

    CANDIDATE = "candidate"
    REVIEW_REQUIRED = "review_required"
    SUPPORTED = "supported"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


# Allowed trust moves. Nothing returns to candidate; rejected is final.
TRANSITIONS: dict[Trust, frozenset[Trust]] = {
    Trust.CANDIDATE: frozenset({Trust.REVIEW_REQUIRED, Trust.SUPPORTED, Trust.REJECTED}),
    Trust.REVIEW_REQUIRED: frozenset({Trust.SUPPORTED, Trust.REJECTED}),
    Trust.SUPPORTED: frozenset({Trust.CONFIRMED, Trust.REJECTED, Trust.SUPERSEDED}),
    Trust.CONFIRMED: frozenset({Trust.SUPERSEDED}),
    Trust.REJECTED: frozenset(),
    Trust.SUPERSEDED: frozenset(),
}
# Types that, when the user holds them, need the user's acceptance to be trusted.
COMMITMENTS = frozenset(
    {RecordType.DECISION, RecordType.PREFERENCE, RecordType.REQUIREMENT, RecordType.ACTION}
)
_ACCEPTED = frozenset({Acceptance.EXPLICIT, Acceptance.CONDITIONAL})


class Provenance(BaseModel):
    """What produced a record, so it can be traced and re-run.

    Attributes:
        stage_id: e.g. ``extract.decisions.v1``.
        stage_key: The exact work (``stg_...``).
        extractor_version: The extractor's code version.
        prompt_version: For model extractors.
        taxonomy_version: The pinned vocabulary its IDs come from.
        provider_id: For model extractors.
        served_model: As reported by the provider.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    stage_id: str = Field(min_length=1)
    stage_key: str = Field(pattern=r"^stg_[0-9a-f]{64}$")
    extractor_version: str = Field(min_length=1)
    prompt_version: str | None = None
    taxonomy_version: str | None = None
    provider_id: str | None = None
    served_model: str | None = None


class CandidateRecord(BaseModel):
    """What an extractor proposes. No trust field: proposing is all it can do.

    Attributes:
        record_type: The kind of knowledge.
        assertion: A short plain statement (kept with the private data).
        actor: Who holds it: whose decision, whose preference.
        origin: ``extracted`` or ``inferred`` (a reviewer uses ``KnowledgeRecord``).
        acceptance: How the actor's acceptance is known.
        scope: Where it applies; ``scope_id`` names the project, chat or segment.
        project_ids: Approved project IDs it concerns.
        term_ids: Approved taxonomy term IDs it concerns.
        evidence: The exact quotes it rests on.
        review_reason: Why the extractor itself is unsure, if it is.
        strength: Soft or hard, for preferences and requirements.
        polarity: For or against, for preferences.
        attributed_to: Set when the speaker reports someone else's view
            ("my client wants..."): a category such as ``external``, never
            a guessed name. Such a record is not the speaker's own.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    record_type: RecordType
    assertion: str = Field(min_length=1, max_length=2000)
    actor: Role
    origin: Origin = Origin.EXTRACTED
    acceptance: Acceptance = Acceptance.ABSENT
    scope: Scope = Scope.SEGMENT
    scope_id: str | None = None
    project_ids: tuple[str, ...] = ()
    term_ids: tuple[str, ...] = ()
    evidence: tuple[EvidenceRef, ...] = ()
    review_reason: str | None = Field(default=None, max_length=500)
    strength: Strength | None = None
    polarity: Polarity | None = None
    attributed_to: str | None = Field(default=None, max_length=40)

    @model_validator(mode="after")
    def _check(self) -> CandidateRecord:
        if self.origin is Origin.REVIEWER:
            raise ValueError("an extractor can't claim to be a reviewer")
        if self.origin is Origin.EXTRACTED and not self.evidence:
            raise ValueError("an extracted record needs source evidence")
        if self.scope is not Scope.GLOBAL and not self.scope_id:
            raise ValueError("a scoped record needs scope_id")
        return self


class KnowledgeRecord(CandidateRecord):
    """A record as stored, with its trust state.

    Attributes:
        record_id: ``krec_`` ID (assigned by the store).
        trust: Where it stands.
        evidence_checked_by: The EXT-002 validator version that passed it.
        reviewer: Who confirmed or rejected it, if anyone.
        provenance: What produced it (None only for a reviewer's own entry).
        schema_version: This contract's version.
    """

    record_id: str = Field(pattern=r"^krec_[0-9a-f]{32}$")
    trust: Trust = Trust.CANDIDATE
    evidence_checked_by: str | None = None
    reviewer: str | None = None
    provenance: Provenance | None = None
    schema_version: str = RECORD_SCHEMA_VERSION

    # Same name as the parent's validator, so it replaces it: a stored
    # record may be a reviewer's own entry, which a candidate may not.
    @model_validator(mode="after")
    def _check(self) -> KnowledgeRecord:
        if self.origin is Origin.EXTRACTED and not self.evidence:
            raise ValueError("an extracted record needs source evidence")
        if self.scope is not Scope.GLOBAL and not self.scope_id:
            raise ValueError("a scoped record needs scope_id")
        if self.origin is not Origin.REVIEWER and self.provenance is None:
            raise ValueError("a machine-made record needs provenance")
        trusted = self.trust in (Trust.SUPPORTED, Trust.CONFIRMED)
        if trusted and self.origin is not Origin.REVIEWER:
            if not self.evidence or not self.evidence_checked_by:
                raise ValueError(f"{self.trust} needs evidence that passed validation")
        if self.trust is Trust.CONFIRMED:
            if not self.reviewer:
                raise ValueError("confirmed needs a named reviewer")
            if self.origin is Origin.INFERRED:
                raise ValueError("an inferred record can't be confirmed")
        if (
            trusted
            and self.actor is Role.USER
            and self.record_type in COMMITMENTS
            and self.acceptance not in _ACCEPTED
        ):
            raise ValueError(
                f"a user {self.record_type} needs explicit or conditional acceptance to be trusted"
            )
        return self


class TrustTransitionError(ValueError):
    """A trust change the lifecycle doesn't allow."""


def advance(record: KnowledgeRecord, new: Trust, **changes: object) -> KnowledgeRecord:
    """Return a copy of ``record`` moved to ``new``; the record itself is untouched.

    Args:
        record: The current record.
        new: The next trust state.
        **changes: Fields that change with it (``reviewer``,
            ``evidence_checked_by``, ``review_reason``).

    Raises:
        TrustTransitionError: If the move isn't in ``TRANSITIONS``.
        pydantic.ValidationError: If the result breaks a record rule (for
            example confirming without a reviewer).
    """
    if new not in TRANSITIONS[record.trust]:
        raise TrustTransitionError(f"cannot go from {record.trust} to {new}")
    data = record.model_dump()
    data.update(changes, trust=new)
    return KnowledgeRecord.model_validate(data)
