# Review of the previous Codex/Hermes classifier attempts

| Field | Value |
| --- | --- |
| Written | 2026-10-27, by Claude, at Louis's request |
| Sources read | The v1 project folder on Louis's PC (plans, results, PRD, README, `handoffs/`, `references/`, `skills/chatgpt-classifier/`, 50 notes in `classified/notes/`) and the v2 project folder (`greenfield-knowledge-system/`, `docs/`, `work/` review and log files). Also this repo's spike outputs in `private/spike-out/` and code in `prototype/classification_spike/`. |
| How | Read-only. No scripts from the old folders were run. Note statistics were computed by reading YAML front matter with a throwaway script. No chat text is quoted here; conversations are referred to by file pattern only. |
| Authority | Evidence of what failed (priority 2–5 in `CLAUDE.md` §1). **Not guidance.** Nothing here adopts the old designs, prompts, taxonomies or skills. Items under "Reusable candidates" are suggestions for Louis to accept or reject. |
| Cross-check | `docs/reference/2026-10-27-why-the-classifier-failed.md` (ChatGPT post-mortem, on PR #2's branch). That post-mortem says it was not an audit of code or logs. This review is, so it adds file evidence and corrects a few points. |

> **Addendum (after this review, same evening).** Several points below were acted on before the spike closed. Code messages are now kept (`loader.CODE_CONTENT_TYPES`). Quote checks tolerate curly quotes, dashes and escaped newlines (`runner._normalise`). The clipping budget was raised to 200,000 characters for discovery mode. Reports name the reviewer and call run 1's figures "Claude's check", not accuracy. The spike was then closed without further paid runs: see `docs/plans/SPIKE_VERDICT.md`. The text below is kept as written, describing the state at the time.

## 1. The short version

1. **Every attempt ended up grading itself.** v1's 30 September "pass" used a golden set the agent wrote and a semantic review by the same model family. v2's "three independent reviewers" were AI sub-agents (`gpt-5.6-luna`, low effort). The current spike's accuracy figures (decisions 7 of 13, subject 95%) come from `claude_review.csv`, a Claude-written review. Louis's own `review_sheet.csv` is still blank. This is the most important finding, and the current run repeats it.
2. **Decisions were never measured against Louis before.** v1 extracted 25 "decision" objects across 50 notes with no proposer, no state and no human check. v2 found "assistant proposals rendered as user decisions" in its own review and wrote a rule against it, but never produced a human-scored decision number. The spike is the first attempt to put a number on decisions at all. That's progress, but the number isn't Louis's yet.
3. **Count rules caused most format failures, every time.** v1 failed on too *few* tags, v1.8 on title-word coverage and summary length, the spike on too *many* topics. A count rule measures form, not meaning, and retrying it wastes calls. The spike's switch to trimming in code is the right fix and is new.
4. **Clipping the chat lost the evidence, then and now.** v1 kept only 20 messages and 800 characters per message. The spike clips chats over 24,000 characters (12 of 50). In Claude's review, 3 of the 4 clipped chats that had decisions got them wrong, against 3 of 9 unclipped. Clipped chats also failed the format check more often (5 of 12, against 3 of 38). The sample is small, but it's the same failure mode.
5. **Free-text topics don't agree with themselves.** The spike's topics overlap only 0.49 between runs. v1 grew 3,154 free-text terms. v2 concluded that labels must come from a frozen registry with stable IDs. Spike v3 plans the same.

## 2. Timeline of attempts and workflows

| When | Attempt | Workflow | How it ended |
| --- | --- | --- | --- |
| Before May 2026 | v1.4–v1.7 (Hermes + DeepSeek) | Flat `tags:` list of 15–25 per chat. 240 notes. | Archived as poor quality (`HANDOFF_CLASSIFICATION_PLAN.md`, "Context"). |
| 26–28 May 2026 | v1.8/v1.9 "tiered tags", PRD v2.0 | Eight stages: preprocess, message scoring, one LLM call, ten count/format checks, auto-promote taxonomy at 3 sightings, relevance ranking, relations, Obsidian output. "Ralph loop" retries up to 5 times, 30% abort rule. Batch tests packed 5–50 chats into one call. | Batch pass rates 22–74%, dominated by `WEAK_SUMMARY`, `TITLE_DROPOUT`, `*_TOO_FEW` (`skills/chatgpt-classifier/references/batch-speed-test-2026-05-26.md`). PRD rewritten as "Tools extract, LLM judges, tools verify". |
| 20 Aug 2026 | Codex smoke gates | `run_full_pipeline.py --limit 5/10` | "Passed", but only checked that fields existed (`handoffs/handoff-20260820-codex-smoke-gates.md`). |
| 22 Aug 2026 | v2 "Greenfield" spec, new folder | 16 spec documents, JSON Schemas, a bootstrap prompt. Codex builds, three AI reviewers judge. | Repeated `REQUEST_CHANGES` from the AI reviewers (`work/independent-luna-review-2026-08-22.json`, `work/final-verified-review-2026-08-22.json`). |
| 24–25 Aug 2026 | v2 semantic provider and canonical rebuild | One core call plus six passes per chat, then one call per cited message. Corpus-derived taxonomy. Rich notes with "five units per section". | Smoke 50 first declared "accepted" after the acceptance rule was changed to meet the goal, then rejected by three quality reviewers (`work/decision-log.tsv`; `work/revalidation/smoke-50-quality-review-2026-08-25.md`). Rebuild plan written, not finished. |
| 30 Sep 2026 | v1 "overhaul" (GPT-6.1 Sol) | Full transcript, candidate terms from code, strict schema, 25 regression tests, smoke ladder 5→10→20→50. | Declared "passed" (`OVERHAUL_RESULTS_20260930.md`). Louis still judged the output not to work. |
| 27 Oct 2026 | This project's spike 0.2 → 0.3 → v3 proposal | Haiku 5.5, Pydantic schema, separate domain/purpose/topics fields, decisions with proposer and state. | Reliable and cheap. Decisions weak, labels "too simplistic". v3 proposed (`docs/plans/SPIKE_V3_PROCESS.md`). |

The workflow pattern repeated three times: write a bigger spec, have an agent build it, have an agent (or the same model) check it, and add rules when it fails. Each round produced more process documents (v2 alone: 16 spec files, 7 JSON Schemas, a rebuild plan of over 560 lines) without a human-checked accuracy number.

## 3. Failure modes, with file evidence

### F1. Self-grading: the agent wrote the answer key and judged the answers
- v1 overhaul: the 10 golden cases in `references/golden_tag_eval.json` each carry a `review_basis` sentence written by the agent. Only one case predates the overhaul. The "independent" semantic review used "a separate context of GPT-6.1 Sol", the same model that classified (`OVERHAUL_RESULTS_20260930.md`, "Scope").
- v2: `work/run-config.json` sets `"review_subagent_model": "gpt-5.6-luna"` with `"review_subagent_effort": "low"`. Every "independent reviewer" in `work/*review*.json` is an AI sub-agent.
- v2 moved the goalposts: `work/decision-log.tsv` first records "Treat Smoke 50 as diagnostic only", then "Accept Smoke 50 under the user-requested acceptance objective", then three quality rejections of the same bundle.
- v1 also counted two chats that the provider refused as passes by having the agent review them locally (`references/local_source_reviews.json`).
- **The current spike repeats this.** `private/spike-out/report.md` lists `review_file_sha256: 8b0721f9411077bb`, which is the hash of `claude_review.csv`, not of Louis's `review_sheet.csv` (all 20 verdict cells empty). Its "reference_labels: 20" and the 95% "accuracy vs reference labels" are Claude's labels scoring Haiku. The diary entry at 20:35 does say "Claude's check", but the report headings say "Your verdicts". Spike v3 step 1 also has Claude write the "blind" answer key, with Louis reviewing it afterwards. That's the same evaluator-mode anchoring problem the v3 plan itself names as problem 4.

### F2. Decisions: extracted without speaker or state, and never scored by a person
- v1 notes (`classified/notes/*.md`, 50 files): 594 extracted objects, 25 of type `decision`. Each has only `type`, `title`, `evidence_message_indexes` and `evidence`. There's no proposer, no state (accepted/rejected/superseded) and no later reversal check. All 25 cite a user message, so the rule "evidence must be a user message" was met, but that rule can't tell "user said yes" from "user asked a question".
- v1 `idea` objects: 205 of 207 cite only assistant messages. Assistant suggestions were stored as Louis's knowledge objects with nothing marking them as unadopted.
- The golden set (`references/golden_tag_eval.json`) has no decision expectations at all. Decisions were never in the test.
- v2's own review found it: "Render key decisions only from source-authored user direction or adoption … Independent review found assistant proposals rendered as user decisions" (`work/decision-log.tsv`). The fix was a rule in code. No human-labelled decision score followed.
- **Spike (run 1, taxonomy spike-0.2):** decisions came from the same call as the labels. Claude's review: 7 right, 6 wrong, 7 n/a. Wrong attribution (Louis's ideas credited to the assistant) and false "accepted". The report shows 10–8 `assistant->accepted` decisions per run and 1–2 accepted with only assistant evidence. Spike 0.3 moves decisions to their own call with message numbers checked by code. That fix hasn't been measured yet.

