# ADR-0002: Raw input formats and read-only source handling

```yaml
id: ADR-0002
kind: architecture_decision
status: proposed
recorded_at: 2026-10-27
scope: ingestion/source-formats
supersedes: []
related_tickets: [SRC-001, ING-001, ING-004, ING-011, MED-002, OPS-008]
```

## Context
The specs assume the input is an official ChatGPT export ZIP (`conversations.json` or numbered parts). A metadata-only inspection of `raw/` on 2026-10-27 found something different (counts only, no content read into reports):

- `raw/export_manifest.json`: a manifest (version 1) describing an original export of 1,726 files (about 1.6 GB): 12 sharded `conversations-NNN.json` parts, `chat.html`, account JSON files, about 721 `.wav` audio clips, 13 `.mp4` videos and about 930 images spread over `user-*/`, `dalle-generations/`, root-level uploads and 26 per-conversation asset folders.
- `raw/conversations/`: 1,160 JSON files. 1,158 are per-conversation "split-wrapper" files (wrapper fields such as title/date/counts plus the embedded native conversation object). 2 are derived outputs from an earlier classifier attempt, not conversations.
- `raw/images/`: 913 images (png/webp/jpg/jpeg, about 1.15 GB) flattened into one folder and named by ChatGPT file ID, plus an empty `unknown_origin/` folder.
- The original sharded JSON, audio and video are **not** present in `raw/`.
- **Provenance (owner, 2026-10-27):** the split-wrapper files, flattened images and manifest were produced by an earlier extraction step run with Hermes. Not an OpenAI format, so its rules (which fields it dropped, how images were renamed, why some are missing) are undocumented and must be inferred and reported.
- In a 50-file sample, mapping nodes had `parent` but no `children`, and messages lacked several fields the official export normally carries. So the split format may have lost fields compared with the original.

## Decision (proposed)
1. Support two ChatGPT input formats behind the `SourceAdapter` port: the official export (ZIP **or** extracted folder, single or sharded JSON) and the split-wrapper directory (`chatgpt-split-v1`, ING-011). Both feed the same native mapping parser, so they yield identical logical records for identical conversations.
2. Prefer the official export as the canonical input when available. Treat the split format as a lower-fidelity adapter whose missing fields are reported, never guessed.
3. Every raw root is opened read-only. The importer never writes, renames or deletes there. A pre/post tree hash proves it (SRC-001).
4. Non-conversation JSON in a conversation folder is classified as `derived_artifact` and reported, not parsed or failed.
5. Manifest-listed files missing from disk become `missing` asset evidence (see ADR-0004), not errors and not fabricated paths.
6. JSON is streamed (e.g. an incremental parser) so a multi-hundred-MB `conversations.json` does not have to fit in memory.

## Alternatives
- Official ZIP only: simplest, but cannot import the data actually present today.
- Split format only: matches today's data but locks in a lossy, undocumented format for every future re-export.
- Convert split files back into an official-style file: invents structure and breaks provenance. Rejected.

## Consequences
- Two adapters and a cross-format equivalence test (EVAL-009 fixtures).
- Owner decision OD-01: is the original export ZIP still available to place under `raw/`?
- Owner decision OD-09: the two derived files inside `raw/conversations/` should ideally be moved out by the owner. The importer excludes them either way.
