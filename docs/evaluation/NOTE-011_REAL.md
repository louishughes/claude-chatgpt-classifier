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

## Re-score after the AI extractor (NOTE-005), same 15 references

The NOTE-005 extractor ran on all 85 segments through request files, answered by 5 fresh Claude Sonnet sessions with every quote checked in code. It stored 94 records. The 40 notes were re-rendered and the code rubric passes 35 of 40 (all 5 failures are size only). A **new** scorer session (Claude Opus), which didn't see the first scoring, compared them with the unchanged references.

| Measure | First score | Re-score |
|---|---|---|
| Summary | 1.53 mean (23/30) | 24/30 |
| Category | 8 exact, 3 top only, 4 unclassified | same (no reclassification yet) |
| Status matches | 12/15 | 12/15 |
| **Decisions found** | **5 of 22 (23%)** | **12 of 22 (55%)**; the notes hold 28, 2 wrong |
| Open questions found | 1 of 9 | 0 of 9 |
| Key points covered | 58/75 (77%) | 59/75 (79%) |
| Unsupported claims | 9 in 6 notes | 9 in 6 notes |
| Noise lines in "from the chat" sections | not counted | 57 (42 are pasted custom instructions, in 10 notes) |
| Readability | 1.73 mean | 19/30 (1.27 mean; the new records add length and noise) |

**What changed:** decision recall more than doubled. **What didn't:** open questions, noise and stitched summaries. The noise comes from the older rule-extractor records, which are still stored and shown next to the new ones. The fixes are the same as listed above, plus two more:

- Hide or retire the rule-extractor records for a chat once a model extraction has run on it, so pasted custom instructions and drafted letter text stop appearing as requirements.
- Have the extractor and the digest fill open questions from how the chat ends (an unanswered offer, an unsent letter, a promise to report back).

## Extraction scored against answer key v2 (`ke gold convert` + `ke gold score`)

The answer key fingerprints were checked first, and both were unchanged: v1 `1dbf3d2a…781b64` and v2 `a37caa31…d9f5b` (combined SHA-256 of the 10 files, as in `docs/reviews/OPEN_DECISIONS.md`). `ke gold convert` turned v2 into a gold set: 90 records, with 21 key items left unmapped (12 `fact_about_owner`, 7 `fact`, 1 `task`, 1 unclear decision) and 0 number mismatches. Label: **AI check (not owner-verified)**.

| | Result |
|---|---|
| Key chats found | 10 of 10 |
| Produced records in those chats | 71 |
| Precision / recall / F1 | **0.056 / 0.044 / 0.050** |
| Gate (anchors, forbidden records, unsupported decisions) | passed; anchor validity 1.0, 0 forbidden |
| Rejections | P 1.00, R 0.50 |
| Requirements | P 0.14, R 0.10 |
| Decisions | 0 of 12 |
| Key "idea" items (32) | 0 found. The engine records an assistant suggestion as a `proposal` (24 produced, none expected) |

**Reading it honestly:** the low score is partly real and partly a vocabulary mismatch between the key and the engine.

- The key calls an assistant's suggestion an `idea`. The engine calls it a `proposal` and never emits `idea`. So 32 key items and 24 engine records can never pair, even when they describe the same suggestion.
- The key has no `action` or `proposal` items at all, so every engine action and proposal counts as a false positive.
- The real misses are decisions (0 of 12 under this matcher, although the separate note re-score found 12 of 22 by meaning) and requirements (2 of 21).
- Changing how types map is a change to the evaluation criteria, so it needs Louis's approval. The decision is whether `proposal` should count as a match for the key's `idea` (assistant suggestion), or whether the extractor should emit `idea`.

## Third score: after NOTE-022 (rule records dropped) and the classification review

The changes since the second score:
- A separate reviewer session (Claude Opus) settled 14 of the 18 unsure segments. The other 4 are empty or nearly empty.
- NOTE-022 leaves rule-extractor records out of a note once a model extraction has run for that segment.
- The 40 notes were re-rendered, and the code rubric passes 38 of 40 (2 fail on size).

A third fresh scorer session (Claude Opus) used the same 15 references, which are unchanged.

| Measure | 1st | 2nd | **3rd** |
|---|---|---|---|
| Summary (of 30) | 23 | 24 | **25** |
| Category exact / top only / miss / unclassified | 8/3/0/4 | 8/3/0/4 | **9/4/1/1** |
| Status matches | 12/15 | 12/15 | 12/15 |
| Decisions found (of 22) | 5 | 12 | **9** (1 fabricated) |
| Open questions found (of 9) | 1 | 0 | **0** |
| Key points (of 75) | 58 | 59 | 59 |
| Unsupported claims | 9 | 9 | 10 |
| Noise lines | – | 57 | **3** |
| Readability (of 30) | 26 | 19 | **25** |