### F3. Count and format rules drove the failures and the retries
- v1.8 verification (`HANDOFF_CLASSIFICATION_PLAN.md`, "Verification Specs"): core 3–5, supporting 5–10, title coverage ≥80%, summary length, total ≤35. Batch tests' top failures were all of this kind (`WEAK_SUMMARY`, `TITLE_DROPOUT`, `CORE_TAGS_TOO_FEW`, `EMPTY_ENTITIES`). Retry prompts told the model "You need at least 8. Add more" (`references/prompt-templates.md`), which rewards padding.
- v2 required "five distinct substantive units" per section (`docs/greenfield-canonical-rebuild.md`, "Definition of done"). Its quality review then rejected notes as "over-produced" with "systematic evidence boilerplate".
- Spike run 1: 26–28 of 50 answers failed the schema on the first try, and 14 of 15 rejected answers had more than 5 topics (diary 20:35; `report.md`). Same pattern, opposite direction: v1 asked for too many, the spike capped too few.
- **New and better in the spike:** 0.3 trims overflows in code instead of retrying (`schema.py`, `_topics`). No old attempt did that. They all retried.

### F4. Evidence lost before the model saw it
- v1: "Only the first 20 signal messages and 800 characters per message reached the model" (`OVERHAUL_RESULTS_20260930.md`, first table row). The fix was to send everything.
- v1: a second parser dropped code and tool output (`OVERHAUL_PLAN_20260930.md`, "Diagnosis").
- **Spike:** `loader.clip_text` keeps the first 65% and last 35% of chats over 24,000 characters (12 of 50 clipped). Among Claude-reviewed chats with decisions, 3 of 4 clipped ones were wrong, against 3 of 9 unclipped. Five of 12 clipped chats ended `review_required`, against 3 of 38 unclipped. The middle of a long chat is where decisions get revised. The loader also keeps only `text` and `multimodal_text`, so code blocks and tool output are dropped (`loader.py`, `TEXT_CONTENT_TYPES`). That's fine for the spike, but it's the same gap v1 hit.

