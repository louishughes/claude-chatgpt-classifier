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

## 2a. Phase by phase: what each old pipeline actually did

Added 2026-10-28 at Louis's request ("There was specific Phases that the processes went through. What are each of those steps."). This was a read-only re-read of the same files. "Maps to now" points at `docs/plans/IMPLEMENTATION_PLAN.md` §2 (dataflow) and §4 (milestones).

### v1, May 2026 (Hermes, `HANDOFF_CLASSIFICATION_PLAN.md`)

Eight numbered stages, run by Hermes Agent with Python scripts in `tools/`. Every stage had a "verification gate": 30% or more failures aborted the run, fewer were retried in a "Ralph loop" up to 5 times.

| # | Stage | What it did | In → out | Run by | Where it broke | Maps to now |
| --- | --- | --- | --- | --- | --- | --- |
| 0 | Pre-processing | Read each chat's message tree and flattened it into date order. Pulled out title words and flagged voice chats and branches. | `raw/conversations/*.json` → `.extracts/batch_stage01_results.json` | Python (`batch_stage01.py`) | Chats containing images were treated as voice, so 229 chats were set aside instead of 31. A second parser elsewhere dropped code and tool output. | M1: adapters, message graph, `BranchClassifier`, active path kept separate from alternatives. |
| 1 | Message scoring | Scored every message 0–10. Only messages scoring 3+ ("signal") went to the model; the rest went to `_supplementary/`. | packets → signal and filler lists | Python heuristic | Short messages ("no, use X") scored low and were dropped, and these are where decisions live. The prompt also kept only the first 20 signal messages and cut each one to 800 characters. | No equivalent. Nothing is filtered out before the model sees it. The M3 `Segmenter` splits chats instead of dropping parts. |
| 2 | LLM classification | One call returned a category, a summary, 3–5 core tags, 5–10 supporting tags, entities, projects and outputs. Speed tests packed 5–50 chats into one call. | signal messages + title words → JSON | DeepSeek v4 Flash via OpenRouter, temperature 0.2, 1,500 output tokens | Packing chats together shrank the answers (22–74% passed). Reasoning written before the JSON caused missing fields. One category mixed subject, intent and output. | M3 `Classifier`: one segment at a time, separate fields, a frozen taxonomy. The model step runs through ADR-0009 (no paid API). |
| 3 | Verification | Ten checks: tag counts, 80% title-word coverage, confidence of at least 0.6, summary length, no overlap, total of 35 or fewer. Up to 2 retries, then quarantine. | JSON → pass, retry or `_quarantine/` | Python (`verify_gate.py`) | It checked the form, not whether the answer was right. Retry prompts said "add more tags". The runner filled in missing fields itself, never called the 30% abort, and exited "OK" after failures. | M3 `EvidenceValidator` plus schema checks. Retries cover transport and format errors only. Correctness is scored by EVAL tickets against a reference set. |
| 4 | Taxonomy promotion | Every tag went into `candidates.json`. Any tag seen 3 times was added to `master.yaml` during the run. | tags → taxonomy files | Python | Results depended on processing order: chat 800 saw a different list from chat 8. The list grew to 3,154 terms with 2,914 pending. | M3 `Taxonomy`: discovered first, then frozen for each run and approved before use. |
| 5 | Relevance ranking | Scored each chat against the taxonomy as Essential, Notable or Archive. | notes + taxonomy → rank | Python | Meaningless while the taxonomy was still growing. About 70% of "Archive" picks were wrong. | None planned. |
| 6 | Relation linking | Similarity of 0.75 or more between chats, plus a one-sentence reason from the model. | summaries → links | `nomic-embed-text` (local) + LLM | Deferred and never run in v1. | M2 structural relationship candidates, then M4 REL-003/004, with evidence and review. |
| 7 | Vault output | Wrote one Obsidian note per chat with the full transcript and tags in the front matter. | JSON → `classified/notes/*.md` | Python | Notes were written before the batch verdict, so failed runs leaked into `notes/`. YAML handling stripped characters from tags. Two background runs wrote to the same folder. | M1 `SourceNoteBuilder` (no model involved), then M4 projectors and the Obsidian vault. |

**28 May change (PRD v2.0, "Tools extract, LLM judges, tools verify, tools write"):** this added **Stage 1.5, candidate extraction** (`keyword_candidates.py`). Code pulled title terms, frequent phrases, capitalised names and taxonomy matches from the full transcript and graded them must/should/optional. The model then had to use or explicitly reject every must-include term. Notes gained two statuses: "archived" and "meaning verified". **Where it broke:** the candidates were noisy, with sentence fragments and schema words. The check measured whether terms were *accounted for*, not whether the classification was right.

### v1 preprocessing in detail (the "initial pre-process of all the conversations")

Read from the old `tools/` scripts and `.extracts/` outputs. This was all Python with no model calls, run once over the whole export before any classification.

