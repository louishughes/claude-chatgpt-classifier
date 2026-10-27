# Architecture Decision Records

Format and rules: `docs/DECISIONS_AND_HISTORY.md` (Context → Decision → Alternatives → Consequences → Status → Supersedes). ADRs are append-only. A changed decision gets a new ADR with `supersedes`.

| ADR | Title | Status |
|---|---|---|
| ADR-0001 | SQLite + FTS5 for the local MVP | Recorded only as the worked example in `DECISIONS_AND_HISTORY.md`; no standalone file was found in the repository. Number reserved so the example keeps its ID. |
| [ADR-0002](0002-raw-input-formats-and-read-only-sources.md) | Raw input formats and read-only source handling | proposed |
| [ADR-0003](0003-logical-identity-and-reimport.md) | Logical identity, revisions and idempotent reimport | proposed |
| [ADR-0004](0004-media-blob-asset-occurrence.md) | Media blob / asset / occurrence model | proposed |
| [ADR-0005](0005-conversation-relationships.md) | Native branches versus cross-conversation relationships | proposed |
| [ADR-0006](0006-deterministic-link-registries.md) | Deterministic URL, YouTube and social registries; opt-in transcripts | proposed |
| [ADR-0007](0007-model-egress-and-structured-output.md) | Cloud-capable intelligence with schema-enforced output | proposed, needs owner confirmation (OD-04, OD-05) |
| [ADR-0008](0008-source-fidelity-slice-first.md) | Source-fidelity vertical slice before the semantic pipeline | proposed |

"Proposed" means written by the 2026-10-27 audit and awaiting product-owner approval. Do not treat a proposed ADR as accepted.
