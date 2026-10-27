# ADR-0003: Logical identity, revisions and idempotent reimport

```yaml
id: ADR-0003
kind: architecture_decision
status: accepted   # delegated owner authority 2026-10-27 22:10 UTC; revisitable (REV-006)
recorded_at: 2026-10-27
scope: domain/identity
supersedes: []
related_tickets: [FND-005, IMP-001, IMP-002, IMP-003, IMP-004, IMP-005, IMP-006, NRM-001]
```

## Context
The owner will re-export the entire ChatGPT history periodically. Each export repeats nearly everything. The current data model keys `content_nodes` by `snapshot_id` and has one `import_runs` table, so a second export would create a second copy of every message unless something sits above the snapshot. There is no account namespace, no message revision concept, no delta categories and no rule for conversations missing from a later export.

## Decision (proposed)
Separate six identities:

| Identity | Key | Changes when |
|---|---|---|
| ImportBatch | random ID per attempt | every run, including failed and repeated runs |
| SourceSnapshot | SHA-256 of file bytes | file bytes change |
| Conversation (logical) | `(workspace, source_system, account_ns, native_conversation_id)` | never; title edits don't matter |
| MessageNode (logical) | `(conversation_id, native_node_id)` | never |
| MessageRevision | `(node_id, canonical_content_hash)` | role, content parts or create_time change |
| GraphEdge | `(child_node_id, parent_node_id)` | a node's parent changes (flagged anomaly) |

- Two hashes per message: `raw_payload_hash` (full JSON, sorted keys) records exactly what the export said. `canonical_content_hash` (role + content parts + create_time) decides whether derived work must be redone. Cosmetic metadata drift between exports creates a new raw observation but no reprocessing and no model calls.
- Delta categories per import: `new`, `unchanged`, `revised`, `new_branch`, `not_seen`, `candidate_duplicate`, `failed`.
- `not_seen` (present before, absent now) means **unknown**, never deleted. Deletion is the separate, audited OPS-004 operation.
- Missing or colliding native IDs never trigger an automatic merge. They create a `candidate_match` with `review_required` and the evidence (hashes, positions). Title, timestamp, embedding similarity and image resemblance are never identity.
- Imports commit in batches inside transactions, with DB unique constraints on logical keys, idempotency keys per stage and a single-writer import lock. An interrupted batch resumes from the last committed checkpoint.
- Reviewer corrections anchor to logical ID + revision. They survive unchanged reimports and become review items when the content they refer to changes (IMP-006).

## Alternatives
- Snapshot-only identity (current spec): simple, but duplicates everything on re-export. Rejected.
- Content-hash-only message identity: breaks when a message is edited, and merges identical short messages ("yes") across conversations. Rejected.
- Single hash: either reprocesses on cosmetic drift or misses real edits. Rejected in favour of two hashes.

## Consequences
New tables (see `DATA_MODEL_AND_CONTRACTS.md` §10), an import lock and property tests for repeated and concurrent imports. Owner decision OD-03: what to use as the account namespace when the split format carries no account ID (recommended: a configured label per raw root).
