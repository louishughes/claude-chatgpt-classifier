# Relationship precision on real chats (EVAL-012)

Numbers only. The key and the full report stay on the owner's PC (`private/answer-key/relationships/`, git-ignored).

- Scorer `eval-012-v1`, key `relkey-v1` (real data)
- Key SHA-256: `8a8b56842ff30adc2acd299ec962edef6e4a7e3db779ad820a001e174fc014db`. It was frozen before scoring, and re-hashed after scoring with no change.
- Key written by session `eval012-relkey-writer-2026-10-28` (claude-opus-5-5), a separate Remote Control session that never saw the engine's proposed links (`saw_engine_output: false`). The owner approved the key on 2026-10-28 15:42 UTC and did no labelling.
- Key: 30 chats (25 chosen because they contain real links, plus 5 controls) and 49 links: forked_from 9, quotes 3, references 9, related_to 19, same_project 9, continues 0. There are 98 evidence items.
- Evidence check (`check_evidence`, workspace of 1158 chats): 0 problems.
- First scored at commit b47b6a1, before the fork-parent fix, then re-scored at cb24bf3, after it (same key, same hash before and after).

## Related-chat suggestions (REL-005, e6a77f6): PASS

Scored on a fresh import of the same export, after `ke related detect` and `ke related suggest` (wording and links only, no taxonomy). Same key and hash.

- Precision: **0.960** (threshold 0.90): **PASS**
- Recall, for information: 0.490 (24 of 49 key links)
- Proposals: 257 distinct, 25 scored

| Kind | correct | wrong_direction | wrong_kind | false_link |
|---|---|---|---|---|
| forked_from | 9 | 0 | 1 | 0 |
| quotes | 2 | 0 | 0 | 0 |
| references | 9 | 0 | 0 | 0 |
| related_to | 4 | 0 | 0 | 0 |

Baseline with the REL-003 rules on the same workspace (suggest had never been run before): 4,991 related suggestions, precision **0.727 (FAIL)**, recall 0.490. related_to was 4 correct and 8 false. REL-005 keeps the same 4 correct links, drops all 8 false ones, and makes 143 suggestions instead of 4,991.

Still missed: 15 `related_to` and all 9 `same_project`. `same_project` needs approved project labels, which come from a classifier run (paid) or a reviewer.

## After the fork-parent fix (cb24bf3): PASS

Re-scored on a fresh import of the same export (1158 chats), because the detectors never delete link rows they proposed earlier.

- Precision: **0.952** (threshold 0.90): **PASS**
- Recall, for information: 0.408 (20 of 49 key links), unchanged
- Proposals: 114 distinct, 21 scored, 93 outside the key's chats

| Kind | correct | wrong_direction | wrong_kind | false_link |
|---|---|---|---|---|
| forked_from | 9 | 0 | 1 | 0 |
| quotes | 2 | 0 | 0 | 0 |
| references | 9 | 0 | 0 | 0 |

One `forked_from` proposal still falls on a pair the key calls `related_to`. The engine still proposes no `related_to` or `same_project` links inside the key's set, which is why recall hasn't moved.

## Before the fix (b47b6a1): FAIL

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
