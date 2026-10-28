"""Taxonomy health and review reports (TAX-008).

A vocabulary drifts as people add to it: two terms come to mean the same
thing, a parent gets retired and leaves its children hanging, a proposal
waits for weeks. ``governance_report`` reads the vocabulary tables and lists
those problems so a reviewer can fix them **through the normal review
workflow**. The report itself changes nothing.

What it checks:

* **duplicates**: one spelling (a label or an alias, normalised) used by
  more than one live term in the same dimension, or by more than one live
  project. Live means proposed or approved. The alias tables refuse an
  exact repeat, so this mostly catches labels that never got an alias row.
* **near duplicates**: spellings that differ only by spaces or a plural
  "s" ("Game Engine" and "Gameengines"). Listed for a reviewer, never
  merged here.
* **cross-scope spellings**: one spelling used in two places (a topic and a
  project, say). Allowed, but it makes alias matching ambiguous, so it is
  listed for a look.
* **parent problems**: a parent that is missing, in another dimension, not
  approved while the child is, part of a loop, or making the tree deeper
  than two levels. The registry API prevents most of these; rows written by
  hand or by an old version may still have them.
* **merge problems**: a merged term or project whose ``merged_into`` is
  missing, is itself not approved, or loops back.
* **orphans**: an approved term with an unusable parent (a subset of the
  parent problems, counted separately because it changes classification).
* **proposals**: open proposals by operation, with the oldest first, and
  each reviewer's approved and rejected counts. A decision where the
  reviewer is the proposer is flagged (the API refuses it; old rows might
  not).

Talking points:
    - "The report only reads. Every fix still goes through a proposal and a
      second person."
    - "Problems are listed by ID, never by guessing what the user meant."
"""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from knowledge_engine.taxonomy.registry import (
    ProjectAliasRow,
    ProjectRow,
    TaxonomyAliasRow,
    TaxonomyProposalRow,
    TaxonomyTermRow,
    TermStatus,
    normalise_alias,
)
from knowledge_engine.taxonomy.review import APPROVED, OPEN, REJECTED

REPORT_VERSION = "tax-008-v1"
# The registry allows a parent and its children: two levels (TAX-002).
MAX_DEPTH = 2
_LIVE = {TermStatus.PROPOSED.value, TermStatus.APPROVED.value}


@dataclass(frozen=True)
class Issue:
    """One problem found.

    Attributes:
        kind: e.g. ``duplicate``, ``parent_cycle``, ``orphan``.
        ids: The term, project or proposal IDs involved, sorted.
        detail: A short plain explanation (IDs and spellings only).
    """

    kind: str
    ids: tuple[str, ...]
    detail: str


@dataclass
class GovernanceReport:
    """Everything one report run found.

    Attributes:
        issues: Problems, sorted by kind then IDs.
        open_proposals: Open proposal count by operation.
        oldest_open: Open proposal IDs, oldest first (at most 20).
        reviewers: Reviewer -> {"approved": n, "rejected": n}.
        terms: Term count by status.
        projects: Project count by status.
    """

    version: str = REPORT_VERSION
    issues: list[Issue] = field(default_factory=list)
    open_proposals: dict[str, int] = field(default_factory=dict)
    oldest_open: list[str] = field(default_factory=list)
    reviewers: dict[str, dict[str, int]] = field(default_factory=dict)
    terms: dict[str, int] = field(default_factory=dict)
    projects: dict[str, int] = field(default_factory=dict)

    def kinds(self) -> Counter[str]:
        """How many issues of each kind."""
        return Counter(issue.kind for issue in self.issues)


def governance_report(session: Session) -> GovernanceReport:
    """Read the vocabulary tables and list problems and review activity.

    Args:
        session: Read only; nothing is written.

    Returns:
        The report. An empty ``issues`` list means nothing was found.
    """
    terms = {row.term_id: row for row in session.scalars(select(TaxonomyTermRow))}
    projects = {row.project_id: row for row in session.scalars(select(ProjectRow))}
    report = GovernanceReport(
        terms=dict(sorted(Counter(t.status for t in terms.values()).items())),
        projects=dict(sorted(Counter(p.status for p in projects.values()).items())),
    )
    issues = report.issues
    issues += _spelling_issues(session, terms, projects)
    issues += _parent_issues(terms)
    issues += _merge_issues({k: v.merged_into for k, v in terms.items()}, terms, "term")
    issues += _merge_issues({k: v.merged_into for k, v in projects.items()}, projects, "project")
    _proposal_activity(session, report)
    issues.sort(key=lambda issue: (issue.kind, issue.ids))
    return report


