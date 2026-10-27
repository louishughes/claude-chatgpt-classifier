# Classification spike: verdict

**Closed 2026-10-27 by owner decision** ("we need to learn"), before it became a rabbit hole. The code stays in `prototype/classification_spike/` as reference. Nothing in `src/` will import it.

## The question
Can a cloud model turn ChatGPT conversations into *consistent, correct, evidence-backed* knowledge, at batch sizes where the earlier attempts broke down?

## What it proved
| Finding | Evidence |
|---|---|
| **Transport is solved.** Direct Anthropic API with bounded retries and checkpointing had 0 timeouts or connection errors across 100 calls, at about 3.5 s per chat. The earlier attempts failed here, through an aggregator. | Run 1: 50 chats × 2, Claude Haiku 5.5 |
| **Cheap enough to iterate.** About $0.035 per 50 chats for labels. A full discovery pass is estimated at about $0.13 per 50. | Run 1 cost $0.069; discovery dry run |
| **Typed output works, if limits are trimmed in code.** 14 of 15 hard failures were "more than 5 topics". The answers weren't wrong, just long. Retrying them was the wrong fix. | Run 1 schema error tally |
| **Fixed-list fields are fairly stable; free text isn't.** Run to run, in different orders: domain 87.5%, purpose 90%, topics overlap 0.49. | Run 1 consistency |
| **Clipping hurts.** 12 of 50 chats clipped at 24k characters did markedly worse. At 200k characters, none are clipped. | Run 1 split by clipping; discovery dry run |
| **Per-chat labels are too simplistic.** 5 of 10 answer-key chats contain 2–3 distinct sections. One broad category held 40% of the sample. Most of the knowledge (ideas, preferences, facts, artefacts) wasn't captured at all. | Owner judgement; answer key |

## What it did *not* prove
- **Accuracy.** No figure has been scored by the owner. The run-1 numbers (domain 95%, purpose 85%, decisions 7/13) are *Claude checking Haiku*, an AI grading an AI, and they don't count as accuracy.
- **Decisions.** Never human-scored in this or any earlier attempt. The checked-decision design (message numbers verified by code) is built and tested but has not been run.
- **Discovery, taxonomy consolidation, project registry, segment classification** (v3 steps 2–5). These are built or designed but not run.

## Lessons for the real pipeline
1. Retry transport and format errors only. Trim harmless overflows in code. Never retry a well-formed answer.
2. Make the model cite **message numbers** and check them in code: speaker, decided-by-user, quote present. Score by message number, not wording.
3. Classify **sections**, not whole chats. Discover first, then freeze a two-level taxonomy and project registry that the owner approves.
4. Send the whole chat (or the whole section). Report clipped and unclipped chats separately whenever clipping happens.
5. Keep code messages. Make quote matching tolerant of curly quotes and escaped newlines.
6. Accuracy needs an **owner-approved reference**. An AI check is a smoke test, not a score. Label who the reviewer is in every report.
7. Stop when the question changes. The spike answered "is the transport reliable?" and showed that "per-chat labels" was the wrong question.

## How to resume (after M1)
1. The owner reviews the answer key in `private/answer-key/` (10 chats, 95 items; ok / fix / drop). Note that it was written after seeing Haiku's labels.
2. Run discovery: `python spike.py --mode discover --sample 50 --runs 2` (about $0.27) and score it against the approved key.
3. Then do v3 steps 3–5 (`docs/plans/SPIKE_V3_PROCESS.md`), or build them directly as M3 tickets on top of M1's stored, segmentable messages.

The answer key, run files and reports stay private in `private/` (git-ignored) on the owner's PC.