| Step | Script | What it did | Output | Where it broke | Maps to now |
| --- | --- | --- | --- | --- | --- |
| P1 Split the export | `split_export.py` | Read every `conversations-*.json` in the export and wrote one file per chat, named `<date>.<title-slug>.json`, wrapping the original chat with counts (messages, user, assistant, image references). Also wrote a status file per chat under `INGEST_LOG/` (split, classified, curated). | `raw/conversations/` (1,160 files: 1,158 chats + 2 stray files) | Files were named by **title and local date**, not the chat's ID, so two chats with the same title became `-2`, `-3`. A re-export would create new files instead of matching old ones. | M1 `RawInventory` + adapters read the export in place (read-only). `LogicalIdentityResolver` keys on the native chat ID, so re-imports match (requirement C). |
| P2 Copy and catalogue images | `extract_images.py` | Found every image file in the export, hashed it (SHA-256) to spot duplicates, copied it to `raw/images/` and listed it in `IMAGE_MANIFEST.json`. | 931 images listed, 914 files copied | The manifest has a `source_conversations` field, but it is **empty for all 931 images**. | M1 `MediaStore` (blob, asset, occurrence) plus `AssetPointerResolver`: every image is linked to the messages that use it. Missing ones are marked `missing`. |
| P3 Link images to chats | `map_images_to_conversations.py` | Meant to scan chats for `file-…` IDs and DALL-E parts and fill in which chat each image belongs to. | `.extracts/image_conversation_map.json` | The path was hard-coded to the old `V:\AI\...` folder. The link never reached the manifest. | Same as P2. |
| P4 Parse messages | `source_messages.py` (September; `split_export.py` had its own copy in May) | Took **every node** in the chat's message tree and sorted all of them by timestamp. It pulled text, code, `thoughts` summaries and media placeholders, and tagged voice messages `voice:`. | message list per chat | Sorting every node by time **mixes regenerated answers and edited branches into one stream**, so competing replies read as one conversation. Different scripts parsed differently until September. | M1 native mapping parser + `BranchClassifier`: the selected path and the alternatives are kept apart (requirement B). |
| P5 Title words | `batch_stage01.py` `extract_title_tokens` | Lower-cased the title and removed stopwords. Words plus word pairs became "forced" tags. | `title_tokens` | It treated the auto-generated ChatGPT title as truth. Untitled and "New chat" chats had nothing. | None. Titles are display text, not evidence. |
| P6 Score messages | `batch_stage01.py` `score_message` | Started at 5. Under 5 words −4, over 50 words +2, "ok/thanks/yes/no" −5, code +3, headings +2, user question +1. Scores of 3+ were "signal", below 3 were "filler". | signal and filler lists | "yes" and "no" scored as filler, which drops the user's accept or reject, the exact evidence a decision needs. | None. Segmenter instead. |
| P7 Flags | `batch_stage01.py` | Voice = any audio content. Branch = the filename contains `branch-`. Also code, images and model name. | 31 voice, 33 "branch", 295 chats with images (1,841 references) | "Branch" only meant **"ChatGPT's 'Branch' button put `branch-` in the title"**. Real in-chat branches were not counted. Only 13 of 33 got a parent candidate (`.extracts/branch_index.json`). Before September, image messages were counted as voice (229). | M1 `BranchClassifier` reads the real tree. Continuation and fork links come later, through relationship candidates with review (requirement B). |
| P8 Build the prompt | `batch_stage01.py` | Signal messages only, each clipped to 800 characters (first and last 400), wrapped in `<title>`, `<title_tokens>` and `<body>`. | `.extracts/batch_stage01_results.json` (98 MB), average prompt 7.7k characters | Evidence was lost before the model saw it (F4). | M3 provider input: whole segment, no clipping. |
| P9 Candidate terms | `keyword_candidates.py` (Stage 1.5, added 28 May) | Word n-grams scored across all chats (in at least 2 chats, at most 65%), capitalised phrases, "high-value entities", taxonomy hits, top 50, graded must/should/optional with evidence indexes. | `.extracts/keyword_candidates.json` (27 MB) | Frequency can't tell a subject from a passing mention. The candidates included sentence fragments and schema words, and the model was then forced to account for them. | M3 `Normaliser`/discovery. Candidates are suggestions, never required tags. |
| Side folders | — | `voice_misdetected/` (16 markers), `_supplementary/` (filler messages), `_quarantine/` | — | Manual workarounds for the voice bug. | Not needed. |

### v1 overhaul, 30 September 2026 (Codex, `references/current-runbook.md`)

Same stages, rebuilt as one runner. Run by Codex, classified by GPT-6.1 Sol through OpenRouter (medium reasoning, 12,000 tokens).

