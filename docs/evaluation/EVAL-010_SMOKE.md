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

## Real data (passed, 2026-10-28, Louis's PC, Windows)

The real-data half ran read-only on `raw/` in a Remote Control session on Louis's PC. It ran on `main` at d878333, with Python 3.13.2 and outputs in the git-ignored `workspace\rev009\`. Nothing was committed from the PC.

| Run | Import | Re-import | Render | Peak memory | Warnings | All checks |
|---|---|---|---|---|---|---|
| 50 conversations | 409.8 s | 856.1 s | 23.2 s | not measured on Windows | `format_lacks_account_id` ×1, `non_conversation_file_skipped` ×2 | passed |
| 100 conversations | 489.3 s | 864.6 s | 14.8 s | not measured on Windows | same | passed |

Every check passed in both runs: `all_rendered`, `no_broken_embeds`, `raw_unchanged`, `reconciled`, `reimport_adds_nothing`, `reimport_all_unchanged` and `zero_model_calls`. stderr was empty. The `raw/` folder holds 2,074 files and none was modified.

Spot checks with `ke inspect` covered three conversations: the largest (45 nodes) and two smaller ones. All three have zero graph issues and one regeneration branch each, with the system node off the active path. Message counts are consistent: messages = nodes − 1, and the active path is one shorter than that. None had images, so image states on real data are still unchecked in `inspect`. The import report counts them.

Found and filed as follow-ups (they don't fail the gate):
- **Speed.** Time barely grows with the number of conversations (50 → 100 adds about 80 s), and a re-import takes about twice as long as the first import. Something done once per run over the whole `raw/` tree dominates, probably hashing all files including about 900 images, and the re-import does it again.
- **Peak memory** is `null` on Windows, because the measurement uses the Unix-only `resource` module. *Fixed in OPS-009: Windows reads `PeakWorkingSetSize` through `ctypes`; a platform with neither says `"unavailable_on_platform"`.*
- **`ke inspect`** prints the full native conversation ID. Reports elsewhere use 8-character prefixes. *Fixed in OPS-009: the rule is that `inspect` stays complete (a local debugging tool) and anything quoted in a report or checklist uses `ke inspect <id> --redact`, which prints the prefix. The G1 demonstration in `IMPLEMENTATION_PLAN.md` §6 now uses `--redact`.*

## Import timing by phase (PERF-001, 2026-10-28)

On Louis's PC a `--limit 50` import took 410 s and the re-import 856 s. Doubling the conversations added only 80 s, so the time went on work done once per run over the whole raw tree.

**Cause.** Every source file in the export is archived on every run, whatever `--limit` says (the snapshot is of the whole export). For a file already stored, the archive still wrote a temporary copy, fsynced it, hashed the stored copy, deleted the temporary copy, and then the ledger hashed the stored copy a second time. On Windows each new file is also scanned by the antivirus, so those throwaway writes were the expensive part, and a re-import paid them on top of the reads.

**Fix.** Bytes already in the store are hashed once from the source and the stored copy is checked once; nothing is written. Small files (up to 16 MB) are read once into memory. New bytes are stored exactly as before (temporary file, fsync, atomic rename, read-only). The `raw_unchanged` check and the check of every stored copy that is reused are unchanged.

**Measured** with `python -m knowledge_engine.evaluation.import_timing` (synthetic split export: 1,100 chats, 2,215 files, 900 unused noise images; `--limit 50`; the same tree imported twice into a fresh workspace). Linux, this container:

| Phase (seconds) | Import before | Re-import before | Import after | Re-import after |
|---|---|---|---|---|
| Total | 8.85 | 7.47 | 9.42 | **5.79** |
| Raw tree fingerprint (before and after) | 0.38 | 0.37 | 0.38 | 0.37 |
| List the export | 0.37 | 0.36 | 0.37 | 0.36 |
| Archive source files | 4.51 | 4.97 | 4.79 | 3.13 |
| … of which fsync | 0.90 | 0.89 | 1.12 | **0.00** |
| Conversations and messages | 2.4 | 1.6 | 2.37 | 1.59 |
| Images, links, related chats, search | 0.6 | 0.1 | 0.58 | 0.06 |

A re-import is now faster than the first import, and does no writes to the archive. The Windows run of the same command is recorded below when it is done; the Linux container has no antivirus, so it understates the gain there.

Still per-run by design: hashing each source file once (needed to know whether it changed) and the before/after tree fingerprint (the `raw_unchanged` proof).

## Link, YouTube and social counts (EVAL-010c, Gate G2)

`ke eval links [--limit 100]` counts what the M2 registries stored for the first N chats (by native ID, the same batch `ke eval semantic --limit` takes). It reads only, makes no model calls and prints no URL, handle or text:

- `links`: occurrences, chats with links, distinct targets by kind, occurrences by origin (message text or citation metadata);
- `youtube`: mentions, distinct videos, mentions with a timestamp or a playlist, transcript status per video;
- `social`: mentions by resolution (`resolved`, `ambiguous`, `rejected`), distinct accounts by platform and identity status, and how many distinct bare @names were left ambiguous instead of being guessed.

```
ke --json eval links --limit 100
```

Two URL forms of one video (`youtu.be/…` and `watch?v=…&t=42`) are two link targets but one video: the link registry keeps each URL as written, and the video registry deduplicates by video ID.

**Real 100 chats:** not run yet. It runs on Louis's PC against the imported workspace, and the counts go here.
