"""Keeping the taxonomy up to date as new chats arrive (NOTE-014).

The first vocabulary (NOTE-006) was built from the chats that existed then.
Every later export brings chats on subjects nobody has named yet, and the
classifier can only use approved terms, so those chats come out with no
label at all. This module closes the loop without ever changing the
vocabulary in the middle of a run:

1. **Queue** (code): which segments the current version doesn't cover.
   A segment is queued when it has no label under that version
   (``unlabelled``), when its answer is waiting for a person
   (``review_required``), or when its chat arrived in an import after the
   last refresh pack, or after the first publish if there is no refresh
   pack yet (``new_chat``). Nothing is stored: the queue is worked
   out from the classifications each time, so it can't drift out of date.
2. **Refresh pack** (code): the NOTE-006 pack, built from the queued
   segments *only*, plus the current vocabulary so the proposer doesn't
   suggest what already exists. Recording the pack moves the "last pack"
   mark, so the next pack only looks at chats imported after it.
3. **Plan, review, publish** (the NOTE-006 steps, unchanged): a proposer
   session drafts terms, a *different* reviewer session decides, and Louis
   publishes ``tax-N+1``. A refresh plan may add only topics or only
   subcategories, so unlike the first plan it needn't contain categories.
4. **Relabel** (code): after publishing, only the segments the new version
   can change are classified again: ones with no label, ones whose labels
   cite a term that changed (TAX-007), and ones that mention a new term's
   name. Every other segment's old answer is *carried* into the new version
   as it is, with no classifier call. Old rows and reviewers' corrections
   are never edited (they're append-only), so nothing is lost.
5. **Counts** for the dashboard: chats with no label under the current
   version, chats waiting for review, and proposals waiting for a reviewer.

Talking points:
    - "New chats don't force a rebuild: only the segments a new term could
      change are relabelled; the rest carry their answers forward."
    - "The vocabulary never moves during a run. New subjects queue up, a
      proposer and a separate reviewer deal with them, and I publish."
    - "My corrections live apart from the machine's answers, so a relabel
      can't overwrite them."
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime, Integer, String, Text, func, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from knowledge_engine.classification.classifier import (
    DONE,
    REVIEW_REQUIRED,
    SegmentClassification,
    SegmentClassifier,
    segment_messages,
)
from knowledge_engine.classification.schema import CODE_VERSION, output_model
from knowledge_engine.classification.store import (
    ClassificationLabelRow,
    ClassificationReviewRow,
    ClassificationRow,
    review_queue,
    save,
)
from knowledge_engine.importer.ledger import ImportBatchRow
from knowledge_engine.importer.records import ConversationRow
from knowledge_engine.infrastructure.db import Base
from knowledge_engine.orchestration.stage_keys import stage_key
from knowledge_engine.rendering.transcript import StoredConversation
from knowledge_engine.segmentation.inventory import SegmentText
from knowledge_engine.segmentation.segmenter import Segment
from knowledge_engine.taxonomy.aliases import AliasResolver
from knowledge_engine.taxonomy.bootstrap import Plan, PlanTerm, build_pack, pack_sha256
from knowledge_engine.taxonomy.changes import (
    diff_snapshots,
    invalidate,
    record_diff,
)
from knowledge_engine.taxonomy.registry import (
    Dimension,
    TaxonomyProposalRow,
    TaxonomyRegistry,
    TaxonomySnapshot,
    TaxonomyVersionRow,
)
from knowledge_engine.taxonomy.review import OPEN

REFRESH_VERSION = "note-014-v1"
# A carried answer is the old answer under a new version; its stage key is
# made from the old one, so carrying the same answer twice is a no-op.
CARRY_STAGE_ID = "taxonomy.carry.v1"
CARRIED = "carried"

# Why a segment is queued, strongest first: a segment that is both new and
# unlabelled is reported once, as unlabelled.
UNLABELLED = "unlabelled"
NEW_CHAT = "new_chat"


def _utc_now() -> datetime:
    return datetime.now(UTC)


class RefreshPackRow(Base):
    """A refresh pack that was handed to a proposer session.

    It holds no chat text: the fingerprint, the version it was built
    against, how many segments were queued and sampled, and which imports
    existed then. A chat whose first import isn't in that list is "new
    since the last pack".
    """

    __tablename__ = "taxonomy_refresh_packs"

    pack_sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    from_version: Mapped[str] = mapped_column(String(40))
    queued: Mapped[int] = mapped_column(Integer)
    sampled: Mapped[int] = mapped_column(Integer)
    imports_json: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utc_now)


# ---------------------------------------------------------------- the queue


def latest_version(session: Session) -> TaxonomySnapshot | None:
    """The newest published version, or None before the first publish."""
    versions = TaxonomyRegistry(session).versions()
    return TaxonomyRegistry(session).snapshot(versions[-1]) if versions else None


def last_pack(session: Session) -> RefreshPackRow | None:
    """The most recently recorded refresh pack."""
    return session.scalar(
        select(RefreshPackRow).order_by(
            RefreshPackRow.created_at.desc(), RefreshPackRow.pack_sha256
        )
    )


def _seen_imports(session: Session) -> set[str] | None:
    """Imports already looked at for the vocabulary, or None before any publish.

    After a refresh pack: the imports that existed when it was recorded.
    Before the first refresh pack: the imports finished by the time the
    first version was published (the NOTE-006 pack was drawn from those).
    """
    pack = last_pack(session)
    if pack is not None:
        return set(json.loads(pack.imports_json))
    first = session.scalar(select(func.min(TaxonomyVersionRow.published_at)))
    if first is None:
        return None
    return {
        row.import_id
        for row in session.scalars(select(ImportBatchRow))
        if _aware(row.started_at) <= _aware(first)
    }


def _new_chats(session: Session) -> set[str]:
    """Chats first imported after the vocabulary last looked at the corpus."""
    seen = _seen_imports(session)
    if seen is None:
        return set()  # nothing published yet: every chat is simply unlabelled
    return set(
        session.scalars(
            select(ConversationRow.conversation_id).where(
                ConversationRow.first_import_id.not_in(seen)
            )
        )
    )


def _aware(value: datetime) -> datetime:
    # SQLite returns naive datetimes; they were written in UTC.
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _labelled_segments(session: Session, version: str) -> set[str]:
    """Segments with at least one label under ``version``, by machine or reviewer.

    A machine label counts only from a ``done`` answer: a ``review_required``
    one is kept for the reviewer to see but may not be used yet (CLS-002).
    """
    machine = session.scalars(
        select(ClassificationRow.segment_id)
        .join(
            ClassificationLabelRow,
            ClassificationLabelRow.classification_id == ClassificationRow.classification_id,
        )
        .where(ClassificationRow.taxonomy_version == version, ClassificationRow.state == DONE)
    )
    reviewed = session.scalars(
        select(ClassificationReviewRow.segment_id).where(
            ClassificationReviewRow.primary_id.is_not(None)
        )
    )
    return set(machine) | set(reviewed)


def queue(
    session: Session, snapshot: TaxonomySnapshot, items: Iterable[SegmentText]
) -> dict[str, str]:
    """Which segments the vocabulary doesn't cover yet, and why.

    Args:
        session: Read only.
        snapshot: The current published version.
        items: Every segment (``corpus_inventory``).

    Returns:
        Segment ID -> ``review_required``, ``unlabelled`` or ``new_chat``.
        Segments that are labelled, settled and from an older import aren't
        listed.
    """
    waiting = {row.segment_id for row in review_queue(session, snapshot.version)}
    labelled = _labelled_segments(session, snapshot.version)
    new = _new_chats(session)
    found = {}
    for item in items:
        if item.segment_id in waiting:
            found[item.segment_id] = REVIEW_REQUIRED
        elif item.segment_id not in labelled:
            found[item.segment_id] = UNLABELLED
        elif item.conversation_id in new:
            found[item.segment_id] = NEW_CHAT
    return found


# ---------------------------------------------------------------- the refresh pack


class NothingToRefresh(ValueError):
    """Every segment is labelled and settled: there's nothing to send a proposer."""