**What it shows:**
- Dropping the rule records removed almost all the noise (57 lines down to 3) and readability recovered. It also removed a few real user constraints that only the rule extractor had caught, so decisions fell from 12 to 9.
- The review fixed most of the unclassified chats.

**What's left (the top three, and what to fix):**
1. **Open questions:** 0 of 9 found. The extractor and digest need to read how a chat ends (an unanswered check-in, an unsent letter, a promise to report back, an option never chosen).
2. **User constraints and decisions:** 13 of 22 missed, mostly short user instructions such as numbers, limits and "no repeats". The extractor prompt should treat a user's own constraint as a requirement even when it isn't phrased as "I decided".
3. **Long, multi-part chats:** summaries are stitched together, with chunk wording left in. These chats hold 6 of the 10 unsupported claims, including one misread request that caused a fabricated decision. The fix is a merge step for multi-part digests.

## Fourth score: the knowledge-v2 extractor and new digest prompts (NOTE-023/025/016)

**Run:**
- On main `44adc42`, the extractor (prompt knowledge-v2) and digest were re-run on the 40 gold chats: 85 + 51 requests, answered by 9 fresh Claude Sonnet sessions, every quote checked in code. That stored 233 records and 40 digests (one invalid answer got its single repair, as designed).
- The 40 notes were re-rendered. The code rubric passes 32 of 40: all 8 failures are size only, and the new part-wording check passes 40 of 40.
- A fresh scorer session (Claude Opus) scored the notes against the same 15 references.

**A correction to the earlier extraction scores:** the 10 chats in answer key v2 are *not* among the 40 gold chats. So the strict F1 0.050 / mapped 0.149 above measured only the old rule-extractor records on those 10 chats. The AI extractor has now run on them too (15 segments, 115 records, the same request-file flow, a separate session that never opened the key). Both key fingerprints were checked again and are unchanged.

### Extraction against answer key v2 (10 chats)

| | Strict | `--count-as idea=proposal` |
|---|---|---|
| Precision | 0.177 | 0.269 |
| Recall | 0.367 | 0.556 |
| F1 | **0.239** (was 0.050) | **0.362** (was 0.149) |

The mapped run in detail:

| Type | Precision | Recall |
|---|---|---|
| Decision | 0.80 | 0.67 |
| Idea (as proposal) | 1.00 | 0.53 |
| Requirement | 0.30 | 0.91 |
| Rejection | 0.44 | 1.00 |
| Question | 0.11 | 0.67 |

The key has no actions, references or bare proposals, so every one of those (66 records) counts as a false positive. That keeps precision low.

### Notes against the 15 references

| Measure | 1st | 2nd | 3rd | **4th** |
|---|---|---|---|---|
| Summary (of 30) | 23 | 24 | 25 | **25** |
| Category exact / top only / miss / unclassified | 8/3/0/4 | 8/3/0/4 | 9/4/1/1 | 9/4/1/1 |
| Status matches | 12 | 12 | 12 | **9** |
| Decisions found (of 22) | 5 | 12 | 9 | **20** (2 fabricated) |
| Open questions found (of 9) | 1 | 0 | 0 | **7** |
| Key points (of 75) | 58 | 59 | 59 | **62** |
| Unsupported claims | 9 | 9 | 10 | **4** |
| Noise lines | – | 57 | 3 | **37** (almost all duplicates) |
| Readability (of 30) | 26 | 19 | 25 | 22 |

**What it shows:** the extractor and digest changes fixed the two biggest gaps. Decisions went from 9 to 20 of 22 and open questions from 0 to 7 of 9, and unsupported claims halved.

**What's left (in order):**
1. **Duplicates.** Overlapping segments and repeated asks produce the same requirement several times. One note lists 28 requirement entries for about 12 ideas. This needs a per-chat merge of equivalent records (REC-001 already proposes equivalences; the note should show one per group).
2. **Status leans "settled".** 6 chats that ended on an unanswered offer or with no final choice are marked settled. The digest's status rule should follow the open questions it found.
3. **Small accuracy slips.** There are 12: a complaint about a missing element read as a rejection, pasted custom instructions read as the request, a returned image missed, and miscounts.