### F5. Unstable free-text vocabulary
- v1 auto-promoted terms after 3 sightings: 3,154 terms, 2,914 pending (`HANDOFF_CLASSIFICATION_PLAN.md`, "Taxonomy"). The overhaul later stopped promotion and counted distinct chats.
- v1 notes average 4.1 core + 7.8 supporting + 31.5 search keywords + 8.2 entities, so about 50 free-text labels per chat.
- v2 concluded that labels must use IDs from "the immutable, published registry" and that new terms stay candidates until reviewed (`docs/greenfield-canonical-rebuild.md`, Pass 3). Its quality review still found typos, fragments and generic phrases in keywords.
- **Spike:** domains and purposes are fixed enums, and they agree well between runs (87.5%, 90%). Free-text topics overlap only 0.49. Same lesson: free text drifts, while a frozen list holds.

### F6. One label per chat for chats that drift
- v1 used a single category from a mixed list (Ideas, Projects, Decisions, Content Assets…). The ChatGPT post-mortem covers this.
- v1's golden set already contained a multi-topic chat whose acceptable categories spanned three values (`golden_tag_eval.json`, the case with three `acceptable_categories`). This was dealt with by allowing several right answers rather than segmenting the chat.
- **Spike:** separate fields fixed the mixed-category problem, but there's still one domain and one purpose per chat. Louis's "too simplistic" verdict and the v3 plan's "games is 40% of the sample" are the same failure one level down.

### F7. Scope and process growth before proof
- v1 PRD listed 28 scripts. The v1 overhaul retired 16 obsolete entry points (`OVERHAUL_PLAN_20260930.md`, "Live diagnosis updates").
- v2 built hashing, tamper tests, zero-call replay, HTML/Markdown/JSON equivalence and attestation bundles before any human-checked accuracy number existed. Its quality review still found basic meaning errors (a misread phrase, wrong refusal tags, a relation based only on similar names).
- The model was switched three times (DeepSeek v4 Flash → GPT-6.1 Sol; DeepSeek v3.2 / v4 Flash in v2) when output was wrong, before the method was questioned.

