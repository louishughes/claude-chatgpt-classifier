# ADR-0010: Purging a conversation: closure, tombstones and the append-only exception

```yaml
id: ADR-0010
kind: architecture_decision
status: proposed   # decided under delegated authority (owner, 2026-10-27 22:10 UTC); revisitable
recorded_at: 2026-10-28
scope: retention/deletion
supersedes: []     # adds the deletion workflow that ADR-0003 and DATA_MODEL §9 point to
related_tickets: [OPS-004, OPS-003, IMP-003, MED-003, YTB-002, SOC-002, DOC-006, RET-004]
issue: "#122 (OPS-004)"
```

## Context

Evidence is immutable and several tables are append-only by trigger (review logs, timeline events, document builds). DATA_MODEL §9 and DECISIONS_AND_HISTORY still require that a lawful deletion removes a source and every derivative "without retaining deleted personal content". ADR-0003 says a chat missing from a new export is `not_seen`, never deleted, so deletion has to be its own explicit operation. Because the owner re-imports his *whole* history, a deleted chat is still in every later export.

## Decision

1. **Unit.** A purge removes whole conversations (by `conv_` or native ID), never single messages.
2. **Closure.** Everything derived from the chat goes (the list is in `retention/purge.py`). Things shared with kept chats stay: an image, link target, video (with transcript) or social account is deleted only when no kept chat still refers to it.
3. **Plan, then confirm.** `ke purge plan` reads only and prints counts plus a 12-character token. `ke purge run` needs that token and a reason. If anything changed in between, the token no longer matches and nothing is deleted.
4. **One transaction.** The rows go in one transaction. The append-only triggers on the touched tables are dropped and re-created inside that transaction. This is the only sanctioned exception to append-only, and a crash leaves the triggers in place.
5. **Archived export files go whole.** The archived copy of every export file that held the chat is deleted, even though it also holds other chats. Their messages stay in the database; only the original-file copy is gone (the plan counts how many chats that affects). The alternative, rewriting a redacted copy, would create a "source" file that never existed.
6. **Tombstones.** A SHA-256 of each purged conversation ID and the SHA-256 of each purged export file are kept. A later import skips the chat (counted as `purged`) and does not re-archive the file. A tombstone can't be read back into anything.
7. **Audit log.** `purge_events` keeps who, why, when, counts and the check result, never the text. It refuses deletes.
8. **Prove it.** Short passages of the chat's own text are held in memory as probes (they are never written anywhere). After `VACUUM` and a WAL checkpoint, and after the indexes are rebuilt, the check requires: searching each probe finds none of the purged revisions, the database file's bytes don't contain them, no table names a purged ID (a kept chat's own text that mentions it is reported separately), every planned file is gone, and, when a vault is given, no note holds a probe and none of the engine's image copies remain.
9. **Not reachable.** The engine does not touch the original export in `raw/`, images kept by reference there, or older backups. The plan and result count these so the person can deal with them.

## Alternatives

- **Soft delete (a hidden flag).** Rejected: it keeps the personal content, which §9 forbids.
- **Rewrite the export file without the chat.** Rejected for now (see point 5). It can be revisited if keeping the other chats' original files matters more.
- **Cascade foreign keys.** Rejected: most links are IDs inside JSON or across tables without foreign keys, so an explicit closure plus a scan for leftovers is the only check that covers them.

## Consequences

- Re-importing after a purge never restores the chat, even from the same file.
- After a purge, chats that shared an export file with it have no archived original file. Backups made before the purge still have it.
- A purge on the owner's real data needs his explicit go-ahead. Building and testing it on synthetic data does not.

## Status

Proposed, decided under delegated authority (2026-10-27 22:10 UTC). Revisitable by the owner.
