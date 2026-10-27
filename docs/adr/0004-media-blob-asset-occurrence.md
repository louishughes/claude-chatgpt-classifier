# ADR-0004: Media blob / asset / occurrence model

```yaml
id: ADR-0004
kind: architecture_decision
status: proposed
recorded_at: 2026-10-27
scope: domain/media
supersedes: []
related_tickets: [MED-001, MED-002, MED-003, MED-004, BRW-001, EXT-005, OPS-004]
```

## Context
`node_assets` (node_id + asset_id, available/missing) mixes "the file" with "this message referenced it". The owner requires that the same image used by several messages is stored once while every message link survives, that missing assets are shown honestly, and that thumbnails/derived metadata stay separate from originals. Real data uses `file-service://` and `sediment://` pointers; in a 50-file sample 26 of 29 image pointers matched a file in `raw/images/` by file-ID prefix and 3 did not.

## Decision (proposed)
Four records:
- **MediaBlob**: bytes identified by SHA-256; storage mode `copy` (into the private workspace store) or `reference` (hash-verified path into `raw/`).
- **MediaAsset**: the logical asset, keyed by native file ID when present, otherwise by blob hash; links to zero or one blob.
- **AssetOccurrence**: one per (message revision, content part index, pointer). Carries the original pointer string, declared size/dimensions from the export, and an availability state: `available`, `missing` (known reference, no bytes), `unresolved` (pointer scheme or ID not matched), `ambiguous` (several candidate files), `unsupported`.
- **DerivedMediaArtifact**: thumbnails and header metadata, never a substitute for the original.

No OCR, computer vision, face recognition or cloud upload of images by default (see ADR-0007).

## Alternatives
- One row per file with a list of message IDs: loses part-level position and per-occurrence state.
- Deduplicate by perceptual hash: merges different images that look alike. Rejected; byte hash only.

## Consequences
Obsidian embeds point to a vault-safe path for available blobs, and a visible "missing" marker naming the pointer and reason otherwise (MED-004). Owner decision OD-14: copy media into the vault or link to a stable store.