| # | Step | What it did | Where it broke |
| --- | --- | --- | --- |
| 1 | Regression tests | 25 unit checks of known bugs. | Fine as far as it went. Every test was written by the agent. |
| 2 | Stages 0/1 + candidates | Parse all 1,158 chats with zero errors, then extract candidates from **every** message. | Fixed the voice and clipping bugs. |
| 3 | Classify | One full transcript per request, strict JSON schema, no 20-message or 800-character cuts. | DeepSeek failed every reference case, so the model was swapped instead of the method being questioned. Two chats were refused by the provider and were "locally reviewed" by the agent instead. |
| 4 | Verify | Schema, candidate coverage, golden-term recall, and an exact source quote for every extracted object. Up to 2 targeted repairs. Abort at 30%. | The golden set (10 chats) was written by the agent and measured tag recall only, with no decisions in it. |
| 5 | Write and read back | YAML written in a run folder, then re-read from disk and compared with the raw chat. | Line endings and possessive names ("X's") broke the comparison until fixed. |
| 6 | Semantic review | A separate context re-read each transcript and judged the note. | Same model family judging itself (F1). |
| 7 | Publish | Notes copied to `classified/notes/` only if every chat in the stage passed. | Worked as designed. |
| 8 | Smoke ladder | 5 → 10 → 20 → 50 chats, restarting at 5 after any code change. | "Passed 50/50" against its own tests. Louis still judged the output not to work. |

### v2 Greenfield, 22–25 August 2026 (Codex, `ChatGPT_Classification_v2`)

The first design (`greenfield-knowledge-system/04-architecture.md`, `09-delivery-plan.md`) defined four operations: **capture → interpret → release → project**, delivered in eleven "slices" (0 freeze contracts … 10 commercial hardening). The first build (`work/canonical-run-1`, Smoke 1/5/10) was rejected repeatedly by three AI reviewers (`work/*review-2026-08-22.json`). It was then rebuilt as a nine-pass "canonical compiler" (`docs/greenfield-canonical-rebuild.md`):

| Pass | What it did | In → out | Run by | Where it broke | Maps to now |
| --- | --- | --- | --- | --- | --- |
| 0 Seal and represent | Stored the raw bytes under a hash and rebuilt each chat's message order from parent links, keeping branches, system and empty messages. | raw JSON → `SourceRevision` + representation | Python | Mostly worked: 1,146 sources reconciled. It needed several fixes to message order. | M1 (the closest match to what's being built now). |
| 1 Corpus candidate profile | Counted words and phrases across all chats (how many chats each appears in), each with evidence. No labels. | all representations → lexical profile (46 MB) | Python | Huge and noisy. It nominated typos and fragments that later became keywords. | M3 `Normaliser`. Spike v3 "discovery" replaced this with a model pass. |
| 2 Provider proposals | The model proposed intent, topics, keywords, summaries, section drafts and relations, citing message numbers. This started as one call per chat, then "core + six passes", then one call per cited message. | chat + profile → proposals (each attempt saved) | DeepSeek v3.2 / v4 Flash via OpenRouter | Long answers stalled. Assistant suggestions came back as user decisions. Evidence explanations were stock phrases. | M3 `Extractors`: speaker and state on every item, message numbers checked by code. |
| 3 Publish taxonomy | Grouped corpus candidates into categories, subcategories and tags, checked against a calibration set, then frozen with stable IDs. | profile + proposals → taxonomy and tag registry | Codex, checked by AI reviewers | The "reviewer" was an AI. Tags were still wrong in the final review. | M3 `Taxonomy`. The plan has an approver for the frozen list; see F1 for who that should be. |
| 4 Frozen classification | Code picked category, tags and keywords from the frozen IDs. Primary keywords had to come from a user message. | proposals + registry → `ClassificationDecision` | Python policy | Keywords kept typos, fragments and boilerplate. | M3 `Classifier` on segments. |
| 5 Assemble release | Built the note's sections, each requiring **five** points with two sentences and two bullets, plus decisions, questions and relations with evidence from both chats. | everything above → `CanonicalRelease` | Python + model drafts | The five-point rule padded short chats. 16 notes said "no user question" when there was one. One relation linked two chats only because their names looked alike. | M4 `Reconciler` and document builders. No fixed section depth. |
| 6 Render | The same release rendered as Markdown, HTML and JSON. | release → three files + manifests | Python | Audit data made notes unreadable, and the HTML showed raw YAML. A redesign followed (`docs/reader-projection-redesign.md`). | M1 renderer core and source notes, M4 Obsidian, and the local web UI (UI-001..003). |
| 7 Assurance and replay | Hash checks, one-byte tamper tests, and a re-run from saved answers with zero model calls, checked byte for byte. | run folder → audit reports | Python | Worked, but it proved the files were *unchanged*, not that they were *right*. | M3 provider cache. Replay is useful, but it isn't an accuracy test. |
| 8 Review and accept | Three reviewers signed off on one frozen bundle. | bundle → attestations | AI sub-agents (`gpt-5.6-luna`, low effort) | Self-grading. The acceptance rule was changed to declare Smoke 50 accepted, then three quality reviews rejected the same bundle. | EVAL-001 answer key. As of 2026-10-28 the plan has an independent Claude session reviewing the key instead of Louis (`IMPLEMENTATION_PLAN.md` §12). That is still an AI checking AI, which is F1's risk. Reports must name the reviewer, and the number must not be presented as Louis's verdict. |

**What the three pipelines share:** each put a model step in the middle, wrapped it in more deterministic checks after every failure, and declared success when its own checks passed. None of them had a step where Louis marked whether the answers were right. The current plan's M1 and M2 avoid the problem by not using a model at all. M3 is where it will come back unless the reference set is produced independently and clearly labelled.

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