def _spelling_issues(
    session: Session, terms: dict[str, TaxonomyTermRow], projects: dict[str, ProjectRow]
) -> list[Issue]:
    # norm form -> scope -> IDs. A label counts as a spelling too.
    owners: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for term in terms.values():
        if term.status in _LIVE:
            owners[normalise_alias(term.label)][term.dimension].add(term.term_id)
    for alias in session.scalars(select(TaxonomyAliasRow)):
        term_row = terms.get(alias.term_id)
        if term_row is not None and term_row.status in _LIVE:
            owners[alias.norm_form][alias.dimension].add(alias.term_id)
    for project in projects.values():
        if project.status in _LIVE:
            owners[normalise_alias(project.name)]["project"].add(project.project_id)
    for palias in session.scalars(select(ProjectAliasRow)):
        project_row = projects.get(palias.project_id)
        if project_row is not None and project_row.status in _LIVE:
            owners[palias.norm_form]["project"].add(palias.project_id)
    found = []
    loose: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for norm, scopes in sorted(owners.items()):
        if not norm:
            continue
        for scope, ids in sorted(scopes.items()):
            loose[_loose(norm)][scope].update(ids)
            if len(ids) > 1:
                found.append(
                    Issue("duplicate", tuple(sorted(ids)), f"'{norm}' names {len(ids)} in {scope}")
                )
        if len(scopes) > 1:
            every = sorted({i for ids in scopes.values() for i in ids})
            found.append(
                Issue("cross_scope", tuple(every), f"'{norm}' used in {', '.join(sorted(scopes))}")
            )
    exact = {issue.ids for issue in found}
    for key, scopes in sorted(loose.items()):
        for scope, ids in sorted(scopes.items()):
            if len(ids) > 1 and tuple(sorted(ids)) not in exact:
                found.append(
                    Issue(
                        "near_duplicate",
                        tuple(sorted(ids)),
                        f"spellings alike once spaces and plurals are ignored ({key}) in {scope}",
                    )
                )
    return found


def _loose(norm: str) -> str:
    # "game engines" and "gameengine" share the key "gameengine".
    return "".join(
        word[:-1] if len(word) > 3 and word.endswith("s") else word for word in norm.split()
    )


def _parent_issues(terms: dict[str, TaxonomyTermRow]) -> list[Issue]:
    found = []
    reported_cycles: set[tuple[str, ...]] = set()
    for term_id, term in sorted(terms.items()):
        if term.parent_id is None or term.status not in _LIVE:
            continue
        parent = terms.get(term.parent_id)
        approved = term.status == TermStatus.APPROVED.value
        if parent is None:
            found.append(Issue("parent_missing", (term_id,), f"parent {term.parent_id} not found"))
            if approved:
                found.append(Issue("orphan", (term_id,), "approved term with missing parent"))
            continue
        if parent.dimension != term.dimension:
            found.append(
                Issue(
                    "parent_dimension",
                    tuple(sorted((term_id, parent.term_id))),
                    f"child in {term.dimension}, parent in {parent.dimension}",
                )
            )
        if approved and parent.status != TermStatus.APPROVED.value:
            found.append(
                Issue(
                    "orphan",
                    tuple(sorted((term_id, parent.term_id))),
                    f"approved term whose parent is {parent.status}",
                )
            )
        chain = [term_id]
        cursor: TaxonomyTermRow | None = parent
        while cursor is not None and cursor.term_id not in chain:
            chain.append(cursor.term_id)
            cursor = terms.get(cursor.parent_id) if cursor.parent_id else None
        if cursor is not None:  # walked back onto the chain: a loop
            loop = tuple(sorted(chain[chain.index(cursor.term_id) :]))
            if loop not in reported_cycles:
                reported_cycles.add(loop)
                found.append(Issue("parent_cycle", loop, f"{len(loop)} term(s) in a parent loop"))
        elif len(chain) > MAX_DEPTH:
            found.append(
                Issue("too_deep", (term_id,), f"{len(chain)} levels (at most {MAX_DEPTH})")
            )
    return found


def _merge_issues(
    targets: dict[str, str | None],
    rows: dict[str, TaxonomyTermRow] | dict[str, ProjectRow],
    what: str,
) -> list[Issue]:
    found = []
    for item_id, target in sorted(targets.items()):
        status = rows[item_id].status
        if status != TermStatus.MERGED.value:
            continue
        if target is None or target not in rows:
            found.append(Issue("merge_target", (item_id,), f"merged {what} has no target"))
            continue
        seen = [item_id]
        cursor: str | None = target
        while cursor is not None and cursor not in seen:
            seen.append(cursor)
            cursor = targets.get(cursor)
        if cursor is not None:
            found.append(Issue("merge_cycle", tuple(sorted(seen)), f"{what} merges loop back"))
        elif rows[seen[-1]].status != TermStatus.APPROVED.value:
            found.append(
                Issue(
                    "merge_target",
                    tuple(sorted((item_id, seen[-1]))),
                    f"merged {what} ends at a {rows[seen[-1]].status} {what}",
                )
            )
    return found


def _proposal_activity(session: Session, report: GovernanceReport) -> None:
    rows = list(
        session.scalars(
            select(TaxonomyProposalRow).order_by(
                TaxonomyProposalRow.created_at, TaxonomyProposalRow.proposal_id
            )
        )
    )
    open_rows = [row for row in rows if row.status == OPEN]
    report.open_proposals = dict(sorted(Counter(row.operation for row in open_rows).items()))
    report.oldest_open = [row.proposal_id for row in open_rows[:20]]
    reviewers: dict[str, dict[str, int]] = defaultdict(lambda: {APPROVED: 0, REJECTED: 0})
    for row in rows:
        if row.status in (APPROVED, REJECTED) and row.reviewer:
            reviewers[row.reviewer][row.status] += 1
            if row.reviewer.casefold() == row.proposer.casefold():
                report.issues.append(
                    Issue("self_review", (row.proposal_id,), "decided by its own proposer")
                )
    report.reviewers = dict(sorted(reviewers.items()))
