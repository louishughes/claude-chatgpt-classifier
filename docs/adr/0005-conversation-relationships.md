# ADR-0005: Native branches versus cross-conversation relationships

```yaml
id: ADR-0005
kind: architecture_decision
status: accepted   # delegated owner authority 2026-10-27 22:10 UTC; revisitable (REV-006)
recorded_at: 2026-10-27
scope: domain/relationships
supersedes: []
related_tickets: [REL-001, REL-002, REL-003, REL-004, REC-002, DOC-003]
```

## Context
Two different things get called "related": branches inside one conversation (edits and regenerations, native to the export) and links between separate conversations (continuations, manual forks, shared projects, similarity). The specs model the first only as `active_leaf_id` + node list and the second only as record-level `relationships`.

## Decision (proposed)
- **Native branches (REL-001):** the message graph is stored whole. Children are derived from parent links when the export omits them. The active path comes from `current_node`. Each fork point is classified: `edit` (sibling user messages), `regeneration` (sibling assistant messages) or `other`. Nothing ever splices sibling branches into one transcript.
- **Cross-conversation relationships (REL-002..004):** a separate `conversation_relationships` table with `kind` (`continues`, `forked_from`, `quotes`, `references`, `related_to`, `same_project`), direction, `evidence_class` (`native`, `structural`, `lexical`, `semantic`, `human`), confidence, `review_state` (`candidate`, `accepted`, `rejected`, `superseded`) and an append-only review history.
- Deterministic detectors first: shared native IDs, identical message-prefix hashes (a likely manual fork), ChatGPT conversation/share URLs and verbatim quotations. Semantic and project similarity come later (REL-003) and can only produce `related_to`/`same_project` candidates.
- `continues` and `forked_from` are never accepted from similarity alone. Without native evidence they stay `review_required`.
- Nothing is ever merged or deleted because two conversations look alike.

## Alternatives
- Reuse record-level `relationships`: mixes knowledge claims with source topology. Rejected.
- Auto-accept prefix-hash forks: tempting, but a shared opening prompt is not proof of a fork. Kept as a candidate (OD-12).

## Consequences
Notes and retrieval show related chats with kind, direction and evidence (REL-004). Rejections are kept, so a rejected link is not re-proposed on every import.
