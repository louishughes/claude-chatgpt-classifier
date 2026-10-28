# Rich conversation notes: what the old attempts did, what we have, and what to build

**Date:** 2026-10-28 (UTC). **Asked by:** Louis (owner). **Written by:** a Claude Code thread on Louis's PC. **Status:** approved. On 2026-10-28 at 12:50 UTC Louis replied "Go ahead with the recommendations and verifications": all eight decisions in §9 are taken as recommended.

**Rules followed while writing this:** the old folders on `P:\` were only read. No private chat text is copied into this file: chats are described by shape and size, never quoted. No tests, evaluation criteria or gold set were changed. No model API was called.

---

## 1. The short answer

The current engine is good at the *plumbing* and almost empty on the *meaning*.

- It imports all 1,158 chats faithfully, keeps branches, images, links, videos and accounts, and can prove where every quote came from. The old attempts never got that right.
- But a conversation note today says only *how many* messages, records and links a chat has. On the real workspace there is **no published taxonomy**, so **no chat has a category**. The rule extractors found **0 decisions** in 85 real segments. The 17-message game-design chat that the 2025 attempt turned into 14 evidence-backed knowledge objects comes out today as a note with **0 knowledge records** and a one-line count.
- The old notes had the sections Louis wants (summary, knowledge card, category and subcategory analysis, keyword and intent candidates, next steps, action items, decisions, insights, tensions, unresolved matters). v1 hid most of them in YAML. v2 showed them, but buried them under about 3,000 repeated evidence blocks, padded empty sections with filler, and got several facts wrong.

**What to do:** keep the current engine's evidence and provenance machinery, add one model step per conversation (a *conversation digest*, run by a Claude session through the existing file-batch provider, never a paid API), publish a first taxonomy, and render a new note template that puts the readable content first and the evidence in compact, clickable citations. §7 is the template and §8 is the ticket list.

---

## 2. What was read

| Source (read-only) | What it is |
|---|---|
| `P:\Codex\ChatGPT_Classification\ChatGPT_Export_Staging\taxonomy\` (`master.yaml`, `candidates.json`, `promotion_log.jsonl`) | v1 vocabulary and the word-frequency candidates behind it |
| `...\ChatGPT_Export_Staging\tools\keyword_candidates.py` | v1 word-frequency pre-pass (the code that made the candidates) |
| `...\ChatGPT_Export_Staging\references\prompt-templates.md`, `hermes-skill-contract.md`, `current-runbook.md` (+ the parts of `technical-execution-spec.md` they point to) | v1 prompts, contract and steps |
| `...\classified\_runs\20260930T163151224482Z_smoke20\notes\` (the requested note plus the 18 others in that run) | v1 output |
| `P:\Codex\ChatGPT_Classification_v2\work\smoke-50-verified\` (every top-level JSON, `notes\`, `releases\`, `review-history\`, `objects\`) | v2 run, 967 files, and its 50 notes |
| This repo at `main` (`0bd2756`): `documents/notes.py`, `extraction/*`, `classification/*`, `taxonomy/*`, `ui/evaluation.py`, `providers/file_batch.py` | the current pipeline |
| `workspace/gold-real/knowledge.db` and two notes generated from it into a scratch folder (not committed) | what the current pipeline actually produces on real chats |

Two chats were used as the running comparison, because both old attempts produced notes for them: **chat A**, a 17-message game-design advice chat, and **chat B**, a 3-message speculative physics chat.

---

## 3. The old pieces, one at a time

### 3.1 The word-frequency pre-pass, categories, subcategories and YAML front matter

**v1 (Stage 1.5, `keyword_candidates.py`).** Standard-library TF-IDF over 1- to 3-word phrases of every message, with a stopword list and a "chat filler" list (`actually`, `maybe`, `thing`...). Phrases had to appear in at least 2 chats and at most 65% of them; the top 50 per chat were kept. Title words were *forced* candidates. A capitalised-phrase detector added named entities, and the taxonomy added alias hits. Each chat got three tiers: **must include** (title words and named entities, each with the message indexes where it appears and a short evidence snippet), **should include** (top 20 TF-IDF) and **optional** (the rest).

- *Good:* per-chat candidate lists with evidence; title accounting ("every title word is either used or excluded with a reason"); deterministic and free; the model chose from candidates instead of inventing terms.
- *Bad:* the vocabulary that grew out of it. `master.yaml` has seven fixed buckets that stayed **empty**, plus 240 terms **auto-promoted** because they appeared in 3+ notes. Many are junk as categories: single words like "new", "red", "high", "list", "request", "error", a two-letter fragment, a person's first name, and the names of TV shows. `candidates.json` holds 3,160 candidates, nearly all seen in only 1 or 2 chats. Lesson: **frequency is not a category**, and promotion without review fills the vocabulary with noise.
- *Categories:* one flat list of 11 (Ideas, Projects, Research Notes, Skills & Systems, Decisions, Content Assets, Templates & Prompts, Business / Offers, Learning / References, Archive, Unsorted). These describe *what kind of note*, not *what subject*. In the 19-note run, 5 chats went to "Archive", which tells you nothing.
- *Front matter:* about 45 fields. It had the right raw ingredients (category, `core_tags` 3 to 5 phrases, `supporting_tags` 5 to 10, `search_keywords`, `entities`, `projects`, `outputs_created`, `extracted_objects`, exclusions with reasons, statuses, hashes, run ID, model). But the same terms appear in four lists (`core_tags`, `supporting_tags`, `tags`, `search_keywords`: 31 entries for chat A), the model's own `reasoning` paragraph sits in the YAML, and misspellings are kept as entity names because nothing canonicalises them.

**v2 (`corpus-lexical-profile.json` -> `corpus-semantic-profile.json` -> `discovered-taxonomy.json` -> `subcategory-registry.json`).** A two-step approach:

1. **Lexical profile** of all 1,146 chats: 2- and 3-word counts, Unicode case-folding, **no stopword list**, 78,399 distinct terms, 46 MB.
2. A **model discovery pass on 50 chats** proposed keywords, intents, topics and tag candidates, then **corpus calibration** re-tiered each keyword by how rare it is across all chats (`corpus_specificity`), so a phrase used everywhere drops to secondary.
3. **Taxonomy discovery** from those 50: 10 categories with descriptions, 29 approved subcategories, 49 subcategory candidates still waiting, and 30 tags in four **facets** (activity, project, workflow, output). Each chat got a category and subcategory with evidence; a **separate reviewer** agreed on 48 of 50 and the 2 disagreements were recorded.

- *Good:* a two-level hierarchy with written descriptions; facets for "what kind of activity" separate from "what subject"; candidates kept apart from approved terms; an independent review recorded rather than hidden; keyword relevance calibrated against the whole corpus.
- *Bad:* the categories came from only 50 chats. Two of the ten are about AI safety and refusals ("AI Interaction & Ethics", "Harmful & Restricted Content"), which are about how ChatGPT behaved, not about Louis's work. Keywords are exact spans, so misspellings become primary keywords and fragments like "*X can be*" survive. Many chats ended with only 2 secondary keywords and a "limitation" note. The front matter for a 3-message chat is about 320 lines because every claim repeats its full evidence block (message UUID, revision hash, text hash, locator, description).

**Pooled lesson for the pre-pass:** keep v1's per-chat *must/should/optional with reasons* and v2's *corpus calibration, facets, two levels and candidate-vs-approved*. Add canonicalisation (a misspelling becomes an alias of the right term, not a label), discover from the whole corpus or a fair sample of it (the engine's NRM-006 sampler already includes rare themes), and never auto-promote.

### 3.2 Prompt templates, skill contract and runbook (format, content and steps)

**Prompt templates (v1).** One prompt per chat with: a short system role ("classifier for a personal knowledge base"), six numbered hard rules, the title and its tokens, the body as tagged messages, and a strict JSON answer. Rules: every title word used or excluded with a reason; 8 to 25 tags; list all proper nouns; 2 to 4 sentences of reasoning *before* the JSON; exactly one category; a 1 to 3 sentence summary "capturing the full arc and specific details". A **retry prompt** names each failure and the exact fix ("you produced N tags, you need at least 8"). A **relation prompt** writes one sentence of at most 20 words on *the specific shared concept* between two chats.

- *Worth keeping:* the summary instruction ("full arc and specific details"), the targeted retry message, and the one-sentence "why these chats are related" line.
- *Not worth keeping:* the 800-character truncation (later removed), reasoning stored with the answer, numeric tag quotas (they force padding), and a single flat category.

**Skill contract (v1).** Seven invariants, of which five are still right: raw chats are never discarded; archive success is separate from wiki readiness; model output is advisory until code verifies it; deterministic candidates run before the model; sub-agents may audit but must not write final notes. It defines a clear **status model** (`ingestion_status`, `curation_status`, `recommended_action`) and a **role split**: Python parses, extracts candidates, verifies and writes; the model classifies, chooses or rejects candidates, proposes objects and repairs flagged fields; the operator runs tools in order and stops at gates. That split is exactly what this repo already does with `ModelStageRunner` and the file-batch provider.

**Runbook (v1, v2.1).** Steps: tests -> parse -> candidates -> a frozen smoke ladder of 5, 10, 20, 50 chats from a fixed manifest; each stage advances only if the command passes, a *separate* full-transcript review passes every chat, and a disk-read audit passes every note. Failed runs are isolated, never published. Abort if 30% or more of a pass fails; at most two repairs per item; only transient errors retry.

- *Worth keeping:* the ladder with a frozen manifest; "smoke size means chats selected, not chats per request"; one transcript per request; failed runs never publish; the separate review context.
- *The flaw that sank it:* the "separate review" was another model call in the same pipeline, so the pipeline still graded itself and printed `ready_for_wiki`. This repo's rule (an independent session that never sees the output produces the reference set) fixes that.

### 3.3 The v1 smoke note (chat A)

**Shape:** 12 KB. Front matter of about 200 lines; the body has only three sections: **Source Links**, **Summary** and **Full Transcript** (inline, every message).

- *What was strong:* the **content**. The summary is four specific sentences covering the arc, what was built, the constraints chosen and what was left open, and it correctly says the assistant's suggestions were *not* adopted. The 14 `extracted_objects` are typed (project, decision, reusable process, idea, unresolved question) and each has message indexes and an exact quote. The decisions are the user's own words, not the assistant's. `outputs_created` names what the chat produced. The exclusion lists explain why each dropped term was dropped.
- *What was weak:* almost none of that is **readable** in Obsidian, because it lives in YAML. There is no knowledge card, no next steps, no insights, no tensions and no related chats. Each of the assistant's five suggestions became its own "idea" object, which over-splits one list. The category ("Projects") is a note type, not a subject. `classification_confidence: 0.97` and `ready_for_wiki` were the model's own verdicts.

### 3.4 The v2 smoke-50-verified data and note (chat B, and chat A again)

**Shape:** every one of the 50 notes has the same 15 sections: Summary, Editorial Knowledge Card, Category Analysis (with Pre-taxonomy discovery, Corpus-calibrated keywords and Independent taxonomy review), Subcategory Analysis, Conversation-Specific Analysis (Brainstorm Canvas), Next Steps, Action Items, Further Exploration, Key Decisions, Generated Insights, Tensions and Tradeoffs, Unresolved Matters, and Original Conversation. Every section states its **provenance** (Source-derived, Deterministic classification, Generated synthesis, Proposed follow-up). There are HTML and JSON projections and release manifests.

- *What was strong:* the **section list**, the provenance label on each section, the split between "proposed follow-up" and "source-derived", candidates kept apart from accepted labels, the reviewer verdict shown in the note, and a "not applicable, because..." line instead of silence.
- *What went wrong, measured over the 50 notes:*
  - **Size.** 4.3 MB for 50 notes; median 76 KB, largest 172 KB. Chat B (3 messages) became a 44 KB note. Chat A became 81 KB, against 12 KB in v1.
  - **Evidence noise.** 3,094 evidence blocks, each with a long hash, a UUID and the stock sentence "This message supports the generated...". Evidence excerpts are cut at a fixed 320 characters mid-word, and the cut text spills out of its bullet and breaks the Markdown, so stray quote fragments appear between sections.
  - **Filler.** 165 "Not applicable" blocks. A rule demanded five points per section; when a chat could not support five, the generator wrote five near-identical blocks titled with the chat's own title (6 notes) or a "not applicable" block with its own evidence.
  - **Wrong decisions.** In 22 of 50 notes "Key Decisions" is simply every user message relabelled "User direction at ordinal N", including a pasted role-play prompt at the start of the chat. That is a prompt, not a decision. Meanwhile the real decisions v1 found in chat A are not separated from the user's ordinary answers and questions.
  - **Contradictions inside one note.** Chat A's Next Steps names a design conflict the user raised, while its Tensions section says "not applicable, no conflicts".
  - **Numbering errors.** "Ordinal" counts from the first non-system message, but transcript headings count the system message, so "ordinal 15" is heading "Message 16". Some generated text cites the wrong message.
  - **Off-target analysis.** Some Action Items analyse the *assistant's* behaviour ("probe why the model refused...") instead of Louis's work.
  - **No second brain.** Related chats exist only in a JSON file: 17 links across 50 chats, 16 of them "shared theme", mostly "both chats contain a refusal". No note links to another note.
  - **Self-certification.** Every note says "Certified source note" in its header while its own front matter says `enrichment_status: review_required`. The "independent" acceptance came from model reviewers inside the same run.

---

## 4. Pooled findings: keep, fix, avoid

**Keep (from the old attempts):**

1. The v2 **section list** and **provenance label per section** (source-derived / classification / generated / proposed follow-up).
2. v1's **summary standard**: 2 to 4 sentences, the whole arc, specific details, and what was *not* decided.
3. v1's **typed knowledge objects** with exact quotes, and its rule that a decision is the user's own words.
4. v1's **must / should / optional candidates with exclusion reasons**; v2's **corpus calibration** and **facets**.
5. A **two-level category > subcategory** taxonomy with descriptions, candidates separate from approved terms, and a recorded reviewer verdict.
6. The **frozen smoke ladder** and "failed runs never publish".
7. The **one-sentence related-chat reason** prompt.

**Fix (they had the idea, the execution failed):**

1. Evidence: a short citation like `[m12]` that links to the transcript anchor, with the quote in a **collapsed** block. Hashes go in a sidecar, not in the note.
2. Empty sections: one plain line ("Nothing was decided in this chat.") and no evidence block. No quotas.
3. Decisions: only user-held, with the acceptance quote and the proposal it accepts (the current EXT-003 rule), and never a pasted prompt.
4. Message numbers: one numbering, the transcript's.
5. Related chats: wikilinks to the other chat's note with a plain reason, in the note itself.

**Avoid:** auto-promoting frequent words; flat note-type categories; the model's reasoning in front matter; tag quotas; inline full transcripts in the knowledge note (the current engine's separate transcript note is better); any "certified" or "ready" label written by the pipeline about itself.

---

## 5. What the current pipeline produces

Checked on `workspace/gold-real` (the real import) and by generating notes for chat A and chat B with `ke docs chat` into a scratch folder.

| Piece | What exists in code | What it produces on the real chats |
|---|---|---|
| Import, branches, images, links, videos, accounts | Complete (M1, M2) | 1,158 chats, all with transcript notes and anchors. Strong. |
| Segmentation (NRM-004) | Complete | Segments exist; a short chat is 1 segment. |
| Taxonomy (TAX-001..008) | Registry, review, discovery (TF-IDF or BERTopic), publish | **0 terms, 0 published versions** in the real workspace. Discovery has never been run on real chats. |
| Classification (CLS-001..005) | Keyword scorer by default; model path through `ModelStageRunner` | **0 classifications.** Without a taxonomy nothing can be labelled. The one paid smoke run (synthetic chats) sent 67 of 67 answers to review; most were a parsing bug on our side (`[m:id]` tags, already the next task in `STATUS.md`). |
| Extraction (EXT-003..006) | Rule-based cue phrases ("I've decided", "you could", "I prefer"...) plus a `ModelExtractor` adapter that no stage uses yet | 264 records from 85 segments: 99 artefacts (mostly "1 produced image or file use(s)"), 57 requirements, 47 preferences, 25 references, 19 proposals, 16 actions, **0 decisions, 1 rejection, 0 questions**. Chat A: 0 records. Chat B: 0 records. |
| Conversation note (DOC-003) | Summary of counts, classification per segment, knowledge records with quotes, branches, images, links, videos, accounts, related chats | Chat A: "17 messages, 0 branches, 1 segment, 0 records... 1 related chat", "No taxonomy version was given", "No knowledge records". The one related chat is a lexical "quotes" link, most likely the shared pasted role-play preamble, not a shared subject. |
| Relationships (REL-002/003) | Native forks, copied prefixes, quotes, chatgpt.com links; semantic and project relatedness | 125 candidates (56 lexical quotes, 51 forks, 18 references), all unreviewed. No "same project" or "same topic" links yet, because there are no projects or topics. |
| Dashboard (`ke ui`, UI-006) | Counts by state, scores against a private answer key, one output at a time, model ledger | Honest and useful for *judging the engine*, but it has nothing to *read about a chat*: no summary, no category, no decisions. That is why it feels interesting but thin. |

**Small bugs found on the way:** the console prints a replacement character instead of the note's file name on Windows when `ke docs chat` reports what it wrote (the file itself is named correctly). The boilerplate rule for quote links (a paragraph in more than five chats) does not catch a pasted preamble used in five or fewer chats.

---

## 6. The gap, section by section

"v1", "v2" and "now" say whether each attempt had the section. "Needed" is what closes the gap.

| Section | v1 | v2 | Now | Needed |
|---|---|---|---|---|
| **Summary** (2-4 sentences, the arc, specifics, what stayed open) | Yes, good, in YAML and body | Yes, shorter, padded with evidence | **No**: counts only | Model-written digest summary, every sentence cited to messages (NOTE-002/003) |
| **Knowledge card** (purpose, outcome, status, category, subcategory, project, tools/entities, date, length) | No (fields scattered in YAML) | Partial: purpose and labels only | **No** | Rendered from the digest plus stored facts (NOTE-001) |
| **Category analysis with evidence** | One flat label, no analysis | Yes, plus reviewer verdict | **No**: no taxonomy | Publish taxonomy v1 (NOTE-006), roll segment labels up to the chat (NOTE-008) |
| **Subcategory analysis with evidence** | No | Yes, with candidates | **No** | Same as above, second level |
| **Intent candidate** | No | Yes | **No** | Digest field, with evidence (NOTE-002) |
| **Topic candidates** | No | Yes | **No** | Digest field; unmatched topics become taxonomy *proposals*, never labels (NOTE-007) |
| **Keyword candidates** (primary/secondary, with reasons and exclusions) | Yes, strong | Yes, weaker (fragments, misspellings) | **No** in notes (TF-IDF theme words exist only inside discovery) | Deterministic per-chat candidates, canonicalised, corpus-calibrated (NOTE-007) |
| **Tags** (facets: activity, output, project) | Flat lists, duplicated | Yes, faceted | **No** | Taxonomy dimensions already support this (OD-17); needs the published taxonomy |
| **Key decisions** (user-held, with acceptance) | Yes, correct | Wrong in 22/50 | Rule extractor exists; **0 found** on real chats | Model-backed extractor under the existing EXT contract (NOTE-005) |
| **Proposals and ideas** (assistant suggestions, not adopted) | Yes, over-split | Mixed into other sections | 19 proposals by rule | Same extractor; group a list of suggestions into one record |
| **Action items** (the user's own commitments) | A few | Generated, often off-target | 16 by rule | Extractor for user-held actions; keep separate from next steps |
| **Next steps** (suggested follow-up, clearly generated) | No | Yes, labelled "proposed follow-up" | **No** | Digest field, labelled generated (NOTE-002) |
| **Generated insights** | No | Yes, some good | **No** | Digest field, labelled generated, each cited |
| **Tensions and tradeoffs** | No | Yes, but contradicted itself | **No** | Digest field; consistency check against next steps (NOTE-011) |
| **Unresolved matters / open questions** | One object type | Yes | Question extractor exists; **0 found** | Digest field plus extractor |
| **Outputs created** | Yes | A fixed list of file types | Artefacts by rule (images, code blocks) | Show artefacts by name, not "1 produced image" (NOTE-001) |
| **Entities and references** | Yes, misspelt | Inside keywords | 25 references by rule | Canonicalise through aliases; show in card |
| **Links, images, videos, accounts** | Images only | No | **Yes**, complete | Keep as is |
| **Branches** | No | No | **Yes** | Keep as is |
| **Related chats (second brain)** | No (relation prompt only) | JSON only, 17 weak links | Yes, but lexical and unreviewed | Same project / topic / entity links, a one-line reason, wikilinks to the other *note*, preamble filter (NOTE-009) |
| **Provenance per section** | No | Yes, too verbose | Records carry trust and actor | One label per section, short citations (NOTE-001/010) |
| **Readable formatting** | Poor (YAML) | Poor (noise) | Plain but empty | Template in §7 (NOTE-010) |
| **Independent quality check** | Self-graded | Self-graded | Answer-key scoring exists for records and labels | A rich-note rubric scored by a separate session (NOTE-011, needs Louis's approval) |

---

## 7. Proposed note template

One note per chat in `Knowledge/`, beside the existing transcript note in `Sources/`. The transcript stays separate and every citation links into it.

**Formatting rules:**

- Readable content first, evidence second. A reader should get the point from the first screen.
- A citation is `[m12]`, a link to `[[<transcript>#^node-…|m12]]`. `m12` is the transcript's own message number, the same number the transcript heading shows.
- Quotes live in a **collapsed callout** under the item (`> [!quote]- Evidence`), at most two per item, each cut at a word boundary and marked with "…".
- Every section says where it comes from in a small label: *From the chat*, *Classification*, or *Generated (check before relying on it)*.
- An empty section is one plain sentence. No evidence block, no padding, no quota.
- Front matter holds only what Obsidian or Dataview needs. Hashes, run IDs and stage keys go in a JSON sidecar (`Knowledge/.meta/<id>.json`).
- A note for a 3-message chat should fit on one or two screens. A soft budget (about 2 KB of body per 10 messages, never more than 40 KB) is checked in tests.

```markdown
---
ke_type: conversation_knowledge
title: "<chat title>"
conversation_id: conv_…
date: <YYYY-MM-DD>
messages: <n>
category: "<Category>"                  # approved label, or "unclassified"
subcategory: "<Subcategory>"
facets:
  activity: [<activity facet>]
  output: [<output facet>]
project: "[[Project note]]"              # only if an approved project matches
tags: [<approved-term>, <approved-term>]   # approved terms only
status: open                             # open | settled | abandoned (from the digest)
related: ["[[Other chat knowledge note]]"]
transcript: "[[<transcript note>]]"
taxonomy_version: tax-v1
digest: generated · reviewed: no
---

# <chat title>

> [!summary] Summary · *Generated, every sentence cited*
> Two to four sentences: what Louis was trying to do, what was built or decided,
> what the assistant suggested, and what was left open. [m4] [m10] [m16]

## Knowledge card
| | |
|---|---|
| **Purpose** | one line [m4] |
| **Outcome** | one line: decided / explored / abandoned [m12] |
| **Category** | <Category> › <Subcategory> (classification, 0.82) |
| **Project** | [[Project note]] or "none matched" |
| **Tools and names** | canonical names of tools, products and works mentioned |
| **Made in this chat** | e.g. a list of suggestions (assistant), 1 code block, 2 images |
| **Length** | 17 messages, 1 segment, no other branches |

## Decisions
*From the chat: the user's own words only*
- **<What the user decided, in a short phrase>.** Accepted in [m8], answering the question in [m7].
  > [!quote]- Evidence
  > m8 (user): "…"

## Suggestions not taken up
*From the chat: the assistant proposed, the user did not accept*
- <The assistant's list of options, as one item> [m17]. Status: open.

## Action items
*From the chat: things the user said they would do*
- None in this chat.

## Open questions
- <A question the user left open> [m16].

## Insights
*Generated (check before relying on it)*
- One to three observations that connect points across the chat, each cited.

## Tensions and trade-offs
*Generated*
- <Goal A> versus <goal B>, as the user described it [m16].

## Next steps
*Generated suggestions, not things Louis said*
- One to three concrete follow-ups, each tied to an open question above.

## Category and subcategory
*Classification under tax-v1*
- **<Category> › <Subcategory>**, primary, from segment 1. Why: one sentence [m4] [m16].
- Reviewer verdict: agree / disagree / not reviewed.
- Candidates waiting for review (not labels): "<proposed subcategory>".

## Keywords and topics
*Candidates. Only approved terms become tags*
- **Intent:** <what the user wanted from the chat> [m4]
- **Topics:** <topic>, <topic>, <topic>
- **Keywords:** primary: …; secondary: …; left out: "<term>" (role-play wording, not a subject)

## Related chats
- [[Other chat knowledge note]]: same project, picks up the open question above (structural, reviewed).
- [[Another chat knowledge note]]: shares the topic "<topic>" (topic, candidate).

## Links, images, videos and accounts
(the existing sections, unchanged)

## Branches
(the existing section, unchanged)

## Source
[[<transcript note>]] · digest by a Claude session on <date>, not yet scored · taxonomy tax-v1
```

---

## 8. Proposed tickets

Approved under D1. Each becomes a GitHub Issue (opened by a session with GitHub access). IDs use the unused `NOTE-` prefix. Each has a concrete finish line and is small enough for one PR. "Blocked by" lists hard dependencies only. Fix attempts: 3 per ticket, then stop and ask.

| ID | Ticket | Blocked by | Finish line |
|---|---|---|---|
| — | **Prerequisite (already queued):** normalise the `[m:id]` evidence tag before the segment check (#255 follow-up) | — | The saved paid-run answers replay with 0 `evidence_outside_segment` caused by the tag format |
| NOTE-001 | **Note template v2 renderer (deterministic parts).** New section order, knowledge card from stored facts, `[m12]` citations with transcript numbering, collapsed evidence callouts, one-line empty states, slim front matter plus JSON sidecar, artefacts shown by name, the length budget. Fix the console file-name print. | — | Golden Markdown for 3 synthetic fixtures; `ke docs check` passes; body under budget; existing DOC-003 tests keep passing (a new golden is added, old ones are not edited) |
| NOTE-002 | **Conversation digest contract.** Pydantic schema, `extra="forbid"`: summary sentences, purpose, outcome, status, intent, topics, insights, tensions, open questions, next steps. Every item lists message IDs and short quotes; provenance is fixed per field. Quotes checked with NRM-003; an unfound quote drops the item and flags it. | — | Schema tests: invented fields, uncited items, quotes not in the chat and wrong message IDs are all refused |
| NOTE-003 | **Digest stage behind the provider switch.** One request per chat (active path, branch summary, chunking when over budget, never clipping), stage key covers text and versions, cache, one repair, `review_required` after. Default provider in tests: `FakeProvider`. | NOTE-002 | Fake-provider tests: cache gives zero new requests on rerun; invalid answer gets one repair then review; egress off writes nothing |
| NOTE-004 | **Claude-session runbook for digests.** Extend `docs/runbooks/LABELLING_SESSION.md`: how a session on Louis's subscription fills digest request files (fresh context per file, inputs as data, append-only), how usage limits pause and resume, and that the session never sees the reference set. | NOTE-003 | Dry run on 3 synthetic chats end to end: request file -> session answers -> collect -> note |
| NOTE-005 | **Model-backed knowledge extractor.** Wire the existing `ModelExtractor` for decision, proposal, action and question (the EXT-001 contract and acceptance rules unchanged). Group one list of suggestions into one proposal. Ignore pasted role-play or system-style preambles as decision sources. | NOTE-003 | Fake-provider tests: assistant suggestion never becomes a user decision; a pasted preamble gives no decision; records pass EXT-002 |
| NOTE-006 | **Taxonomy v1 from the whole corpus.** Run discovery over the NRM-006 fair sample of all chats; a Claude session names groups and writes descriptions as TAX-004 proposals (category > subcategory, plus activity and output facets); a separate Claude reviewer session reviews; publish after Louis's decision D2. Exclude "how ChatGPT behaved" groups from subject categories (they can be a facet). | — | A published `tax-v1` with descriptions; the taxonomy QA report (TAX-008) shows no duplicates, orphans or loops |
| NOTE-007 | **Per-chat keyword and topic candidates (deterministic).** Port v1's must/should/optional with reasons: title words, TF-IDF 1-3-grams with a filler list, v2-style corpus calibration, alias canonicalisation (misspellings map to the right term), exclusions with a reason. Unmatched topics become taxonomy proposals, never labels. | NOTE-006 for matching (works without it, unmatched) | Unit tests on synthetic chats, including a misspelt entity, a pasted preamble and a title word that is excluded |
| NOTE-008 | **Category and subcategory section.** Classify segments under `tax-v1`, roll up to a chat-level primary (share of messages) with secondaries, show the reason and citations, the reviewer verdict and waiting candidates. | NOTE-006, prerequisite above | Golden note for a two-topic synthetic chat shows both, with the larger as primary |
| NOTE-009 | **Related chats for the second brain.** Add same-project, same-topic and shared-entity links (REL-003 already proposes them), a one-sentence reason (v1 relation prompt, via the digest stage), wikilinks to the other chat's knowledge note, and a preamble filter so a shared pasted prompt is not a "quote" link. | NOTE-006, NOTE-007 | Fixture: a shared preamble gives no link; two chats on one project link both ways with a reason |
| NOTE-010 | **Readability pass and note budget.** Apply §7 across topic and project masters too; Dataview-friendly properties; a check that fails a note that is over budget or has an empty-section evidence block. | NOTE-001 | `ke docs check` reports budget and empty-section problems; all fixture notes pass |
| NOTE-011 | **Rich-note quality rubric and independent scoring.** *New evaluation criterion, needs Louis's approval (D4).* Code checks: every claim cited to a real message; decisions user-held with an acceptance quote; no contradiction between tensions and next steps; numbering matches the transcript. Plus: a separate Claude session (a different model where possible), which never sees the engine's notes, writes reference digests for 15 to 20 chats; a third session scores engine notes against them. The record states which sessions did what. | NOTE-003, NOTE-005 | A scored report in `docs/evaluation/`, with the reference set's provenance |
| NOTE-012 | **Dashboard: read a chat.** On `/chats/<id>`, show the rendered knowledge note beside the transcript, and a "notes" view listing chats by category with their status and open questions. | NOTE-001, NOTE-008 | UI tests: a chat page shows summary, card and decisions; links open the right message |
| NOTE-013 | **Ladder run on real chats.** Gold 40, then 50, then all 1,158, through Claude-session batches on the subscription. Each step only after the previous one scores and passes NOTE-011; failed runs never publish. | NOTE-001..011 | A diary entry with counts, scores, time and how many sessions it took |

**Suggested order:** prerequisite, NOTE-001, NOTE-002, NOTE-003, NOTE-004, NOTE-006, NOTE-007, NOTE-005, NOTE-008, NOTE-009, NOTE-010, NOTE-011, NOTE-012, NOTE-013. NOTE-001 can start now and makes every later step visible. NOTE-006 can run in parallel with NOTE-002/003 because it touches different files.

**How the AI steps run without paid calls.** Every model step (digest, extractor, discovery naming, relation reason) goes through the existing `StructuredModelProvider` interface. In tests it is `FakeProvider`. On real chats it is the file-batch provider: the engine writes request files to `private/model-batches/`, a Claude Code session on Louis's subscription answers them, and the engine validates every answer in code. The `text_llm` switch is turned on only for that run. The reference set for scoring is made by a different session that never sees the engine's output.

---

## 9. Decisions (taken 2026-10-28, as recommended)

Louis approved every recommendation below on 2026-10-28 at 12:50 UTC ("Go ahead with the recommendations and verifications"). The prerequisite in §8 (`[m:id]` evidence tag) was already fixed on main in #266. Quality scores for notes (NOTE-011) must come from a session that did not write them.

| # | Decision | Decided (as recommended) |
|---|---|---|
| D1 | **Priority.** Do the NOTE tickets next, ahead of PROD-004 and the rest of the parked product work? | Yes. Rich notes are the product; the plumbing is already ahead of the content. |
| D2 | **Who approves taxonomy v1.** (a) You approve the publish after a Claude reviewer session has checked every proposal, from one summary page, without labelling anything; or (b) you delegate approval fully to an independent Claude reviewer session. | (a). It is one look at about 10 categories and 30 to 40 subcategories, and the taxonomy shapes everything after it. |
| D3 | **Generated sections.** Show insights, tensions and next steps in the note, clearly labelled as generated? Or only what is said in the chat? | Show them, labelled, with citations. They were the most useful part of v2 when they were right. |
| D4 | **New quality rubric (NOTE-011).** It adds evaluation criteria, so it needs your approval. It does not change any existing test or the gold set. | Approve it, so "rich" is measured by someone other than the pipeline. |
| D5 | **Where synthesis lives.** (a) A separate "conversation digest" for generated content, with knowledge records kept for claims (decisions, proposals, actions, questions); or (b) new record types for insight, tension and next step. | (a). It keeps the record contract's trust rules clean: a generated insight should never sit next to a confirmed decision as if it were the same kind of thing. |
| D6 | **Category style.** v2-style subject categories with subcategories, plus facets (activity, output), or v1-style note types (Ideas, Projects, Archive...). | v2 style. "Archive" told us nothing about a third of v1's chats. |
| D7 | **First real run size and pace.** Gold 40 first, through Claude-session batches, accepting it may take several sessions because of usage limits. | Yes. Start with 40, look at five notes yourself as a reader (not a labeller), then decide on 50 and the full corpus. |
| D8 | **Transcript placement.** Keep the full transcript as a separate linked note (now), or inline it at the bottom of the knowledge note (as v1 and v2 did). | Keep it separate. The knowledge note stays short and every citation still jumps to the exact message. |

---

## 10. Talking points

- "My first two attempts had the right *sections* but the wrong *trust model*: the pipeline graded itself and stamped its own notes 'certified'."
- "The rebuild got the hard plumbing right first: branches, images, links, exact quotes. Now the meaning goes on top, with every sentence cited to a message."
- "Frequency isn't a category. The old vocabulary auto-promoted words like 'new' and 'red'. The new one is discovered, reviewed and versioned."
- "Evidence should be one click away, not 3,000 copies of a hash in the reader's face."
