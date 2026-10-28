# Relationship precision on real chats (EVAL-012)

Numbers only. The key and the full report stay on the owner's PC (`private/answer-key/relationships/`, git-ignored).

- Scorer `eval-012-v1`, key `relkey-v1` (real data)
- Key SHA-256: `8a8b56842ff30adc2acd299ec962edef6e4a7e3db779ad820a001e174fc014db`. It was frozen before scoring, and re-hashed after scoring with no change.
- Key written by session `eval012-relkey-writer-2026-10-28` (claude-opus-5-5), a separate Remote Control session that never saw the engine's proposed links (`saw_engine_output: false`). The owner approved the key on 2026-10-28 15:42 UTC and did no labelling.
- Key: 30 chats (25 chosen because they contain real links, plus 5 controls) and 49 links: forked_from 9, quotes 3, references 9, related_to 19, same_project 9, continues 0. There are 98 evidence items.
- Evidence check (`check_evidence`, workspace of 1158 chats): 0 problems.
- Scored against the engine's detectors as of commit b47b6a1 (before the fork-parent fix).

## Result

- Precision: **0.800** (threshold 0.90): **FAIL**
- Recall, for information: 0.408 (20 of 49 key links)
- Proposals: 125 distinct, 25 scored, 100 outside the key's chats

| Kind | correct | wrong_direction | wrong_kind | false_link |
|---|---|---|---|---|
| forked_from | 9 | 0 | 5 | 0 |
| quotes | 2 | 0 | 0 | 0 |
| references | 9 | 0 | 0 | 0 |

The engine proposed no `related_to` or `same_project` links between chats in the key's set, so most of the missed recall is those 28 links.

## What the 5 wrong-kind links are

On every pair where the engine said `forked_from` and was marked wrong, the key says `related_to`. These pairs are two forks of the same parent (siblings), or a fork of a fork and its grandparent. The key's rule is that `forked_from` names the direct parent only. The detector was linking every pair of chats that share copied message IDs, so siblings and grandparents got linked too. The fix gives each chat one parent and comes with a new test (`tests/integration/test_fork_parents.py`). Re-scoring needs a fresh import and the same, unchanged key.
