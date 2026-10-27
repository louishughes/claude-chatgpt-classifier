# ADR-0008: Source-fidelity vertical slice before the semantic pipeline

```yaml
id: ADR-0008
kind: architecture_decision
status: accepted   # delegated owner authority 2026-10-27 22:10 UTC; revisitable (REV-006)
recorded_at: 2026-10-27
scope: roadmap/sequencing
supersedes: []
related_tickets: [DOC-002, BRW-001, EVAL-010, IMP-005]
```

## Context
In the original backlog nothing is browsable until `DOC-001`, which waits for the reconciliation projector (`REC-006`), i.e. the whole LLM pipeline. `DOC-002` (a generic Markdown/YAML writer) depended on `DOC-001` for no technical reason. The owner requires the first slice to prove read-only raw import, provenance, branch graph, images, reimport idempotency and source browsing before any LLM work, and wants batch tests at 50 and 100 conversations early.

## Decision (proposed)
- Milestone M1 (gate G1) ends with `BRW-001` (LLM-free source transcript notes and inspect views) and `EVAL-010` (50/100 batch smoke).
- `DOC-002` now depends on `FND-005` instead of `DOC-001`.
- Milestone M2 (gate G2) adds link, YouTube, social and structural-relationship registries, still LLM-free.
- The semantic pipeline (M3) starts only after G1 and G2 pass, and its first gate includes EVAL-011 (50/100 batch smoke with fake then real provider).

## Alternatives
Keep the original order: knowledge first, browsing last. Rejected because import bugs would only surface after money was spent on model calls.

## Consequences
Phase/ticket order in `ROADMAP_AND_TICKETS.md` is annotated; execution order lives in `docs/plans/`.
