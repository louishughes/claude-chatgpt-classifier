# EVAL-010 batch smoke test

The smoke test runs the whole M1 path on a batch: import, an identical re-import, and rendering every conversation as a source transcript note. It records counts, timings and warning codes only, with no titles, text or file names.

```
ke eval smoke --synthetic 50 [--seed 1]     # generated batch
ke eval smoke <export folder or ZIP> --limit 50   # first 50 conversations of a real export (read-only)
```

Each run uses a fresh scratch workspace under `<workspace>/smoke/` and writes its full report there as JSON. It passes only if every check holds:

| Check | Meaning |
|---|---|
| `reimport_adds_nothing` | Every logical table has the same row count after the second import |
| `reimport_all_unchanged` | The second import reports every conversation as `unchanged` |
| `zero_model_calls` | Neither import calls a model |
| `all_rendered` | One transcript note per stored conversation |
| `no_broken_embeds` | The link checker finds every image embed's file in the vault |
| `raw_unchanged` | The source's tree fingerprint is the same before and after |
| `reconciled` | ING-007's source-vs-stored counts agree |

## Synthetic results (2026-10-28, Linux container, seed 1, split layout)

| Batch | Import | Re-import | Render | Peak memory | Warnings | Result |
|---|---|---|---|---|---|---|
| 50 conversations | 1.52 s | 1.01 s | 0.24 s | 74.5 MB | `format_lacks_account_id` ×1 | passed |
| 100 conversations | 2.74 s | 1.90 s | 0.48 s | 76.1 MB | `format_lacks_account_id` ×1 | passed |

The generated batches include edits, regenerations, reused images and missing images. Missing images render as markers, so they don't count as broken embeds.

## Real data (pending)

The real-data half (50 and 100 conversations from `raw/`, read-only) runs on Louis's PC as part of the REV-009 checkpoint (#143): `ke eval smoke raw --limit 50` and `--limit 100`, with outputs only in the git-ignored workspace. It has not been run yet. Until it has, EVAL-010 (#39) stays open.
