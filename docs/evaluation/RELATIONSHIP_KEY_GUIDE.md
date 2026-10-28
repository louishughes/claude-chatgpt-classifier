# Relationship answer key guide (EVAL-012)

How to write the answer key that scores links between chats (`relkey-v1`).
The scorer is `src/knowledge_engine/evaluation/relationship_key.py`; run it
with `ke eval relationships --key <file> [--out report.md]`.

## Who writes it

A **separate Claude session** that has never seen the engine's proposed
links (no `ke related list`, no notes, no `conversation_relationships`
table). Ideally a different model from the one that built the detectors.
The key records that session and model under `produced_by`, and must say
`"saw_engine_output": false`. Louis does not label (project rule); he
approves whether a key is used.

The real key cites private chats, so it lives in the git-ignored workspace
on Louis's PC, never in Git, like the real golden set.

## What it holds

- `conversations`: the export's conversation IDs the key covers. Whoever
  writes the key looks at **every pair** in this list, because any link the
  engine proposes between two listed chats that the key doesn't contain is
  scored as wrong.
- `links`: every true link between those chats, read as
  "`from_conversation` `kind` `to_conversation`". Kinds: `continues`,
  `forked_from`, `quotes`, `references`, `related_to`, `same_project`.
  The later chat is the `from` end. `related_to` and `same_project` have
  no direction.
- Each link's `evidence`: at least one message from one of its two chats,
  by `message_number` (active-path numbering, counting system, code and
  tool messages, as `ConversationGraph.message_number` does), `speaker`
  and a word-for-word `quote`.

## Checks before scoring

`ke eval relationships` refuses to score until every quote is proved by
code: the message exists on the active path, the speaker matches, and the
quote is in it. Problems are listed by link, chat ID and message number
only.

## What the score means

Each distinct proposal between listed chats is `correct`,
`wrong_direction`, `wrong_kind` or `false_link`. Precision is correct ÷
scored, against the 0.90 floor in TEST_STRATEGY §6. Proposals touching an
unlisted chat are `out_of_scope` and not judged. Recall is shown for
information only.
