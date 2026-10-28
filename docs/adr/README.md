# Architecture Decision Records

Format and rules: `docs/DECISIONS_AND_HISTORY.md` (Context → Decision → Alternatives → Consequences → Status → Supersedes). ADRs are append-only. A changed decision gets a new ADR with `supersedes`.

| ADR | Title | Status |
|---|---|---|
| ADR-0001 | SQLite + FTS5 for the local MVP | Recorded only as the worked example in `DECISIONS_AND_HISTORY.md`; no standalone file was found in the repository. Number reserved so the example keeps its ID. |
| [ADR-0002](0002-raw-input-formats-and-read-only-sources.md) | Raw input formats and read-only source handling | accepted (owner authority 2026-10-27 22:10; revisitable) |
| [ADR-0003](0003-logical-identity-and-reimport.md) | Logical identity, revisions and idempotent reimport | accepted (owner authority 2026-10-27 22:10; revisitable) |
| [ADR-0004](0004-media-blob-asset-occurrence.md) | Media blob / asset / occurrence model | accepted (owner authority 2026-10-27 22:10; revisitable) |
| [ADR-0005](0005-conversation-relationships.md) | Native branches versus cross-conversation relationships | accepted (owner authority 2026-10-27 22:10; revisitable) |
| [ADR-0006](0006-deterministic-link-registries.md) | Deterministic URL, YouTube and social registries; opt-in transcripts | accepted (owner authority 2026-10-27 22:10; revisitable) |
| [ADR-0007](0007-model-egress-and-structured-output.md) | Cloud-capable intelligence with schema-enforced output | accepted (owner authority 2026-10-27 22:10; revisitable). Provider/egress detail still open: OD-04, OD-05, ADR-0009 |
| [ADR-0008](0008-source-fidelity-slice-first.md) | Source-fidelity vertical slice before the semantic pipeline | accepted (owner authority 2026-10-27 22:10; revisitable) |
| [ADR-0009](0009-model-step-without-paid-api.md) | The model step without paid API calls (batch file in, batch file out) | proposed (decided under delegated authority 2026-10-27 22:10, revisitable); refines ADR-0007 §3–5 and §9 while the no-paid-API rule holds |
| [ADR-0010](0010-purge-closure-and-tombstones.md) | Purging a conversation: closure, tombstones and the append-only exception | proposed (decided under delegated authority 2026-10-27 22:10, revisitable); using it on real data needs the owner's go-ahead |
| [ADR-0011](0011-tenant-isolation-by-folder.md) | Separate workspaces are separate folders, not filtered rows | proposed (decided under delegated authority 2026-10-27 22:10, revisitable) |

ADR-0002..0008 were written by the 2026-10-27 audit as "proposed". M1 code is already built on them, so they were accepted under the owner's delegated authority (blanket authority given 2026-10-27 22:10 UTC; REV-006, #140). This is revisitable: the owner can reverse any of them, and a change still goes through a new ADR with `supersedes`. A future ADR marked "proposed" is not accepted until the owner (or an explicit delegation) accepts it.
