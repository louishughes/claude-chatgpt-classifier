"""Bootstrapping the first taxonomy from the real chats, with no paid API (NOTE-006).

Nothing can be classified until an approved vocabulary is published, and the
best source of that vocabulary is the chats themselves. The work is split so
that no one grades their own work (``docs/plans/RICH_NOTES_GAP_ANALYSIS.md``
D2):

1. **Pack** (code): a fair sample of segments (NRM-006, rare themes
   included), short excerpts of each, and the TF-IDF groups (TAX-006) as
   hints. The pack holds private chat text, so it is written only to a
   git-ignored folder, and its SHA-256 ties everything after it to it.
2. **Plan** (a Claude session, the *proposer*): reads the pack and writes a
   JSON plan: categories with subcategories, activity and output facets, and
   topics. Each term has a definition and cites the sampled segments it is
   based on. ``Plan`` checks the shape in code (unknown fields, a third
   level, uncited terms and segments not in the pack are refused).
3. **Propose** (code): files each top-level term as a TAX-004 ``add``
   proposal. Subcategories need an *approved* parent, so they wait.
4. **Review** (a *different* Claude session): reads the review sheet and
   writes approve/reject decisions with a reason each. TAX-004 already
   refuses a reviewer who is also the proposer.
5. **Children**: once categories are approved, subcategories are filed under
   them and reviewed the same way.
6. **Summary** for Louis, then **publish** only on his word.

Talking points:
    - "One Claude proposes the categories, a different one reviews them,
      and I approve the publish. Nobody marks their own homework."
    - "The plan is checked in code: every category has to point at real
      chats from the sample, or it's refused."
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.segmentation.inventory import SegmentText, sample, summarise
from knowledge_engine.taxonomy.discovery import TfidfBackend
from knowledge_engine.taxonomy.registry import (
    Dimension,
    TaxonomyAliasRow,
    TaxonomyProposalRow,
    TaxonomyTermRow,
    TermStatus,
    normalise_alias,
)
from knowledge_engine.taxonomy.review import (
    OPEN,
    Operation,
    ReviewError,
    approve,
    propose,
    reject,
)

PACK_KIND = "ke-taxonomy-pack"
PACK_VERSION = "note-006-v1"
EXCERPT_CHARS = 600  # enough to see what a segment is about, not the whole chat

# Which plan list files into which dimension. "Category" is the two-level
# domain dimension; the facets and topics are one level.
PLAN_DIMENSIONS = {
    "categories": Dimension.DOMAIN,
    "activities": Dimension.PURPOSE,
    "outputs": Dimension.OUTPUT,
    "topics": Dimension.TOPIC,
}


# ---------------------------------------------------------------- the pack


# A paragraph found in more segments than this is boilerplate (custom
# instructions, tool notices) and is left out of excerpts, so each excerpt
# shows what the segment is about rather than the same preamble 100 times.
BOILERPLATE_MIN_SEGMENTS = 5


def _paragraphs(text: str) -> list[str]:
    return [" ".join(p.split()) for p in text.split("\n\n") if p.strip()]


def boilerplate(items: Sequence[SegmentText]) -> set[str]:
    """Paragraphs that repeat across many segments (see ``BOILERPLATE_MIN_SEGMENTS``)."""
    seen: Counter[str] = Counter()
    for item in items:
        seen.update(set(_paragraphs(item.text)))
    floor = max(BOILERPLATE_MIN_SEGMENTS, len(items) // 100)
    return {p for p, n in seen.items() if n > floor}


def _excerpt(text: str, skip: set[str] | None = None) -> str:
    kept = [p for p in _paragraphs(text) if p not in (skip or set())]
    line = " ".join(kept) or " ".join(text.split())
    if len(line) <= EXCERPT_CHARS:
        return line
    return line[:EXCERPT_CHARS].rsplit(" ", 1)[0] + " …"


def build_pack(items: Sequence[SegmentText], *, size: int, seed: str) -> dict[str, Any]:
    """The proposer's input: corpus counts, a fair sample with excerpts, and hints.

    The result holds private chat text (the excerpts): write it only to a
    git-ignored folder.

    Args:
        items: The whole inventory (``corpus_inventory``).
        size: How many segments to sample.
        seed: Same seed, same sample.
    """
    drawn = sample(items, size, seed=seed)
    skip = boilerplate(items)
    groups = TfidfBackend().cluster(drawn)
    summary = summarise(items)
    return {
        "kind": PACK_KIND,
        "version": PACK_VERSION,
        "seed": seed,
        "corpus": {
            "conversations": summary.conversations,
            "segments": summary.segments,
            "sampled": len(drawn),
            "boilerplate_paragraphs": len(skip),
        },
        "hints": [
            {
                "keywords": list(g.label_words),
                "segments": sorted(drawn[i].segment_id for i in g.members),
            }
            for g in groups
            if len(g.members) >= 2
        ],
        "segments": [
            {
                "segment_id": s.segment_id,
                "conversation_id": s.conversation_id,
                "messages": s.messages,
                "excerpt": _excerpt(s.text, skip),
            }
            for s in drawn
        ],
    }


def pack_sha256(pack: dict[str, Any]) -> str:
    """The pack's fingerprint (canonical JSON), which a plan must quote."""
    encoded = json.dumps(pack, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------- the plan


class PlanTerm(BaseModel):
    """One proposed term. ``children`` are subcategories (categories only)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    label: str = Field(min_length=2, max_length=60)
    definition: str = Field(min_length=10, max_length=300)
    aliases: tuple[str, ...] = ()
    segments: tuple[str, ...] = Field(min_length=1, description="sampled segments it rests on")
    children: tuple[PlanTerm, ...] = ()


class Plan(BaseModel):
    """What the proposer session writes. Checked in code before anything is filed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    pack_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    proposer: str = Field(min_length=3, max_length=80)
    categories: tuple[PlanTerm, ...] = Field(min_length=1)
    activities: tuple[PlanTerm, ...] = ()
    outputs: tuple[PlanTerm, ...] = ()
    topics: tuple[PlanTerm, ...] = ()


class PlanError(ValueError):
    """The plan doesn't fit the pack or the rules; nothing was filed."""


def check_plan(plan: Plan, pack: dict[str, Any]) -> None:
    """Refuse a plan that doesn't belong to this pack or breaks a rule.

    Rules: the pack fingerprint matches; every cited segment is in the
    sample; labels are unique per dimension once normalised; only categories
    have children, and children have none (two levels).

    Raises:
        PlanError: Listing every problem found.
    """
    problems = []
    if plan.pack_sha256 != pack_sha256(pack):
        problems.append("the plan was written for a different pack")
    sampled = {s["segment_id"] for s in pack["segments"]}
    for name in PLAN_DIMENSIONS:
        seen: set[str] = set()
        for term in getattr(plan, name):
            kids = term.children if name == "categories" else ()
            if name != "categories" and term.children:
                problems.append(f"{name}: '{term.label}' can't have children")
            for t in (term, *kids):
                if t is not term and t.children:
                    problems.append(f"'{t.label}' would be a third level")
                norm = normalise_alias(t.label)
                if norm in seen:
                    problems.append(f"{name}: '{t.label}' appears twice")
                seen.add(norm)
                unknown = [s for s in t.segments if s not in sampled]
                if unknown:
                    problems.append(f"'{t.label}' cites {len(unknown)} segment(s) not in the pack")
    if problems:
        raise PlanError("; ".join(problems))


# ---------------------------------------------------------------- filing


@dataclass
class Filed:
    """What filing a plan did."""

    proposed: list[str] = field(default_factory=list)
    already_known: list[str] = field(default_factory=list)  # an approved term has it
    already_waiting: list[str] = field(default_factory=list)  # an open proposal has it
    already_rejected: list[str] = field(default_factory=list)  # a reviewer turned it down
    waiting_for_parent: int = 0  # subcategories whose category isn't approved yet


def _approved(session: Session, dimension: Dimension) -> dict[str, str]:
    """Normalised alias -> approved term ID, for one dimension."""
    rows = session.execute(
        select(TaxonomyAliasRow.norm_form, TaxonomyTermRow.term_id)
        .join(TaxonomyTermRow, TaxonomyTermRow.term_id == TaxonomyAliasRow.term_id)
        .where(
            TaxonomyTermRow.dimension == dimension.value,
            TaxonomyTermRow.status == TermStatus.APPROVED.value,
        )
    )
    return dict(rows.tuples().all())


def _labels_in(session: Session, dimension: Dimension, status: str) -> set[str]:
    """Normalised labels of ``add`` proposals in one status, for one dimension."""
    found = set()
    for row in session.scalars(
        select(TaxonomyProposalRow).where(
            TaxonomyProposalRow.status == status,
            TaxonomyProposalRow.operation == Operation.ADD.value,
        )
    ):
        payload = json.loads(row.payload_json)
        if payload.get("dimension") == dimension.value:
            found.add(normalise_alias(payload["label"]))
    return found


def _file(
    session: Session,
    term: PlanTerm,
    dimension: Dimension,
    plan: Plan,
    filed: Filed,
    parent_id: str | None = None,
) -> None:
    norm = normalise_alias(term.label)
    if norm in _approved(session, dimension):
        filed.already_known.append(term.label)
        return
    if norm in _labels_in(session, dimension, OPEN):
        filed.already_waiting.append(term.label)
        return
    # Re-running a plan never re-files what a reviewer rejected; a new plan
    # (or the owner) has to make the case again under a different label.
    if norm in _labels_in(session, dimension, "rejected"):
        filed.already_rejected.append(term.label)
        return
    payload: dict[str, Any] = {
        "dimension": dimension.value,
        "label": term.label,
        "definition": term.definition,
    }
    if term.aliases:
        payload["aliases"] = list(term.aliases)
    if parent_id is not None:
        payload["parent_id"] = parent_id
    row = propose(
        session,
        Operation.ADD,
        payload,
        proposer=plan.proposer,
        evidence={
            "source": PACK_VERSION,
            "pack_sha256": plan.pack_sha256,
            "segments": sorted(term.segments),
            "subcategories_planned": len(term.children),
        },
    )
    filed.proposed.append(row.proposal_id)


def file_plan(session: Session, plan: Plan, pack: dict[str, Any]) -> Filed:
    """File every term whose place exists, as TAX-004 proposals.

    That is every top-level term, and each subcategory whose category is
    already approved. Run it again after a review round to file the
    subcategories that were waiting. The caller commits.

    Raises:
        PlanError: See ``check_plan``. Nothing is filed then.
    """
    check_plan(plan, pack)
    filed = Filed()
    for name, dimension in PLAN_DIMENSIONS.items():
        for term in getattr(plan, name):
            _file(session, term, dimension, plan, filed)
    domain = _approved(session, Dimension.DOMAIN)
    for category in plan.categories:
        parent = domain.get(normalise_alias(category.label))
        for child in category.children:
            if parent is None:
                filed.waiting_for_parent += 1
            else:
                _file(session, child, Dimension.DOMAIN, plan, filed, parent_id=parent)
    return filed


# ---------------------------------------------------------------- review


def review_sheet(session: Session) -> list[dict[str, Any]]:
    """The open proposals a reviewer session decides on (labels, no chat text)."""
    labels = {t.term_id: t.label for t in session.scalars(select(TaxonomyTermRow))}
    sheet = []
    for row in session.scalars(
        select(TaxonomyProposalRow)
        .where(TaxonomyProposalRow.status == OPEN)
        .order_by(TaxonomyProposalRow.created_at, TaxonomyProposalRow.proposal_id)
    ):
        payload, evidence = json.loads(row.payload_json), json.loads(row.evidence_json)
        sheet.append(
            {
                "proposal_id": row.proposal_id,
                "operation": row.operation,
                "dimension": payload.get("dimension"),
                "label": payload.get("label"),
                "parent": labels.get(payload.get("parent_id", "")),
                "definition": payload.get("definition"),
                "aliases": payload.get("aliases", []),
                "segments": evidence.get("segments", []),
                "proposer": row.proposer,
            }
        )
    return sheet


class Decision(BaseModel):
    """One reviewer decision. A reason is always required."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    proposal_id: str = Field(pattern=r"^prop_[0-9a-z]+$")
    verdict: Literal["approve", "reject"]
    note: str = Field(min_length=5, max_length=500)
    label: str | None = Field(default=None, max_length=60)


class Review(BaseModel):
    """What the reviewer session writes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    reviewer: str = Field(min_length=3, max_length=80)
    decisions: tuple[Decision, ...]


@dataclass
class Applied:
    """What applying a review did. A refused decision is listed, never forced."""

    approved: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    refused: dict[str, str] = field(default_factory=dict)  # proposal ID -> why


def apply_review(session: Session, review: Review) -> Applied:
    """Apply each decision through TAX-004 (which refuses self-review).

    One decision failing (a collision, a proposal already decided) doesn't
    stop the others: it is listed in ``refused`` with the reason. The caller
    commits.
    """
    applied = Applied()
    for decision in review.decisions:
        try:
            with session.begin_nested():
                if decision.verdict == "approve":
                    approve(
                        session,
                        decision.proposal_id,
                        reviewer=review.reviewer,
                        note=decision.note,
                        label=decision.label,
                    )
                    applied.approved.append(decision.proposal_id)
                else:
                    reject(
                        session, decision.proposal_id, reviewer=review.reviewer, note=decision.note
                    )
                    applied.rejected.append(decision.proposal_id)
        except ReviewError as problem:
            applied.refused[decision.proposal_id] = str(problem)
    return applied


# ---------------------------------------------------------------- the summary for Louis


def summary_markdown(session: Session) -> str:
    """A one-page picture of the vocabulary so far, for the owner's publish decision.

    Labels and definitions only (no chat text): approved terms as a tree per
    dimension, then rejected proposals with the reviewer's reason, then
    what is still open.
    """
    terms = list(
        session.scalars(
            select(TaxonomyTermRow)
            .where(TaxonomyTermRow.status == TermStatus.APPROVED.value)
            .order_by(TaxonomyTermRow.label)
        )
    )
    lines = ["# Taxonomy so far", ""]
    titles = {
        Dimension.DOMAIN: "Categories and subcategories",
        Dimension.PURPOSE: "Activities",
        Dimension.OUTPUT: "Outputs",
        Dimension.TOPIC: "Topics",
        Dimension.KNOWLEDGE_TYPE: "Knowledge types",
    }
    for dimension, title in titles.items():
        mine = [t for t in terms if t.dimension == dimension.value]
        if not mine:
            continue
        lines += [f"## {title} ({len(mine)})", ""]
        for top in (t for t in mine if t.parent_id is None):
            lines.append(f"- **{top.label}**: {top.definition or 'no definition'}")
            for child in (t for t in mine if t.parent_id == top.term_id):
                lines.append(f"  - **{child.label}**: {child.definition or 'no definition'}")
        lines.append("")
    decided = Counter(row.status for row in session.scalars(select(TaxonomyProposalRow)))
    rejected = session.scalars(
        select(TaxonomyProposalRow)
        .where(TaxonomyProposalRow.status == "rejected")
        .order_by(TaxonomyProposalRow.proposal_id)
    )
    gone = [f"- {json.loads(r.payload_json).get('label')}: {r.decision_note}" for r in rejected]
    if gone:
        lines += [f"## Rejected ({len(gone)})", "", *gone, ""]
    lines.append(
        f"Proposals: {decided.get('approved', 0)} approved, {decided.get('rejected', 0)} "
        f"rejected, {decided.get(OPEN, 0)} still open."
    )
    return "\n".join(lines) + "\n"
