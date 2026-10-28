# Review: synthetic golden set and gold-v1 schema (EVAL-001)

- **Reviewer kind:** `ai_session`, an independent Claude session that did not write the set. The owner delegated review ("you perform the review", 2026-10-28). The set is **not owner-approved**.
- **Reviewed:** `src/knowledge_engine/evaluation/gold.py`, `tests/fixtures/gold/synthetic-v1/gold.json` and the synthetic fixture conversations they name. All content is synthetic.
- **Date:** 2026-10-28.
- **Verdict:** CHANGES_REQUESTED. All six must-fix items were applied before merge (#215).

Accuracy reports scored against this set print this file's SHA-256 as the review hash (LEG-002, REV-012).

## Must-fix items and what was done

| # | Finding | Done |
|---|---|---|
| 1 | No extraction scope: "not annotated for records" looked the same as "no records expected", and two conversations with decisions had empty `records`. | `records_annotated` flag added. Only conversations with the flag set are scored for records. |
| 2 | The `wk-u1` forbidden decision was arguable: "I'll sand it tomorrow" answers the assistant's suggestion. | Removed. |
| 3 | The `topic_segments` segment 1 started at the empty system message, which ties the key to how the segmenter treats system messages. | Changed to `shed-u1`. |
| 4 | Nothing checked that `reviewed_by` differs from `annotator`. | Validator added. |
| 5 | `write_gold` overwrote an existing file, so re-running the template would wipe an annotated private set. | Refuses to overwrite. |
| 6 | Nothing tested that committed gold files are synthetic. | Test added: committed sets must be `synthetic: true` and name only SYNTHETIC-marked fixture cases. |

## Also done

- Label IDs are checked against the set's own vocabulary.
- A primary label can't also be listed as a secondary.
- Duplicate segment starts are refused.
- `strength` was added to gold records.

## Deferred, as suggested by the reviewer

- Evidence spans in gold records.
- A record-level "ambiguous / review expected" flag.
- Supersession cases.
- "Ideally the tests run in parallel" stays a soft requirement (`strength: soft`). It could equally be a preference.
