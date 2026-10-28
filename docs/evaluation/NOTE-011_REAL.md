# NOTE-011 (real half): first independent score of the rich notes

**Date:** 2026-10-28. **Data:** the 40 golden-v1 chats in Louis's workspace. Everything private stays in `private/notes/gold-40-tax-1/` (git-ignored). This report holds counts only, with no chat text.

## What was run

| Step | Who | Result |
|---|---|---|
| Publish taxonomy `tax-1` | Louis's decision, run on his instruction | 64 terms (13 categories, 37 subcategories, 8 activities, 6 outputs) |
| Classify 85 segments (`ke classify run`) | 6 fresh labelling sessions (Claude Sonnet, subscription), via request files | 67 labelled, 18 sent to review (13 unsure, 3 split-part disagreements, 2 secondary-without-primary) |
| Digest 40 chats (`ke digest run`) | 4 fresh digest sessions (Claude Sonnet), via request files | 40 of 40 done, every quote checked in code |
| Render rich notes (`ke docs chat --template v2 --taxonomy tax-1`) | the engine | 40 notes |
| Code rubric (`ke docs rubric`, NOTE-011 code half) | the engine | 36 of 40 pass. The 4 failures are size only (up to 2x budget on one long chat). Citations, claims cited, user-held decisions, empty sections and tension/next-step consistency pass for all 40 |
| Reference digests for a seeded sample of 15 chats | a separate session (Claude Opus) that never opened the engine's notes | 15 references; provenance in `reference/PROVENANCE.md` |
| Scoring | a third session (Claude Opus) that wrote neither the notes nor the references; the transcript settles disagreements | `scores.json`, `SCORES.md` |

No paid API was called.

## Scores (15 chats)

| Measure | Result |
|---|---|
| Summary (0-2) | mean **1.53** (8 full, 7 partial, 0 wrong) |
| Category | 8 exact, 3 category only, **4 unclassified**, 0 wrong |
| Top-level category, when the note had one | **11 of 11 right** |
| Status (settled/open) | 12 of 15 match |
| Decisions | **5 of 22** reference decisions found (23% recall); 5 of 7 note decisions right (71% precision) |
| Open questions | **1 of 9** found |
| Key points covered | 58 of 75 (77%) |
| Unsupported claims in generated sections | 9, in 6 of 15 notes (6 of them in long, chunked chats) |
| Readability (0-2) | mean 1.73 |

## What this says

**Strong:** summaries are accurate and cited, the taxonomy works (no wrong top-level category), insights and tensions catch real issues, and a simulated team's agreement is correctly kept apart from the user's decisions.

**Weak, in order:**

1. **Decisions and open questions are nearly empty.** Only the rule extractors' records reached these notes. The model-backed extractor (NOTE-005, #291) was not run on these chats, and the rules found no decisions. The fix is to run NOTE-005 through request files, the same way, then re-score.
2. **Noise in the "from the chat" sections.**
   - Pasted custom-instruction profiles show up as requirements in 10 of 15 notes.
   - Lines from assistant-drafted text (for example a letter the assistant wrote) become suggestions, requirements and actions, with duplicates.
   - 5 suggestions were shown as "supported" although the user never took them up.
   - The fix is to filter out repeated boilerplate paragraphs (the same rule `taxonomy pack` already uses) and text quoted inside assistant drafts before extraction, and to show the user-acceptance state instead of trust.
3. **Long chats get stitched summaries.** In 4 notes the per-part digests are concatenated out of order with "this part" wording left in, and 6 of the 9 unsupported claims are there. The fix is a merge step that orders parts and rewrites one summary (or a merge request to the session), with the code rubric flagging leftover part wording.
4. **Classification gaps.** 4 notes are unclassified, because every segment went to review, and 2 have no subcategory. The fix is to show the best reviewed candidate as "suggested" instead of "unclassified", and to route the 18 reviews to a reviewer session.
5. **Status from the ending.** Image chats ending on an assistant offer were called open. The digest instructions need a rule for that.

## Next

- Run the NOTE-005 extractor on the 40 chats (request files, fresh sessions), re-render and re-score with the same references. The references stay unchanged.
- File fixes 2 to 5 as tickets with the build thread.
