"""Data for the Timeline page: how decisions moved, current state on top (UI-008).

The PRD's Timeline screen (§10) is "current state atop chronological
proposals/decisions and supersession links". The pieces already exist:

* ``reconciliation.projection.project`` says where each stated record
  (decision, rejection, requirement, preference) stands now: current,
  conflicted, pending, superseded or unknown (REC-006);
* ``reconciliation.timeline.timeline`` lists the events that moved it,
  oldest first (REC-004).

This module puts them together for one page. Records are grouped by
status, current first, then the ones needing attention, then the replaced
ones, so the top of the page is "what holds now". Each record shows its
first quote's message as a link, its events in time order, and "replaced
by" / "in conflict with" links to the other record on the same page.

Nothing is derived or written here: if ``ke timeline --build`` hasn't run,
the page shows what is stored and says so when there is nothing.

Talking points:
    - "The timeline page puts what holds now at the top and every replaced
      decision below it, each linked to the decision that replaced it."
    - "It only reads: the same projection the command line and notes use."
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from knowledge_engine.extraction.store import GateError, load
from knowledge_engine.reconciliation.projection import Status, project
from knowledge_engine.reconciliation.timeline import timeline
from knowledge_engine.taxonomy.registry import ProjectRow
from knowledge_engine.ui.registries import places

# Page order: what holds now, then what needs a look, then history.
ORDER = (Status.CURRENT, Status.CONFLICTED, Status.PENDING, Status.UNKNOWN, Status.SUPERSEDED)
WORDS = {
    Status.CURRENT: "Holds now",
    Status.CONFLICTED: "In conflict with another current record",
    Status.PENDING: "Waiting for evidence checks or review",
    Status.UNKNOWN: "Can't tell when it was said",
    Status.SUPERSEDED: "Replaced later",
}
# Event names as a sentence fragment: "<this record> <words> <other record>".
EVENT_WORDS = {
    "proposes": "proposed",
    "accepts": "accepts",
    "rejects": "rejects",
    "clarifies": "clarifies",
    "revises": "revises",
    "supersedes": "replaces",
    "contradicts": "contradicts",
    "related_to": "is related to",
    "revokes": "withdraws an event",
}


class UnknownProject(LookupError):
    """No project has this ID."""


def timeline_view(session: Session, project_id: str | None = None) -> dict[str, Any]:
    """Stated records grouped by status, each with its events. Reads only.

    Args:
        session: A read session.
        project_id: Only records naming this project, optionally.

    Raises:
        UnknownProject: ``project_id`` names no project.
    """
    label = None
    if project_id is not None:
        row = session.get(ProjectRow, project_id)
        if row is None:
            raise UnknownProject(project_id)
        label = row.name
    state = project(session, project_id=project_id)
    records = {}
    for entry in state.entries:
        try:
            records[entry.record_id] = load(session, entry.record_id)
        except GateError:  # an entry always has a record; skip rather than crash
            continue
    first_revision = {rid: r.evidence[0].revision_id for rid, r in records.items() if r.evidence}
    where = places(session, first_revision.values())
    groups = []
    for status in ORDER:
        items = []
        for entry in state.entries:
            if entry.status is not status or entry.record_id not in records:
                continue
            record = records[entry.record_id]
            events = [
                {
                    "words": EVENT_WORDS.get(event.predicate, event.predicate),
                    "outgoing": event.from_record == entry.record_id,
                    "other": event.to_record
                    if event.from_record == entry.record_id
                    else event.from_record,
                    "when": datetime.fromtimestamp(event.happened_at, UTC)
                    if event.happened_at is not None
                    else None,
                    "revoked": event.revoked,
                }
                for event in timeline(session, [entry.record_id])
                if event.predicate != "revokes"
            ]
            items.append(
                {
                    "record_id": entry.record_id,
                    "record_type": entry.record_type,
                    "assertion": record.assertion,
                    "place": where.get(first_revision.get(entry.record_id, "")),
                    "events": events,
                    "superseded_by": list(entry.superseded_by),
                    "conflicts_with": list(entry.conflicts_with),
                }
            )
        if items:
            groups.append({"status": status.value, "words": WORDS[status], "records": items})
    return {
        "project_id": project_id,
        "project_label": label,
        "groups": groups,
        "shown": set(records),
    }