def build_refresh_pack(
    session: Session,
    snapshot: TaxonomySnapshot,
    items: Sequence[SegmentText],
    *,
    size: int,
    seed: str,
) -> dict[str, Any]:
    """A NOTE-006 pack built from the queued segments only.

    The pack also lists the current vocabulary (labels only), so the
    proposer can see what's already there. Like any pack it holds private
    chat text: write it only to a git-ignored folder.

    Raises:
        NothingToRefresh: If no segment is queued.
    """
    reasons = queue(session, snapshot, items)
    pool = [item for item in items if item.segment_id in reasons]
    if not pool:
        raise NothingToRefresh("every segment is labelled under " + snapshot.version)
    pack = build_pack(pool, size=size, seed=seed)
    pack["refresh"] = {
        "version": REFRESH_VERSION,
        "from_version": snapshot.version,
        "segments_in_corpus": len(items),
        "queued": dict(sorted(Counter(reasons.values()).items())),
        "vocabulary": {
            dimension.value: sorted(t.label for t in snapshot.dimension(dimension))
            for dimension in Dimension
            if snapshot.dimension(dimension)
        },
    }
    return pack


def record_pack(session: Session, pack: dict[str, Any]) -> RefreshPackRow:
    """Remember that this pack went out; recording the same pack again changes nothing.

    From now on, "new chats" are the ones whose first import came after
    this call. The caller commits.
    """
    sha = pack_sha256(pack)
    row = session.get(RefreshPackRow, sha)
    if row is not None:
        return row
    imports = sorted(session.scalars(select(ImportBatchRow.import_id)))
    row = RefreshPackRow(
        pack_sha256=sha,
        from_version=pack["refresh"]["from_version"],
        queued=sum(pack["refresh"]["queued"].values()),
        sampled=pack["corpus"]["sampled"],
        imports_json=json.dumps(imports),
    )
    session.add(row)
    session.flush()
    return row


