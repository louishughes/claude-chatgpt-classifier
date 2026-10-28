# Golden set annotation guide (EVAL-001)

The golden set is the answer key that classification (EVAL-003) and extraction (EVAL-004) are scored against. Its format is `gold-v1` (`src/knowledge_engine/evaluation/gold.py`; `ke gold schema` prints the JSON Schema).

## Two sets, one format

| Set | Where | In Git? | Purpose |
|---|---|---|---|
| Synthetic (`golden-synthetic-v1`) | `tests/fixtures/gold/synthetic-v1/gold.json` | yes (synthetic only) | proves the evaluators and runs in tests |
| Real (`golden-v1`) | `<workspace>/gold/golden-v1.json` | **never** | measures quality on the owner's own chats |

The real set holds private conversation IDs and labels. It stays in the git-ignored workspace. Only report numbers leave the machine.

## Starting the real set

```
ke gold template --count 40 --taxonomy tax-N --annotator <name>
```

This picks 40 conversations with the seeded, theme-balanced sampler (NRM-006) and writes a template that holds **IDs only**, with no titles or text. The same seed always picks the same conversations. Aim for 30 to 50 conversations, and include:

- short and very long chats;
- chats about several projects at once;
- chats with edits or regenerated answers (branches);
- chats where the assistant suggests things the user ignores, questions, rejects or accepts;
- chats that quote other people (a client, a forum post).

## Labelling segments

- Name each segment by its **first message ID**. Segment IDs can change when the segmenter changes, but message IDs can't.
- For each field (`domain`, `purpose`, `topic`, `knowledge_type`, `output`, `projects`), give at most one `primary` and any `secondary` labels. Use only IDs approved in the stated taxonomy version.
- Leave a field out when nothing in the vocabulary fits. That means "no label expected".
- If you genuinely can't decide, set `"ambiguous": true` and add a short `note`. The evaluator then checks whether the system *asked for review*, not which label it guessed.

## Records that must be found

For each record, give `record_type`, `actor` (who holds it), `message_id` (the message carrying its main evidence) and, where it applies, `acceptance`, `attributed_to` and `strength` (`hard` for "must", `soft` for "ideally" or "I'd like").

Set `"records_annotated": true` only once you have listed **every** record in the conversation. Only then does the extraction evaluator count a found record that isn't listed as a false positive. A conversation labelled for segments only leaves it `false`, and its records aren't scored. If you can't tell whether something is a record (for example "ideally..." as a requirement), leave it out and add it to `forbidden` only if claiming it would do harm.

- **Decision**: the user's own words accept something ("yes, let's do that", "I've decided to..."). The actor is `user`. A conditional yes is `conditional`.
- **Proposal**: the assistant suggests something. The actor is `assistant`, and it is **never** a user decision on its own.
- **Rejection**: the user turns something down.
- **Preference / requirement**: the user's own taste or constraint. If the user reports someone else's view, set `attributed_to: "external"`.
- **Action**: a task. The user's own commitment has actor `user`; a task the assistant hands out has actor `assistant`.
- **Question**: an open question, meaning one that is unanswered or answered with "I'm not sure".
- **Artefact**: something the assistant or a tool produced (an image, a file, code).
- **Reference**: a named game, piece of software, book, film or creator.

## Records that must never appear (`forbidden`)

List the mistakes that would do real harm, each with a short `reason`. Above all:

- an assistant suggestion recorded as the user's decision;
- a question or "maybe" recorded as acceptance;
- someone else's preference recorded as the user's.

Any forbidden record that the system produces counts as a failure, whatever its other scores.

## Review

A golden set is annotated by one person (`annotator`) and checked by another (`reviewed_by`). The owner delegated review to an independent Claude session, so `reviewed_by` names that session's role, never the annotator. A set is only used for a published baseline once every conversation has `reviewed_by` set. The schema refuses a reviewer with the annotator's name.

`ke gold template` never overwrites an existing set: annotation is hours of work. Move or rename the old file first.

## Stability and schema failures

The EVAL-001 amendment asks for run-to-run label stability and the schema-failure rate. Neither needs extra annotation: stability compares two runs of the same versions on the gold conversations (`stability()` in `classification_eval.py`), and the schema-failure rate comes from the model ledger (`schema_failures()`). Compare stability only between runs with the same taxonomy, prompt and model versions.

## Report labels (LEG-002, REV-012)

Every scored report (`ClassificationReport.as_markdown`, `ExtractionReport.as_markdown`) opens with the answer key it was scored against:

```
## AI check (not owner-verified)

- Answer key: `golden-synthetic-v1 (gold-v1)`, SHA-256 `…`
- Reviewer: agent-reviewed, not owner-approved (`ai_session`)
- Review file SHA-256: `…`
```

| `reviewer_kind` | Heading | Reviewer label |
|---|---|---|
| `owner` | Owner verdict | owner-approved |
| `ai_session` | AI check (not owner-verified) | agent-reviewed, not owner-approved |
| `same_model` | AI check (not owner-verified) | checked by the same model that made it, not owner-approved |
| `none` | AI check (not owner-verified) | not reviewed, not owner-approved |

- "Owner verdict" prints **only** when the key's reviewer is the owner.
- Any reviewed kind needs the review file's hash. The synthetic set's review is `docs/reviews/GOLD_SYNTHETIC_V1_REVIEW.md`.
- A report missing the key's version, hash or label refuses to render.
- A report with no key prints `unscored` and no numbers.
- `evaluate_*` without an explicit key uses a content hash and claims no review (`none`). Use `key_from_file(path, kind, review_file)` for a published baseline.
