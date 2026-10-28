# ADR-0011: Separate workspaces are separate folders, not filtered rows

```yaml
id: ADR-0011
kind: architecture_decision
status: proposed   # decided under delegated authority (owner, 2026-10-27 22:10 UTC); revisitable
recorded_at: 2026-10-28
scope: multi-user / tenancy
supersedes: []
related_tickets: [PROD-002, PROD-003, PROD-004, PROD-001]
issue: "#128 (PROD-003)"
```

## Context

PROD-003 asks for zero cross-workspace exposure through SQL, the word index, the meaning index, the graph, caches, answers, exports and deletion. Every record has a workspace ID in the import tables (TR-05), but about 50 derived tables (segments, classifications, knowledge records, links, timelines, document builds...) key off the conversation instead, and the search indexes are per-folder SQLite files. One database shared by several people would need a `workspace_id` filter added to, and kept on, every query in every module, and one forgotten filter is a leak.

## Decision

1. **One folder per workspace.** With `tenants_root` set, the API serves workspaces from `<tenants_root>/workspaces/<name>/`. Each is an ordinary, complete workspace (database, archive, word and meaning indexes, exports, logs), exactly what one person's engine already uses.
2. **The request picks the folder, once.** The `X-KE-Workspace` header names it; `get_settings` turns it into that folder's settings, and every other dependency (database, indexes, provider batch folder, import and export jobs) is built from those settings. No endpoint or query takes a workspace argument, so none can forget it.
3. **Accounts live in each workspace's database** (PROD-002 tables). A token from one workspace is unknown in another (401). An unknown workspace name gets the same 401 as a bad token, so names can't be probed. In this mode, a workspace with no accounts lets nobody in.
4. **Imports only from the workspace's inbox**, `<tenants_root>/inbox/<name>/`. Paths are resolved first, so `..`, absolute paths and links leading out are refused before the disk is checked.
5. **Deletion is per folder.** A purge opens only that folder's database and files. Deleting a whole workspace is deleting its folder (PROD-004 owns the procedure).
6. **One person's engine is unchanged.** Without `tenants_root`, nothing here applies.

## Alternatives

- **Shared database with `workspace_id` everywhere.** Rejected for now: a schema change to ~50 tables and a filter in every query, with isolation depending on none being missed. Better density for many tiny tenants, but this project has a handful of people at most.
- **PostgreSQL row-level security** (with PROD-001's backend). Strong, but only on PostgreSQL, and the word and meaning indexes are SQLite cache files outside it.

## Consequences

- Isolation is checked by `tests/integration/test_tenant_isolation.py`: an adversarial second user probes every endpoint, and the first workspace's folder must stay byte-for-byte unchanged.
- The taxonomy is per workspace too, so "one shared vocabulary" holds within a workspace, not across people. Sharing a vocabulary between workspaces would be a later, explicit copy.
- Cross-workspace features (an admin seeing all workspaces) would have to open several folders on purpose.
- Many tenants means many small SQLite files; at hosted scale the PostgreSQL option (PROD-001) would need its own isolation design (one database per tenant is the natural fit).