class RefreshPlan(Plan):
    """A plan written for a refresh pack.

    The same shape and checks as the first plan, except that categories are
    optional: a refresh may only need a new topic, or a subcategory under a
    category that already exists (name the category with its current label
    and list the new subcategory under it; the existing category is reused,
    not filed again).
    """

    categories: tuple[PlanTerm, ...] = ()


def plan_for(pack: Mapping[str, Any], text: str) -> Plan:
    """Read a plan with the rules of its pack: a refresh pack takes a ``RefreshPlan``.

    Raises:
        pydantic.ValidationError: If the JSON doesn't fit.
    """
    model = RefreshPlan if "refresh" in pack else Plan
    return model.model_validate_json(text)


# ---------------------------------------------------------------- relabelling after a publish


@dataclass
class RelabelReport:
    """What a relabel did, by segment ID (no text).

    Attributes:
        from_version: The version labels came from.
        to_version: The newly published version.
        relabelled: Segment ID -> why it was classified again
            (``unlabelled``, ``cites_changed`` or ``mentions_new_term``).
        carried: Segments whose old answer now stands under the new version.
        invalidated: Stage keys of old answers TAX-007 marked stale.
        states: How the relabelled segments came out (done, pending, review_required).
        conversations: Chats with at least one relabelled segment: their
            notes are the ones the vault sync will rewrite.
    """

    from_version: str
    to_version: str
    relabelled: dict[str, str] = field(default_factory=dict)
    carried: list[str] = field(default_factory=list)
    invalidated: list[str] = field(default_factory=list)
    states: dict[str, int] = field(default_factory=dict)
    conversations: list[str] = field(default_factory=list)


def _newest(session: Session, segment_id: str, version: str) -> ClassificationRow | None:
    # A carried row counts too: after tax-2 carried an answer, relabelling
    # into tax-3 starts from that answer.
    return session.scalar(
        select(ClassificationRow)
        .where(
            ClassificationRow.segment_id == segment_id,
            ClassificationRow.taxonomy_version == version,
        )
        .order_by(ClassificationRow.updated_at.desc(), ClassificationRow.classification_id)
    )


def _cited(session: Session, row: ClassificationRow) -> set[str]:
    return set(
        session.scalars(
            select(ClassificationLabelRow.target_id).where(
                ClassificationLabelRow.classification_id == row.classification_id
            )
        )
    )


def _carry(
    row: ClassificationRow, new: TaxonomySnapshot, segment: Segment
) -> SegmentClassification | None:
    """The old answer as an answer under ``new``, or None if it doesn't fit there.

    The old answer is checked against the new version's answer model, so a
    carried label can only be an ID the new version approves.
    """
    if row.answer_json is None:
        return None
    try:
        answer = output_model(new).model_validate_json(row.answer_json)
    except ValueError:
        return None
    versions = {"code": CODE_VERSION, "taxonomy": new.version, "taxonomy_sha": new.content_sha256}
    origin = hashlib.sha256(row.stage_key.encode("utf-8")).hexdigest()
    return SegmentClassification(
        segment_id=segment.segment_id,
        conversation_id=segment.conversation_id,
        taxonomy_version=new.version,
        method=CARRIED,
        stage_key=stage_key(CARRY_STAGE_ID, origin, versions),
        state=DONE,
        answer=answer,
        problems=(),
        message_ids=tuple(segment.messages),
    )


