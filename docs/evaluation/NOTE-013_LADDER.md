# NOTE-013: ladder run on the real chats (counts only)

Owner goal (2026-10-28 22:40 UTC): work up through all 1,158 chats in passes of 100, with an independent quality review each pass. No paid API calls. Every model step is a Claude session on the subscription answering request files (`ke classify run`, `ke extract run`, `ke digest run`), and every answer is validated in code. Private material stays in `private/` and `workspace/`.

**How each step is checked:** a reference session that never sees the engine's notes writes reference digests for a seeded sample. A separate scorer session compares the notes with them, using the transcript as the final authority. Neither the reference writer nor the scorer is the session that labelled, extracted or digested the chats.

| Step | Chats | Classify | Extract | Digest | Notes, rubric | Sample scored |
|---|---|---|---|---|---|---|
| Gold | 40 | 85 segments (review: 14 of 18 settled) | 233 records | 40 | 40, rubric 32/40 (size only) | 15 (four scorings, see NOTE-011_REAL.md) |
| Step 2 | 50 | 65 segments, 50 chats (review: 24 settled) | 158 records | 48 + 2 oversize (now handled) | 50, rubric 46/50 (size only); 3 unclassified | 10 |

## Step 2 score (10 chats, scorer `claude-session-note-scorer-g`, references by a separate session)

| Measure | Result |
|---|---|
| Summary | 15/20 |
| Category exact / top only / miss / unclassified | 6 / 1 / 3 / 0 (2 of the misses fall in categories the reference itself calls defensible) |
| Status matches | 8/10 |
| Decisions found | **21 of 24**, 0 fabricated |
| Open questions found | 6 of 7, but the notes list 23 |
| Key points | 39/51 |
| Unsupported claims | 9 (in 5 notes) |
| Noise lines | 19 |
| Readability | 16/20 |

**Weak spots, and the tickets raised with the build thread:**

1. **Too many open questions.** 7 are duplicates across chat parts, and 4 claim "not answered" for an offer a later part shows the user accepting. Each part is read alone, so an earlier part can't see the answer. Fix: reconcile open questions across all parts of a chat, and drop any that a later message answers.
2. **Long-chat summaries stop early or leave out the outcome** (5 of 10 scored 1/2). Fix: the merged summary must cover the last part's outcome.
3. **Bugs found during the run, all fixed by the build thread:**
   - An oversize request stopped the whole run (now review_required, and the run continues).
   - Pending requests whose batch files were gone blocked a stage (requests now remember their run; migration 0031).
4. **Open:** an empty chat still gets a digest request that can't be answered. Taxonomy gaps found by reviewers (food and cooking, home and garden) go to the NOTE-014 refresh loop.
