# Review: real golden set `golden-v1` (EVAL-001)

- **Reviewer kind:** `ai_session`. The reviewer was an independent Claude session (`gold-reviewer-b`) that did not write the set. The owner delegated review ("you perform the review", 2026-10-28). The set is **not owner-approved**.
- **Annotator:** `gold-annotator-a`, an independent Claude session. It ran on a different model from the reviewer and from the session that ran the import, the checks and this record. That session labelled nothing.
- **Models:** the model each role used is in the private provenance file next to the set (`<workspace>/gold/PROVENANCE.md`). Model names aren't committed.
- **Date:** 2026-10-28.
- **Set file:** `<workspace>/gold/golden-v1.json`. It is private and never in Git. SHA-256 `b63a7260d849eeb7de8528efc659ecc3df5b981835eef4fcccb51d4d1d6a0b3d`.
- **Verdict:** CHANGES_REQUESTED. All the reviewer's changes were applied before the set was written.

Accuracy reports scored against this set print this file's SHA-256 as the review hash (LEG-002, REV-012).

## What the set covers

| | Count |
|---|---|
| Conversations (seeded template, `--count 40 --seed golden-v1`) | 40 |
| Conversations with `records_annotated: true` | 40 |
| Records that must be found | 398 |
| Forbidden records | 64 |
| Segments with labels | 0 |
| Conversations with `reviewed_by` set (`gold-reviewer-b`) | 40 |

The 398 records break down by type and holder like this:

| Type / holder | n |
|---|---|
| requirement / user | 60 |
| proposal / assistant | 56 |
| reference / assistant, user, tool | 55, 27, 2 |
| artefact / assistant, tool | 75, 1 |
| idea / assistant, user | 31, 6 |
| rejection / user | 22 |
| fact / user, assistant | 16, 5 |
| decision / user | 12 |
| preference / user | 11 |
| recommendation / assistant | 9 |
| action / assistant | 7 |
| question / assistant, user | 2, 1 |

There are 56 assistant proposals but only 12 user decisions. That gap is the trap the old attempts fell into, and the 64 forbidden records guard most of it.

## No segment labels yet (taxonomy not published)

When the set was made, the database held **no published taxonomy version**. The guide allows only label IDs approved in a stated version, so there was nothing valid to label against. The set records `taxonomy_version: tax-none`, and every conversation has an empty `segments` list.

As a result, the set scores **extraction (EVAL-004) only**. Classification (EVAL-003) has nothing to score until segment labels are added under the first published version. Adding them later needs another annotation and review pass, and that pass gets its own review record.

## How it was made

1. **Import.** The full export in `raw/` went into a fresh git-ignored workspace inside the project folder: 1,158 chats and 0 failures. `raw/` was only read.
2. **Template.** The command was `ke gold template --count 40 --taxonomy tax-none --annotator gold-annotator-a`. It writes IDs only.
3. **Transcripts for annotators.** A small read-only script rendered the 40 chosen chats straight from the raw JSON. Each message shows its native ID, speaker, parent, and whether it sits on the selected branch or an alternative one. The transcripts went into a git-ignored private folder. No engine output was involved (no segments, classifications, extractions, ledger or reports).
4. **Annotation.** `gold-annotator-a` worked in 4 batches of 10 chats. It could see only the transcripts, the guide and the schema. Every record carried a verbatim evidence quote, and the quotes were removed before the set was saved.
5. **Code checks (annotation).** Every cited message must exist in its chat, and every quote must appear verbatim in that message. A user-held decision, rejection, preference or requirement must cite a user message. The set must also pass the `gold.py` validators. The annotation passed with 0 errors.
6. **Review.** `gold-reviewer-b` worked in 4 batches. It could see only the transcripts, the guide, the schema and the annotation. It wrote a corrected key plus a findings list for each batch.
7. **Code checks (reviewed).** The same checks were run again with `reviewed_by` set. The result was 0 errors and 0 warnings. `load_gold` reads the file, `ke gold schema` prints the gold-v1 schema, and the gold tests pass (16 passed).

## Reviewer findings and what was done

| Change | Severity | n | Done |
|---|---|---|---|
| Modify a record (wrong type, actor, acceptance or cited message) | must_fix | 5 | Applied |
| Add a missed record | must_fix | 1 | Applied |
| Add a missed record | should_fix | 27 | Applied |
| Remove a record that isn't one, or a duplicate | should_fix | 9 | Applied |
| Modify a record | should_fix | 2 | Applied |
| Forbidden entries changed | — | 0 | — |

Per conversation, the reviewer marked 18 as changed and 22 as ok, and left none unsettled.

Most of the additions were short user replies of one to four words, such as a rejection or a requirement. The annotator had first skipped these, because the prompt suggested quotes of at least 5 words. The orchestrating session told the annotator that a whole short message is a valid quote. The annotator then added what it found, and the reviewer found more.

## Known limits

- The set has **no owner verdict**. Both the annotator and the reviewer are Claude sessions on different models, but they come from the same model family, so their errors may be correlated.
- One annotator and one reviewer. There is no second annotation to measure agreement against.
- Voice chats whose messages are only audio placeholders have almost no records. That is correct for the text that exists, but it is thin.
- Records from roleplay and from assistant-written stories (including characters who share the user's name) were kept out, and forbidden entries were added to guard them.
- The record-level "ambiguous" flag and evidence spans are still deferred from the synthetic review.