### F8. Engineering bugs (real, but secondary)
These are documented and fixed in the old work. They're worth keeping as test ideas, not as designs: hidden reasoning used up the output budget (`current-runbook.md`, "Configuration"), a provider error inside HTTP 200 was counted as a model answer, a rate limit erased the previous attempt's repair context, newline handling changed transcripts on read-back, possessive names ("X's") failed exact matching, two background runs wrote to the same folder, and images were misdetected as voice (229 chats wrongly excluded, really 31) (`OVERHAUL_RESULTS_20260930.md`, table).

## 4. How each failure maps to the current plan

| Failure | Current plan (spike 0.3 / v3, `docs/TEST_STRATEGY.md`, guardrails) | Status |
| --- | --- | --- |
| F1 Self-grading | Guardrail: "Never judge your own output as correct; score it against the gold set." Evaluator mode in `review.py`. | **Conflict (active).** The current report's accuracy comes from `claude_review.csv`. v3 step 1 has Claude author the answer key. Needs a Louis-authored or Louis-verified key before any accuracy number is quoted as real. |
| F2 Decisions | Spike 0.3 `Decision` model has proposer, state, deciding *user* message and a quote checked by code. v3 scores state and proposer at 85% or more. | **Covered in design, unproven.** No old attempt measured this, so there's no evidence that the 0.3 design works. Score it against Louis's verdicts before building on it. |
| F3 Count rules | 0.3 trims overflows. Retries only for transport and format errors. | **Covered.** Better than any old attempt. Keep caps as trims, never as reasons to retry. |
| F4 Clipping | 24,000-character head/tail clip. Real importer (M1) keeps everything. | **Gap.** Decisions in the middle of long chats are cut. Either raise the budget for the decision call or split long chats into segments (v3 already plans segments). Report clipped and unclipped accuracy separately. |
| F5 Free-text vocabulary | v3: discovery, then consolidation, then frozen two-level taxonomy and project registry with stable IDs, approved by Louis. | **Covered in design.** It matches v2's conclusion. The difference that matters is that Louis approves the frozen list, not an AI reviewer. |
| F6 One label per chat | v3 segments chats by message range. | **Covered in design.** |
| F7 Scope creep | `CLAUDE.md` §4 one ticket at a time. Spike first, M1 import before NLP. v3 go/no-go targets. | **Covered.** Keep v3 small: the old v2 shows how "discover everything" turns into 594 objects per 50 chats. Consider limiting v3's typed items to decisions, requirements and preferences at first. |
| F8 Bugs | Pydantic boundary, transient-only retries, checkpoint/resume, `private/` outputs. | **Mostly covered.** Not yet covered: possessive and line-ending matching for quote checks, and provider errors returned inside successful responses. |

## 5. Reusable candidates (for Louis to accept or reject, not adopted)

1. **Count "ideas" by who said them.** v1's 205 of 207 assistant-only ideas show the risk. A deterministic tag of `assistant_suggested` vs `user_adopted` on every extracted item would make the risk visible in reports.
2. **Quote-checking normalisation cases** from F8 (possessives, escaped newlines, word boundaries) as test fixtures for the spike's `decisions_quote_found` check.
3. **Separate "archived" from "verified"** (v1's `classification_verified` vs `semantic_enrichment_verified`). The idea is sound: structural validity never implies correctness.
4. **The old failure list as regression ideas:** provider error inside HTTP 200, rate limit erasing prior context, images misread as voice. These are tests, not designs.
5. **Report accuracy split by clipped and unclipped chats, and by chat length.** This is new, motivated by F4.

Explicitly **not** recommended for reuse: the v1/v2 prompts, the tag tiers and counts, the "five units per section" depth rule, the 30% abort and Ralph loops, the auto-promotion taxonomy, the AI reviewer attestation bundles, and the golden set in `golden_tag_eval.json` (agent-authored, tag-recall only, no decisions).

## 6. Corrections to the ChatGPT post-mortem

- It says the old tests rewarded the wrong things. True, but by September the v1 overhaul *had* moved to full transcripts, strict schemas and a 10-case golden set, and it still failed Louis's judgement. The deeper problem was who wrote the golden set (F1), not only what it measured.
- It says auto-promotion caused order dependence. True for May. The September overhaul had already switched to recommend-only, so vocabulary was not the last thing that broke.
- It doesn't mention clipping (F4) or decisions in the golden set (F2). Both are in the files.
- Its ranking holds otherwise. The file evidence supports causes 1, 3, 5 and 6 most strongly.

## 7. Talking points

- "Three attempts passed their own tests and still failed the only test that mattered: does the owner agree?"
- "The fix isn't more rules. It's a definition of correct that the AI didn't write."
- "Same bug, three costumes: count rules for tags, for summary length, for topics."
- "I audited the old logs before trusting the new run, and found the new run was making the oldest mistake."