def relabel(
    session: Session,
    old: TaxonomySnapshot,
    classifier: SegmentClassifier,
    items: Sequence[tuple[StoredConversation, Segment]],
    *,
    provider_id: str | None = None,
) -> RelabelReport:
    """Bring every segment's labels into the classifier's (new) version, redoing only what changed.

    For each segment, its newest answer under ``old`` decides:

    * no answer, not ``done``, or no labels: **relabel** (``unlabelled``);
    * it cites a term or project the new version removed or changed:
      TAX-007 marks it stale, then **relabel** (``cites_changed``);
    * its text names a term or project the new version *added*:
      **relabel** (``mentions_new_term``), because the old answer couldn't
      have chosen it;
    * otherwise **carry** the old answer into the new version unchanged.

    Running it again after model answers arrive collects them (CLS-004
    completes pending rows) and changes nothing else. The caller commits.

    Args:
        session: Read and write.
        old: The version the existing labels came from.
        classifier: Pinned to the new version (keyword, or model with a
            provider behind the switch).
        items: Every (conversation, segment) to bring across.
        provider_id: For model answers, which provider (stored with them).
    """
    new = classifier.snapshot
    if new.version == old.version:
        raise ValueError("relabel needs two different versions")
    diff = diff_snapshots(old, new)
    record_diff(session, diff)
    resolver = AliasResolver(new)
    report = RelabelReport(old.version, new.version)
    redo: list[tuple[StoredConversation, Segment]] = []
    stale: dict[str, set[str]] = {}
    carried: list[SegmentClassification] = []
    for conversation, segment in items:
        row = _newest(session, segment.segment_id, old.version)
        cited = _cited(session, row) if row is not None else set()
        reason = None
        if row is None or row.state != DONE or not cited:
            reason = UNLABELLED
        elif cited & diff.touched:
            reason = "cites_changed"
            stale[row.stage_key] = cited
        elif diff.added and _mentions(resolver, conversation, segment, diff.added):
            reason = "mentions_new_term"
        carry = None if reason or row is None else _carry(row, new, segment)
        if carry is None:
            # No reason but nothing to carry: the old answer doesn't fit the
            # new version's answer model, so it is asked again.
            report.relabelled[segment.segment_id] = reason or "does_not_fit"
            redo.append((conversation, segment))
        else:
            carried.append(carry)
            report.carried.append(segment.segment_id)
    report.invalidated = invalidate(session, diff, stale)
    save(session, carried)
    results = classifier.classify(redo) if redo else []
    save(session, results, provider_id=provider_id)
    report.states = dict(sorted(Counter(r.state for r in results).items()))
    report.conversations = sorted({r.conversation_id for r in results})
    return report


def _mentions(
    resolver: AliasResolver,
    conversation: StoredConversation,
    segment: Segment,
    added: frozenset[str],
) -> bool:
    """True if the segment's text names one of the added terms or projects."""
    for message in segment_messages(conversation, segment):
        for mention in resolver.find(message.text):
            if any(c.target_id in added for c in mention.resolution.candidates):
                return True
    return False


# ---------------------------------------------------------------- dashboard counts


@dataclass(frozen=True)
class RefreshStatus:
    """The headline numbers for the dashboard (counts only, no text).

    Attributes:
        version: The current published version (None before the first).
        chats: Chats stored.
        unlabelled_chats: Chats with no label at all under that version.
        review_chats: Chats with a segment waiting for a reviewer.
        new_chats: Chats imported since the last refresh pack.
        candidates: Vocabulary proposals waiting for a reviewer.
        last_pack_at: When the last refresh pack went out.
    """

    version: str | None
    chats: int
    unlabelled_chats: int
    review_chats: int
    new_chats: int
    candidates: int
    last_pack_at: datetime | None


def refresh_status(session: Session) -> RefreshStatus:
    """Count what the current vocabulary doesn't cover yet. Reads only, no segmenting."""
    chats = int(session.scalar(select(func.count()).select_from(ConversationRow)) or 0)
    candidates = int(
        session.scalar(
            select(func.count())
            .select_from(TaxonomyProposalRow)
            .where(TaxonomyProposalRow.status == OPEN)
        )
        or 0
    )
    pack = last_pack(session)
    new = len(_new_chats(session))
    snapshot = latest_version(session)
    if snapshot is None:
        return RefreshStatus(None, chats, chats, 0, new, candidates, None)
    labelled_segments = _labelled_segments(session, snapshot.version)
    labelled_chats = set(
        session.scalars(
            select(ClassificationRow.conversation_id).where(
                ClassificationRow.segment_id.in_(labelled_segments)
            )
        )
    )
    review = {row.conversation_id for row in review_queue(session, snapshot.version)}
    return RefreshStatus(
        snapshot.version,
        chats,
        chats - len(labelled_chats),
        len(review),
        new,
        candidates,
        pack.created_at if pack else None,
    )
