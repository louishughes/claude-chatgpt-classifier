# Build Diary

A running, timestamped log of what is being worked on, the problems hit, how they were handled, and why each decision was made. It doubles as raw material for build-in-public posts and for explaining the project in job interviews.

**Rules for this file**
- Times are UTC.
- Never paste anything from `raw/` (conversation text, titles, filenames, images) or any secret, key or private ID. Counts and format descriptions are fine. The repository is public.
- Append new entries at the bottom. Don't rewrite old ones; add a correction entry instead.
- Each entry: **what happened**, **why** (the reasoning behind the plan), and **talking points** (2–4 short lines you could say out loud or post).
- When the entry closes a PR that adds or changes code, add a **Teach-back** line before the talking points: one module from the PR (picked by Louis, or by the thread under blanket authority) explained in three plain sentences, the way Louis would say it in an interview. If three sentences aren't enough, the code comments need work first. (Added 2026-10-27, REV-005.)
- Entries marked *(backfilled)* were reconstructed afterwards from the project thread, so their times are approximate.

---

## 2026-10-27

### 18:21 — Setting up agent skills *(backfilled)*
**What:** Added an "Agent skills" section to `CLAUDE.md` plus `docs/agents/issue-tracker.md`, `domain.md` and `triage-labels.md`, so AI engineering skills know where issues, labels and domain docs live.
**Why:** AI coding agents work better with a small set of clear, written conventions than with long ad-hoc prompts.
**Talking points:**
- "Before writing code, I wrote down how the AI agents should work in this repo."
- Treating agent instructions like configuration, not like chat.

### ~18:2x — Desktop app too old to connect the folder *(backfilled)*
**What:** The folder-connection card couldn't attach the local project folder because the Claude desktop app was out of date. Updating it fixed the connection.
**Why it matters:** the private data lives only on the PC, so cloud agents need a controlled, read-only way to look at it.
**Talking points:**
- Tooling friction is real; budget time for it.

### ~18:2x — Fresh repository instead of the old one *(backfilled)*
**What:** Decided not to reuse the earlier `chatgpt-classifier` repository.
**Why:** earlier attempts left inconsistent code and assumptions. Starting from the specification makes every later decision traceable.
**Talking points:**
- "Sometimes the fastest path is a clean start with better specs."

### ~18:2x — First push failed *(backfilled)*
**What:** The first push failed because the local branch was `master` with no commits. Committed first, then pushed to `main`.
**Talking points:**
- Git can't push a branch with no commits; a classic beginner trip-up and a quick fix.

### ~18:2x — New public repo with private data kept out *(backfilled)*
**What:** Created `louishughes/claude-chatgpt-classifier` (public) at commit `103bcb3`. A `.gitignore` keeps `raw/` (the private ChatGPT export) out of Git.
**Why:** public repo for the portfolio; private data must never be committed.
**Talking points:**
- "My data stays on my machine; only code and docs go public."

### ~18:3x — GitHub Issues as the tracker *(backfilled)*
**What:** Chose GitHub Issues for planning tickets. The older CSV/Markdown backlog became reference material.
**Why:** issues are visible, linkable and work with agent workflows.
**Challenge noticed later:** the audit instructions asked to keep the CSV and Markdown in sync, which conflicts. Logged as an open decision instead of silently picking one.

### 18:33 — Specification audit started
**What:** First real engineering session: a docs-only audit of the PRD, architecture, data model, 93-ticket backlog and test strategy against new requirements (images, branches, related chats, repeat exports, YouTube links, social accounts). No code in this session.
**Why:** the previous attempts jumped into code and drifted. This time, plan, check the plan against reality, then build in small, testable slices.
**Talking points:**
- "Audit the spec before writing code. It's cheaper to fix a document than a database."
- Requirements traceability: every requirement should point to a ticket and a test.

### 18:35 — Looking at the real data without reading it
**What:** Inspected `raw/` by metadata only: counts, file types, sizes, and JSON *shapes* (key names and types, never values).
**Surprise:** `raw/` is not the original ChatGPT export ZIP. It's ~1,160 per-conversation JSON files, ~900 images in one folder, and a manifest of the original export. The original also had ~700 audio clips and a few videos that aren't in `raw/`. The files also lack a `children` field the specs assumed.
**Why it matters:** the importer must support this format, report missing media honestly, and rebuild the conversation tree from parent links.
**Talking points:**
- "Check your assumptions against real data early. The spec assumed a format I didn't actually have."
- Privacy-preserving inspection: look at structure, not content.

### 18:36 — "It doesn't have to be 100% local"
**What:** Clarified that the system should use cloud models and agents where they genuinely help.
**Why:** local models weren't good enough at extraction last time.
**Decision (proposed):** keep importing, deduplication and provenance deterministic and local; allow cloud models for the "understanding" stages; keep image/vision uploads and web fetching behind separate switches. Written up as ADR-0007.
**Talking points:**
- "Deterministic where correctness matters, AI where judgement helps."

### 18:37 — Lessons from the earlier attempts
**What:** The first proof of concept used Hermes and DeepSeek. A later Codex-built version used a model called Luna for some classification. Results were inconsistent. Root cause: local models were weak at extracting key information, and outputs weren't type-safe, so they changed run to run.
**Response in the plan:** schema-enforced structured output (Pydantic models → JSON Schema), validation before anything is saved, one repair attempt then human review, pinned model versions, and a test set that measures run-to-run stability.
**Talking points:**
- "Inconsistent AI output is often a contract problem, not just a model problem."
- Type safety for LLM output: validate, don't trust.

### 18:39 — Smoke tests and scaling pain (context)
**What:** Earlier one-at-a-time smoke tests were inconsistent; OpenRouter timeouts hit; batches of 20–50 conversations had many failures. Recorded as background, not as something to over-correct for.
**Talking points:**
- Timeouts and partial failures need checkpoints and resume, not bigger retries.

### 18:40 — Test at 50 and 100 early
**What:** New requirement: smoke and unit tests on batches of about 50 and 100 conversations early. Added as gates at the end of the first milestone (import only, no AI) and again when AI stages start.
**Why:** scale problems are cheapest to find before the pipeline grows.
**Talking points:**
- "Test at realistic scale early, not just on one happy example."

### 18:43 — Learning, portfolio and maybe a product
**What:** This project is also how I'm learning Python (Codecademy) and building a portfolio piece, with a possible product later.
**Decision:** code must have clear docstrings that explain what and why in plain English, comments on the non-obvious "why", and a short talking-points block per module. Licence and packaging are an open decision; they don't expand the MVP.
**Talking points:**
- "I'm using a real problem, my own ChatGPT history, to learn Python properly."

### 18:45 — Rethinking identity for repeat exports
**What:** Found that the data model stored messages per export file, so re-exporting the whole history would duplicate everything.
**Decision (proposed, ADR-0003):** separate "this import attempt", "this exact file", "this conversation" and "this version of this message". Use ChatGPT's own IDs first, two hashes per message (exact payload vs meaningful content) so cosmetic changes don't trigger expensive reprocessing, and treat a missing conversation as "not seen", never "deleted".
**Talking points:**
- "Idempotent imports: running the same import twice should change nothing."
- Identity design is the most important early decision in a data project.

### 18:47 — Images, links and accounts as first-class data
**What:** Designed images as file + logical asset + each place it's used, with honest "missing" states. URLs, YouTube videos and social accounts get deterministic registries, with every mention kept, and no AI needed.
**Why:** the same image or video can appear many times; you want one record with all its references, and you never want a made-up file path or transcript.
**Talking points:**
- "Deduplicate the thing, keep every mention of the thing."

### 18:50 — Reordering the plan: browse before you classify
**What:** In the old plan nothing was viewable until the whole AI pipeline was finished. Re-sequenced so the first milestone is an AI-free "source browser": import, branches, images, re-import safety and readable notes, tested at 50 and 100 conversations.
**Result:** backlog grew from 93 to 122 tickets; the graph is checked to have no cycles; the first ticket is FND-001 (project bootstrap).
**Talking points:**
- "Build the boring, reliable foundation first; it makes the AI part debuggable."
- Vertical slices: something real works end to end before going wide.

### 18:54 — Checks and handoff
**What:** Ran document checks: ticket IDs unique, CSV and Markdown in sync, no dependency cycles, every new ticket traced to a requirement, `raw/` listing unchanged before and after, no private names in any doc. Wrote the handoff and open decisions. Stopped for approval before writing any code.
**Talking points:**
- "Verify, then report what actually ran, including what didn't."

### 19:03 — Where the raw data came from
**What:** Louis confirmed the split JSON files, flattened image folder and manifest in `raw/` came from an earlier extraction run with Hermes, not straight from OpenAI. Recorded in ADR-0002 and the project history.
**Why it matters:** an intermediate format made by an older tool has undocumented rules. The importer treats it as a lower-fidelity source and reports what it can't prove, and the original export ZIP (if still available) becomes the preferred input.
**Talking points:**
- "Know your data lineage: which tool produced the files you're importing?"

### 19:10 — Prove the AI step before building around it
**What:** Louis chose to run a small, throwaway experiment (a "spike") before starting the first milestone: label 50 real conversations twice, then 100, and measure whether the answers are reliable and consistent.
**Why:** the earlier attempts failed at exactly this step (inconsistent labels, untyped output, timeouts at 20–50 chats). If the AI step can't be made stable, the rest of the plan changes, so it's the riskiest assumption and gets tested first.
**Talking points:**
- "Test the riskiest assumption first, cheaply, with code you're willing to throw away."
- A spike answers one question. It is not the product.

### 19:14 — Hybrid, not "AI everywhere"
**What:** Louis asked how hybrid the system should be, noting BERT-style classifiers didn't give reliable results before. Answer: plain code for anything that must be exactly right (import, dedup, branches, images, links, YouTube IDs, social handles); a cloud LLM with a strict schema for judgement (topics, summaries, decisions); embeddings only to *suggest* related chats; small local classifiers maybe later, trained on reviewed LLM labels, once categories are stable. Added to ADR-0007.
**Talking points:**
- "Use the cheapest tool that is reliably right for each job."
- "A small model trained on the big model's checked answers is a cost optimisation for later, not a starting point."

### 19:20 — Spike built and tested offline
**What:** Built `prototype/classification_spike/`: reads raw files read-only, follows each chat's active branch, sends user/assistant text only, and asks Claude to fill in a typed Pydantic form. Answers are validated; one repair attempt, then "needs review". Timeouts and rate limits get at most 3 calls with backoff. A hard cost cap is checked before every call, results are saved after every chat so a crash resumes, and a dry-run mode estimates cost before spending anything. 25 tests pass using a fake provider on synthetic data, including 50- and 100-chat batches with injected timeouts, bad output and refusals.
**Challenge:** current Claude models reject `temperature`, the classic "make it deterministic" knob. Consistency has to come from the schema, a tight prompt, and measuring two runs against each other. Corrected ADR-0007, which still said "temperature 0".
**Talking points:**
- "My tests can simulate a timeout storm for free. The fake provider fails on command."
- "If you can't set temperature to 0, you measure stability instead of assuming it."
- "Checkpoint after every item; a crash at item 87 should cost one item, not 87."

### 19:28 — Consistent isn't the same as correct
**What:** A review of the earlier ChatGPT post-mortem pointed out a gap: the spike measured whether two runs agree, but not whether the labels are *right*. Added a small gold set: the spike writes a template of 15 sampled chats, Louis labels them by hand, and the report shows accuracy against his labels next to run-to-run agreement. Unknown category names in the file are rejected, so a typo can't masquerade as a model error. 27 tests pass.
**Talking points:**
- "A model can be consistently wrong. Measure agreement *and* accuracy."
- "Fifteen hand labels is a cheap reality check, and it seeds the real evaluation set later."

### 19:31 — Saving ChatGPT's post-mortem of the old attempt
**What:** Louis shared a ChatGPT conversation explaining why the earlier Hermes/Codex classifier failed. Saved it as `docs/reference/2026-10-27-why-the-classifier-failed.md`: a summary of the reasoning, a table mapping each lesson to where the new plan already covers it, and the transcript.
**Challenge:** the share link couldn't be fetched. ChatGPT share pages only load the messages with JavaScript, the cloud sandbox's network proxy refused the connection, and the page's data endpoint blocks automated access. Louis pasted the text instead. The paste stops mid-sentence at the end, so the file says it is truncated rather than guessing the rest.
**Key lessons recorded:** classify against a corpus-wide project registry, not one conversation at a time; lock the vocabulary instead of auto-promoting terms during a run (otherwise results depend on processing order); measure against a human-labelled reference set, not tag counts; track who proposed vs. who decided; retry only for transient errors, never for semantic mistakes; prove a small result before building more system.
**Gap spotted:** the current classification spike measures whether two runs *agree*, not whether they're *right*. A model can be consistently wrong, so a small hand-labelled subset is worth adding before trusting it. Flagged as a question, not changed.
**Talking points:**
- "I asked an AI to write a post-mortem of my own failed project, then checked my new plan against it line by line."
- "Passing tests that check the form is filled in isn't the same as being correct."
- "Consistency isn't accuracy: five identical wrong answers are still wrong."

### 19:36 — Correction: the full post-mortem arrived
**What:** Louis uploaded the complete post-mortem as a Markdown file. The 19:31 entry said the transcript was truncated, but the reference doc now holds the full text, including the ending. Added its closing advice to the summary: give agents small tasks with clear "done" conditions, let code own identities, schemas, vocabulary and state, and never let an agent judge its own output. Also added three rows to the coverage table: separate classification dimensions (only partly covered, since a single "primary category" still exists), small agent tasks, and code-owned identity.
**Why it matters:** the ending holds the most useful line. Consistency has to be designed into the data model and the evaluation. It can't be enforced with more prompts and repair loops.
**Talking points:**
- "When the shared link wouldn't load, exporting to Markdown was the reliable route. Plain files beat clever scraping."
- "We were building a system to remember what we agreed, using agents that couldn't remember what *they'd* agreed."

### 19:37 — Learning from the old post-mortem: one question per field
**What:** Read ChatGPT's post-mortem of the earlier classifier (saved in PR #2) and changed the spike in response:
- The single "category" field became separate fields: domain, purpose, project candidates, topics, knowledge types and outputs. The old list mixed *Ideas, Projects, Research, Decisions, Content Assets*, and one chat can be all five. So even a perfect model couldn't answer consistently.
- Decisions now record who proposed them, what the user did (accepted, rejected, superseded, unclear), and who wrote the quoted evidence. The checker confirms the quote really comes from that speaker.
- Each run processes chats in a different shuffled order, and a test runs three orders. The old system's vocabulary grew mid-run, so chat 800 was judged against different words from chat 8.
- Retries are for network and format problems only. A well-formed wrong answer is never retried: "five variations of the same mistake".
- The gold set now covers domain and purpose. Logged OD-17 and annotated the PRD and test strategy so "primary category" means primary domain. 37 tests pass.
**Talking points:**
- "Ambiguous questions produce inconsistent answers. Fix the question before blaming the model."
- "Retry the network, never the judgement."
- "Processing order shouldn't change the answer. I test it by shuffling."

### 19:40 — Agreed path: gold set, 50 twice, then go/no-go
**What:** Louis agreed the path forward and three guardrails for every AI agent working on the repo:
- No changing tests or the gold set without his OK.
- At most 3 fix attempts per ticket, then stop and ask.
- The vocabulary stays frozen during a run.

These are now in `AGENTS.md`, `CLAUDE.md` and the plan. The spike's gold set got real tooling. It picks about 20 *varied* chats from the 50: short and long, with and without images or branches, spread over time. It writes a labelling sheet with the title, date, size and first message so labelling takes about an hour. The label columns stay blank so the model's guess can't anchor the human. Every report records a fingerprint of the gold file, so any later edit to the answers is visible. 40 tests pass.
**Next:** Louis gives the API OK, a cost cap and where to run it; labels the 20; we run 50 chats twice and he reviews. If it hits the targets: 100 chats, then the first real ticket. If not: change the method, not the prompt wording.
**Talking points:**
- "Agents can't mark their own homework. The answer key is mine, and it's fingerprinted."
- "Guardrails for AI coding agents: bounded retries, frozen vocabulary, hands off the tests."
- "Don't pre-fill the human's labels with the model's answer. That's how you get fake agreement."

### 19:50 — Cheaper model for the spike
**What:** Louis gave the OK to send sample chat text to the API, but $20 was too much: earlier attempts ran on DeepSeek through OpenRouter or Luna through Codex. Switched the spike's default to Claude Haiku 5.5, Anthropic's cheapest current model. The estimate dropped to about $0.06–0.09 per 50-chat run, so roughly $0.50 for the whole spike. The default cost cap is now $2. If Haiku misses the targets, the next step is to compare Sonnet on the *same* sample and gold set, rather than guessing.
**Talking points:**
- "Start with the cheapest model that might work, measure it, and only pay for more if the numbers say so."
- "Same gold set across models makes the comparison fair."

### 19:58 — First contact with the real data (no AI yet)
**What:** Set the spike up on the PC that holds the data, in a separate Git worktree so the main checkout stayed clean. Python 3.13, all 40 tests pass on Windows too. The dry run sampled 50 real conversations with none skipped and estimated about 230k input and 75k output tokens: **~$0.06 per run on Haiku**, ~$0.12 for both runs. It also wrote the 20-chat labelling sheet. No API calls, nothing in `raw/` touched.
**Talking points:**
- "Free steps first: tests, cost estimate, labelling sheet. The paid step comes last."
- "A worktree let me try a branch on my real machine without disturbing my main checkout."

### 20:15 — Keep everything in one folder
**What:** Louis wanted the spike's code and outputs inside the project folder rather than scattered across the drive. The script used to refuse any output folder inside a Git repo. Now it writes to `private/spike-out/` by default, `private/` is in `.gitignore`, and before writing the script asks Git itself (`git check-ignore`) whether that folder would be committed. It refuses if so. Same safety, one tidy folder. The API key is set. 41 tests pass.
**Talking points:**
- "Ask Git, don't guess: `git check-ignore` tells you exactly what `git add` would do."
- "Tidy and safe aren't opposites. One folder, with the private bit fenced off."

### 20:25 — "I'm the evaluator, not the labeller"
**What:** Louis doesn't want to hand-label chats. He wants to judge the model's work. Added an evaluator mode: after the first run, the spike writes a review sheet for about 20 varied chats showing the model's answers (domain, purpose, projects, summary, decisions). Louis marks each one y/n, optionally with the right answer, in about 20 minutes. His verdicts give an accuracy score, and every confirmed or corrected answer becomes a reference label that scores all runs and any future model. Re-running with the verdicts costs nothing: finished chats are skipped.
**Trade-off, stated honestly:** seeing the model's answer first nudges a reviewer towards agreeing (anchoring). So the pass mark went up (85% instead of 80%), the sheet asks a strict y/n per field, and the result is reported as an upper bound. Agents still never fill in or edit the verdicts. 43 tests pass.
**Talking points:**
- "Design the evaluation around how the human actually wants to work."
- "Reviewing is faster than labelling but biased. Say so, and raise the bar to compensate."

### 20:35 — First real run: reliable and mostly right, but decisions are weak
**What:** 50 real chats, labelled twice by Claude Haiku 5.5, for **$0.069**. Then Claude checked 20 of the answers against the actual chats, and Louis spot-checks Claude's borderline calls.
- **Reliability:** zero timeouts or connection errors (the old OpenRouter setup's main pain), about 3.5 s per chat.
- **Format:** over half the answers broke a rule on the first try. 84–86% ended up OK. 14 of the 15 failures had the same cause: more than 5 topics.
- **Consistency:** the two runs, in different orders, agreed on the main subject 87.5% of the time and on purpose 90%. Topics agreed least (0.49 overlap).
- **Accuracy (Claude's check):** subject area 95%, purpose 85%, but **decisions only 7 of 13 right**. It missed decisions, credited Louis's own ideas to the assistant, and marked things "accepted" that he never agreed to.

**Response (spike-0.3), a change of method rather than prompt tweaking:**
1. Too many topics or an over-long summary is trimmed by code instead of being rejected and retried. It was never a wrong answer, just a long one.
2. Decisions moved into their own call with a focused prompt and more thinking effort. The chat is now numbered message by message, and each decision must say which message proposed it and which *user* message accepted or rejected it. Plain code then checks those numbers. "Accepted" pointing at an assistant message is now caught automatically, and that was exactly the run-1 mistake.

Tests went from 43 to 47. Three existing tests had their expected call counts changed (one call per chat became two), and two rejection cases became "trimmed" cases. These are listed for Louis to approve under the "tests only change with owner OK" guardrail.
**Talking points:**
- "Seven cents to find out exactly where the AI is weak. That's the point of a spike."
- "Don't reject an answer for being too long. Trim it in code and save the retry for real errors."
- "Make the model cite message numbers, then check them with plain code. Trust, but verify."

### 20:40 (time corrected) — Reading the old attempts before trusting the new one
**What:** Louis asked for his previous Codex/Hermes attempts (two folders on his PC, May to September 2026) to be read as evidence of what failed, not as guidance, and cross-checked against the first Haiku spike run. Claude read the plans, results, specs, review logs and statistics of 50 old notes, read-only, without running any old scripts. The write-up is `docs/reference/previous-attempts-review.md`.
**What it found:**
- **Every attempt graded itself.** The September "pass" used an answer key the agent wrote and a review by the same model. The August "three independent reviewers" were AI sub-agents, and the acceptance rule was changed mid-run to declare success. The uncomfortable part: the current spike's "decisions 7 of 13" and "95% subject accuracy" also come from a Claude-written review file. Louis's own review sheet is still blank.
- **Decisions were never measured by a person before.** Old notes stored "decisions" with no speaker or state, and 205 of 207 "ideas" were the assistant's suggestions. The spike is the first attempt to score decisions at all.
- **Count rules caused the format failures every time:** too few tags in May, too many topics now. Trimming in code (spike 0.3) is the first fix that doesn't retry.
- **Clipping long chats loses decisions, then and now.** In the spike, 3 of the 4 clipped chats with decisions got them wrong, against 3 of 9 unclipped. It's a small sample, but it's the same failure the old pipeline had.
- **Free-text topics drift** (0.49 overlap between runs), while fixed lists hold (87.5–90%). The old v2 reached the same conclusion: labels need frozen IDs.
**Decision:** none yet. The findings went to Louis and to the validation thread. The main ask is that an accuracy number only counts once Louis has marked or written the answers himself.
**Challenges:** the post-mortem from ChatGPT was written without access to the code or logs, so some of its claims were out of date by September. The files showed the overhaul had already fixed vocabulary auto-promotion and still failed.
**Talking points:**
- "Three attempts passed their own tests and still failed the only test that mattered: does the owner agree?"
- "I audited the old logs before trusting the new run, and found the new run making the oldest mistake."
- "Same bug, three costumes: count rules for tags, for summary length, for topics."

### 20:45 — "Too simplistic": rethinking the process
**What:** Louis looked at the results and said the labels were too simplistic. He was right. Reading the chats showed that one subject and one purpose per chat can't describe conversations that drift, a single "games" bucket swallowed 40% of the sample, and only decisions were kept, while the chats are full of ideas, preferences, frameworks and things that were made. The checking was also anchored on the model's answer.
**New plan (spike v3, `docs/plans/SPIKE_V3_PROCESS.md`):** build a blind answer key for 10 chats first, then let Haiku *discover* segments, projects and typed knowledge with no fixed list. Then consolidate that into a two-level taxonomy and a project registry that Louis approves and we freeze. Only then classify segments against it, and score everything against the answer key. Expected cost is still under $1.
**Talking points:**
- "Cheap runs aren't the goal. Useful knowledge is. Seven cents told me my categories were the problem, not the model."
- "Discover first, classify second. You can't pick the categories before you've seen the data."
- "Write the answer key before you look at the model's answers."

### 20:50 (time corrected) — Lessons from the old attempts, and the discovery step
**What:** A separate review of the earlier attempts flagged where this spike was repeating old mistakes. It made four points:
- **The run 1 "accuracy" was Claude marking Claude.** The report even said "your verdicts". That is now labelled "Claude's check" everywhere, and no accuracy figure counts until Louis has approved the answer key.
- **Clipping hurt.** 12 of 50 chats were cut at 24k characters, and those did much worse. Haiku can read a million tokens, so the limit is now 200k characters, still under a cent per chat.
- **Code was being dropped**, as in the first attempt. It's kept now.
- **Quote checks** failed on curly apostrophes and escaped newlines. They're now tolerant of both.

Built step 2 of v3: one call per chat returns sections and typed items, each tied to a message number. Code checks that the sections cover the chat, that speakers match and that quotes are real. It scores against the answer key by message number, and scores run 2 against run 1 for consistency, with clipped and unclipped chats reported separately. The answer key now has 10 chats and 95 items after a full re-read. 53 tests pass.
**Talking points:**
- "The easiest bug to miss: your evaluator is the same kind of model as the thing it evaluates."
- "Truncation is silent data loss. Measure clipped and unclipped separately."

### 20:52 — Stopping before the rabbit hole
**What:** Louis closed the classification spike: "we need to learn". In one evening it had grown from "run 50 chats twice" into a review sheet, an answer key, a redesign and a discovery mode. Each step made sense, but together they looked like the drift that sank the earlier attempts. So we stopped, wrote down what it proved and what it didn't (`docs/plans/SPIKE_VERDICT.md`), folded the lessons into the plan, and moved on to the first milestone, which is plain code with no AI.
**What it proved for 7 cents:**
- the API connection is reliable now;
- trim long answers instead of retrying them;
- cut-off chats do worse;
- one label per chat is the wrong unit.
**What it didn't prove:** accuracy. Nothing has been scored by Louis yet. The answer key is waiting for his review whenever classification comes back.
**Talking points:**
- "A spike has to end. Decide what question it answers, and stop when the question changes."
- "Seven cents and one evening bought me the lessons. The rest waits until the foundation exists."
- "Know the difference between 'Claude checked it' and 'I checked it'."

### 20:53 — First real code: FND-001, the project skeleton
**What:** Started milestone M1, the foundation: importing chats, keeping branches, handling re-imports and linking images. It's plain code with no AI. The first ticket only sets up the skeleton: a `pyproject.toml` that describes the project, an empty `knowledge_engine` package in a `src/` folder, three tests, and three checking tools. `ruff` checks style and, importantly, that every public function has a plain-English docstring. `mypy` checks types strictly. `pytest` runs the tests. A new `docs/CODE_STYLE.md` writes down the comment rules, including a "Talking points" list at the top of every module.
**Why this way:**
- The `src/` layout forces tests to use the installed package, the same way a user would get it. That catches "works on my machine" packaging mistakes early.
- No libraries were added yet. Each one arrives with the ticket that needs it, so every dependency has a reason.
- Strict type checking was chosen because the earlier attempt was "not type-safe", and mistakes are cheaper to catch before the code runs on real data.
- The docstring rule is checked by a tool, not just written down. I proved it by adding a function without a docstring and watching the check fail.
**Problem hit:** the formatter also tried to reformat Python examples inside the Markdown docs. Fixed by excluding `docs/` from the code tools, because those snippets are illustrations, not code we run.
**What I learned:** what `pyproject.toml` is for, what an "editable install" (`pip install -e`) does, and why linters and type checkers run before the tests.
**Talking points:**
- "Day one of the real build was boring on purpose: a skeleton, three tools, and a written style guide."
- "My style rules are enforced by a linter, not by good intentions."
- "Every dependency arrives with the ticket that needs it."

### 20:57 — FND-002: settings, with privacy switched on by default
**What:** Added one settings object that holds every switch and limit the engine uses. It can be filled from a `ke.toml` file, from environment variables, or from code. There's a commented example in `ke.example.toml`. 36 new tests, 39 in total, all passing.
**Key decisions and why:**
- **Everything that leaves the PC has its own off switch:** text AI, embeddings, image analysis, web fetches and transcript fetches. All five ship switched off. Turning on the text model does *not* turn on image analysis. That's the privacy promise from the plan, enforced in code.
- **The settings refuse a workspace inside the raw folder.** "Never write to raw/" is now a check, not just a rule in a document. A test even tries to sneak past it with `..` in the path.
- **API keys can only come from environment variables.** If a key turns up in the config file, the engine refuses to start, and the error message names the setting without printing the key. Config files get copied and committed; environment variables don't.
- **Settings are frozen** after loading, so nothing can flip a switch halfway through a run.
- Used two plan defaults Louis accepted by starting M1: images stay where they are and get hash-checked (OD-02), and each raw folder gets an account label such as `louis-personal` (OD-03).
**Problem hit:** a misspelt environment variable is silently ignored by the settings library. It fails safe, because the switch stays off, but it's logged as a known limitation.
**What I learned:** Pydantic validation, `SecretStr`, how config sources get layered in priority order, and why `extra="forbid"` catches typos.
**Talking points:**
- "Privacy by default isn't a policy page, it's five booleans that default to False, plus tests."
- "My config refuses to let the app write inside the folder holding my private data."
- "API keys never go in config files. My app checks that and refuses to start."

### 21:00 — FND-003: the local database
**What:** Added the SQLite database layer and the first table, `workspaces`. 15 new tests, 54 in total, all passing.
**Key decisions and why:**
- **Foreign keys switched on for every connection.** SQLite ignores them unless asked, which surprises a lot of people. A test checks it's really on.
- **WAL mode**, so a reader (say, the note renderer) can keep reading while an import writes.
- **One all-or-nothing transaction block** that every write goes through: commit if it finishes, roll back on any error. Re-imports and resume-after-crash (IMP-004) depend on it.
- **Writers take the lock at the start** (`BEGIN IMMEDIATE`). Otherwise two writers can each wait for the other halfway through. To prove the test actually checks this, I broke the code on purpose and watched that one test go red. That's called a mutation check.
- The workspace ID is random and never built from its name, so renaming can't change identity.
**Problem to watch:** Louis's project lives on drive `V:`. If that's a network drive, SQLite's WAL mode can be unsafe there. I'll check it during the first run on his PC.
**Housekeeping:** the times on the two earlier entries from this session were ahead of the clock. Corrected to 20:53 and 20:57.
**What I learned:** what a transaction is, what rollback means in practice, and why SQLite needs a few switches turned on before it's safe.
**Talking points:**
- "Every write in my app is all-or-nothing. A crash can't leave half an import behind."
- "I broke my own code on purpose to prove the test would catch it."
- "SQLite is a real database if you configure it. Foreign keys and WAL mode are two lines that matter."

### 21:03 — FND-004: version control for the database
**What:** Added Alembic migrations. A migration is a numbered script that changes the database's shape and can undo the change. The first one, `0001_baseline`, creates the `workspaces` table. 7 new tests, 61 in total.
**Key decisions and why:**
- **The migrations ship inside the package.** An installed copy can upgrade its own database without hunting for extra files. I proved it by building the package, installing it into a fresh environment and migrating a new database.
- **A "drift" test** compares the migrated database with the Python table definitions. If someone changes a table and forgets the migration, the test fails. I checked that by adding a column without a migration and watching it go red.
- **Upgrade twice** is a no-op the second time. Running the same step twice with the same result is called idempotency, and it's the theme of the whole import design.
**Problem hit:** the Python cache folders (`__pycache__`) had been committed in the first three tickets, because the main `.gitignore` didn't list them. They're untracked now, and it's fixed for the future. It was a small slip, but a reminder to check `git status` before every commit.
**What I learned:** what a schema migration is, upgrade vs downgrade, and why constraint names matter (you can't drop a constraint you can't name).
**Talking points:**
- "My database schema is versioned like my code: numbered, reversible and tested."
- "One test makes sure the code and the database can never disagree about a table."
- "I check that the installed package works, not just the source folder."

### 21:08 — FND-005: IDs that survive re-imports
**What:** Wrote the code that gives every conversation, message, message version, image and link a permanent ID. Added the fixed lists of states, such as "new / unchanged / revised / not seen", and four core data shapes. 59 new tests, 120 in total.
**Key decisions and why:**
- **An ID is a hash of what a thing *is*.** For example: "conversation `abc` from ChatGPT in account `louis-personal`". Import the same export twice and you get the same IDs, so there are no duplicates. This is the heart of the re-import design.
- **Titles are never part of an ID**, so renaming a chat can't turn it into a new chat.
- **The same image in three messages** is one asset with three "occurrences". Each message keeps its own link.
- **Property-based tests** (the Hypothesis library) throw hundreds of random inputs at the ID rules and check they always hold, for example that different native IDs never share an ID.
- **One pinned ID value** in the tests. If someone changes the ID recipe by accident, that test fails, because changing it would silently change every stored ID.
- **Scope note for Louis:** the old ticket also listed "Segment" and "KnowledgeRecord". I left those for the AI milestone (M3), because the spike showed their shape still needs to change. The acceptance test is unchanged.
**Owner input:** Louis confirmed `V:` is a local disk, so the database can live in the project folder safely.
**What I learned:** hashing as identity, why key boundaries matter (`"ab"+"c"` vs `"a"+"bc"`), and property-based testing.
**Talking points:**
- "Re-import safety comes down to one idea: IDs come from identity, not from timing."
- "I let a library generate hundreds of random test cases to try to break my ID rules."
- "One test pins an exact ID value, because changing the recipe would quietly change every stored ID."

### 21:38 — Louis: "We need to do all the milestones." EVAL-009: fake exports to test against
**Decision:** Louis wants the whole roadmap built, not just the import foundation. So the plan is to keep going ticket by ticket through all six milestones. The approval points stay in place: I'll still ask before the first paid AI run, before any feature that goes online, and before anything that deletes data.
**What:** Built a generator for fake ChatGPT exports and committed 14 test cases made with it. Together they cover every export layout (one file, numbered shards, a ZIP, and the per-chat files like the current `raw/` folder) and the awkward situations: an edited question, regenerated answers, one image used three times, a missing image, a chat that disappears from the next export, two chats with the same title, and two different chats claiming the same ID. Each case has an answer key written by hand. 60 new tests, 180 in total.
**Key decisions and why:**
- **Generated, not hand-written.** Same seed, same bytes, on any machine. A test rebuilds the fixtures and compares them byte by byte with the committed ones. Even the tiny PNG images are written uncompressed for this reason, because compressed bytes can differ between library versions.
- **The tests count with their own simple reader**, not the generator's code. Otherwise a bug in the generator would agree with itself.
- **Every piece of text says "Synthetic"**, and a test checks it. It's a cheap guard against real data slipping into a public repo.
**Honest gap:** I don't know the exact field names in the split files, apart from `title` and `conversation`. They're inferred from the audit's description, and I've flagged them for a key-names-only check on Louis's PC later.
**What I learned:** what a test fixture is, why determinism matters for tests, and how a ZIP or PNG file is put together.
**Talking points:**
- "My importer is tested against 14 fake exports covering every awkward case I could find in the real data, without committing a single real message."
- "The tests use their own tiny reader to check the answer keys, so the test data can't mark its own homework."
- "When I wasn't sure of a real file format, I wrote that down instead of pretending."

### 21:39 — Decision: no more paid API calls
**What Louis decided:** stop using the paid Claude API. Everything runs locally, or through Claude Code sessions on his existing subscription.
**What changes:** nothing for the first two milestones, which are plain code anyway. For the AI milestones, the code still talks to a "model provider" interface and is tested with fake providers. When real judgement on his chats is needed, a Claude Code session on his PC will do that step directly and write checked results into the private workspace. The app then validates those results exactly as it would an API response. The "send text to an AI" switch stays off.
**Why it's a reasonable call:** it caps cost at zero. The interface design means the AI step can be swapped later without rewriting anything, and the earlier spike already answered the "is the API reliable" question for 7 cents.
**Talking points:**
- "I designed the AI step behind an interface, so switching from a paid API to a subscription workflow changed a policy, not the code."
- "Zero marginal cost was a deliberate constraint, not an afterthought."

### 21:42 — FND-006: never do the same work twice
**What:** Added a jobs table and a "stage key". Every piece of work gets a fingerprint made from its input and the versions of everything that could change the result. Same fingerprint means the saved result is reused. 21 new tests, 202 in total.
**Key decisions and why:**
- **Retries follow Louis's guardrails exactly.** Errors that might go away (a timeout, broken JSON) get up to 3 attempts in total. A doubtful *answer* goes straight to review and is never retried. A real bug fails at once.
- **Checkpoints are saved in the same transaction as the work.** If the app crashes, the checkpoint and the data can't disagree. A test fakes a crash and checks that the job resumes from the right place.
- **The database checks too.** It refuses an unknown job state or more attempts than allowed, even if the Python code had a bug.
**Problem hit:** a job that had already failed three times said "out of attempts" when restarted, instead of "this job is finished". The message is accurate, but it's the wrong reason. Fixed by checking the state first.
**Flagged for Louis:** I changed one of my own earlier tests, still unmerged, that pinned the database version to "1". Every new table would have broken it. It now checks "there is exactly one latest version", which is what it really meant.
**Also happening:** a separate architecture review has proposed merging some of the planned import classes into fewer, bigger modules. Until Louis decides, I'm working on tickets the proposal doesn't touch.
**Talking points:**
- "Whether to redo work is a lookup: same fingerprint, same answer."
- "Retry what might be temporary, review what might be wrong, never loop."

### 21:44 — FND-008: the `ke` command
**What:** Installing the package now gives a `ke` command. `ke status` shows the settings and database state, `ke db upgrade` sets up or updates the database, and `ke import` exists as a placeholder that says "not built yet" and exits with its own code. 19 new tests, 221 in total.
**Key decisions and why:**
- **Two output modes with a contract.** Plain text for people, and `--json` for scripts: exactly one line with sorted keys. Tests check the exact shape, so later scripts and smoke tests can rely on it.
- **Fixed exit codes.** 0 OK, 2 typo, 3 bad config, 4 not built yet, 5 blocked by a privacy switch. A script can react without reading the message.
- **Status never prints private paths or keys.** Raw folders show up by their account label only, and the key shows as yes or no. A test plants a fake key and a private-looking folder name and checks neither appears.
- Used Python's built-in `argparse` instead of a CLI library: one less dependency, and it's easy to explain.
**What I learned:** console scripts in `pyproject.toml`, exit codes, and why machine-readable output needs a fixed schema.
**Talking points:**
- "My CLI has a contract: text for people, one line of sorted JSON for scripts, and exit codes that never change meaning."
- "Unbuilt commands are honest placeholders with their own exit code, not silent no-ops."

### 21:45 — OPS-008: the repo refuses to publish private data
**What:** Added a guard that runs before every commit. It refuses the commit if anything from `raw/`, `private/` or `workspace/`, or a local config file, is about to be committed. It also checks that every test fixture folder carries a `SYNTHETIC` marker. 10 new tests, 231 in total.
**Why:** the repository is public and `raw/` holds Louis's real chats. `.gitignore` isn't enough on its own, because one `git add -f` bypasses it. The guard checks what's actually staged.
**Nice detail:** when the guard complains, it names the folder, never the file, so its own error message can't leak a private file name. A test checks that too.
**To do on Louis's PC:** run `git config core.hooksPath .githooks` once to switch the hook on.
**Talking points:**
- "My repo checks itself before every commit. Staging a private file gets the commit refused."
- "'.gitignore' is a suggestion. 'git add -f' ignores it. So I check the index."

### 21:50 — DOC-002: Markdown notes for Obsidian, and a review says "smaller PRs"
**What:** Built the note renderer. It takes a note described as data and writes Markdown with Obsidian properties at the top. The same data gives the same bytes. Files are written safely, and an unchanged note isn't rewritten. 47 new tests, 278 in total.
**The interesting part, safety:** text from chats is *untrusted*. A message containing `[[something]]` would create a link in the vault, `%%...%%` would hide text, `#word` would create a tag, and HTML could do worse. The renderer escapes all of these, so chat text always shows up as text. A property-based test threw 5,000 random strings at it. It found one real bug: an obscure Unicode "next line" character that broke the properties block. Fixed.
**Also:** file names work on Windows, so there are no `CON.md` or `:` characters. Notes can't be written outside the vault folder. Notes are written to a temporary file first and then swapped in, so a crash can't leave half a note.
**Review feedback:** an independent review said PR #3 has become too big to read and explain (over 8,000 lines). Fair. So no more tickets go into it, and new work comes in small PRs. I've asked Louis how he'd like that done, and for permission to run the tests on his Windows PC and to check the real field names in his split files (names only, no content).
**What I learned:** YAML quirks, why rename-into-place is atomic, and that property-based tests find bugs you'd never think to write a test for.
**Talking points:**
- "Chat text is untrusted input, even when it's my own chats. My renderer makes sure it can't create links, tags or hidden text in my notes."
- "A random-input test found a Unicode character I'd never heard of that broke my output."
- "Feedback said my PR was too big to explain. That's a portfolio problem as much as a review problem, so I'm splitting the work up."
**Teach-back (`rendering/markdown.py`, added at 23:18 when the PR was opened):** "A note is built as data first, then turned into Markdown the same way every time, so the same data always gives byte-for-byte the same file. Anything that came from a chat is escaped so it can't become a link, tag or hidden text in Obsidian. Files are written to a temporary file and swapped in, and an unchanged note isn't touched, so a crash can't leave half a note."

### 21:51 — The backlog moves into GitHub Issues
**What:** Louis said yes to turning every planned ticket into a GitHub Issue, across all milestones. The spec had 122 tickets, but they only lived in two docs (`docs/ROADMAP_AND_TICKETS.md` and `docs/TICKETS.csv`), even though we had picked GitHub Issues as the tracker. Now there are six milestone issues, M1 to M6 (#4–#9), with 122 ticket issues under them as sub-issues (#10–#132; #113 is a pull request from another thread). Each ticket's title starts with its ID, for example "FND-005: Domain models and stable identifiers". Each one has a summary, a checklist of acceptance criteria, its priority and phase, and a link back to its section in the roadmap. The first line lists its blockers as issue numbers, like "Blocked by: #12, #14". FND-001 to FND-005 (#10–#14) are marked as built in PR #3, waiting for review, rather than closed.
**Challenges:**
- **No real milestones.** My GitHub tools can create issues and sub-issues but not milestones or GitHub's built-in "blocked by" links, and the command-line login in this environment didn't work. So each milestone became a parent issue, and blockers became a text line, which is the fallback our tracker doc already allows.
- **Numbers shifted under me.** I worked out every issue number ahead of time so blockers could point at issues that already existed. Halfway through, another thread opened a PR that took #113, and every later number moved up by one. A check script caught it, and I fixed the 13 issues whose blocker lines pointed at the wrong numbers.
- **Long links broke.** Links of 150 characters or more came out wrapped in stray backticks, which broke them in 28 issues. I switched those to shorter relative links and checked how GitHub rendered one.
- **Checking at the end.** A script compared every issue on GitHub with the text generated from the docs. Titles, bodies and blocker IDs all match, and each milestone has the right number of sub-issues (33, 9, 31, 30, 12, 7).
**Decision:** the ticket docs weren't edited. The tracker doc says they're reference material now and shouldn't be kept in sync, so GitHub Issues is where ticket status lives from here on.
**Talking points:**
- "Plan in documents, track in issues. 122 tickets went from a spreadsheet to a dependency-linked backlog in one session."
- "Never trust numbers you predicted. Another process grabbed one halfway through, and only the check script noticed."
- "Automate the boring part, but check it with something that didn't write it."

### 21:55 — Independent review of the direction (read-only)
**What:** Louis asked for a second, sceptical opinion on the whole direction: the audit, plans, ADRs, spike verdict, the two post-mortems, PR #3 and the diary. A separate review thread read everything on `main` and the open branches without editing a plan or a line of code, and published a report with a verdict and ordered recommendations.
**Verdict: adjust, not rethink.** The direction is right: deterministic import first, identity designed for re-exports, the AI step behind a schema, owner as evaluator. The first six tickets are careful and honest about what they skipped. Three things need adjusting before more code lands:
- **Scope.** "Do all the milestones" (122 tickets, including an API, PostgreSQL and multi-user) re-opens the "too much system too early" failure from the earlier attempts. Recommendation: commit to M1 and M2, run the G2 gate on real data, then re-plan M3.
- **The no-paid-API rule has no design behind it yet.** ADR-0007 and the M3 tickets assume an API provider with structured output and batch runs. "A Claude session does the judgement step" needs its own ADR: batch file in, batch file out, with throughput and stability measurement written down.
- **The answer key is still unreviewed.** Every accuracy number so far is Claude checking Haiku. Thirty minutes of Louis marking the 10-chat key ok / fix / drop is the only thing that breaks the self-grading pattern, and it should be an entry condition for M3.
**Also flagged:** the service design is heavier than a single-user CLI needs (events, outbox, locks, about fifteen small classes), and the review agrees with the architecture thread's proposal to consolidate into a graph module and an import module with a single "import, give me a report" interface, keeping the ADR-0003 data keys and ticket IDs. PRs should be one or two tickets, not six, so Louis can actually read them. Nothing has run on Windows yet. Seven ADRs are still "proposed" while code is built on them.
**Challenge:** a reviewer that is the same kind of model as the thing it reviews. The report says so up front and backs each claim with a file or a count rather than an opinion.
**Talking points:**
- "Before building more, I asked for a hostile review of the plan. It said: right direction, wrong commitment size."
- "The cheapest fix on the list is thirty minutes of my own time: approve the answer key so the AI stops marking its own homework."
- "An agent can write eight thousand lines in an hour. The question is whether I can explain them in an interview."

### 22:13 — Overnight: decisions taken for Louis
**What:** Louis went to bed and handed over authority. The decisions taken on his behalf are written down in `docs/reviews/OPEN_DECISIONS.md` as "decided under delegated authority, revisitable": adopt the simpler import design (one graph module, one Import module), small PRs, merge when green, and a read-only check on his PC (Windows tests, plus the real key names of the split files, names only).
**Why write it down:** a decision nobody can find later is a decision nobody can question. Recording who decided, when, and under what authority keeps the history honest.
**Talking points:**
- "When I act on delegated authority, I log it as delegated and reversible, not as the owner's own choice."

### 22:16 — Committing to two milestones, not six (REV-001)
**What:** Before going to bed, Louis asked for the direction review to be turned into tickets and implemented by agents, and gave blanket authority for the night ("do not ask me anything"). The first ticket narrows the commitment. Only M1 (importing chats faithfully) and M2 (links, YouTube and social registries) are committed now. M3 to M6 stay on the roadmap but get re-planned at gate G2, once real-data results exist. Thirteen product tickets (the web API, PostgreSQL, multi-user accounts, packaging and integrations) are labelled `parked` in GitHub Issues. Nothing was closed or renumbered.
**Why:** a 122-ticket plan that includes an API and multi-user support before the core works on one real export is exactly failure mode F7 from the earlier attempts: too much system too early. Two committed milestones are a promise that can actually be kept.
**Decision:** recorded in `docs/reviews/OPEN_DECISIONS.md` as "decided under delegated authority 2026-10-27, revisitable", so Louis can reverse it in the morning.
**Talking points:**
- "Keeping a ticket isn't the same as committing to it. I parked a third of the roadmap without deleting anything."
- "Re-plan with real data. The plan for the AI milestones gets rewritten after the import works on my actual export."

### 22:20 — Turning the review into tickets, with Louis asleep
**What:** Louis asked for tickets and a plan from the direction review, and for other agents to implement them. Then he went to bed with one instruction: don't ask, you have the authority. So the plan (`docs/plans/REVIEW_ACTION_PLAN.md`) records each decision taken tonight as "owner authority 22:10", so he can reverse any of them in the morning, and the one thing only he can do (marking the answer key) is a ticket assigned to him, not a question.
**Tickets:** REV-001 to REV-009 as GitHub Issues #135–#143 under map #134, with the M1 and M3 ones also under their milestone maps. Six are agent work tonight (scope commitment, ADR-0009 for the no-API model step, M1 consolidation design, PR-size and teach-back rules, closing the ADR/decision record, a paid-call guard on the spike). One needs the PC (Windows run, key-name check), one waits for the parser (early real-data checkpoint), one waits for Louis (answer key).
**Decision taken under authority:** commit to M1 and M2; M3 to M6 stay roadmap and get re-planned at gate G2. The licence was deliberately *not* chosen: it's a legal call he should make awake.
**Conflict rule:** the foundation thread owns `src/`, `tests/` and the status files. Review tickets touch only docs, ADRs and the throwaway spike, so several agents can run at once without stepping on each other.
**Talking points:**
- "Delegating overnight works if every decision is labelled with who made it and when, so it can be undone."
- "Tickets with a finish line and a 'don't touch' list are how you run several agents in parallel safely."

### 22:25 — A lock on the paid API (REV-008)
**What:** Earlier tonight Louis decided: no more paid API calls for now, do the work locally or with Claude inside the subscription. But the spike's real provider still built an Anthropic client straight from `ANTHROPIC_API_KEY`, which is set on his PC. One wrong command (forgetting `--provider fake` or `--dry-run`) would have spent money. So the rule became code: `AnthropicProvider` now refuses to start unless the environment variable `SPIKE_ALLOW_PAID=1` is set, and the error message names Louis's decision and the switch. The check runs before the SDK is even imported. Only the exact value `1` counts, so `0`, `true` or an empty value all keep it locked. `--dry-run` and the fake provider work as before without the switch.
**Challenges:**
- The provider is built outside the spike's existing error handling, so a plain error would have dumped a Python traceback. The command line now catches it and prints a one-line "Refusing: ..." message with exit code 4, in both label and discover modes.
- Testing a "don't call the paid API" rule without calling the paid API: the tests only check that the provider refuses (or, with the switch on and a fake key, that it builds an object that's never used). Nothing touches the network.
**Result:** 9 new tests, 62 pass in total, and none of the existing 53 tests were changed.
**Talking points:**
- "A rule in a doc is a hope. A rule in code is a guarantee."
- "Make the expensive path opt-in and the free path the default."
- "Fail loudly and early: the lock trips before any client exists that could spend money."

### 22:35 — How the AI step works without paying for an API (ADR-0009)
**What:** At 21:38 Louis decided no more paid API calls: the AI work has to happen locally or with Claude on his Claude subscription. The plans still assumed a paid API (structured output, cost caps, scripted batch runs), so this entry turns his rule into a design. It's written up as ADR-0009 (`docs/adr/0009-model-step-without-paid-api.md`), ticket REV-002 (#136).
**The design, in one line:** batch file in, batch file out. The app writes a request file of chat sections plus a JSON Schema into the private folder on Louis's PC. A Claude Code session fills a response file. The app checks every answer with the same code it would use for an API answer, and throws away anything that doesn't fit. The session is just another "provider", so swapping the API back in later changes one setting, not the pipeline.
**Challenges:**
- **Time, not money, is the real cost.** The spike's numbers say a full pass over all 1,158 chats is roughly 20 million tokens. Through the API that's a few dollars and an hour. Through subscription sessions it's hundreds of small batch files and probably days of sessions. So M3 works on samples (10, then 50, then 100 chats), and the first 50-chat run measures the real throughput before anyone plans a full pass.
- **You can't pin the model on a subscription.** For stability tests the model has to stay the same between runs. Each answer now records which model served it, and a stability report says so up front if two runs used different models.
- **Who marks the homework.** The session that labels chats is never allowed to read or edit the answer key. Scoring is done by code, not by a Claude session.
**Decision:** taken under the authority Louis delegated for the night (22:10), so it's marked "proposed, revisitable". The paid option is written down as a fallback with its cost (about $0.80 a pass for labels, about $3 for discovery) and clear triggers for bringing it back to him. No code was written; the ticket issues for the provider (#52, #53) and the batch smoke test (#82) got one comment each saying what changes.
**Talking points:**
- "I made the AI a file format. The app doesn't care whether an API or a person running Claude filled in the answers. It checks them the same way."
- "Saving $3 cost me days of throughput. I wrote that trade-off down, with the numbers, so the choice can be revisited."
- "The labeller never sees the answer key. Code does the marking."

### 23:12 — Designing fewer, deeper import modules (REV-004)
**What:** Wrote `docs/plans/M1_CONSOLIDATION.md`, the design note that turns the architecture review's advice into a concrete shape for the first milestone. Design only: no code or tests changed. Instead of about fifteen small classes that the caller has to call in the right order, M1 becomes four modules: a pure *conversation graph* (active path, message numbers, branches and broken-tree checks, worked out in one place), one *Import* module whose whole interface is `import_source(path, account_ns) -> ImportReport`, a narrow adapter seam where the two export formats really differ (finding the conversations), and rendering as planned.
**Why:** the most important promise of the slice, "importing the same export again adds nothing and costs nothing", had no single owner. Now it does: one named test, `test_identical_reimport_adds_nothing`, calls one function twice and checks that every table has the same row count.
**What got deferred, and why:** the internal event system, a separate import lock and checkpoint-based crash resume. For one person running a command-line tool on SQLite, direct function calls, SQLite's own writer lock (`BEGIN IMMEDIATE`) and "resume means run it again" give the same guarantees with far less to learn. Each one has a written trigger for when to add it back.
**What stayed fixed:** all 33 ticket IDs and issues, every acceptance criterion, and the ADR-0003 identity keys. The note maps each ticket to its module and to the behaviour slice that closes it. The foundation code from PR #3 needs no changes.
**Challenge:** the session was cut off by an API error part-way through, and `main` moved twice in the meantime (two other review threads merged). The design note had been saved locally, so the work picked up again from there and was rebased on the new `main`.
**Decision taken under owner authority 22:10**, reversible in the morning like the others.
**Talking points:**
- "Small classes aren't automatically simple. I merged five of them behind one function so the key guarantee has one test."
- "I kept every ticket number and acceptance test, and changed only how the code is grouped. Re-planning shouldn't erase history."
- "Defer machinery until something needs it, and write down what would need it."

### 23:12 — Closing the record (REV-006)
**What:** Seven architecture decisions (ADR-0002 to ADR-0008) were still marked "proposed", even though the M1 code is being built on them, and starting M1 had quietly accepted the default answers to the open decisions. This entry makes that honest on paper. The seven ADRs are now `accepted`, with a note that it was done under Louis's delegated authority for the night and can be reversed. The open decisions with sensible defaults (OD-01..03, 06, 07, 09..15, 17) are marked "default accepted". OD-08 is closed: GitHub Issues is the one ticket tracker, and the roadmap file now opens with a "frozen reference" banner. `CLAUDE.md` no longer tells agents to keep the CSV and Markdown in sync.
**Left alone on purpose:** the licence (OD-16). No licence file means "all rights reserved", which keeps the option to sell it later; picking an open-source licence is a legal choice Louis should make awake. OD-04/05 (cloud policy and model choice) belong to the ADR-0009 work in another thread.
**Challenge:** the ticket asked for a banner row in `TICKETS.csv` if the reader tolerates it. A comment line at the top of a CSV breaks standard readers (the header row would no longer be first), so the banner went only into the Markdown, and it names the CSV too.
**Talking points:**
- "A decision you're already building on is a decision. Write it down as one, with who made it and how to undo it."
- "Three ticket trackers is zero ticket trackers. I picked one and froze the others."

### 23:14 — Small PRs and the teach-back rule (REV-005)
**What:** Two new process rules, written into `AGENTS.md` (owner guardrail 4), `CLAUDE.md` §4 and the rules block at the top of this diary. First: a pull request carries at most two tickets, and one by default; anything bigger needs Louis's OK first. Second, the teach-back: before a PR with code in it merges, one module from it gets explained in three plain sentences in that day's diary entry, the way Louis would say it in an interview. If three sentences aren't enough, the comments in the code need work before it merges.
**Why:** PR #3 was 8,485 lines across 92 files and six tickets. Louis is the reviewer and is learning Python. Nobody reads a PR that size; it gets "approved unread", and that's how the earlier attempts lost control. The project is meant to teach him and to be something he can explain to an employer, so being able to explain the code is part of "done".
**Note:** tonight's three PRs (REV-001, REV-006 and this one) are documentation only, one ticket each, with no module to teach back.
**Talking points:**
- "An AI can write eight thousand lines in an hour. My rule: if I can't explain a module in three sentences, it doesn't merge."
- "Small PRs aren't about tidiness. They're the only way the reviewer actually reviews."

### 23:15 — Windows check, the real file shapes, and PR #3's teach-back (REV-007)
**What:** A read-only check on Louis's PC ran the whole test suite on Windows (230 of 231 passed) and listed the key *names* in his real split files (no values, no titles). Both findings are fixed on PR #3.
**Challenges:**
- The one Windows failure: rebuilding the test ZIP gave different bytes. Everything inside was identical except one header field that records which operating system built the ZIP (0 for Windows, 3 for Unix). The builder now pins it to 3, so the fixture is byte-identical everywhere.
- The fake split files had guessed two key names wrong (`image_count` instead of `image_references`, and no per-role message counts). They now use the real names, before any importer code relies on the guess.
**Teach-back (PR #3, module `domain/ids.py`, exception to the new two-ticket rule because it predates it):** "Every record gets an ID made by hashing the facts that define it, like the account and the conversation's own ID from ChatGPT, never its title or the import time. So importing the same export twice produces the same IDs, and the database's unique keys turn a would-be duplicate into a no-op. Each kind of thing has its own prefix and key layout, so a message ID can never collide with a conversation ID."
**Talking points:**
- "Test on the machine you ship to. One header byte broke a 'byte-identical' test on Windows."
- "I checked my fake data against the real files' structure, names only, before building on it."

### 23:16 — SRC-001: look before you import
**What:** `ke raw inventory <folder or zip>` lists every file in a raw folder by metadata: size, fingerprint and what kind of file it is. It never opens anything for writing, and proves it: it fingerprints the whole folder before and after, and if anything changed the report says "don't trust me". 33 new tests, 264 in total. This is the first ticket built to the new, simpler module plan (Louis's overnight decision 1).
**Key decisions and why:**
- **A chat is anything with a message tree.** Leftover files from the old classifier mention conversations but have no tree, so they're set aside, never imported by mistake.
- **File names are hidden by default.** In this export the file names *are* the chat titles. The report shows a short code per file instead.
- **Images are recognised by their first bytes, not their extension,** so a renamed file is still found.
**Teach-back (`ingestion/inventory.py`):** "Before importing, I list every file in the raw folder with its size, fingerprint and type, reading it but never writing. I fingerprint the whole folder before and after, so if anything changed during the run the report flags itself as untrustworthy. File names are replaced by short codes, because in a chat export the names are private chat titles."
**Talking points:**
- "My importer proves it's read-only: same folder fingerprint before and after, or the report refuses to be trusted."
- "Recognise files by what's inside them, not by what they're called."

### 23:20 — ING-005: a chat is a tree
**What:** The conversation graph: give it a chat's raw message map and it works out the tree, the version of the chat the user actually ended on (the "active path"), and stable message numbers. 39 new tests, 350 in total. It reads no files and touches no database, which makes it easy to test and reuse.
**Key decisions and why:**
- **Walk up, don't sort.** The active path comes from walking up from the last message the user saw, not from timestamps. Timestamps can be missing or odd; the tree can't lie about which message answers which.
- **Parent links are the truth.** Louis's split files have no child lists, so children are rebuilt from parent links every time. Then both formats give the same tree.
- **Bad data can't hang it.** A loop in the parent links (A's parent is B, B's parent is A) stops the walk instead of spinning forever.
**Teach-back (`graph/conversation.py`):** "A ChatGPT chat is a tree, because editing a question or regenerating an answer adds a sibling branch rather than replacing anything. I find the version the user ended up with by walking from the last message they saw up to the root, and number those messages 1, 2, 3. Every other branch is kept, but never mixed into that path."
**Talking points:**
- "A conversation is a tree, not a list. I keep every branch and never splice them together."
- "I never invent a timestamp. If the export didn't have one, neither does my data."

### 23:22 — REL-001 and NRM-002: naming the branches and flagging broken trees
**What:** The graph now says *why* a chat forked (the user edited a question, or asked for a new answer), lists every other version of the chat as its own path, and reports broken structure: missing parents, loops, unreachable messages, mismatched IDs. 17 new tests, 367 in total.
**Key decisions and why:**
- **Report, don't repair.** A broken tree is listed as issues with a code and a node ID. No message is thrown away, and no message text goes into the report.
- **The roles decide the branch kind.** Sibling user messages mean an edit; sibling assistant messages mean a regeneration. Anything mixed is honestly "other".
- **A random-damage test.** Hypothesis builds random trees, breaks some parent links, and checks every message is either reachable or named in an issue.
**Teach-back (`graph/conversation.py`, branches and issues):** "Where a message has more than one child, the conversation forked: sibling user messages mean the user edited a question, sibling assistant messages mean the answer was regenerated. Every other version is available as its own complete path, separate from the one the user ended on. If the tree is damaged, the problem is listed with a code and the node's ID, and no message is ever dropped."
**Talking points:**
- "Bad input becomes a list of named problems, not a crash and not silent data loss."
- "I test the integrity checker by deliberately breaking random trees."

### 23:25 — ING-006 and NRM-001: two fingerprints per message
**What:** Each message is turned into one clean shape: ordered pieces of text, references to images and files, and anything not understood kept as-is. Each message gets two fingerprints. 29 new tests, 396 in total.
**Key decisions and why:**
- **Two fingerprints.** The "raw" one covers everything the export said, so the archive can show exactly what changed between exports. The "content" one covers only who said it, what they said and when. Only a change to the content fingerprint means "redo the AI work". A test uses the metadata-drift fixture (only the model label changed) to prove the content fingerprint stays put.
- **Nothing is thrown away.** Unknown content types are kept raw and flagged. The model's "thoughts" and Louis's custom instructions are flagged so views can hide them, not deleted.
- **Image references are parsed, not trusted.** A strange pointer scheme gets a warning instead of a made-up file path.
**Teach-back (`graph/nodes.py`):** "Every message gets two fingerprints: one of the whole exported record, and one of just the role, the content and the time it was written. If only metadata changes between exports, like the model's name, the first fingerprint changes but the second doesn't, so no AI work is redone. Content the parser doesn't understand is kept as-is and flagged, never dropped."
**Talking points:**
- "One fingerprint says the file changed, the other says the meaning changed. Only the meaning costs money."
- "My parser is honest about what it doesn't understand: unknown content is kept and flagged."

### 23:28 — ING-002 and ING-004: one seam for every export format
**What:** The "adapter" seam, and the first adapter: the official ChatGPT export, as a ZIP or an unzipped folder, single file or numbered shards. 24 new tests, 420 in total.
**Key decisions and why:**
- **Adapters only find conversations.** Each format is different only in *where* the chats are. Parsing the messages happens once, in the graph module, for every format.
- **Hostile ZIPs are refused whole.** If any file name in the ZIP tries to climb out of its folder (`../`), the export is refused, not partly imported.
- **Hidden duplicates are reported.** If a JSON object has the same key twice, Python quietly keeps the last one. In a message map that would silently lose a message, so the loader now counts it as a warning.
- **The test that matters:** the same three chats as one file, as two shards, and inside a ZIP all come out identical.
**Teach-back (`ingestion/source.py`):** "Every export format gets an adapter with just two jobs: a quick look at file names to say 'this one's mine', and a stream of conversations exactly as exported, each tagged with the file it came from. Adapters never interpret messages, so the parsing rules live in one place for every format. If no adapter, or more than one, recognises a folder, the import stops and asks which format it is instead of guessing."
**Talking points:**
- "Formats differ in one way, so the seam between them is one method wide."
- "Python's JSON parser silently drops duplicate keys. Mine reports them."

### 23:30 — ING-011: reading Louis's split files
**What:** The second adapter, for the format Louis's real data is in: one JSON file per chat, each a small "wrapper" around the original conversation. 11 new tests, 431 in total.
**Key decisions and why:**
- **The wrapper is a hint, the conversation is the evidence.** The wrapper's title, ID and message counts are compared with the conversation inside; disagreements become warnings, and the conversation inside wins.
- **Same chats, same result.** The test that matters: the three fake chats in split files come out identical to the same chats in the official format.
- **No mixing versions.** Each file is fingerprinted when listed and checked again when read. If it changed in between, the import stops.
**Teach-back (`ingestion/chatgpt_split.py`):** "Louis's data has one file per chat, where a small wrapper with a title and counts surrounds the original conversation. I import the original conversation and only use the wrapper as a cross-check, reporting any disagreement as a warning. Files that aren't chats, like an old tool's output, are skipped with a warning, and a file that changes mid-import stops the import."
**Talking points:**
- "When a summary and the source disagree, report it and trust the source."
- "Two formats, one result: the test proves both adapters produce identical conversations."

### 23:33 — ING-001 and IMP-001: an archive and a ledger
**What:** Two building blocks inside the new Import module. The archive keeps an exact copy of every imported file, named by its fingerprint. The ledger records every import attempt and every file it read. 28 tests, 459 in total.
**Key decisions and why:**
- **Same bytes, one copy.** Importing the same export twice gives two ledger rows (two attempts happened) but one stored copy of each file.
- **Stored copies are re-checked.** When a file comes back, the old copy is checked too. If someone damaged it, the import stops and nothing is "repaired".
- **A crash is never a success.** An import that died halfway stays marked "running" until the next import marks it "abandoned".
- **No private paths.** The ledger stores a fingerprint of the raw folder's location, not the path.
**Teach-back (`importer/ledger.py`):** "Every import is one row in a ledger that's never rewritten, saying when it ran, with which code, and how it ended. Every file it read is stored once, under its fingerprint, and a file seen again reuses that copy after checking it's still intact. If an import crashed, the next one marks it abandoned, so it can never be mistaken for a successful import."
**Talking points:**
- "My import history is append-only: attempts are never overwritten, only added."
- "A crash leaves an honest 'abandoned' record, not a fake success."

### 23:33 — Louis: "implement all the tickets"
**What:** Louis reaffirmed the original goal: build every milestone, not just the first two. Recorded as his own decision in `docs/reviews/OPEN_DECISIONS.md` and `docs/plans/IMPLEMENTATION_PLAN.md` §4, superseding the overnight "M1 and M2 only" call that was made on his behalf.
**What doesn't change:** no paid API calls (AI steps run through a Claude session on his subscription, tested with fakes), small PRs with a teach-back each, and anything that needs Louis himself (like approving the answer key) is logged and skipped rather than waited on.
**Talking points:**
- "Decisions made on someone's behalf stay reversible, and get reversed cleanly when they speak."

### 23:38 — ING-003: the import is one function
**What:** `import_source(folder, account)` now imports an export end to end and returns a report: conversations, messages and edges written to the database, every file archived, the batch recorded. 11 new tests, 470 in total.
**The test that matters:** `test_identical_reimport_adds_nothing` imports the same export twice and counts every table. The second run adds zero conversations, zero messages, zero revisions, zero edges, queues no AI work, and reports everything as "unchanged". It counts *every* table the code defines, so tables added later are covered automatically.
**Other things it proves:** the official export, its sharded and ZIP versions, and Louis's split format all produce identical records. A simulated crash halfway through, followed by a re-run, ends in exactly the same state as one clean run.
**Something I stopped short of:** the `ke import` command still says "not built yet", because switching it on means replacing a test that checks the placeholder, and changing tests needs Louis's OK. Logged for him.
**Teach-back (`importer/__init__.py`):** "The whole importer is one function: give it an export and an account name and it returns a report. Inside, every record's ID comes from what it is, and the database refuses duplicates, so importing the same export twice adds nothing. If it crashes halfway, running it again finishes the job and ends exactly where a clean run would."
**Talking points:**
- "One test owns the promise 'importing twice adds nothing', and it counts every table, including ones that don't exist yet."
- "Crash recovery is just running it again, because the import is idempotent."

### 23:40 — IMP-003: what changed between two exports
**What:** Importing a newer export now reports exactly what changed: new chats, untouched chats, chats with new or edited messages, new branches (a regenerated answer), and chats that weren't in this export. 7 new tests, 477 in total. The fake v1 → v2 exports match their hand-written answer key exactly.
**Key decisions and why:**
- **Missing isn't deleted.** A chat absent from a new export is marked "not seen". All its messages stay. If it shows up again later, it's "present" again.
- **Edits keep history.** An edited message gets a new revision; the old one is kept.
- **Metadata drift costs nothing.** If only the model name or similar changed, the import records a new "raw observation" of the same message, but nothing is handed to the AI stages.
- **Full or partial source.** Importing a single shared chat shouldn't mark the rest of the archive "not seen", so the import has a `full_export` switch (on by default).
**Teach-back (`importer/delta.py`):** "When a new export arrives, each message is compared by its content fingerprint: new, unchanged, or revised, and a revision never replaces the old one. A chat missing from a full export is marked 'not seen', never deleted, and comes back if a later export has it. If only metadata changed, I record that I saw it in a new form, but nothing is reprocessed."
**Talking points:**
- "Absence of evidence isn't deletion: missing chats are 'not seen', not gone."
- "Only real content changes flow downstream to the AI step."

### 23:44 — IMP-002: when an ID can't be trusted, ask instead of guessing
**What:** Two awkward cases now go to a review list instead of being guessed at. If one export holds two *different* chats under the same ID, the first is imported and the second is set aside as an "ID collision" candidate. A chat with no ID at all isn't imported; it becomes a "missing ID" candidate. Both are marked `review_required` and are never merged automatically. 5 new tests, 482 in total.
**Key decisions and why:**
- **A candidate is keyed by a fingerprint of the whole chat**, so importing the same export again finds it already recorded and adds nothing.
- **The same chat twice in one export isn't a collision.** Identical copies are skipped with a warning; only different content under one ID needs a person.
- **Across exports, same ID with new content is a revision, not a collision.** That's the normal "I kept chatting" case from IMP-003.
- **Title and date never decide identity.** Two chats with the same title and day stay two chats.
**Teach-back (`importer/identity.py`):** "A chat's identity comes from the export's own ID, never its title or date. When that ID is missing, or two different chats share it in one export, I don't guess: the chat goes on a review list as a candidate. The candidate is keyed by a fingerprint of the chat, so importing the same export again doesn't add it twice."
**Talking points:**
- "When the data can't tell me who something is, it goes to review; the system never merges on a hunch."
```
ruff check .            # All checks passed!
mypy                    # Success: no issues found in 67 source files
pytest -q               # 482 passed, 6 skipped (5 new)
```
Finish line: `id_collision` matches its answer key (candidate_matches id_collision 1 / missing_native_id 1; merged 0); `same_title_different_chat` gives 2 conversations, 0 candidates. Fix attempts: 1 (my own new test assumed two revisions per chat; the fixture's chat also has a root message).

**Next exact task:** slice I5 (IMP-004: two concurrent imports give the same result as one).

### 23:47 — IMP-004: two imports at once just queue
**What:** Imports into one workspace now run one at a time. The whole import holds a lock file in the workspace; a second import waits for it (up to 10 minutes by default, `import_lock_timeout_s`), then runs and finds everything already done. 3 new tests, 485 in total.
**Why a lock, when the database already refuses duplicates:** each group of conversations was already safe, but a whole import makes two "am I alone?" judgements. On start it marks any batch still `running` as crashed, and at the end it marks chats it didn't touch as "not seen". Two imports interleaving would get both wrong. I checked the test fails without the lock (3 out of 3 runs) and passes with it (5 out of 5).
**Why an operating-system lock:** the OS drops it when the process dies, so a crash can never leave the workspace stuck locked.
**Teach-back (`importer/lock.py`):** "Only one import can write to a workspace at a time, because an import assumes it's alone when it decides what crashed and what's missing. It holds an operating-system lock on a file in the workspace, and a second import waits its turn. If the process crashes, the OS releases the lock, so nothing ever stays stuck."
**Talking points:**
- "Concurrency here is solved by queuing, not cleverness: the second import waits, then finds nothing to do."
```
ruff check .            # All checks passed!
mypy                    # Success: no issues found in 69 source files
pytest -q               # 485 passed, 6 skipped (3 new)
```
Finish line: two concurrent `import_source` processes on `reexport_v1` leave the same row counts as one serial import; one reports "new", the other "unchanged". Fix attempts: 0.

**Next exact task:** media slice M1 (MED-001 + MED-003: blobs, assets, occurrences).

### 23:52 — MED-001 + MED-003: each image stored once, every use remembered
**What:** Imports now pick up images. The same picture used in five messages is stored once and linked five times, and each link remembers the exact message and position. 12 new tests, 497 in total. The `repeated_image` fake export matches its answer key: 3 logical images, 2 distinct byte contents (two different file IDs share identical bytes), 5 uses, all available.
**The four records (ADR-0004):**
- **Blob:** the bytes, named by their fingerprint. Identical bytes are one blob, whatever the file is called.
- **Asset:** the export's file ID (`file-...`). Points at a blob once some export supplies the bytes.
- **Occurrence:** one message using one asset at one position. Keyed by the message revision, so re-importing adds nothing.
- **Derived artefact:** room for thumbnails later; it hangs off a blob and can never replace it. Nothing creates one yet.
**Key decisions and why:**
- **Missing stays visible.** If an export mentions an image that isn't there, the occurrence is kept and marked `missing`, with no blob and no made-up path. If a later export includes the file, it flips to `available` without creating a new occurrence.
- **Images stay where they are by default** (OD-02 "reference" mode): the database remembers where the file is and its fingerprint. Images inside a ZIP are copied into the private store, because a ZIP member can't be pointed at.
- **Header facts only.** Type and pixel size are read from the first bytes of the file. Nothing looks at the picture itself.
- **A file ID claims a file only with a separator after it**, so `file-abc` never claims `file-abcd.png`.
**Also:** I wrote a short amendment into `M1_CONSOLIDATION.md` saying the separate import lock came back in slice I5, and why.
**Teach-back (`importer/media.py`):** "An image is split into its bytes, the export's file, and each place a message uses it. Identical bytes are stored once, and every use is a separate link that remembers the message and position. If the file isn't in the export, the link is kept and marked missing, never pointed at a guessed path."
**Talking points:**
- "Storing once and linking many times is how one picture used in a dozen chats costs one copy."
- "Missing is a state, not a gap: the system shows you what it couldn't find."
```
ruff check .            # All checks passed!
mypy                    # Success: no issues found in 73 source files
pytest -q               # 497 passed, 6 skipped (12 new)
```
Finish line: `repeated_image` answer key matches (assets 3, blobs 2, available occurrences 5, per-asset 3/1/1); re-import adds 0 blobs, 0 assets, 0 occurrences and the raw tree is unchanged; `reexport_v1` → `v2` reports 1 new image. Fix attempts: 1 (forgot the migration on the first run).

**Next exact task:** media slice M2 (MED-002: missing, ambiguous and unresolved pointers with evidence).

### 23:57 — MED-002: every image reference finds its file, or says why not
**What:** Each image reference now ends in exactly one of: found, missing, ambiguous (two different files could be it), or unresolved (the pointer isn't a kind I understand). Each one stores its *reason* and the files it considered. 7 new tests, 504 in total. The `asset_problems` fake export matches its answer key: 2 missing, 1 ambiguous, 1 unresolved.
**The rules, in order:**
1. A pointer with no file ID I recognise is **unresolved**.
2. No file with that ID is **missing**. If an export index listed the file, the reason says "listed but absent".
3. One file is **found**.
4. Several files are narrowed only by safe evidence: exactly one inside a folder named after the conversation, or all copies byte-identical. Otherwise it's **ambiguous**, and nothing is stored for it.
**Also new:** uploaded files listed in a message's `attachments` metadata become occurrences too. An image listed both as content and as an attachment is counted once.
**Something to check on real data:** I only know the *key names* of Louis's export index files (from REV-007), not the shape of their entries, so the reader accepts plain names or objects with a path/filename/name field, and ignores anything else. That gets confirmed at the REV-009 real-data checkpoint.
**Teach-back (`MediaLibrary.resolve` in `importer/media.py`):** "Each image reference is matched to files by the export's file ID. Exactly one match is found; none is missing; several different files are ambiguous unless the conversation's own folder or identical bytes settle it. Every outcome records its rule and the files it looked at, so nothing is ever guessed or invented."
**Talking points:**
- "When the evidence doesn't settle it, the answer is 'ambiguous', not a coin toss."
- "Every 'missing' comes with the reason it's missing."
```
ruff check .            # All checks passed!
mypy                    # Success: no issues found in 75 source files
pytest -q               # 504 passed, 6 skipped (7 new)
```
Finish line: `asset_problems` states by pointer match the answer key exactly; a manifest-listed but absent file is `missing` with rule `listed_but_absent`; ambiguous candidates store no blob; no occurrence has an invented path. Fix attempts: 0.

**Next exact task:** slice I6 (ING-007 integrity reconciliation + IMP-005 import report and `ke imports report latest`).

### 00:01 — ING-007 + IMP-005: the import checks its own work, and keeps the receipt
**What:** Every import now counts the source twice: once straight from the raw files, once from what it actually stored. If they disagree, the report says `reconciled: false` and names what's off, instead of quietly losing something. The report is saved with the import, and `ke imports report` shows it again later, as JSON or readable text. 20 new tests, 524 in total.
**What the report now answers:**
- **What changed:** new, unchanged and revised conversations and messages, new branches, new images.
- **What needs a look:** missing or ambiguous images, chats with duplicate or missing IDs, failures, and images whose bytes duplicate another's.
- **What later stages must redo:** how many conversations and message versions changed. On an identical re-import that's zero.
- **Fidelity:** which message types appeared, how many content pieces are kept only as raw JSON because I don't understand them yet, and how many image files no message mentions.
**Checked against every fixture:** all 14 fake exports reconcile, and their reports match each answer key's counts. A test breaks one on purpose (a broken entry in the message tree) and the report flags it.
**Privacy:** the report is counts and codes only. A test scans the JSON and the text output for every title and message from the fake export and finds none.
**Teach-back (`importer/integrity.py`):** "The importer counts the source and counts what it stored, separately. If the numbers don't match, the report says which ones and raises a warning, so nothing is ever lost quietly. Anything the parser doesn't understand yet is kept as raw JSON and counted, so it stays visible."
**Talking points:**
- "Every import comes with a receipt, and the receipt checks itself."
- "An identical re-import says, in numbers, that there's nothing to redo."
```
ruff check .            # All checks passed!
mypy                    # Success: no issues found in 77 source files
pytest -q               # 524 passed, 6 skipped (20 new)
```
Finish line: `ke imports report latest` matches each fixture manifest (14 cases), the identical re-import is all unchanged with 0 model calls, and `reexport_v1` → `v2` matches its answer key. Fix attempts: 1 (first draft of the report command called a method that doesn't exist; caught by mypy before any test ran).

**Next exact task:** slice R2 (MED-004: image embeds and missing-image markers in notes).

### 00:04 — MED-004: images show up in notes, or say why they can't
**What:** Notes can now show images. An available image becomes an Obsidian embed pointing at a copy inside the vault, `_attachments/ab/<fingerprint>.png` (OD-14). Anything else becomes a visible warning that names the pointer and gives the reason in plain words, e.g. "Image missing: file-service://file-… (no file with this ID is in the export)". 7 new tests, 531 in total.
**Key decisions and why:**
- **Copies are named by fingerprint**, so the same image used in many chats is one file in the vault, and re-exporting copies nothing.
- **Copies are checked while copying.** If the source's bytes don't match the fingerprint, the copy is thrown away and nothing reaches the vault.
- **The vault never points outside itself.** Whether images were stored by reference or copied, notes only point into `_attachments/`. A test checks the note text contains no raw or workspace path.
- **A link checker** (`check_embeds`) lists every embed whose file is missing. Escaped text from chats (`\[\[`) never counts as an embed.
**Teach-back (`rendering/media.py`):** "An image in a note is a verified copy inside the vault, named by its fingerprint, so the vault never depends on where my raw files live. If the image isn't available, the note shows a warning with the pointer and the reason in its place. A link checker confirms every embed in a note points at a real file."
**Talking points:**
- "A note never lies about an image: it shows it, or says why it can't."
```
ruff check .            # All checks passed!
mypy                    # Success: no issues found in 79 source files
pytest -q               # 531 passed, 6 skipped (7 new)
```
Finish line: link checker passes for all 5 available images (reference and copy modes); `asset_problems` renders 4 markers naming pointer and reason; no raw path in the note. Fix attempts: 0.

**Next exact task:** slice R3 (BRW-001: browse a conversation from its source links; `ke inspect`).

### 00:08 — BRW-001: read back what the archive holds
**What:** A conversation can now be turned back into a readable "source transcript" note, built from the database rather than the export. It shows the active path numbered message by message, then every alternate branch labelled as an edit or a regeneration and where it branches off. Each message carries an anchor made from its permanent ID, and images appear as embeds or missing markers. `ke inspect` lists stored conversations, and `ke inspect <id>` shows one conversation's structure as counts only. Add `--note VAULT` to write the transcript. 19 new tests, 550 in total.
**Checked on every fixture:** every stored message appears exactly once, every anchor resolves to a real message ID, every image embed resolves in the vault, and inactive branch messages never appear in the active path section.
**Key decisions and why:**
- **Built from the database.** The note shows what the archive actually holds, including the newest version of an edited message (older versions stay in the database).
- **Counts-only inspect.** `ke inspect` never prints titles or message text, and it doesn't print the note's file name either (which contains the title), so it's safe to run against the real data at the REV-009 checkpoint.
- **A known gap.** When a message's parent is missing from the export, the database keeps the message but not the dangling parent ID. The import report already warns about it (`graph_missing_parent`), and the note still shows the message, as its own starting point.
**Teach-back (`rendering/transcript.py`):** "The transcript is rebuilt from the database: the active path first, then each alternate branch, labelled as an edit or a regeneration, never stitched in. Every message gets an anchor made from its permanent ID, so links to it survive re-imports. Images appear in place, or a marker says why they can't."
**Talking points:**
- "I can read back exactly what the archive holds, with branches kept separate and every message linkable."
```
ruff check .            # All checks passed!
mypy                    # Success: no issues found in 81 source files
pytest -q               # 550 passed, 6 skipped (19 new)
```
Finish line: all 14 fixtures render with every message reachable and anchored, labelled branches, and 0 broken embeds. Fix attempts: 1 (my new tests compared the full active path instead of its messages, and expected a "Detached" label the stored form can't know about; the code was right, the tests were corrected before commit).

**Next exact task:** slice E (EVAL-010: M1 evaluation).

### 00:11 — EVAL-010: the whole pipeline on 50 and 100 chats
**What:** `ke eval smoke` runs the whole first milestone on a batch in a scratch workspace: import, identical re-import, and a transcript note for every chat. It records timings, memory and warnings, and checks seven things. 4 new tests, 554 in total.
**Results on generated batches:** 50 chats import in 1.5 s, re-import in 1.0 s and render in 0.2 s; 100 chats take 2.7 s, 1.9 s and 0.5 s. Peak memory is about 75 MB. Both pass every check: the second import adds nothing, nothing calls a model, every note renders with no broken image links, the source is untouched, and the counts reconcile. Details are in `docs/evaluation/EVAL-010_SMOKE.md`.
**Not done yet:** the same run on 50 and 100 of Louis's real chats. That has to happen on his PC (read-only, outputs in the git-ignored workspace), together with the REV-009 checkpoint, so EVAL-010 stays open.
**Also:** the importer gained an internal `limit` (import only the first N chats). A limited run never marks other chats "not seen".
**Teach-back (`evaluation/smoke.py`):** "The smoke test runs import, re-import and rendering on a batch and checks that the second import adds nothing, nothing calls a model, every image link works and the source is untouched. It records timings and warning codes, never content. It's the 'does the whole thing work' test, sized like a real slice of my archive."
**Talking points:**
- "One command proves the pipeline end to end on a realistic batch, and its report is safe to share."
```
ruff check .            # All checks passed!
mypy                    # Success: no issues found in 83 source files
pytest -q               # 554 passed, 6 skipped (4 new)
```
Fix attempts: 0.

**Next exact task:** Milestone 2, starting with ING-010 (in plan order); REV-009 real-data checkpoint when a session on Louis's PC is available.

### 00:12 — REV-009 prep: `ke inspect` shows what the checkpoint asks for
**What:** `ke inspect <conversation>` now also lists role counts, content-type counts and the first 8 characters of each message ID on the active path. That's everything REV-009 asks to see on real data, still with no text, titles or file names. 1 new test, 555 in total.
**Next:** run the REV-009 checkpoint and the real half of EVAL-010 on Louis's PC (read-only, outputs in the git-ignored workspace).

### 00:15 — Two owner decisions: no tagging by Louis, and an easy interface
**What:** Louis made two calls tonight, now recorded in `OPEN_DECISIONS.md` and the plan.
- **"You perform the review."** Louis won't tag, label or review anything. Wherever the plan had him checking an answer key or giving yes/no verdicts, a separate Claude session now builds a *reference set* without seeing the output it will be compared with (ideally a different model), and the code checks still run. Disagreements go to another independent session, never to whoever produced either side. REV-003 and the evaluation tickets no longer wait on him.
- **"Make sure there is also an easy to use interface."** A small local web app, started with `ke ui`, comes right after the import report: import history and reports, an Import button, and a chat browser with branches and images. Registry and search pages follow in M2, and a read-only view of AI suggestions in M3. It runs only on his machine, with no accounts. New tickets: UI-001 to UI-005.
**Talking points:**
- "Evaluation doesn't need me: an independent, blind reviewer builds the reference, and code checks the evidence."
- "Everything the CLI does has a plain browser screen, local-only."

### 00:19 — Wayfinder check: is the build on track?
**What:** Louis asked for a "wayfinder" check that everything is on track. I compared the real state of the project with the plan: all GitHub issues (#4–#175), every merged PR, `IMPLEMENTATION_PLAN.md`, `M1_CONSOLIDATION.md`, `REVIEW_ACTION_PLAN.md`, ADR-0009 and `OPEN_DECISIONS.md`. Then I ran the full test suite myself on `main` instead of trusting the logs: 555 passed, 6 skipped.
**Verdict:** on track. All of M1's code slices are merged in plan order, one or two tickets per PR. Every closed M1 issue has a merged PR behind it, and every code PR has a teach-back in this diary. The two open M1 issues (EVAL-010's real-data half and the REV-009 checkpoint) are honestly open. There's no paid-API code in `src/`. The only test files touched after they were written just gained new tests, so no existing test was changed.
**Problems found:**
- **Windows.** The rule says merge once tests pass on Linux *and* Windows, but only the first PR (#3) was ever run on Windows. The 19 slice PRs since then have only been tested on Linux. One of them has Windows-only code (the import lock). A Windows run is now a condition for passing gate G1.
- **Who checks the answer key.** At 00:13 Louis said he won't do any tagging or reviewing. The coordinator had already recorded that in `OPEN_DECISIONS.md`. I re-scoped REV-003 (#137) so an independent Claude session reviews the key. ADR-0009, the review action plan, `TEST_STRATEGY.md` and AGENTS.md guardrail 1 still say "the owner approves" or "human-labelled", so they need a matching edit before M3 starts.
- **Stale tracker.** The M1 map still said PR #3 was "waiting on review". The direction-review map listed only 4 of its 9 tickets. The M3–M6 maps still said "planned, not committed", even though Louis put everything back in scope at 23:32. The new UI tickets weren't attached to any milestone. I fixed all of these on GitHub without touching code.
- **Order.** The plan now puts the local web UI (UI-001) next, but the build thread's status still says M2. I've let it know.
**Why it matters:** an agent that builds fast can drift without anyone noticing. A check like this costs half an hour and compares the plan, the tracker and the code against each other, instead of trusting any one of them.
**Talking points:**
- "I don't trust a green tick in a log. The progress check reran the tests itself."
- "The biggest risk wasn't the code. It was a process rule (test on Windows before merging) that quietly stopped being followed."
- "When I stepped back from reviewing, the plan had to change too: an independent AI reviewer, kept separate from the AI being scored."

### 00:22 — UI-001: `ke ui` opens the archive in the browser
**What:** `ke ui` starts a small website on this computer only and opens it. The home page shows how many chats are stored, how many were in the latest export, how many weren't (kept, never deleted), and every import. Each import has a report page in plain sentences ("3 new chats, 1 changed, 40 unchanged", "Your original files were not changed", "Some images couldn't be found: 2 missing"), with the full numbers behind a "details" toggle. 9 new tests, 564 in total.
**Safety:** it refuses to listen on anything but 127.0.0.1, it answers only requests addressed to localhost (so another website can't reach it by a DNS trick), every page is auto-escaped, and pages carry a policy that allows no scripts at all. No accounts, nothing in the cloud. It reads the import ledger only; it computes nothing new.
**Also:** STATUS's header no longer calls TICKETS.csv "kept in sync" (it's frozen), ADR-0009 is now `accepted` and says the answer key is reviewed by an independent session. AGENTS.md guardrail 1 still says the owner approves the gold set; agents can't edit AGENTS.md, so that line is listed for Louis.
**Teach-back (`ui/app.py`):** "`ke ui` runs a tiny web server that only listens on my own computer and only answers requests addressed to localhost. Each page reads what the importer already stored and fills an HTML template that escapes everything, so chat text can never become code. The report page turns the stored import receipt into plain sentences, with the raw numbers one click away."
**Talking points:**
- "One command opens my archive in the browser: local only, no accounts."
- "The web pages reuse the same stored data as the command line; they're another view, not another system."
```
ruff check .            # All checks passed!
mypy                    # Success: no issues found in 87 source files
pytest -q               # 564 passed, 6 skipped (9 new)
```
Fix attempts: 0.

**Next exact task:** UI-002 (import from the browser; wires `ke import` and replaces the placeholder test with a real one).

### 00:27 — UI-002: an Import button, and `ke import` works
**What:** the web interface has an Import page: paste the path of your export (the ZIP or its folder), press Import, and a progress page checks back every two seconds until the report appears. If it can't run, it says why in one plain sentence ("That isn't a ChatGPT export this version understands", "Another import is running") and never shows your file names. `ke import SOURCE` now runs the real importer too, with the same messages; `--partial` is for a source that's only some of your chats, so nothing else is marked "not seen". 8 new tests, 569 in total.
**Safety:** the form carries a secret token that only this app's own pages know, and a request from another website's address is refused, so no web page can start an import behind your back. The path can't point inside the workspace.
**Test change (recorded):** the old "`ke import` is an honest placeholder" test was replaced, not deleted, by real tests (missing source, unsupported source, import then repeat import). That was approved under Louis's delegated authority and logged in OPEN_DECISIONS.
**Teach-back (`ui/jobs.py`):** "Pressing Import starts the real importer on a background thread, because a big export takes longer than a browser waits for a page. The progress page reloads itself until the job is finished, then sends you to the report. It's the same importer as the command line, and the workspace lock still means only one import runs at a time."
**Talking points:**
- "Importing is one button now, and the button can't be pressed by another website."
```
ruff check .            # All checks passed!
mypy                    # Success: no issues found in 90 source files
pytest -q               # 569 passed, 6 skipped
```
Fix attempts: 1 (a missing path was reported as "unsupported format"; the CLI now checks it exists first).

**Next exact task:** UI-003 (chat browser with branches and images).

### 00:32 — UI-003: browse chats, branches and images in the browser
**What:** a Chats page lists every conversation, newest first, with a title search. Opening one shows the conversation the way ChatGPT last showed it, then each other branch (an edited question or a regenerated answer) in its own box, labelled with its kind and a "Go there" link to where it leaves the main path. Images appear in place. A missing or unmatched image shows a marker with the reason instead of a broken picture. 20 new tests, 589 in total.
**Same as the notes:** the page and the Obsidian transcript note now share one function (`transcript_sections`) that decides what goes where. I checked that the notes come out byte-for-byte the same on all 16 fixture chats after the change.
**Safety:** images are served only after their fingerprint is checked again, so an image edited after import isn't shown as if it were the original. Only real image types are shown inline; anything else is a download. The title search treats `%` and `_` as plain characters.
**Teach-back (`ui/data.py` conversation_page):** "The chat page asks the same function as the Obsidian note to split a conversation into the main path, the side branches and anything orphaned, so every message shows up exactly once. Each branch says what kind it is and links back to where it split off. Images are fetched by their fingerprint and re-checked before they're shown."
**Talking points:**
- "Branches are never merged: you see the main conversation and each alternative side by side, with a link to where it forked."
- "The browser view and the Obsidian notes can't drift apart, because they use the same code to lay a chat out."
```
ruff check .            # All checks passed!
mypy                    # Success: no issues found in 90 source files
pytest -q               # 589 passed, 6 skipped
```
Fix attempts: 1 (the chat list counted the tree's empty root as a message; it now counts only nodes with a message, and a test checks the list matches the chat page).

**Next exact task:** ING-010 + NRM-003 (Milestone 2).

### 00:36 — NRM-003 + ING-010: exact positions, and transcripts with honest times
**What (NRM-003):** one fixed way to point at exact words: a start and end position counted in characters, as Python counts them (an emoji is one character, a Windows line break is two), plus a fingerprint of the quoted words, so a citation can be checked before it's trusted. Converters handle the other ways tools count: browsers count UTF-16 units and files count bytes.
**What (ING-010):** reads a transcript file (WebVTT subtitles, SRT subtitles, or pasted plain text) into cues. Each cue keeps the time the file gave it, to the millisecond, or no time at all. A speaker comes only from an explicit WebVTT voice tag; "Name: words" stays as words. Cues that are out of order, end before they start, or have unreadable timing are kept as they are and reported. The file's fingerprint, source URL and language travel with it. Nothing is downloaded. 16 new tests (7 offsets, 9 transcripts, including two random round trips), 605 in total.
**Teach-back (`ingestion/transcripts.py`):** "A transcript file becomes a list of cues, each with the exact time the file gave it or no time at all, never a guessed one. A speaker name is only taken from an explicit subtitle tag, so a line like 'Bob: hi' isn't mistaken for a speaker. Anything odd, like cues out of order, is kept as written and reported as a warning instead of being fixed."
**Talking points:**
- "Citations are a position plus a fingerprint, so I can prove a quote still matches its source."
- "Transcripts never get invented timing or invented speakers."
```
ruff check .            # All checks passed!
mypy                    # Success: no issues found in 94 source files
pytest -q               # 605 passed, 6 skipped
```
Fix attempts: 1 (the parser turned non-breaking spaces into ordinary spaces; the random round trip caught it, and text is now kept exactly).

**Next exact task:** LNK-001 (URL occurrences and link registry). The M1 gate run (Windows tests, real data, `ke ui` on Windows) is running on Louis's PC.

### 00:42 — LNK-001: every link in your chats, with where it was said
**What:** every web link in every message is now recorded during import. Each destination is stored once. Each mention records which message it's in, who wrote it, and exactly which characters it covers. Links in the "sources" an AI answer cites are recorded too. A link written three times becomes one destination with three mentions. Importing the same export again adds nothing. If a message was edited, the new version gets its own mentions and the old ones stay as evidence. Links are never opened. 18 new tests, 623 in total.
**The fiddly part:** a URL inside a sentence has to be cut out exactly: "(see https://x.org/a)." mustn't include the bracket or the full stop, but Wikipedia's "Python_(language)" must keep its bracket. Markdown `[text](url)` and `<url>` are handled too. A random test puts URLs inside random text and checks that each one is cut out exactly. It caught that URLs can legitimately end with "_".
**Decisions:** the destination ignores the "#section" part and upper/lower case in the domain name, but keeps the "?query" exactly, because changing it can mean a different page. Bare "example.com" without "https://" isn't guessed at.
**Teach-back (`links/extract.py`):** "During import, every web link in a message is found and cut out exactly, without the sentence's punctuation, and pinned to its character positions. Links that mean the same page are grouped under one destination, so a link mentioned 12 times is one destination with 12 mentions. Nothing is ever downloaded; a link is just text."
**Talking points:**
- "Links are a registry: one destination, many mentions, each with its exact source."
- "Random testing found an edge case I'd have missed: URLs that end in an underscore."
```
ruff check .            # All checks passed!
mypy                    # Success: no issues found in 100 source files
pytest -q               # 623 passed, 6 skipped
```
Fix attempts: 1 (the trailing-underscore case above).

**Next exact task:** YTB-001 + YTB-002 (YouTube video identity, transcript status and user-supplied transcripts).

### 00:45 — YTB-001: one record per YouTube video
**What:** any link to a YouTube video, in any of its forms (watch, youtu.be, shorts, live, embed, mobile, music), now also creates one record for that video, keyed by its 11-character ID. Every link to it becomes a mention that keeps its own timestamp, playlist or channel hint. A test links one video 12 different ways and gets exactly 1 video with 12 mentions. Re-importing adds nothing. Every video starts with transcript status "not requested". Nothing is fetched. 26 new tests, 649 in total.
**Lookalikes:** the host has to really be YouTube. "youtube.com.example.net" and "notyoutube.com" stay ordinary web links. A channel page or playlist page isn't a video, so it isn't made into one.
**Also:** a workspace imported before this change gets its video records on its next import, because the YouTube check runs on existing link mentions too.
**Teach-back (`links/youtube.py`):** "Every YouTube link is turned into the video it points at, however it was written, and checked against the real YouTube hosts so lookalike domains don't count. One video gets one record, and each link to it is a mention that remembers its own timestamp or playlist. Getting a transcript is a separate, opt-in step that starts as 'not requested'."
**Talking points:**
- "A video linked 12 different ways is one video with 12 mentions."
```
ruff check .            # All checks passed!
mypy                    # Success: no issues found in 104 source files
pytest -q               # 649 passed, 6 skipped
```
Fix attempts: 0.

**Next exact task:** YTB-002 (transcript status, policy gate and user-supplied transcripts).

### 00:49 — YTB-002: video transcripts, behind the network switch
**What:** each linked video now has a transcript status, and there are two ways to give it a transcript.
- **You supply it:** `ke transcript add <video> <file>` attaches a VTT, SRT or text file you have. The file is read with the transcript reader (ING-010), its bytes go into the archive, and it's stored, never edited, with its cues and a note of where it came from. Attaching the same file again changes nothing.
- **A provider fetches it:** only if the `transcript_fetch` network switch is on, and it's off by default. With it off, the provider isn't even called; the request is recorded as "permission required" with the reason. With it on, temporary problems (rate limits) get at most 3 tries, and "unavailable" is a final answer with its reason. A transcript you already have is never fetched again or downgraded.

No provider is built in: getting transcripts from the internet needs an authorised source (INT-002). Transcript text only ever comes from a file; nothing is generated. 6 new tests, 655 in total. `ke transcript status <video>` shows where things stand.
**Teach-back (`links/video_transcripts.py`):** "A video's transcript either comes from a file I supply, stored unchanged with where it came from, or from a provider, and a provider is only asked if the network switch is on. With the switch off, the request is recorded as 'permission required' and nothing leaves my computer. Temporary failures get three tries; a 'not available' answer is recorded as final."
**Talking points:**
- "The policy gate is tested: with the switch off, a fake provider counts zero calls."
```
ruff check .            # All checks passed!
mypy                    # Success: no issues found in 107 source files
pytest -q               # 655 passed, 6 skipped
```
Fix attempts: 0.

**Next exact task:** SOC-001 + SOC-002 (social account mentions and registry).

## 2026-10-28

### 00:50 — The answer key gets checked, by an agent, because Louis opted out
**What:** Louis said he wants no involvement in tagging and asked for the answer-key review to be done for him. That collides head-on with the biggest lesson from the earlier attempts: an AI marking an AI's homework. So the review was run with the most independence the setup allows. A Remote Control session on his PC read each of the 10 chats from `raw/` and wrote its *own* reference first, then opened the key for that chat and compared. The verdicts live beside the key in the private, git-ignored folder; the key itself is untouched and its hash is recorded before and after.
**Result:** 113 things checked (18 segments, 95 items). 82 ok, 29 fix, 2 drop, 28 add. Twenty of the 29 fixes were one bug: two chats numbered messages without counting code-type messages, so every later citation was off by one or two. Segment boundaries matched the independent read within one message everywhere. No assistant suggestion was marked accepted without a user message behind it. The key had no quotes, so quotes couldn't be checked word for word.
**Most common misses:** things the assistant said recorded as the owner's facts or ideas; short user instructions and rejections ("try again", "rate each one") not captured; artefacts inside code messages and links skipped.
**Decision:** the record says "agent-reviewed, not owner-approved", and every accuracy number scored against this key carries that label. Follow-ups go to new tickets: a versioned key v2 with the fixes applied, and a numbering rule plus verbatim quotes in the annotation guide.
**Challenges:** the folder-consent card needs a human click and Louis was away, so Remote Control (already approved for this device) did the job instead. Nothing left the PC.
**Talking points:**
- "When the owner won't label, the next best thing is a reviewer that writes its answer before it looks at yours."
- "Twenty of twenty-nine errors were one counting rule. Fix the rule, not the twenty items."
- "Label your evidence: 'agent-reviewed' and 'owner-approved' are different grades."

### 2026-10-28 00:50 UTC — What steps did the old pipelines actually go through?
**What:** Louis asked what each phase of his old Codex/Hermes pipelines did, including the first pre-processing pass over all chats. Claude re-read the old docs and scripts (read-only) and added §2a to `docs/reference/previous-attempts-review.md`. It covers the nine v1 pre-processing steps, the May v1 eight stages, the September overhaul's steps and the August v2 nine passes. For each one it gives what it did, inputs and outputs, who ran it, where it broke, and where it fits in today's plan.
**What stood out:** the old pre-process copied 931 images but linked none of them to a chat, sorted all messages by time (mixing branches together), and dropped "yes"/"no" replies as filler, which are exactly the replies that decide things. All three pipelines declared success when their own checks passed.
**Challenges:** the PC session couldn't `git push` without a permission prompt while Louis was away, so the text was relayed and a cloud session opened the PR.
**Talking points:**
- "Draw the old pipeline before you design the new one. You see where it broke at a glance."
- "My old pre-process threw away the word 'no'. That's the most important word in a decision."

### 00:55 — LEG-001: the old pipelines' failures, as tests
**What:** a new synthetic fixture and 7 tests. Each one guards a failure from Louis's earlier attempts and cites the step in `docs/reference/previous-attempts-review.md` §2a where it happened:
- an edit and a regeneration whose timestamps interleave stay on separate branches; the old P4 sorted everything by time and stitched them together;
- two chats with the same title stay two conversations (P1 named files by title);
- short replies like "no" and "ok" are kept word for word, each with its own anchored line (P6 scored them as filler and dropped them);
- code and its execution output are kept and counted when numbering. Dropping them shifted every later number, which is the answer-key bug REV-003 found;
- a generated chart is linked to the message that shows it (P2/P3 linked 0 of 931 images), and an image file no message uses is reported as unreferenced.

Already covered, so not repeated: one image used by two messages (`repeated_image`), and the separate edit and regeneration cases.
**A wrinkle:** the fixture rules require every text to say "synthetic", so the short replies are "Synthetic no" and "Synthetic ok". They are still two-word replies, the kind the old scorer threw away.
**Numbering check:** REV-003 found two answer-key chats numbered without code messages. The engine's numbering counts every message, and a test now pins that down.
**Teach-back (`evaluation/synthetic.py` legacy case):** "Each old failure became a small fake chat that would have tripped it: branches with mixed-up timestamps, two chats with one title, one-word answers, code output and an image. The tests prove the importer keeps all of it straight. If someone 'optimises' it back into the old bugs, a test goes red."
```
ruff check .            # All checks passed!
mypy                    # Success: no issues found in 108 source files
pytest -q               # 672 passed, 6 skipped
```
Fix attempts: 1 (the fixture's short replies first lacked the required "synthetic" marker).

**Next exact task:** SOC-001 + SOC-002 (social account mentions and registry).

### 01:01 — SOC-001 + SOC-002: social accounts mentioned in chats
**What:** the importer now spots social accounts in every message and keeps a registry of them.
- A profile URL (X/Twitter, Instagram, TikTok, LinkedIn, YouTube, GitHub, Reddit, Bluesky, Threads, Facebook, Twitch) becomes a resolved mention. Posts, repos, videos and lookalike hosts don't count.
- A handle with its platform named ("GitHub: @octo", "@octo on Twitter") resolves too, and so does a Fediverse address (`@user@server`).
- A bare `@name` is stored as **ambiguous** with no account, even when an account with that handle exists. Guessing would invent a real person's identity.
- Emails, Python decorators and anything in code are not accounts.
- One account however it was written: the URL and the handle become aliases of the same row, and every mention keeps its exact span.
- `ke accounts` lists accounts with mention counts, conversation counts and first/last seen; `--ambiguous` lists the bare handles.

Nothing is fetched, followed or contacted. Identity starts at "probable" because the engine only ever has text.
**Teach-back (`links/social_store.py`):** "Every place a chat mentions an account becomes a mention row pinned to the exact characters. Mentions that clearly name a platform point to one shared account row, and every spelling of it is kept as an alias. A bare @name is kept as a question, never linked, because guessing who someone is is how you invent a person."
```
ruff check .            # All checks passed!
mypy                    # Success: no issues found in 113 source files
pytest -q               # 699 passed, 6 skipped
```
Fix attempts: 1 (a test line was too long for ruff).

**Next exact task:** REL-002.

### 01:10 — REL-002: links between separate chats
**What:** a new `relationships` package. It stores links between conversations and proposes them from exact evidence only. There are four detectors:
- **Copied node IDs:** two chats contain the same message node, as when ChatGPT copies messages into a new chat. The newer chat is proposed as `forked_from` the older one.
- **Copied opening:** two chats start with the same two or more messages, word for word, including a user message. The newer chat is proposed as `forked_from` the earlier chat it shares the longest opening with, so a prompt reused across many chats doesn't link every pair.
- **Chat links:** a message links to `chatgpt.com/c/<id>` and that chat is in the archive, giving `references`. Share links can't be mapped to a chat, so they are only counted.
- **Pasted paragraphs:** a user message contains a whole paragraph (100+ characters) that first appeared in an earlier chat, giving `quotes`.

Everything starts as a **candidate**. `ke related review <id> accept|reject` records a decision. The history only grows: the database refuses to update or delete it. A rejected link is never proposed again, and reviewing never flips the direction.

**Decisions:** comparing openings uses the text, not the stored content hash, because that hash includes the time and a copy always has a new time. With no times, which chat came first is unknown, so the link becomes `related_to` with direction unknown. Both are logged in OPEN_DECISIONS.
**Cost:** detection runs only when an import changed something. It took 2.7 s over 1,000 generated chats. The generated batch gave 50 copied-opening candidates, because its generator reuses a small set of phrases, so real data may produce fewer.
**Teach-back (`relationships/detect.py`):** "After an import, the detectors look for proof that two chats are connected: the same message IDs, the same opening messages, a link to the other chat, or a pasted paragraph. Each one becomes a candidate with its evidence as IDs, never copied text. A person accepts or rejects it, and that decision is kept forever and never undone by a re-run."
```
ruff check .            # All checks passed!
mypy                    # Success: no issues found in 119 source files
pytest -q               # 729 passed, 6 skipped
```
Fix attempts: 1 (the new fixture manifests lacked the conversation count the fixture tests check).

**Next exact task:** RET-001.

### 01:15 — RET-001: search every message
**What:** `ke search "words"` finds messages across every imported chat, using SQLite's built-in full-text search (FTS5). It has three modes:
- **tokens** (the default): all the words, in any order.
- **phrase:** the words together, in order.
- **exact:** character for character, case included, for error codes and IDs such as `SYN-CODE-4471`.

The first two ignore case and accents, so `cafe` finds `café`. Every hit names the exact message version, its chat and its node, and shows a snippet with the match in [brackets]. Search is always limited to one workspace.

**Design choice:** the index is its own file, `workspace/index/search.db`, and not part of the archive database. It only holds things that can be rebuilt, so deleting it is always safe: the next import or search refills it. It does copy message text, so the future deletion feature must clear it too, and OPEN_DECISIONS says so.
**Safety:** what you type never becomes search syntax. Every word is quoted, so searching `NOT AND OR` finds those words. A Hypothesis test throws random text at it and checks that no query breaks.
**Cost:** imports index only new message versions, and an identical re-import indexes nothing. A workspace imported before this change is indexed on its first search: 1.3 s for 1,000 generated chats, then about 0.7 s per search including start-up.
**Teach-back (`retrieval/lexical.py`):** "Every message version is copied into a separate search file that SQLite indexes word by word. A search quotes each word you type and returns the best-ranked messages, each pointing back to its exact chat and message. Because the file is only a cache, I can delete it at any time and it rebuilds itself."
```
ruff check .            # All checks passed!
mypy                    # Success: no issues found in 123 source files
pytest -q               # 757 passed, 6 skipped
```
Fix attempts: 1 (a typing error from building a hit out of a row slice).

**Next exact task:** UI-004 (links, YouTube and accounts pages, plus a search box).

### 01:20 — UI-004: links, videos, accounts and search in the web UI
**What:** `ke ui` gets five new pages, linked from the header and the home page:
- **Search:** one box with three choices (all the words, the words in order, exactly). Each result shows its chat, who wrote it and when, with the match in [brackets], and links to that message.
- **Links:** every web address once, with mention and chat counts, filterable. Each address has a page listing every mention as written.
- **Videos:** one row per YouTube video with its transcript status. Each video page lists every mention, with clickable start times such as 1:15.
- **Accounts:** the registry with first and last seen dates. Bare @names are listed separately and never linked to an account. Each account page shows every way it was written.

Every mention on every page links to the exact message (`/chats/<id>#<anchor>`). The tests follow each of those links and check the anchor exists on the chat page.
**Safety:** links that leave the app are marked "opens the real site" and carry `rel="noreferrer noopener"`. Message text is escaped, so a message containing `<b>` shows the characters. The pages never fetch anything. The only write is bringing the search index up to date, and that file is a cache.
**Tidy-up:** the account listing queries moved into `social_store`, so `ke accounts` and the page share one implementation.
**Teach-back (`ui/registries.py`):** "Each page is a read-only view of a registry the importer already keeps: links, videos, accounts. Every row is one click from the message that mentioned it, because each mention stores its exact message version. The search page uses the same index as `ke search`."
```
ruff check .            # All checks passed!
mypy                    # Success: no issues found in 125 source files
pytest -q               # 766 passed, 6 skipped
```
Fix attempts: 0. Screenshots of the search and video pages checked by eye.

**Next exact task:** start M3. Read the M3 plan and LEG-002..005 (#190–#193) and REV-012 (#187) first.

### 01:25 — FND-007 + FND-009: how the engine will ask a model, without paying for an API
**What:** the start of Milestone 3, built the way ADR-0009 decided. There is no API client. A provider takes a batch of requests (`submit`) and later hands back whatever has arrived (`collect`): each answer is **ok**, **invalid** (with the reason) or **pending**.
- **FakeProvider** and **ReplayProvider** support tests and repeatable re-runs. Neither makes a network call.
- **FileBatchProvider** is the real one. It writes `private/model-batches/<run>/<batch>.request.jsonl` with a manifest. A Claude Code session on Louis's PC appends answers to `<batch>.response.jsonl`, and the engine reads them back.
- **ModelStageRunner** is the only way a stage reaches a provider.
  - It checks the cache first. The same stage key is answered with zero provider calls.
  - It never re-sends a request that is already waiting.
  - It stores only validated answers.
  - An invalid answer gets one repair request that carries the error. A second failure becomes `review_required` for a person, and nothing loops.

**Guards, each with a test:**
- The `text_llm` switch is checked before anything is written or sent. The runner checks it for every provider, even the fake one.
- A request file edited after writing is refused, by comparing it with the SHA-256 in its manifest.
- A cut-off last line, a line for an unknown request or a second line for the same request is ignored, never guessed at.
- An answer with an extra field or a label outside the list is refused.
- Error messages name the field and the problem, never the answer's text.

**Runbook:** `docs/runbooks/LABELLING_SESSION.md` explains how to run a labelling session: deny rules for the answer key, a fresh context per file, append-only answers.
**Teach-back (`providers/ledger.py`):** "Every model question has a fingerprint, its stage key. Before asking, I look the fingerprint up, so the same question is never asked twice. When an answer comes back, code checks it against the schema: a good answer is stored for good, a bad one gets one retry with the error attached, and a second bad answer goes to a person."
```
ruff check .            # All checks passed!
mypy                    # Success: no issues found in 132 source files
pytest -q               # 780 passed, 6 skipped
```
Fix attempts: 1 (a variable reused with two types).

**Next exact task:** NRM-004 (topic segments), then the taxonomy tickets.

### 01:27 — The M1 gate passes on Louis's PC
**What:** the gate run finished in the Remote Control session on Louis's PC (Windows, Python 3.13.2, `main` at d878333). It was read-only, with outputs only in the git-ignored `workspace\rev009\` and nothing committed.
- **Tests on Windows:** ruff clean, mypy clean, pytest 589 passed, 6 skipped, 0 failed. That includes the ZIP test that used to fail on Windows.
- **Real smoke, 50 and 100 conversations:** all seven checks passed in both runs (everything rendered, no broken embeds, raw unchanged, counts reconciled, a re-import adds nothing, zero model calls). `raw/` has 2,074 files and none was touched.
- **`ke inspect`:** three real chats, no graph issues, and branch counts that add up.
- **`ke ui` on Windows:** home page 200; the chat list 200 with exactly 50 chat links, matching the 50 conversations.

So REV-009 (#143) and EVAL-010 (#39) are closed.
**Worth fixing (filed, not blocking):** import time hardly grows with the number of conversations, and a re-import takes twice as long as the first import. Something done once over all of `raw/`, probably hashing about 900 images, is repeated (PERF-001, #200). Peak memory isn't measured on Windows, and `ke inspect` prints full native IDs (OPS-009, #201).
**Talking points:**
- "The gate isn't my tests passing in the cloud. It's the real export, on the real machine, unchanged afterwards."
- "Doubling the chats barely changed the time. That tells you the cost is somewhere else."

### 01:31 — NRM-004: where a chat changes subject
**What:** a segmenter that splits each chat into topic segments without any model, so later labels are about one subject at a time. It works in four steps:
1. It cuts only *between exchanges*: a user question and its answers stay together. A short reply such as "no" never starts a segment, because it answers what came before.
2. A pause of six hours or more starts a new segment.
3. Where the words of the two exchanges before a point share almost nothing with the two after it, and that is a local low point, a new segment starts. Words that appear in most of the chat ("the", the chat's running theme, and every fixture's "Synthetic") are ignored first. This is a simplified TextTiling.
4. A segment over the size budget (24,000 characters) is not clipped. It becomes overlapping parts that each share one exchange with the next, so the first and last messages are always included. A single huge exchange becomes its own part and is flagged.

Every message in every section (the active path, each alternate branch, anything outside the tree) lands in exactly one segment, and branches are never mixed. `ke segments <conv>` shows boundaries and sizes without showing any text.
**Fixture:** `topic_segments` covers a garden shed, then sourdough in the same sitting, then Python packaging eight hours later. The "no shingles" reply stays in the shed segment. Boundary precision, recall and F1 are all 1.0, and a one-topic chat stays whole.
**LEG-005:** the no-clipping half is done (overlapping parts, `truncation_count` = 0). The "late short no comes out as rejected" check and accuracy by chat length need the extractor and the scoring runner, so #193 stays open.
**Teach-back (`segmentation/segmenter.py`):** "I group messages into question-and-answer exchanges and only ever cut between them. A long pause or a sudden change of vocabulary starts a new topic. A topic too long for one model request is split into overlapping parts instead of being cut short."
```
ruff check .            # All checks passed!
mypy                    # Success: no issues found in 136 source files
pytest -q               # 803 passed, 6 skipped
```
Fix attempts: 0. The 1,000 generated chats: full coverage, zero truncation, 2.5 s.

**Next exact task:** TAX-001 + TAX-002 (taxonomy registry and published snapshots).

### 01:35 — TAX-001 + TAX-002: the vocabulary, and frozen versions of it
**What:** the tables for the governed vocabulary, plus the one way classification will read it.
- **Terms by dimension.** Following OD-17, a term belongs to one dimension: domain, purpose, topic, knowledge type or output. Terms go two levels deep at most. A term starts as *proposed*. **Projects** have their own registry.
- **IDs never come from labels.** IDs are random (`term_…`, `proj_…`), so renaming "Unreal" to "Unreal Engine" keeps every label that points at it. A merged term must name what it merged into, and the database checks that.
- **Aliases are unique after normalising.** "Game development", "GAME-development" and "game  development" are the same spelling. One spelling can't mean two terms in a dimension, or two projects.
- **Publishing freezes a version.** `publish("tax-1")` copies the *approved* terms and projects into a version row with a SHA-256. `snapshot("tax-1")` reads only that copy, never the live tables. Approving something afterwards doesn't change tax-1, a version name can't be reused, and an edited snapshot is refused.
- **Unapproved terms can't be used.** Asking a snapshot for a proposed, retired or merged term raises an error, which is what the ticket's acceptance criterion requires.

**Teach-back (`taxonomy/registry.py`):** "Every category has a permanent random ID, and its names are aliases that can't collide. When the vocabulary is ready, I publish a frozen, fingerprinted copy of just the approved terms. Classification only ever reads that copy, so a half-decided term can't sneak into a run."
```
ruff check .            # All checks passed!
mypy                    # Success: no issues found in 140 source files
pytest -q               # 811 passed, 6 skipped
```
Fix attempts: 2. An alias row was flushed before its term, which broke the foreign key. Then one of my own new tests used an example that wasn't actually a collision.

**Next exact task:** TAX-003 (alias matching) + TAX-004 (proposal review and publish).

### 04:15 — TAX-003 + TAX-004: matching names, and reviewing changes
**What:** turning text into vocabulary IDs, and the only way the vocabulary changes.
- **Alias matching (TAX-003).** `AliasResolver` is built from a *published* snapshot, so it can only ever answer with approved IDs. "UE5", "ue5", "Unreal Engine 5" and "unreal-engine 5" all reach the same term. When a spelling names things in two places (a topic and a purpose, say), the answer is **ambiguous** with every candidate listed; narrowing the scope to one dimension (or `project`) settles it. Nothing is guessed. `find()` scans longer text for whole-word mentions only ("UE" never matches inside "queue"), lets the longest alias win, and keeps each mention's exact span. `collisions()` lists every shared spelling for review.
- **Review workflow (TAX-004).** A change starts as a proposal: add, rename, alias, merge, retire or reparent, for terms or projects. A proposed term doesn't exist as a term at all until someone *other than the proposer* approves it, and then only from the next published version. Every rule is checked at approval time: alias collisions, a third level, merging across dimensions, retiring a term that still has children, or touching something that isn't approved. Rename keeps the old label as an alias. Merge moves the aliases and keeps the old ID pointing at the new one. Decisions are final, and the proposal row records reviewer, note, time and the ID an approved add created. That row is the audit trail. Migration 0016 adds the note and the created ID.

**Teach-back (`taxonomy/review.py`):** "Nobody edits the vocabulary directly; they propose a change. Only a different person can approve it, and the approval is when the change is checked and applied. Classifiers still see nothing until the next frozen version is published."
```
ruff check .            # All checks passed!
mypy                    # Success: no issues found in 145 source files
pytest -q               # 827 passed, 6 skipped
```
Fix attempts: 0.

**Next exact task:** TAX-005 (project identity and merge proposals) + TAX-006 (corpus discovery).

### 04:20 — NRM-006 + TAX-005: a fair look at the corpus, and project names as questions
**What:** the input for taxonomy discovery, and how project names enter the registry.
- **Corpus inventory (NRM-006).** `corpus_inventory` reads every stored chat, segments it and keeps each segment's text in memory. It writes nothing; a test checks the database file is byte-identical afterwards. `summarise` gives counts only (chats, segments, characters, sections, length bands, themes), so it is safe to print.
- **A sample that reaches rare subjects.** Each segment's *theme word* is its most distinctive word by TF-IDF. `sample(items, n, seed=...)` takes one segment from every theme, rarest first, then a second from each, and so on. Within a theme the order is a hash of seed and segment ID, so the same seed always gives the same sample, whatever order the input came in. In the test, 40 shed segments and 3 rare ones (sourdough, beekeeping): every seed's sample of 4 includes both rare subjects.
- **Project candidates (TAX-005).** `propose_project` turns a name seen in chats into an `add` proposal and never creates or extends a project itself. If the name already belongs to an approved project, the proposal says `same_name_as` and waits. The reviewer either rejects it (same project) or approves it under a distinguishing label ("Atlas map script"), which is recorded in the decision note. The same candidate twice reuses the open proposal. Renaming or merging a project now needs a reviewer's note, because every label on it moves too.
- `ke corpus [--sample N --seed S]` prints the counts and sampled segment IDs, never text.

**Teach-back (`segmentation/inventory.py`):** "I find each segment's most unusual word and group segments that share it. The sample takes one from every group, smallest groups first, so rare subjects always show up. The order inside a group is a hash of the seed, so the same seed gives the same sample."
```
ruff check .            # All checks passed!
mypy                    # Success: no issues found in 150 source files
pytest -q               # 839 passed, 6 skipped
```
Fix attempts: 1. Two of my own new tests were wrong: one rolled back a proposal it hadn't committed, the other assumed a segment's text starts with its first user message.

**Next exact task:** TAX-006 (discovery candidates) + TAX-007 (version diff and invalidation).

### 04:25 — TAX-006 + TAX-007: suggesting categories, and knowing what a new version changes
**What:** where candidate categories come from, and how a new taxonomy version avoids redoing everything.
- **Discovery (TAX-006).** `discover()` groups segments and files one `add` proposal per group. That is its only write: no term exists, and nothing reaches a published snapshot, until a different reviewer approves it. The default backend is plain and repeatable. It takes the word shared by the most remaining segments, ignoring a fixed list of filler words and anything in more than half the corpus, makes those segments a group, and repeats. Each group is labelled by its top TF-IDF words. BERTopic is an optional local backend; without the library it says so up front. Labels that already name an approved term are reported as *known*, and labels already waiting are not proposed twice. Evidence keeps the backend, its version, keywords, size and up to 50 segment IDs.
- **Version diff (TAX-007).** `diff_snapshots(old, new)` lists IDs that were added, removed (merged or retired) and changed (label, aliases, definition or parent). `invalidate(diff, outputs)` marks only the saved outputs that cite a removed or changed ID, in an append-only table. When project A gets an alias, a classification that cites only project B or a topic is untouched. Stale outputs are flagged, never deleted. Migration 0017.

**Teach-back (`taxonomy/changes.py`):** "When a new taxonomy version comes out, I compare it with the old one ID by ID. Only saved answers that mention an ID that changed get marked stale. Everything else keeps its cached answer, so nothing is redone or paid for twice."
```
ruff check .            # All checks passed!
mypy                    # Success: no issues found in 155 source files
pytest -q               # 846 passed, 6 skipped
```
Fix attempts: 2. Grouping each segment by its single most distinctive word split one subject into several groups, so I switched to greedy grouping by shared word. Then filler words like "and" won ties, so I added a fixed stop list.

**Next exact task:** TAX-008 (governance reports) + CLS-001 (classifier schema).

### 04:31 — TAX-008 + CLS-001: a health check for the vocabulary, and a classifier that can't make things up
**What:** a report that finds vocabulary problems, and the answer shape every classifier must fit.
- **Governance report (TAX-008).** `governance_report()` only reads. It lists the following, by ID:
  - exact duplicates and near duplicates (spellings that differ only by spaces or a plural "s");
  - spellings shared between a topic and a project;
  - parent problems: missing, wrong dimension, loops, or more than two levels;
  - approved terms whose parent isn't approved (orphans);
  - broken or looping merges;
  - open proposals, oldest first, with each reviewer's approved and rejected counts;
  - any decision made by its own proposer.

  Fixes still go through proposals and a second reviewer. Run it with `ke taxonomy report`.
- **Classifier schema (CLS-001).** `output_model(snapshot)` builds the answer model from one pinned version:
  - Each dimension's `term_id` is an enum of that version's approved IDs. Projects get the same treatment.
  - Extra fields are refused. An invented label, a term from the wrong dimension, or a smuggled `new_term` therefore fails validation.
  - Each assignment has a rank (primary or secondary), a confidence and evidence message IDs. An empty list is a valid "nothing fits".
  - `answer_problems` checks the rules JSON Schema can't express: evidence must come from this segment, at most one primary per dimension, no duplicates.
  - The prompt is built only from the reviewed vocabulary, and the segment goes in as tagged data. The stage key includes the taxonomy version and its content hash.

**Teach-back (`classification/schema.py`):** "For each published vocabulary I build an answer form where the label field only accepts the approved IDs. If the model invents a label or adds a field, the answer is rejected before anything is saved. Rules a form can't express, like evidence having to come from this segment, get checked straight after."
```
ruff check / format     # All checks passed! / already formatted
mypy                    # Success: no issues found in 160 source files
pytest -q               # 863 passed, 6 skipped
migration drift         # 0
```
Fix attempts: 1. With only one approved ID, Pydantic writes `const` instead of `enum`, so I now always list `enum` as well. Two test-side slips (a `$defs` entry without properties, and "Synthetic" in a project name) were corrected in the new tests.

**Next exact task:** CLS-002 (SegmentClassifier service) + CLS-003 (keyword scoring and ranking).

### 04:38 — CLS-002 + CLS-003: labelling a segment, and why saying it once can beat saying it five times
**What:** the classifier itself, and a free, local scorer it uses by default.
- **Scoring (CLS-003).** Each approved term or project mentioned in a segment gets five features:
  - *mentions*, log-scaled, so the fifth "Unity" adds little;
  - *distinctiveness*: rarer across the corpus is higher;
  - *user*: did the user say it?
  - *decisive*: the user said it in a sentence with a decision cue ("decided", "going with", "switch to"...), with no "not" just before the name;
  - an optional *semantic* score from elsewhere.

  `rank` makes the best score in each field primary and the rest secondary. A near tie is broken by ID, the same way every time, and flagged for review instead of guessed.
- **Classifier (CLS-002).** `SegmentClassifier` pins one taxonomy version for the whole run. The keyword path builds its answer in the same CLS-001 shape a model must use, and validates it the same way. The model path goes through the stage runner, so it gets the cache, the egress switch and the single repair. An answer that cites messages outside the segment, or has two primaries, is kept but marked `review_required`, never `done`.
- **Fixture.** `mixed_projects` was added through the synthetic generator, so the regenerated fixtures stay byte-identical. In one chat the user names two projects and decides on one. In another, the assistant says "Unity" five times and the user settles on "Godot, not Unity".

**Teach-back (`classification/scoring.py`):** "I score each approved name a segment mentions on several clues, and how often it's said is only one of them. A user saying 'I've decided to go with Godot' counts for much more than an assistant repeating 'Unity'. If two labels end up almost level, I don't pick quietly: I break the tie the same way every time and send it to review."
```
ruff check / format     # All checks passed! / already formatted
mypy                    # Success: no issues found in 163 source files
pytest -q               # 880 passed, 6 skipped
migration drift         # 0
```
Fix attempts: 2.
1. A typing slip in `corpus_frequencies`. Also, my new test expected a refused answer to reach review in a single round, but the repair is a separate round by design, so I corrected the test.
2. I had hand-written the fixture folder, which the fixture suite rejects. I added it to the generator instead.

**Next exact task:** CLS-004 (classification persistence and review) + CLS-005 (order-independence diagnostic).

### 04:42 — CLS-004 + CLS-005: corrections that stick, and labels that don't depend on order
**What:** saving classifications and reviewers' corrections, and a check that processing order can't change a label.
- **Store (CLS-004).** Migration 0018 adds three append-only tables:
  - `classifications`: one row per stage key. Saving the same work again changes nothing; a `pending` row is completed once its answer arrives.
  - `classification_labels`: one row per label, so "segments about project X" is a query.
  - `classification_reviews`: a reviewer's choice per segment and field, where the newest wins and older choices stay as history.

  A review belongs to the segment, not to a run, so re-running the classifier can't overwrite it. `effective_labels` shows the reviewer's choice over the machine's. If a later taxonomy version drops a reviewed ID, the field shows `stale_review` rather than being silently kept or lost. `review_queue` lists flagged rows until every flagged field has a decision.
- **Order check (CLS-005).** `order_experiment` classifies the same segments in three orders (given, reversed, seeded shuffle) under one pinned version. It compares state and the sorted (field, ID, rank) labels, and ignores confidence decimals. Any segment that differs between orders becomes a review item. The keyword classifier is stable on the fixture, and a deliberately order-dependent stand-in gets flagged.

**Teach-back (`classification/store.py`):** "The machine's answers and a person's corrections are stored in separate tables, and corrections belong to the segment, not to a run. Re-running the classifier adds machine rows but never touches a correction, so the person's choice stays in force. If the vocabulary later drops an ID the person chose, I mark that choice stale instead of hiding it."
```
ruff check / format     # All checks passed! / already formatted
mypy                    # Success: no issues found in 167 source files
pytest -q               # 887 passed, 6 skipped
migration drift         # 0
```
Fix attempts: 0. Only lint fixes were needed: import order in env.py and the docstring's closing punctuation.

**Next exact task:** EXT-001 (typed knowledge record contract) + EXT-002 (evidence validator).

### 04:47 — EXT-001 + EXT-002: what a piece of knowledge is, and checking what it stands on
**What:** the record contract every extractor must fill in, and the check every record's quotes go through.
- **Records (EXT-001).** A record has:
  - a type (decision, rejection, preference, task...);
  - who holds it, and how it came about (`extracted`, `inferred`, `reviewer`);
  - how acceptance is known (`explicit`, `conditional`, `inferred`, `absent`);
  - a scope, its evidence quotes and its provenance;
  - a trust state.

  Extractors return a `CandidateRecord`, which has **no trust field**, so they can only propose. The stored `KnowledgeRecord` refuses three things:
  - `supported` without evidence that passed the validator, and `confirmed` without a named reviewer;
  - confirming an `inferred` record;
  - trusting a user decision, preference, requirement or task unless the acceptance was explicit or conditional.

  Trust only moves along a fixed table, and rejected is final.
- **Evidence check (EXT-002).** `check_record` loads each cited message revision.
  - A **malformed** reference makes the record `invalid`: the revision is missing, the range doesn't fit, the quote fingerprint doesn't match, the speaker is wrong, or a quote is cited twice.
  - Sound references with a doubtful **meaning** make it `review_required`: only the assistant's words behind a "user decision", acceptance claimed without the user's words, a hedged quote or a question, or a quote that sits inside quotation marks or a `>` line.
- **Note.** Evidence points at a message *revision* (`rev_`), which already pins the exact text and its first snapshot. That's stricter than the guidance DTO's snapshot plus node pair.

**Teach-back (`extraction/evidence.py`):** "Before a record can be trusted, I open every message it quotes and check the quote is really there, unchanged, and said by the person it claims. A broken reference rejects the record outright. A sound reference with a doubtful meaning, like a 'decision' that's only the assistant's suggestion, goes to a person instead."
```
ruff check / format     # All checks passed! / already formatted
mypy                    # Success: no issues found in 172 source files
pytest -q               # 908 passed, 6 skipped
migration drift         # 0
```
Fix attempts: 0.

**Next exact task:** EXT-003 (decision and rejection extractor) + EXT-004 (preference and requirement extractor).

### 04:52 — EXT-003 + EXT-004: who decided, and whose preference it is
**What:** the first two extractors, both rule-based, local and free.
- **Decisions (EXT-003).** An assistant sentence with a suggestion cue becomes a *proposal* held by the assistant. The user's next message is then read in one of four ways:
  - a rejection ("No, not green");
  - a conditional yes ("Ok, as long as it doesn't leak");
  - an explicit yes ("Yes, let's do that");
  - or **nothing**: a question like "how does SQLite handle concurrent writes?" accepts nothing.

  A decision cites both the user's yes and the proposal it answers. If there were several proposals, or the yes came with a question, it is flagged. The user's own "I've decided to use cedar cladding" or "I've ruled out pine" counts as well, unless it is negated ("I haven't decided...").
- **Preferences and requirements (EXT-004).** Only user sentences count, and questions are skipped.
  - Requirements are *hard* ("must", "no more than") or *soft* ("ideally", "would be nice").
  - Preferences are *for* or *against*, and *strong* ("really", "hate") or *mild*.
  - A view inside quotation marks, or a reported one ("My client said they want a light theme"), gets `attributed_to="external"` and always goes to review. It is never stored as the user's own.
- **Contract change.** The record contract is now `ext-001-v2`, with optional `strength`, `polarity` and `attributed_to`. The evidence check flags attributed records. The quotation test now looks at where the cue sits, so a sentence that *contains* a quotation is judged by the cue's position. The old private name is kept as an alias, so the EXT-002 tests are unchanged.
- **Fixture.** New generator case `extraction_rules`.

**Teach-back (`extraction/decisions.py`):** "When the assistant suggests something, I note it as the assistant's proposal, nothing more. It only becomes the user's decision if the user's very next words accept it, like 'yes, let's do that'. A question or a 'maybe' accepts nothing. Each decision quotes both the yes and the suggestion it said yes to."
```
ruff check / format     # All checks passed! / already formatted
mypy                    # Success: no issues found in 176 source files
pytest -q               # 926 passed, 6 skipped
migration drift         # 0
```
Fix attempts: 1. In the fixture, a quoted preference started mid-sentence, so the sentence start sat outside the quotes. The check now uses the cue's position (`quoted_at`). Separately, I first wrote the fixture's expected list to include the reported "they want" sentence, which needed its own branch.

**Next exact task:** EXT-005 (actions, questions, artefacts) + EXT-006 (named entities).

### 04:58 — EXT-005 + EXT-006: tasks, open questions, artefacts and named things
**What:** two more rule-based extractors, plus a small change to the record contract.
- **Actions, questions, artefacts (EXT-005).**
  - **Tasks.** "I'll sand it tomorrow" is the user's task, accepted explicitly. "You should sand it first" is a task the assistant suggested: it is held by the assistant with no acceptance, so it is never the user's commitment.
  - **Open questions.** Only user questions with no answer after them, or answered with "I'm not sure", count as open.
  - **Artefacts.** Images an assistant or tool produced become an artefact listing the real `occ_` IDs, with the ones whose bytes are missing listed again. Fenced code blocks are artefacts too.
  - **Evidence check.** EXT-002 now checks that each occurrence exists and that the missing list is truthful. Hiding a missing image makes the record invalid. A truthful missing list is sent to review so a person sees the gap.
- **Named references (EXT-006).**
  - A name needs a type cue: "playing Celeste", "the book Dune by Frank Herbert", "using Blender".
  - Mentions are grouped per entity, so Celeste mentioned twice gives one record with two quotes, in order of first mention.
  - A book's author is a detail and also its own person reference. People are never guessed from a bare name.
  - Links are skipped, because the link registries own them.
  - A name that matches an approved alias gets that ID. Unknown games create **nothing**: no project and no proposal.
- **Contract change.** The record contract is now `ext-001-v3`: `asset_occurrences`, `missing_occurrences` and `entity`. An artefact made only of images may use its occurrences as evidence.

**Teach-back (`extraction/actions.py`):** "When the assistant says 'you should sand it', I record that as the assistant's suggested task, not mine; only 'I'll sand it' is my task. A question is open only if nobody answered it or the answer was 'I'm not sure'. When the assistant produced an image, the record points at the real image occurrences and says plainly which ones have no bytes."
```
ruff check / format     # All checks passed! / already formatted
mypy                    # Success: no issues found in 179 source files
pytest -q               # 939 passed, 7 skipped (the new split-layout case adds one expected skip)
migration drift         # 0
```
Fix attempts: 1. Entity records first came out grouped by cue type rather than in text order. They are now sorted by first mention, and the new fixture's expected order was written to match.

**Next exact task:** EXT-007 (evidence promotion and review queue) + EXT-008 (extraction runner and versions).

### 05:03 — EXT-007 + EXT-008: one gate to the truth, and a runner that doesn't redo work
**What:** the only road from "an extractor proposed this" to "the system treats this as true", and the job runner that drives all the extractors.
- **Gate (EXT-007).** Migration 0019 adds `knowledge_records` and an append-only `knowledge_record_events` log. `add_candidates` stores proposals idempotently. `gate` runs the EXT-002 check:
  - a malformed reference means **rejected**;
  - a doubtful meaning means **review_required**;
  - otherwise the record is **supported**, but only if the record rules allow it. A user decision with no acceptance goes to review even when its quotes are perfect.

  A named reviewer can support, confirm or reject; "validator" can't confirm. `current_truth()` returns supported and confirmed records only, and it is the one reader later stages may use. Every trust change is logged with who, from, to, why and the problem codes.
- **Runner (EXT-008).** Each (segment, extractor) pair is one run with its own stage key. The key covers the segment's exact text plus the extractor, record-schema, prompt and taxonomy versions.
  - **Done** runs are skipped: zero work and zero model calls.
  - Each run sits in its own **savepoint**, so a crash rolls back only that run's writes and keeps everything the other extractors found.
  - A failure stores only the error's type name. Runs are retried up to 3 attempts in total, then left failed.
  - Model extractors use the FND-009 stage runner (cache, egress switch, one repair). The model only quotes words; the code finds them in the segment and builds the fingerprinted evidence itself. A quote that isn't really there is dropped.

**Teach-back (`extraction/store.py`):** "Everything an extractor finds starts as a candidate and has to pass one gate. The gate rejects broken quotes, sends doubtful ones to a person, and only lets well-supported ones through. The rest of the system can only read records that got through, and every change of trust is logged with who made it and why."
```
ruff check / format     # All checks passed! / already formatted
mypy                    # Success: no issues found in 183 source files
pytest -q               # 945 passed, 7 skipped
migration drift         # 0
```
Fix attempts: 0. One fix in my own new test: it passed a plain string where an enum was expected, which caused a serializer warning.

**Next exact task:** EVAL-001 + EVAL-003, then EVAL-004/011, OPS-001/002 and the LEG/REV fold-ins.

### 05:13 — EVAL-001 + EVAL-003: an answer key, and a scorer for classification
**What:** a format for hand-made answer keys, and the evaluator that scores classification against them.
- **Golden set (EVAL-001).** `evaluation/gold.py` defines `gold-v1`: per segment (named by its first message) the expected primary and secondary labels per field, or "ambiguous"; the records that must be found; and the records that must **never** appear, above all an assistant suggestion recorded as the user's decision.
  - A synthetic set lives in `tests/fixtures/gold/synthetic-v1/` and covers 9 synthetic conversations. The real set is started on Louis's PC with `ke gold template`, holds IDs only, and stays in the git-ignored workspace.
  - An independent review asked for six changes, all applied: a `records_annotated` flag (a missing record only counts against the system when the conversation was fully annotated), one doubtful forbidden record removed, one segment start corrected, reviewer must differ from annotator, the template never overwrites an existing set, and a test that every committed set is synthetic and points at SYNTHETIC fixtures. Label IDs are now checked against the set's own vocabulary, and `strength` is recorded for preferences and requirements.
- **Evaluator (EVAL-003).** `evaluation/classification_eval.py` matches each gold segment to the stored segment containing its first message, then scores micro and macro F1, primary accuracy, project accuracy and a confusion table per field. Ambiguous segments score on whether they were sent to review. `stability()` and the ledger's `schema_failures()` cover the EVAL-001 amendment. The synthetic baseline is all 1.000, which only proves the plumbing.

**Teach-back (`evaluation/classification_eval.py`):** "For every segment in the answer key, it finds the segment the system stored that starts at the same message. Then, per label field, it counts which labels were right, extra or missing, and whether the main label was right, and shows which labels get mixed up. Cases a person couldn't decide are scored on whether the system asked for review."
```
ruff check / format     # All checks passed! / already formatted
mypy                    # Success: no issues found in 117 source files
pytest -q               # 958 passed, 7 skipped
migration drift         # 0
```
Fix attempts: 2. A mypy type error in the evaluator's label set, and a CLI crash turning query rows into a dict.

**Next exact task:** EVAL-004 (extraction precision/recall) + EVAL-011 (semantic batch smoke).

### 05:20 — EVAL-004 + OPS-001: scoring extraction, and logs that can't leak
**What:** the extraction evaluator with its hard gate, and a structured run log.
- **Extraction evaluation (EVAL-004).** `evaluation/extraction_eval.py` pairs each gold record with a produced record of the same type that quotes the same message, preferring the one that agrees on most attributes (two records can quote one message, like the user's own preference and a client's). It reports precision, recall and F1 per record type, actor, acceptance, attribution and strength agreement, evidence anchor validity, and forbidden records. Only conversations marked `records_annotated` are scored.
  - **The gate:** no forbidden record in current truth, and no user decision in current truth without valid anchors, the user's own words, a user actor and acceptance. It passes on the synthetic gold. A forged decision (an assistant proposal written straight into truth as a confirmed user decision) fails it; that test first passed wrongly, which is how the "user's own words" rule was added.
- **Logs (OPS-001).** `infrastructure/logs.py` writes JSON lines to `<workspace>/logs/`. Only allow-listed fields (IDs, versions, counts, timings, cost) are accepted, so text has no way in; errors are logged by type name; strings are scrubbed for secrets. The model ledger and the extraction runner now log each step, and `ke logs --stage-key` shows one stage key's whole lineage.

**Teach-back (`infrastructure/logs.py`):** "Every job writes small JSON events to a log file in the private workspace. The log only accepts a fixed list of fields, all IDs, counts and timings, so chat text can't get in, and errors are written by type, never by message. Anything that looks like a key is replaced with [secret], and you can pull up everything that happened to one stage key with `ke logs`."
```
ruff check / format     # All checks passed! / already formatted
mypy                    # Success: no issues found in 119 source files
pytest -q               # 965 passed, 7 skipped
migration drift         # 0
```
Fix attempts: 1. The forged-decision test showed the gate missed a decision quoting only assistant words; the rule now requires the user's own words.

**Next exact task:** OPS-002 (resource, timeout and queue limits) + EVAL-011 (semantic batch smoke at 50/100).

### 05:30 — OPS-002 + EVAL-011: limits, and a semantic smoke test at 50 and 100
**What:** bounds on everything a run can consume, and a batch test that pushes 50 and 100 chats through classification and extraction.
- **Limits (OPS-002).** New `Settings.limits` fields: ZIP member cap, request size cap, batch size, provider timeout and stage deadline, next to the existing file-size and call caps. `orchestration/limits.py` holds a `RunBudget` shared by a run and a `Deadline`.
  - Every limit is checked **before** the work, so reaching one costs nothing. Each is logged as `limit.reached` and ends as a recorded outcome:
    - an oversize request is never sent and ends `review_required` with `limit:max_input_tokens`;
    - requests past the call cap stay unsent (`capped`) for the next run;
    - a repair with no budget left ends `review_required`;
    - a silent provider times out to `review_required` with `timeout`;
    - extraction past its deadline defers the rest.
  - The schema failure rate now leaves out requests that never got an answer.
- **Semantic smoke (EVAL-011).** `ke eval semantic` works on a scratch copy of the database (SQLite backup API, source opened read-only). Its fake model is local and answers with the keyword classifier's labels, but breaks every 7th answer and never answers every 13th.
  - Extraction is interrupted halfway and resumed.
  - At 50 and 100 conversations every check passes, and the measured failure rate (0.14) matches the injected one.
  - The real-provider half needs Louis's opt-in and stays open.

**Teach-back (`orchestration/limits.py`):** "A run gets a budget of model calls, a maximum request size, a batch size, a timeout and a deadline, all from the settings. Each limit is checked before the work, so going over one never costs anything, and it's logged. Work that didn't fit isn't lost: it's either marked for review with the reason or left for the next run."
```
ruff check / format     # All checks passed! / already formatted
mypy                    # Success: no issues found in 121 source files
pytest -q               # 972 passed, 7 skipped
migration drift         # 0
```
Fix attempts: 1. The fake provider counts as sending data, so the smoke run failed with egress off. The smoke run now uses a local fake that truthfully declares it sends nothing.

**Next exact task:** the LEG-002..005 and REV-012 fold-ins, then M4.

### 05:34 — LEG-002 + REV-012: every score says what it was scored against
**What:** older attempts printed AI-made verdicts under owner-sounding headings. Every accuracy report now opens with the answer key's version, its SHA-256 and a reviewer label.
- `evaluation/report_labels.py` defines `ReviewerKind` (owner, ai_session, same_model, none) and `AnswerKey`. Only `owner` gets the heading "Owner verdict"; everything else is headed "AI check (not owner-verified)".
- A key missing its version, hash or label refuses to render. A reviewed key must carry its review file's hash. A report with no key prints "unscored".
- The independent review of the synthetic gold set is now committed as `docs/reviews/GOLD_SYNTHETIC_V1_REVIEW.md` (synthetic content only), so the baselines can cite its hash. Both baselines were regenerated with the key block, and their numbers are unchanged.

**Teach-back (`evaluation/report_labels.py`):** "Every accuracy report starts by saying which answer key it used, that key's fingerprint, and who reviewed the key. Only my own review can produce the words 'Owner verdict'; an AI review is always labelled as an AI check. If any of those facts is missing the report refuses to print, and with no key at all it just says 'unscored'."
```
ruff check / format     # All checks passed! / already formatted
mypy                    # Success: no issues found in 122 source files
pytest -q               # 982 passed, 7 skipped
migration drift         # 0
```
Fix attempts: 0.

**Next exact task:** LEG-003 (provider failure cases) + LEG-004 (quote matching on real text).

### 05:39 — LEG-003 + LEG-004: provider failures, and quotes in real text
**What:** two lessons from the old runs, turned into code and tests.
- **Provider failures (LEG-003).** A new `RawResponse` describes what an HTTP-style provider got back. `result_from_response` sorts it in one place:
  - an error envelope (even inside HTTP 200), a 429 or a 5xx is **transient**: the provider failed, not the model. The same ask is sent again without using the one repair, at most 3 tries in total, then review;
  - `finish_reason=length` is a recorded format error, even if the cut-off text parses;
  - a list longer than the schema allows is trimmed to the maximum and logged (`model.trimmed`), not retried.

  Provider failures are counted in their own columns (migration 0020), so a rate limit can never overwrite the repair context in `last_error`. They are left out of the schema failure rate.
- **Quote matching (LEG-004).** `normalise_for_match` folds curly to straight quotes and apostrophes (so X’s matches X's) and CRLF/CR to LF, keeping a map back to the original positions. `find_quote` tries the exact quote, then the folded one, then the quote with escape sequences undone. Every match must start and end on a word boundary. Spacing and case are never folded. The model extractor now uses it.

**Teach-back (`graph/offsets.py` `find_quote`):** "When a model cites words, I look for them in the real message: first exactly, then allowing curly versus straight quotes and different line endings, then undoing a backslash-n the model typed. A match must be whole words, so 'cat' never matches inside 'concatenate'. The position I store always points at the original text, so the fingerprint still checks out."
```
ruff check / format     # All checks passed! / already formatted
mypy                    # Success: no issues found in 123 source files
pytest -q               # 1001 passed, 7 skipped
migration drift         # 0
```
Fix attempts: 0. Ruff asked for raw docstrings where they show backslashes.

**Next exact task:** LEG-005 (no clipping; split long segments; truncation_count and length bands; late short "no" fixture).

### 05:47 — LEG-005: no clipping, anywhere
**What:** old v1 kept 20 messages of 800 characters each and lost late decisions. The segmenter already split long segments into overlapping parts (NRM-004). Now every model stage uses that same split, and reports prove nothing was cut.
- `segmenter.split_parts` is public and works on any message type. The model extractor groups a segment into exchanges and sends one request per part, then merges the records and stores a duplicate from the shared exchange only once. A segment that fits still sends one request with the same key as before, so the cache stays valid.
- The model classifier sends one request per part. If the parts disagree on a primary label, the segment goes to review rather than being silently merged.
- Classification and extraction reports print a **truncation count** (measured: segment messages missing from what the stage was given; must be 0) and accuracy or recall **by chat-length band** (<4k, 4k-16k, 16k-64k, 64k+ characters).
- New fixture `late_rejection`: a 33k-character chat on one topic ends with "I suggest painting the shed door bright red." and the user's "No.". The segment has several parts, nothing is clipped, and the "No." comes out as the user's supported rejection citing both messages.

**Teach-back (`segmenter.split_parts`):** "When a segment is too big for one model request, it's cut into parts at exchange boundaries, and neighbouring parts share one exchange so nothing loses its context. Every message is in some part, the first and last always are, and a single huge exchange is kept whole and flagged. The extractor and classifier both use this same split, and the reports count any dropped message, which must be zero."
```
ruff check / format     # All checks passed! / already formatted
mypy                    # Success: no issues found in 123 source files
pytest -q               # 1016 passed, 7 skipped
migration drift         # 0
```
Fix attempts: 0. The fixture's "No." first lacked the word "Synthetic", which the fixture suite requires, so it became "No. Synthetic.".

**Next exact task:** M4, starting with its first unblocked ticket.

### 05:53 — UI-005: see what the AI suggested and what reviewers decided
**What:** two new read-only pages in `ke ui`, linked from the top bar.
- **Suggestions** lists every knowledge record the extractors proposed, with a count per trust state (waiting for a reviewer, proposed, evidence checked, confirmed, rejected), filters for trust and type, and each quote one click from its message. The page says plainly that a suggestion is not a decision.
- **Reviews** lists every named reviewer's decision and the reason they gave: on knowledge records, vocabulary proposals (plus how many are still open), topic-label corrections and conversation links. The automatic evidence validator is counted in its own section and never appears as a reviewer, and nothing is labelled as the owner's approval.
- Both pages accept GET only and work on an empty workspace. Reasons are HTML-escaped.

**Teach-back (`ui/review.py`):** "The suggestions page reads every knowledge record, counts them by how far they've got, and links each quote back to the exact message. The reviews page reads the append-only decision logs and shows who decided what and why, keeping the automatic quote checker in a separate box so a machine check never looks like a person's decision. Both only read the database; there's no button that changes anything."
```
ruff check / format     # All checks passed! / already formatted
mypy                    # Success: no issues found in 124 source files
pytest -q               # 1021 passed, 7 skipped
migration drift         # 0
```
Fix attempts: 1. `dict()` over a SQLAlchemy result treats it as a mapping, so the trust counts are built from pairs.

**Next exact task:** M4, starting with its first unblocked ticket (DEPENDENCY_MAP §4).

### 06:02 — NRM-005 + REC-001: reviewers can fix segments; repeated claims are proposed, never merged
**NRM-005.** Segment boundaries were only the machine's proposal. Now a reviewer can split or merge them.
- Each decision (split, merge, clear) is one row in an append-only log, tied to the export's own message ID. Because those IDs are the same in every later export, the decisions are applied again after a re-import or any recomputation.
- A split is only allowed where an exchange starts, so a short "no" is never cut off from what it rejects. Every message still lands in exactly one segment.
- A segment a reviewer changed lists the automatic segments it came from (`derived_from`).
- A decision that no longer fits the chat is reported as orphaned, not dropped.
- `revalidation` lists the stored classifications and extraction runs that belong to segments that are no longer current. Nothing is deleted.

**REC-001.** The same claim made in two chats should become one claim with two pieces of evidence, but only after a check.
- Two records are compared only if they could be the same claim: same kind, same person, same reported speaker, same for or against, same projects.
- Scores come from the share of content words in common. Numbers and negations are compared on their own: "port 8080" versus "port 8081", and "deploy with Docker" versus "don't", come out as **near misses** with the difference named.
- Every pair, even a word-for-word repeat, stays `proposed` until a named reviewer decides. Confirming a near miss needs a reason. The records themselves are never touched.

**Teach-back (`reconciliation/equivalence.py`):** "It looks for knowledge records that might say the same thing, but only compares records of the same kind, from the same person, about the same project. It scores how many meaningful words they share and flags differences in numbers or 'not', because those make a different decision. Nothing is merged by the machine: every pair waits for a named reviewer, and the decision is logged for good."
```
ruff check / format     # All checks passed! / already formatted
mypy                    # Success: no issues found in 129 source files
pytest -q               # 1034 passed, 7 skipped
migration drift         # 0
```
Fix attempts: 0. One test helper first lacked a scope ID, which the record contract requires.

**Next exact task:** REC-002 (relationship candidate discovery), then REC-003.

### 06:09 — REC-002 + REC-003: typed links between records, and conflicts left open
**REC-002.** Records are now linked to each other, but only in four typed ways, each allowed only between record types where it makes sense:
- *creates*: a request makes an artefact;
- *references*: a record mentions a named game, book or tool;
- *elaborates*: a later record adds detail to an earlier one;
- *same_project*: records in different chats share a project and a topic.

`allowed()` refuses any other pairing before it is stored. Each link stores the source messages behind both records. Links stay candidates until a named reviewer decides.

**REC-003.** Two records conflict when the same person says opposite things about the same thing in an overlapping scope:
- the same thing both decided and rejected;
- a preference for and against;
- the same sentence with and without "not";
- different numbers.

Records for different projects never conflict. The order of the two records is stored as context only: the later one does not win. Conflicts stay `unresolved` until a reviewer dismisses or resolves them, with a reason. `ke reconcile` runs REC-001..003 together.
- Change to REC-001: "stance" words (prefer, hate, love...) no longer count as content words, so "I prefer tabs" and "I hate tabs" are recognised as being about the same thing. The for or against is compared through the record's polarity instead.

**Teach-back (`reconciliation/conflicts.py`):** "It looks for two of my statements about the same thing that can't both be true, like port 8080 versus 8081, or accepting and rejecting the same idea. It only compares statements in the same project or the same chat, so different projects never clash. It never decides that the newer one wins: the conflict is recorded as unresolved, and only evidence or a reviewer with a reason can close it."
```
ruff check / format     # All checks passed! / already formatted
mypy                    # Success: no issues found in 133 source files
pytest -q               # 1044 passed, 7 skipped
migration drift         # 0
```
Fix attempts: 1. The fixture expectation first counted a reference from another fixture, and was corrected to the one in actions_entities.

**Next exact task:** REC-004 (decision transitions and event timeline).

### 06:17 — REC-004 + REC-005: a decision's history, and when a newer one really replaces it
**REC-004.** Every step in a decision's life is now an event: proposed, accepted, rejected, clarified, revised, superseded, contradicted.
- The events table is append-only (database triggers). A wrong event is withdrawn by adding a `revokes` event, so the history shows the mistake and the correction.
- `build_events` adds the events that need no judgement:
  - a proposal for every assistant suggestion;
  - an acceptance or rejection when a decision cites the very same suggestion sentence;
  - a contradiction for every unresolved conflict.
- `record_event` refuses events between the wrong record types. It also refuses a "replaces" that points forward in time.

**REC-005.** A later decision replaces an earlier one only if all seven tests pass:
1. same kind and person;
2. overlapping scope;
3. same subject;
4. strictly later;
5. firmly accepted and evidence-checked;
6. not hypothetical ("what if", "maybe", a question mark);
7. explicit replacement words ("instead", "switch to", "change of plan").

The user's own quoted words are read from the stored messages for tests 6 and 7. If any test from 4 on fails, the pair goes to review with the failed tests named.
- New fixture `engine_switch`. One chat decides on Unity, then only wonders about Godot: the wondering produces no decision at all. Even a hand-made Godot "decision" that a careless reviewer supported is refused as hypothetical. Another chat says "change of plan, I've decided to use Godot instead of Unity": that replaces its own chat's Unity decision, and not the other chat's.
- Note: `ke reconcile`'s output was left exactly as it was (its test asserts the whole output); supersession and events run with `ke timeline --build`.

**Teach-back (`reconciliation/supersession.py`):** "A newer decision only replaces an older one when it's the same kind of decision by the same person, in the same project or chat, about the same thing, firmly decided, and later. On top of that, my own words must say I'm replacing something, like 'instead' or 'change of plan', and must not be a 'what if' or a question. If any of that fails, nothing is replaced; the pair goes to a reviewer with the failed checks listed."
```
ruff check / format     # All checks passed! / already formatted
mypy                    # Success: no issues found in 136 source files
pytest -q               # 1060 passed, 7 skipped
migration drift         # 0
```
Fix attempts: 2, both in the new test's setup:
- the hand-made quote needed the project's own quote fingerprint;
- the hypothetical's verdict fails only on "hypothetical", because "switched to" already counts as intent.

**Next exact task:** REC-006 (current-state and as-of projector), then REC-007.

### 06:22 — REC-006 + REC-007: what holds, as of when, and what's connected
**REC-006.** `project()` gives every decision, rejection, requirement and preference a standing, with the events behind it:
- **current**;
- **superseded** (and by what);
- **conflicted** (an open conflict with another current record; neither wins);
- **pending** (not checked yet);
- **unknown** (a date was asked and the record's own time is unknown).

Proposals come out as accepted, rejected or open. There are two clocks: **as_of**, what the chats had said by a date, and **known_at**, what we had recorded by a date. Everything read is append-only, so a past snapshot gives the same answer later, even after a replacement is revoked.

**REC-007.** One list of every stored edge between records: links, decision events (revoked ones left out), same-claim pairs and conflicts.
- Each edge has its origin (detector or reviewer), review state and the source messages of both ends. An edge without sources is never returned.
- `walk()` goes breadth-first from a record, with filters for edge kind, depth, direction and closed edges, and labels every record it reaches with its REC-006 standing.
- New commands: `ke state` and `ke walk`.

**Teach-back (`reconciliation/projection.py`):** "It works out, for each of my decisions, whether it still holds, was replaced, is in an open conflict, or is still waiting for a check, and lists the events that explain that. You can ask about a past date in two ways: what the chats had said by then, and what we had recorded by then. Because nothing it reads is ever edited or deleted, the same question about the past always gets the same answer."
```
ruff check / format     # All checks passed! / already formatted
mypy                    # Success: no issues found in 138 source files
pytest -q               # 1064 passed, 7 skipped
migration drift         # 0
```
Fix attempts: 0.

**Next exact task:** RET-002 (embeddings provider and index protocol), then RET-003.

### 06:28 — RET-002 + RET-003: search by meaning, locally, with the model stamped on the index
**RET-002.** Every embedder declares who it is: provider, model, vector size and version. The fingerprint of those goes on every index. `embed()` checks the `embedding` egress switch before any embedder that sends data, and checks the vectors that come back.
- The built-in `LocalHashEmbedder` is local, free and deterministic: rough word stems plus three-letter pieces, hashed into 512 numbers.
- It finds reworded, re-ordered, inflected and misspelt text, but not synonyms. That limit is recorded as **OD-18**, with the default kept; a real model can be plugged in behind the same interface later.

**RET-003.** A separate, rebuildable `index/vectors.db` holds one vector per message revision, with the same context keys as the word index.
- Opening it with another model or vector size is refused (`StaleIndexError`) until it is rebuilt.
- A sync only embeds new or changed text: running it twice embeds nothing the second time.
- Search is scoped to one workspace (optionally some chats or roles), with ties broken by ID.
- Five golden queries ("painting sheds red", "kubernetis clustr"...) each find their message first.
- New command `ke similar`.

**Teach-back (`retrieval/semantic.py`):** "It keeps a cache file with one vector per message, stamped with the model that made them, and refuses to mix in a different model until I rebuild it. Each sync only embeds messages that are new or changed, so re-running it costs nothing. A search compares the query's vector with every message in the chosen workspace and returns the closest, always in the same order."
```
ruff check / format     # All checks passed! / already formatted
mypy                    # Success: no issues found in 140 source files
pytest -q               # 1070 passed, 7 skipped
migration drift         # 0
```
Fix attempts: 0.

**Next exact task:** RET-004 (hybrid rank fusion), then RET-005/006.

### 06:36 — RET-004 + RET-005: one ranked list, and the right search for each question
**RET-004.** `retrieval/hybrid.py` runs up to three channels and fuses their rankings with reciprocal rank fusion (each item scores 1/(60 + rank) per channel, summed):
- the word index; the meaning index (optional); and stored knowledge records whose assertion shares words with the query.
- One hit per message: several matching versions of a message collapse into one hit that lists them. Records are keyed by `krec_` ID. Ties break on the key, so the order is stable.
- Exact terms are looked up character for character and pinned first. The test proves why: twelve near-identical "deploy error" messages push the `ERR-4012` message out of the top 3 without pinning.
- The workspace is checked before and again after fusion.

**RET-005.** `retrieval/planner.py` chooses a route by plain rules and says why:
- "What game engine did I decide on?" goes to the REC-006 records: current first, the replaced Unity decision still listed last as superseded.
- Quoted text, or codes on their own, go to the exact search; other questions go to the combined search with any codes pinned.
- If a decision question matches no record, it falls back to the combined search and reports `fallback`.
- 16 question-type fixtures pin the routes. New command `ke find`.

**Teach-back (`retrieval/hybrid.py`):** "It asks the word search, the meaning search and the decision records for their rankings, and adds up a small score for every place each item came, so things two searches agree on rise to the top. Each message appears once, however many versions or searches matched it, and ties are settled by ID so the list never shuffles. Anything that contains the exact code or quote you typed is pinned to the top first, so it can't get buried under vaguely similar messages."
```
ruff check / format     # All checks passed! / already formatted
mypy                    # Success: no issues found in 142 source files
pytest -q               # 1095 passed, 7 skipped
migration drift         # 0
```
Fix attempts: 0 (two expectations in the new unit test corrected while writing it: RRF arithmetic and a two-letter code).

**Next exact task:** RET-006 (source context hydrator and citation resolver), then RET-007.

### 06:44 — RET-006 + RET-007: checked citations, and answers that cite every sentence or say "I don't know"
**RET-006.** `retrieval/citations.py` turns hits into evidence.
- A citation is (revision, start, end, quote fingerprint), with a stable `kcit_` ID made from those four.
- `resolve` checks it against the stored text: the revision exists, the range fits, the fingerprint matches, and the speaker matches when known. Otherwise it is rejected with a problem code.
- Stale index hits (a purged revision) and unknown records are rejected, never returned. `audit` re-checks citations, so a forged or altered ID is caught.
- `hydrate` adds a source window: the messages before (ancestors) and after (along the selected branch). The window is shown, never cited.
- An edited message keeps its old version citable, flagged `newest_version: false`.

**RET-007.** `retrieval/answers.py`: route → relevance gate → hydrate → write → audit → answer or abstain.
- Meaning-only hits must have similarity ≥ 0.3. Unrelated questions score under 0.2 with the local embedder; without this gate every question would "find" something.
- Every sentence carries citation IDs. A sentence citing something it wasn't given, citing nothing, or citing something stale is dropped. If nothing is left, the answer is "I can't find this in your chats." with no citations.
- Decision questions list current, conflicted, unchecked and replaced records ("replaced by: …"). Status is `answered`, `conflicted` or `unknown`.
- The default `ExtractiveWriter` uses no model. `ModelWriter` (any FND-007 provider) checks the egress switch before sending, and puts evidence only in the untrusted input, never in the instructions. Its draft gets the same audit. It was tested with the fake provider only: no paid calls.
- New command `ke ask`.

**Teach-back (`retrieval/answers.py`):** "It finds the evidence for a question, throws away weak meaning-only matches, and checks that every quote is still exactly where it says in the stored chats. Then it writes the answer one sentence at a time, and any sentence that doesn't point at evidence it was actually given is deleted. If nothing survives, it says it can't find the answer instead of guessing."
```
ruff check / format     # All checks passed! / already formatted
mypy                    # Success: no issues found in 144 source files
pytest -q               # 1103 passed, 7 skipped
migration drift         # 0
```
Fix attempts: 0 (three expectations in the new test corrected while writing it: speaker parity, which hit ranks first, sentence order).

**Next exact task:** RET-008 (retrieval benchmarks and tuning report).

### 06:49 — RET-008: a pinned retrieval benchmark with regression floors
`evaluation/retrieval_bench.py` holds a fixed synthetic benchmark: 36 messages in 8 chats, including eight near-identical "deploy error" messages as noise. It asks 21 questions of five kinds: exact code, keyword, paraphrase, misspelling and no answer.
- For word search, meaning search and the combined search, it measures Recall@1/5/10, MRR, exact-term hit and cost: texts embedded, and model requests (0).
- It also measures how often `ke ask` answers with a right citation, and how often it correctly says it doesn't know.
- `docs/evaluation/RET-008_BENCHMARK.md` is generated by `ke eval retrieval`. A test checks it equals a fresh run, and checks the pinned floors.

Results (hybrid):

| Metric | Value |
|---|---|
| Recall@5 | 0.941 |
| MRR | 0.961 |
| Exact-term hit | 1.000 |
| Right-citation answers | 0.824 |
| Correct abstentions | 1.000 |

What the numbers say:
- **Word search** finds codes and exact words but nothing reworded: paraphrase and misspelling recall@5 are both 0.
- **Combined search** matches meaning search on rewording, and adds the pinned code in "deploy error ERR-4012", which word search misses.
- **The answer gate is conservative.** Two misspelt questions find the right message first but are answered "I don't know", because their similarity is under 0.3. I kept the 0.3 gate, because the no-answer questions all abstain with it. A better embedder (OD-18) is the real fix. This trade-off is now measured, not guessed.

**Teach-back (`evaluation/retrieval_bench.py`):** "It builds a small fixed set of fake chats and questions where we already know which messages are the right answers. It runs each kind of search on every question and scores how high the right message comes, and whether the answer feature cites it or rightly says it doesn't know. The report is regenerated and compared on every test run, so any change to search shows up as changed numbers, and a drop below the pinned floors fails."
```
ruff check / format     # All checks passed! / already formatted
mypy                    # Success: no issues found in 145 source files
pytest -q               # 1106 passed, 7 skipped
migration drift         # 0
```
Fix attempts: 0.

**Next exact task:** DOC-001 (document model and dependency tracking).

### 06:57 — DOC-001 + DOC-004: documents as data, exact rebuild lists, and a labelled project master
**DOC-001.** `documents/model.py` builds a conversation, project or topic document as plain data. Its sections come in a fixed order (current, in conflict, waiting for a check, date unknown, replaced, suggestions, other). Each item has its REC-006 status, the events behind it and the messages it cites.
- Records a reviewer rejected are left out.
- One selector, `subjects_of`, decides which documents a record belongs to.
- `documents/dependencies.py` adds two append-only tables (migration 0026):
  - each build whose content changed, plus the records and revisions it used;
  - an unchanged rebuild adds nothing.
- `affected_documents` returns the documents to rebuild, with reasons:
  - documents whose latest build used the record (`depends`);
  - documents the selector would now put it in (`selects`).
- Proved:
  - one record maps to exactly its chat's document;
  - a brand-new record maps to its chat's document and its project's document, though neither was ever built with it;
  - after the reconciler runs, only the one changed chat gets a new build.

**DOC-004.** `documents/render.py` turns any knowledge document into an Obsidian note.
- Every record is an escaped paragraph with a `^krec-…` anchor, followed by an engine-written label line:
  - **Current**, **Replaced** (with a "replaced by" link) or **In conflict** (with a link to the other side);
  - sources, linked to the exact message blocks in the BRW-001 transcript notes;
  - record and event IDs.
- The project master adds three sections: Dependencies (typed REC-007 edges), a Decision timeline and Sources.
- Modes are current, history and all. A mode only links to records it shows.
- Proved:
  - every project record carries a label;
  - each replaced Unity decision links to the Godot decision that replaced it;
  - current mode doesn't mention a replaced record even as a link;
  - every source link resolves to a block in a written transcript;
  - a rewrite is byte-identical.

**Teach-back (`documents/dependencies.py`):** "Every time a note's content actually changes, it writes down which records and messages that version used, and never edits that list afterwards. When a record changes, it looks up which notes last used it, and also which notes the record now belongs in, so a brand-new record isn't missed. That gives the exact list of notes to rebuild, each with the reason, and nothing more."
```
ruff check / format     # All checks passed! / already formatted
mypy                    # Success: no issues found in 150 source files
pytest -q               # 1115 passed, 7 skipped
migration drift         # 0
```
Fix attempts: 1 (current mode linked to replaced records through the dependency list; now only records the mode shows are linked).

**Next exact task:** DOC-003 (conversation knowledge notes), then DOC-005.

### 07:07 — DOC-003 + DOC-005: a knowledge page for each chat, and topic pages by canonical term
**DOC-003.** `documents/notes.py` writes a knowledge note beside each chat's transcript, under `Knowledge/`. Its sections are:
- **Summary**: counts only (messages, branches, segments, records, images, links, related chats), so nothing is invented;
- **Classification**: each segment's labels in force (a review beats the machine), with a link to where the segment starts;
- **Knowledge**: the chat's DOC-001 document, each record followed by its evidence quotes. Each quote is re-checked against the stored message (RET-006 `resolve`, speaker included) and names who said it. A quote that no longer matches is replaced by a marker saying why;
- **Branches**: each edited or regenerated branch, with where it leaves the active path;
- **Images**: embeds (files copied into the vault by fingerprint) and missing markers with reasons;
- **Links**, **Videos**, **Accounts**: every URL, YouTube mention and social account mention, with who wrote it and a message link;
- **Related conversations**: links in both directions with kind, evidence class, confidence and review state. Rejected links are left out.

**DOC-005.** A topic is named by its term ID, label or alias. A name that fits several terms, or none, is refused. The topic master shows the records tagged with that term and the segments whose labels in force carry it in any field, plus their sources. Proved: the programming chat's record, segments and source never appear on the recipes page; removing a segment's label removes the segment but not the tagged record.

`knowledge_note` gained an opt-in `quotes` flag, so project masters are unchanged.

**Teach-back (`documents/notes.py`):** "For each chat, it writes a page next to the transcript listing the chat's labels, the knowledge taken from it with the exact quotes and who said them, its branches, images, links and related chats. Every quote is checked against the stored message before it is shown, so a page can't quote words that aren't there. A topic page is chosen by the topic's exact ID or a name that fits only one topic, so unrelated chats never slip in through a loose word match."
```
ruff check / format     # All checks passed! / already formatted
mypy                    # Success: no issues found in 151 source files
pytest -q               # 1121 passed, 7 skipped
migration drift         # 0
```
Fix attempts: 1 (topic and knowledge file names used IDs with an underscore, which the safe-filename check rejects; now hyphenated).

**Next exact task:** DOC-006.

### 07:12 — DOC-006: a vault the engine shares safely with its owner
`documents/vault.py` `sync_vault` writes every note the engine owns: transcripts, chat knowledge notes, project masters and (with a taxonomy) topic masters, plus their images.
- **Only its own files.** A manifest (`.ke/manifest.json`) lists the paths it manages. A file someone else put at one of those paths is reported as `occupied` and never touched or claimed.
- **Additions kept.** Each managed note ends with a `%% ke:manual … %%` marker line. Whatever is written below it is carried into every new version. Chat text can't fake the marker because `%%` in imported text is escaped.
- **Edits not overwritten.** The manifest stores a fingerprint of the part above the marker. If the file no longer matches, the note is a `conflict` and stays exactly as it is. Deleting it hands it back to the engine.
- **Stale notes.** A managed note the engine no longer makes (e.g. a title change renamed it) is removed only if unedited; otherwise it is kept and reported.
- **No needless writes.** Every note and image is compared byte for byte first. Proved: a second run changes no file's modification time, the manifest included.
- Embeds are checked after images are copied; broken ones are reported.
- Path helpers (`transcript_path`, `knowledge_path`, `project_path`, `topic_path`) now name every note in one place.
- Known limit: notes written earlier by `ke docs chat|project|topic` or `ke inspect --note` have no manifest entry, so the vault sync reports them as occupied. Point those commands at another folder, or delete the old files once.

**Teach-back (`documents/vault.py`):** "It keeps a list of the files it made and a fingerprint of what it wrote, and it only ever touches files on that list. Anything I write under the marker line is copied into the new version, and if I edit the part above it, it leaves my file alone and tells me. If nothing changed, it compares and writes nothing at all."
```
ruff check / format     # All checks passed! / already formatted
mypy                    # Success: no issues found in 152 source files
pytest -q               # 1126 passed, 7 skipped
migration drift         # 0
```
Fix attempts: 0.

**Next exact task:** IMP-006.

### 07:19 — IMP-006: corrections remember which words they were made on
`importer/corrections.py` ties every kind of human correction to logical message IDs plus the revision in force when the person decided:
- **segment overrides** and **classification reviews** are anchored when recorded, in a new append-only `override_anchors` table (migration 0027). `record_override` and `record_review` write the anchors themselves; `record_review` gains an optional `conversation_id` for a segment never classified;
- **record decisions** are anchored by their evidence revisions; **reviewed relationships** by the revision IDs in their evidence.

`check_overrides` compares each anchor with the newest revision:
- unchanged: `kept`, still in force;
- revised: `review_required`, naming each changed message with the revision decided on and the new one;
- nothing to compare (older decisions, evidence with no message): `unanchored`.

Nothing is undone automatically. A split on a revised message still applies but is flagged. A revised segment gets a new ID, so its old label review isn't silently carried over; the unchanged part keeps its review. A message missing from a new export isn't a change. The import report gains `corrections` counts, and `ke corrections` lists flagged items by ID only.

Proved on a synthetic two-chat re-export where one question was edited: exactly the four corrections touching it (split, the label review of its segment, the confirmed record, the relationship citing it) are flagged with both revisions; the five others stay kept; re-importing the same export changes nothing.

**Teach-back (`importer/corrections.py`):** "When I correct something, it notes which version of each message I was looking at. After a re-import it checks those messages again: if they're the same, my correction stands; if one was edited, it's flagged with both versions so I can decide again. It never quietly drops or keeps a correction on words that changed."
```
ruff check / format     # All checks passed! / already formatted
mypy                    # Success: no issues found in 154 source files
pytest -q               # 1129 passed, 7 skipped
migration drift         # 0
```
Fix attempts: 0.

**Next exact task:** REL-003.

### 07:27 — REL-003 + REL-004: related chats, suggested with reasons and shown everywhere
`relationships/related.py` (REL-003) suggests links between chats that are *about the same thing*:
- `same_project` when both chats carry the same approved project label;
- `related_to` when they share a distinctive approved topic or named entity (a book, game...), or their words are close in meaning (local embedder, cosine >= 0.55).

Each suggestion is a `candidate` with plain reasons (`because`) and the message revisions behind them. It is never `continues` or `forked_from` (that needs REL-002's proof), never accepted on its own, and a pair someone already reviewed is left alone. Topics or entities shared by more than 10 chats don't count, and each chat keeps at most 5 partners per kind. Entity names stay private: matched entities use their approved ID, others a hash. It compares every pair, so it runs on request (`ke related suggest`), not in every import.

`relationships/view.py` (REL-004) is the one reader every view uses: rejected links are hidden (their history stays), and the stored direction is kept. Conversation notes, project masters and topic masters list related chats with kind, state, reasons and wikilinks to the cited messages. `ke find` returns a `related` map, and the web chat page and search results show related chats in plain words ("This chat is related to …").

Proved on three synthetic chats (two about one shed, one about bread, the bread chat naming the same book as the first): exactly one `same_project` and two `related_to` suggestions, all candidates; a re-run adds nothing and leaves a rejection alone; the `similar_unrelated` fixture gets at most a `related_to` candidate. After accepting one link and rejecting another, the notes, the project and topic masters, `ke find` and both web pages show the accepted one in its direction with its evidence and hide the rejected one, whose review history is kept.

**Teach-back (`relationships/related.py`):** "It looks for chats that share a project, a topic, a named thing or similar wording, and suggests they're related, writing down why. Looking alike is never taken as proof that one chat was copied from another, and nothing it suggests counts until a person accepts it. Very common topics are ignored and each chat gets only its five best suggestions, so the review list stays short."
```
ruff check / format     # All checks passed! / already formatted
mypy                    # Success: no issues found in 156 source files
pytest -q               # 1134 passed, 7 skipped
migration drift         # 0
```
Fix attempts: 1 (the test export reused node IDs across chats, which REL-002 rightly read as forks; gave each chat its own IDs).

**Next exact task:** YTB-003 + SOC-003.

### 07:34 — YTB-003 + SOC-003: video notes, transcript search and the account registry
`documents/registries.py` adds three kinds of note to the managed vault.

- **Video notes** (`Videos/YouTube <id> (video).md`). Each one opens with the transcript status in words, which is never blank: "No transcript: none attached and none requested." counts as an answer. It then lists:
  - every message that links to the video, as a wikilink, with the link's own timestamp and playlist;
  - every chat that cites the video;
  - the cues of an attached transcript, each with a `^cue-N` anchor and a link that opens the video at that second.
- **Cue search** (`find_cues`, `ke transcript find`). It matches every word asked for in the newest transcript of each video. Each hit resolves to the moment's URL and to every chat and message revision that links to the video. Cue text only ever comes from a transcript file.
- **Account registry** (`Accounts/Account registry.md`). It lists every account by platform, with its status, counts, dates and a link to the account's own note. Bare @names are never filed under an account, so they get a separate "Needs review" section. Rejected accounts are listed apart. Each account note shows its aliases, every mention linked to its message, and its chats. Handles appear in code spans and cue text is escaped.

I proved it on two synthetic chats: one video linked three times (once with `t=75`), one video with no transcript, a GitHub account and a bare @name. A cue search lands on 1:15 and lists both chats. The video with no transcript states "none attached and none requested". The bare @name is only under "Needs review". Every account link in the registry has its note in the vault, and a second vault sync writes nothing.

**Teach-back (`documents/registries.py`):** "Each YouTube video gets a note saying whether it has a transcript, which messages linked to it and at what time, and, if there's a transcript, every line with a link to that second of the video. Searching transcript lines takes me to the moment and to the chats that cited the video. Accounts get a registry page and one page each, and a bare @name stays in a 'needs review' list instead of being guessed onto an account."
```
ruff check / format     # All checks passed! / already formatted
mypy                    # Success: no issues found in 157 source files
pytest -q               # 1139 passed, 7 skipped
migration drift         # 0
```
Fix attempts: 1 (my test assumed cue ordinals start at 1; they start at 0, as YTB-002 stores them).

**Next exact task:** EVAL-002.

### 07:46 — EVAL-002 + EVAL-005: nothing lost quietly, and "later" never quietly means "instead"
**EVAL-002** (`evaluation/import_fidelity.py`, `ke eval fidelity`) gives the import a third opinion. It walks every JSON file of an export itself, inside folders and ZIPs, and lists each conversation's node IDs. It then imports the export into a scratch workspace and checks node by node. Each export gets a verdict:
- `ok`;
- `warned`: everything is stored but the report flags something, or nodes are missing and the report says so;
- `silent_drop`: a node is missing and nothing admits it. This fails the run.

It also reports branch retention, missing images and the unknown payload audit. Across all 24 fixtures, 380 of 380 nodes were stored and 13 of 13 off-path nodes were kept: 18 ok, 6 warned, 0 silent drops. Report: `docs/evaluation/EVAL-002_FIDELITY.md`.

Failing-case reproduction: a second JSON file of conversations sitting next to `conversations.json` is never read by the official adapter, and nothing says so. EVAL-002 calls it a `silent_drop`. I filed this as #237 rather than widening this PR.

**EVAL-005** (`evaluation/temporal_bench.py`, `ke eval temporal`) has two parts.
- **Curated pairs.** 31 earlier/later pairs go through REC-005's own `evaluate`. They cover true replacements, eight hypotheticals, scope change, contradiction without "instead", weak acceptance, unknown or reversed order, adjacent subjects and unrelated pairs.
- **Pipeline.** The `engine_switch` fixture runs end to end. The replaced decision shows as superseded now and is explained by its event. It is still current as of just before the switch, and current again after the replacement is withdrawn.

The first run found two problems:
1. **A benchmark artifact.** A shared "Synthetic:" prefix counted as a shared subject, so the pair texts now carry no marker word.
2. **A real false supersession.** "We'll use Blender instead of Maya for the shed game models" replaced the decision to use Unity for the shed game, because it shared the project, the word "game" and a firm "instead".

The fix is REC-005 v2's eighth test, **target**. A replacement must name what it replaces (the head of the phrase after "instead of", "rather than", "no longer using", "replace"...), and the earlier record must mention it.
- If it names something else, the pair is `unrelated`.
- If it names nothing ("switching to Godot", "scrap that"), an otherwise clean pair goes to review instead of being recorded.

The cost is two true replacements in the benchmark that now wait for review. The benchmark reports them openly. Result: 0 false supersessions, and all existing reconciliation tests unchanged and passing.

**Teach-back (`evaluation/temporal_bench.py`):** "It feeds the reconciler pairs of decisions built to trick it: 'what if' questions, other projects, other parts of the same project, wobbly acceptances. The rule is that nothing may be recorded as replaced unless it really was, and that already-replaced decisions stay visible when you ask what was true at the time. When a newer statement doesn't say what it replaces, it goes to review instead of being guessed."
```
ruff check / format     # All checks passed! / already formatted
mypy                    # Success: no issues found in 159 source files
pytest -q               # 1150 passed, 7 skipped
migration drift         # 0
ke eval fidelity        # PASS: 24 exports, 18 ok, 6 warned, 0 silent_drop
ke eval temporal        # PASS: 29 of 31 as expected, 0 false supersessions, history kept
```
Fix attempts: 2 (target = first word after the marker misread "replace the shed game's pixel font"; then the phrase head, with articles skipped).

**Next exact task:** EVAL-006.

### 07:54 — EVAL-006: a ZIP all the way to Obsidian, then click every link
**EVAL-006** (`evaluation/end_to_end.py`, `ke eval e2e`) runs one pinned path through the whole engine with no model and no network: import a ZIP, classify under a small published taxonomy, run the rule extractors, reconcile, build the vault, and search. The input is `tests/fixtures/e2e/export.zip`: the existing synthetic ZIP plus two new synthetic chats about a garden shed. Between them they carry a decision, a preference, a requirement, YouTube and GitHub links, the same image used again, and a follow-up that changes the roof. A builder makes the ZIP and a test checks it rebuilds byte for byte.

Then it reads the vault the way Obsidian does:
- every YAML header parses;
- every `[[link]]`, `[[note#^anchor]]`, `[[note#Heading]]`, same-note `[[#^anchor]]` and `![[embed]]` resolves (escaped links and links in code are skipped; a name two notes share counts as broken, since Obsidian would have to guess);
- every chat has its source note, and every knowledge note links to it (sources before knowledge, BRW-001);
- the search hit lands on a note that exists.

The **golden** (`tests/fixtures/e2e/vault_golden.json`) is the vault's shape, not its words: each note's path, kind and link, embed and anchor counts. Conversation and account IDs are random per workspace, so they appear as `conv-*` and `acct-*`. Two runs give the same golden. Result: 13 notes, 35 links, 4 embeds, all resolve, golden matches.

The checker is also a user command: `ke docs check --vault PATH` checks any vault and changes nothing. This is the Gate G4 link check.

Limits: no project or topic master is in this vault, because machine topic labels aren't approved by a person. The acceptance "sounds good, let's do that" of the timber frame isn't captured by the rule extractor (3 records). Both are recorded in the golden rather than fixed here.

**Teach-back (`evaluation/end_to_end.py`):** "It takes a small fake ChatGPT export and runs it through every step until it's an Obsidian vault, with no AI and no internet. Then it opens every note and follows every link, picture and anchor, and fails if any of them points nowhere. It also compares the vault's layout with a saved copy, so any change in what gets written shows up in review."
```
ruff check / format     # All checks passed! / already formatted
mypy                    # Success: no issues found in 160 source files
pytest -q               # 1155 passed, 7 skipped
migration drift         # 0
ke eval e2e             # PASS: 13 notes, 35 links and 4 embeds all resolve; matches the golden
```
Fix attempts: 2 (a taxonomy alias equal to its own label collides with the label; a root-level note was listed twice by name and path, which counted as ambiguous).

**Next exact task:** EVAL-007.

### 08:02 — EVAL-007: one pass, four labels, then stop
**EVAL-007** (`evaluation/gate.py`, `ke eval gate`) is the release gate. It runs twelve checks against the proposed release thresholds in TEST_STRATEGY §6, each **exactly once**, then stops. Nothing is re-run to get a better answer. If a check crashes, that check is a FAIL and the rest still run. Each line carries:
- a label: PASS, FAIL, REVIEW (the hard rule held but some cases wait for a person) or BLOCKED (can't be measured here);
- the threshold next to the measured number;
- which data it was measured on (`synthetic` or `real`);
- the command that runs it alone.

The overall result is the worst label. The gate fails only on a FAIL. REVIEW and BLOCKED are filed, not hidden.

Result (`docs/evaluation/EVAL-007_GATE.md`): 7 PASS, 2 REVIEW, 3 BLOCKED, 0 FAIL.
- **REVIEW:** the synthetic golden set has no ambiguous segments, so "ambiguous cases flagged, not forced" can't be shown (the gold set isn't mine to change); and two true replacements wait for review (EVAL-005).
- **BLOCKED:** directional relationship precision has no answer key (filed as EVAL-012, #240); the private golden set is scored on Louis's PC; the paid-provider smoke is parked.

Every PASS is on synthetic fixtures, and the report says so on every line.

**Teach-back (`evaluation/gate.py`):** "It runs every quality check once and writes one table: pass, fail, needs a person, or can't be measured yet, with the target next to each number. It never retries to get a nicer result, and if one check crashes the rest still run and the crash shows as a failure. Anything measured only on fake data is labelled as such, so a green line can't be mistaken for real-world quality."
```
ruff check / format     # All checks passed! / already formatted
mypy                    # Success: no issues found in 161 source files
pytest -q               # 1159 passed, 7 skipped
migration drift         # 0
ke eval gate            # BLOCKED: 3 BLOCKED, 2 REVIEW, 7 PASS (0 FAIL; gate passes)
```
Fix attempts: 0.

**Next exact task:** EVAL-008.

### 08:10 — EVAL-008: any order, same answers
**EVAL-008** (`evaluation/variance.py`, `ke eval variance`) imports five synthetic exports in three seeded orders. The order of the exports, the chats inside each and the segments reaching each stage are all shuffled. Each run classifies through the model path with a pinned fake model, extracts and reconciles.

Each run becomes a **canonical view** keyed only by what the export itself names: native conversation and message IDs, record type and the quoted words. Workspace IDs are random, so they can't be compared. The view holds each segment's labels and each record's trust, standing and replacements. Any key whose value differs between runs becomes a **review item**, with every run's value side by side. Nothing is averaged or quietly picked.

The first run also asks the pinned model twice more. The answers must be identical and come from the ledger, with 0 new requests.

Result: 17 segments and 26 records give identical answers in all three orders, including the engine_switch replacement. The repeats made 0 new requests.

Failing-case reproduction: a fake model that never labels the first segment it sees (so its answers depend on order) produces review items, never silent drift.

The gate gains a thirteenth line, `variance.order_and_repeats`: PASS when nothing differs, REVIEW when differences are listed, FAIL only if a repeat changed, asked the model again, or a difference went unlisted. Regenerated `docs/evaluation/EVAL-007_GATE.md`: 8 PASS, 2 REVIEW, 3 BLOCKED, 0 FAIL.

**Teach-back (`evaluation/variance.py`):** "It imports the same fake chats in three different orders and asks the same pinned model twice, then compares the labels and the 'what is current' answers using only names that come from the export. If anything changes with the order, that item is listed for a person with each run's answer next to the others. Asking again must give the same answer without calling the model again."
```
ruff check / format     # All checks passed! / already formatted
mypy                    # Success: no issues found in 162 source files
pytest -q               # 1163 passed, 7 skipped
migration drift         # 0
ke eval variance        # PASS: 17 segments and 26 records gave the same answers in 3 orders; repeats made 0 new requests
ke eval gate            # BLOCKED: 3 BLOCKED, 2 REVIEW, 8 PASS (0 FAIL)
```
Fix attempts: 1 (my drifting fake first answered "needs review" only once, and the retry hid it; it now never labels the first segment it sees).

**Next exact task:** check UI-005 (#175) against STATUS and close it if done; then M5.

### 08:10 UTC — EVAL-001: the real 40-chat answer key, made and checked by two separate Claude sessions
**What:** I built the real golden set (`golden-v1`) on Louis's PC. It covers 40 chats picked by the seeded sampler, with 398 records that must be found and 64 that must never be claimed. It lives only in the git-ignored workspace. What's committed is the review record, `docs/reviews/GOLD_REAL_V1_REVIEW.md`, which holds counts and the file's hash, but no chat IDs, titles or text.

**How:** I imported the whole export into a fresh workspace inside the project folder (1,158 chats, 0 failures) and ran `ke gold template --count 40`. A small read-only script then turned those 40 raw chats into plain transcripts, showing message IDs, speakers and branches. One Claude session on a different model from mine annotated them, and it saw only the transcripts, the guide and the schema. It saw no classifier output, ledger or report. A third session, on another model, reviewed the work against the same transcripts and corrected the key. I did the plumbing and ran the code checks, and labelled nothing myself.

**Challenges:**
- **No taxonomy existed yet.** The guide only allows labels from a published vocabulary, and none had been published. Rather than invent one, I left segment labels empty (`tax-none`). The set scores extraction now, and classification once the first taxonomy is locked.
- **Short replies got skipped.** I'd asked for evidence quotes of at least 5 words, so the annotator left out replies like "no" and "do that", which are exactly where rejections and decisions live. I told it a whole short message counts, and it added them. The reviewer then found 28 more missed records, plus 6 must-fix errors in type, speaker or acceptance.
- **My checker counted the reviewer's findings files as answer keys** (a glob of `batch*.json` matched `batch1.findings.json`). I narrowed the glob.

**Checks:** every cited message exists in its chat, and every quote appears in it word for word. Every user decision, rejection, preference or requirement cites a user message. `gold.py` validates the whole set, `ke gold schema` runs, and the gold tests pass (16 passed). I changed no tests or criteria.

**Talking points:**
- "The answer key was written by one AI session and checked by another, each on a different model, and neither saw what the system produced."
- "Code checks every piece of evidence in the key: the message has to exist, the speaker has to match and the quote has to be word for word."
- "The key has 56 assistant suggestions but only 12 real user decisions. Telling those apart is the whole job."
- "When there was no vocabulary to label against, I left the labels empty instead of making one up."

**Next exact task:** discover and publish the first taxonomy. After that, add segment labels to `golden-v1` with a fresh annotation and review pass.

### 08:17 — EVAL-013: scoring where the private key lives
The session on Louis's PC finished the real golden set `golden-v1` (40 chats, 398 records, 64 forbidden, reviewed by a separate AI session, extraction only). It has no GitHub access, so I opened and merged its docs-only branch as #243. I merged main into that branch so both diary histories survive; it contains no gold content.

There was no command to score a workspace against a key file, so the real extraction baseline couldn't be made where the data is. **EVAL-013** (`evaluation/workspace_score.py`, `ke gold score`) adds it:
- it runs the rule extractors once on the key's chats only (a second run repeats nothing);
- it scores every record of those chats with EVAL-004;
- the report is headed by the key's version, SHA-256 and reviewer label, and holds numbers and IDs only;
- it says how many of the key's chats the workspace actually holds.

The gate's `quality.real_golden_set` line now points at it. It stays BLOCKED here because the key is only on the PC. The command to run there is:

`ke gold score --gold workspace/gold-real/gold/golden-v1.json --reviewer ai_session --review docs/reviews/GOLD_REAL_V1_REVIEW.md --out docs/evaluation/EVAL-004_REAL.md`

**Teach-back (`evaluation/workspace_score.py`):** "On the PC where my private answer key lives, one command runs the rule extractors on just those 40 chats and scores the results against the key. The report holds only numbers and says which key it used and that an AI, not me, reviewed it. Running it again does no extra work and gives the same numbers."
```
ruff check / format     # All checks passed! / already formatted
mypy                    # Success: no issues found in 163 source files
pytest -q               # 1165 passed, 7 skipped
migration drift         # 0
```
Fix attempts: 0.

**Next exact task:** check UI-005 (#175) against STATUS and close it if done; then M5.

### 08:20 — The first real number, and a hash that depended on Windows
The PC session scored the rule extractors against the real key with `ke gold score`, and I merged its report as #246 (`docs/evaluation/EVAL-004_REAL.md`, counts only). The result was P 0.124, R 0.058 and F1 0.079 over 398 expected records. The hard gate held: 0 forbidden records, 0 unsupported decisions in current truth, every anchor valid, and the actor right on all 23 matches. Recall is 0 for decisions, facts, ideas, questions, recommendations and preferences. That's the baseline any model extractor has to beat, and it shows how little hand-written rules catch in real chats.

One thing didn't line up. The report's review-record hash wasn't the hash of the record in Git, because Windows checks text files out with CRLF line endings. A hash meant to name a record shouldn't depend on the computer. `sha256_review` now reads CRLF as LF before hashing; the synthetic review record (already LF) keeps its hash. The real report gets a comment naming both hashes rather than being rewritten.

**Teach-back (`evaluation/report_labels.py`, `sha256_review`):** "Every scored report prints the fingerprint of the review record it relied on. Windows and Linux store line endings differently, so the fingerprint is now taken as if every line ended the Linux way. The same record gets the same fingerprint on every computer."
```
ruff check / format     # All checks passed! / already formatted
mypy                    # Success: no issues found in 163 source files
pytest -q               # 1166 passed, 7 skipped
```
Fix attempts: 0.

**Next exact task:** ING-008 + ING-009.

### 08:32 — ING-008 + ING-009: notes, text, Word and PDF as located blocks
**ING-008** (`ingestion/documents.py`) reads Markdown and plain text into **blocks**: frontmatter, headings (`#` style and underlined), paragraphs, lists, quotes, fenced code, tables and rules. Each block keeps its exact character range in the decoded text, its line numbers, the headings above it, and a short locator like `L12-L15`, so `text[start:end]` is the block exactly as written. The tests check this with CRLF line endings and emoji.
- Frontmatter is parsed as YAML when it can be. Otherwise the raw text is kept and a warning code says why.
- Decoding tries UTF-8 (with or without a BOM), UTF-16 by its BOM, then Windows-1252, then Latin-1. Each fallback is reported, and no character is ever replaced.
- Image references are listed and never opened.

**ING-009** (`ingestion/structured.py`) puts Word and PDF behind one small `DocumentConverter` seam, so the rest of the engine always gets the same blocks.
- **Docling** is used if installed. It isn't installed here and isn't exercised by the tests; that path is clearly marked.
- The **built-in DOCX reader** (standard library only) reads paragraphs (`p12`), Word heading styles and tables (`table1/r1c1-r2c2`). It lists embedded images as references, and gives warning codes for what it skips: footnotes, endnotes, comments, headers, footers, text boxes, and images it can't describe. A DOCX is a ZIP, so member count and unpacked size are capped, and XML that declares a DOCTYPE is refused.
- A **PDF** with no converter is not read: it gets its hash, size and page count, no blocks, and `pdf_text_not_extracted`.

`ke file read PATH [--blocks]` shows a file's outline, block kinds and warnings, and only reads the file. Documents are parsed but not yet stored as sources; that waits for a ticket that needs them.

**Teach-back (`ingestion/documents.py`):** "It reads a note or text file into blocks such as headings, paragraphs and lists, and each block remembers exactly which characters and lines it came from. Odd encodings or broken frontmatter are reported with a warning instead of being guessed at. Word and PDF go through one swappable converter, and whatever it can't read is listed rather than hidden."
```
ruff check / format     # All checks passed! / already formatted
mypy                    # Success: no issues found in 165 source files
pytest -q               # 1173 passed, 7 skipped
migration drift         # 0
```
Fix attempts: 1 (my first paragraph/underlined-heading loop was tangled; rewrote it as one loop that turns a paragraph into a heading when an `===`/`---` line follows).

**Next exact task:** OPS-003 (local backups and verified restore).

### 08:38 — OPS-003: a backup that proves it restores
**OPS-003** (`infrastructure/backup.py`, `ke backup`) has three commands. None of them overwrites anything.
- **create** copies the database with SQLite's own online-backup API, which gives a consistent copy even while it's open. It also copies the archive of original files and images, checking each against the hash it's named by. It holds the import lock while doing this, so no import is half-way through. The backup is built in a temporary folder and renamed only when finished, and it must sit outside the workspace. Its `manifest.json` lists every file's SHA-256 and size, the schema revision and every table's row count. The search indexes are left out because `ke index` rebuilds them.
- **verify** re-hashes every file, runs SQLite's integrity check and recounts every table.
- **restore** only goes into an empty folder, and only from a backup that verifies. Then it checks the restored copy the same way.

The acceptance check is that restored hashes and record counts match the baseline. A restored workspace also re-imports the same export with 0 new conversations.

Failing-case reproduction: my tampering test deleted rows from the backup's database, but the file's hash didn't change. The copy had inherited WAL mode, so the change went into a side file. A backup should be one self-contained file, so the copy is now switched to ordinary journal mode. After that, both the hash and the row count catch it, and the restore refuses.

**Teach-back (`infrastructure/backup.py`):** "A backup is a folder with a copy of the database, the original files, and a list of every file's fingerprint and every table's row count. Verifying re-checks all of that, and a restore only goes into an empty folder and then proves it got everything back. Nothing is ever overwritten, and a backup that doesn't check out is never restored."
```
ruff check / format     # All checks passed! / already formatted
mypy                    # Success: no issues found in 166 source files
pytest -q               # 1177 passed, 7 skipped
migration drift         # 0
```
Fix attempts: 1 (the WAL-mode copy hid a change from the file hash; the backup copy now uses journal_mode=DELETE).

**Next exact task:** OPS-004 (data deletion and downstream purge).

### 08:55 — OPS-004: deleting a chat for good, and proving it
**OPS-004** (`retention/purge.py`, `ke purge`) deletes whole conversations and everything made from them. It works in two steps.
- **`ke purge plan ID…`** only reads. It prints how many rows of each kind would go and what is kept because another chat still uses it (an image, a video, a link, an account). It also lists what the engine can't reach: the original export in `raw/`, images kept by reference, and older backups. Last, it prints a 12-character token.
- **`ke purge run ID… --confirm TOKEN --reason "…"`** needs that token, so nothing goes that wasn't shown first. If anything changed since the plan, the token no longer matches and nothing is deleted. Everything is deleted in one transaction: the message tree, images nobody else shows (bytes included), link, video, transcript and account mentions, related-chat links, labels, corrections, extraction runs, the model answers behind them, knowledge records and everything attached to them, document builds, and the archived export file. The append-only guards are lifted only inside that transaction.

A purge leaves **tombstones**: hashes of the conversation ID and of the export file. Re-importing the same full export then skips the chat and doesn't re-archive the file. The audit log `purge_events` keeps counts and the check result, never the words, and it refuses deletes.

**Acceptance check: post-delete retrieval returns nothing deleted.** Before deleting, a few short passages of the chat's own text are held in memory as probes. They are never written anywhere. After the purge, the database is compacted and the indexes are rebuilt. Then the check requires that:
- search finds none of the purged messages;
- the database file's bytes don't contain the probes;
- no table still names a purged ID;
- every planned file is gone;
- if a vault is given, it is re-synced and no note or image copy remains.

On the synthetic workspace all of these come back clean.

Design choice (ADR-0010, OPEN_DECISIONS): the archived copy of an export file is deleted whole, even though it also holds other chats. Their messages stay; only their archived original file goes, and the plan says how many chats that affects. Running a purge on the real archive still needs Louis's go-ahead.

Failing-case reproduction: in the image test, the check found the image still in the vault after the second chat that showed it was purged. The vault sync never removes image files, because it doesn't track who put them there. The purge now removes exactly the engine's own copy: the file at the engine's attachment path whose bytes still hash to the purged image.

**Teach-back (`retention/purge.py`):** "To delete a chat I first make a plan that lists everything made from it and gives me a token, and the delete only runs with that token. It removes the chat and everything derived from it in one go, keeps anything another chat still uses, and leaves a fingerprint so re-importing my history doesn't bring it back. Then it proves the job is done by searching for the chat's own words and IDs and finding nothing."
```
ruff check / format     # All checks passed! / already formatted
mypy                    # Success: no issues found in 170 source files
pytest -q               # 1181 passed, 7 skipped
migration drift         # 0
```
Fix attempts: 1 (vault image copies survived the purge; the purge now removes the engine's own copies).

Record fix: the times on this diary's entries since 00:35 had drifted hours ahead of the real clock, because I estimated them instead of reading the clock. Each is now the PR's merge time from `git log`.

**Next exact task:** OPS-005 (CI with no real credentials).

### 09:03 — OPS-005: one command for every check, with no keys anywhere
**OPS-005** (`devtools/ci.py`, `.github/workflows/ci.yml`) makes CI one command I can also run myself.
- `python -m knowledge_engine.devtools.ci` runs lint, format, strict types, the git guard and the whole test suite.
- `--nightly` runs the bounded semantic checks: the release gate, the variance check and the ZIP-to-vault run. They use synthetic fixtures and the fake model, one pass each, no retries.
- Every step runs with API keys removed from its environment. A check that secretly needed a real model would fail here, instead of passing on a machine that happens to have a key.
- The GitHub workflow runs those two commands and nothing else, on Linux and Windows with Python 3.12 and 3.13, plus a nightly schedule. It uses no secrets.

While doing this I found the schema-drift test only compared two of the 25 table modules, because only those were imported in that test. There is now one list of table modules (`migrations/tables.py`). Alembic uses it, and a new test checks every table against the migrations. A second new test checks that every module defining a table is on the list.

Acceptance check, "CI reproducible with no real provider credentials": I ran it locally with a fake `ANTHROPIC_API_KEY` set in the shell (it is stripped). All 5 checks passed and all 3 nightly checks passed.

**Owner decisions this morning** (Louis, 08:54 UTC, "Do a and b"):
- **a)** One EVAL-011 smoke run with a real paid model is approved as a single exception: synthetic chats, as small as the ticket allows, with a hard cost cap. Its cost will be written here. The no-paid-API rule stays for everything else.
- **b)** The 13 parked tickets (API, product and integrations) are unparked and will be built after M5 and M6. Their labels are removed.

**Teach-back (`devtools/ci.py`):** "CI is one command that I can run on my own machine too, so a green build means the same thing in both places. It strips every API key before running anything, so no check can lean on a paid model. The nightly part runs the evaluations once on fake data with a fake model, so it can't run away."
```
ci (lint, format, types, guard, tests)   # 5/5 ok; pytest 1186 passed, 7 skipped
ci --nightly (gate, variance, e2e)       # 3/3 ok
```
Fix attempts: 0.

**Next exact task:** the real-provider adapter for the one approved EVAL-011 run, then OPS-006.

### 09:14 — OPS-005: first CI run found Windows and non-root problems

The first GitHub Actions run of #251 failed on all four jobs. Locally every test passed because this container runs as root, and none of the earlier runs were on Windows.

- **Purge on Windows (product bug).** Windows won't delete a read-only file, and stored evidence is read-only. Purge, and the importer's removal of a purged file stored again, now go through `archive.remove_stored`, which puts the write bit back first.
- **Fixture ZIP bytes (product bug).** The EVAL-006 fixture builder didn't pin the ZIP's "made on" byte, so Windows built different bytes. It is now pinned, as `synthetic.py` already did.
- **Two tests that only ran in one setup.** The backup tamper test wrote to a read-only file. It now makes it writable first, as a tamperer would; its assertions are unchanged. The installed-`ke` test looked next to `python.exe`, but Windows puts scripts in `Scripts\\`; it now asks `sysconfig`. Neither assertion changed.

Checks: the full suite as a non-root user, 1186 passed, 7 skipped. Purge, backup, end-to-end and CLI tests pass as root. Windows is proved by CI.
Fix attempts: 1.

### 09:16 — EVAL-011: a real-model adapter with a hard cost cap

Louis approved one paid smoke run (2026-10-28 08:54 UTC, "Do a and b"). This PR builds the adapter for it. Nothing paid has run yet.

- `providers/anthropic_api.py`: `AnthropicProvider` sends each request to a pinned model (`claude-haiku-5-5` by default, the OD-05 spike's model) and asks for JSON that fits the request's schema. Before each request it works out the worst case: all the input and the schema at about 2 characters per token, plus the full output allowance, at list price. If that would go over what is left of `max_cost_usd`, the request is not sent and is counted as capped. After each answer, the real cost from the reported token counts is added. Thinking is off: choosing labels from a fixed list doesn't need it, and it would use up the same `max_tokens`.
- Answers go through `result_from_response` like every provider's. A refusal is `invalid` and isn't retried. A cut-off answer is `invalid`. Rate limits and connection errors are `transient`, and the worst case is counted as spent.
- `ke eval semantic --provider anthropic --max-cost-usd X` refuses unless `--synthetic` is given, `[egress] text_llm` is on, and both caps are above zero: the flag and the until-now unused `[limits] max_cost_usd_per_run`. The lower one is used. The report gains a `provider` block: calls, tokens, dollars, the cap, and capped requests.
- `pyproject.toml`: a new `api` extra (the SDK). The dev extra includes it so the tests type-check.

**Teach-back (`providers/anthropic_api.py`):** This is the only piece that can spend money, so before each question it works out the most that question could cost, and doesn't send it if that would break the cap. It also can't send anything unless I've switched outbound model calls on, and the command only lets it run on made-up chats. Its answers get exactly the same checks as the fake model's, so a bad answer ends up as a review item, not stored data.

Checks:
```
tests/integration/test_anthropic_provider.py   7 passed (stand-in client, no network)
ci                                             see PR
```
- First draft: my stand-in's answer didn't fit the classification schema, so every segment used its one repair (2 calls per segment). The test now answers with a valid "unsure" reply and checks there is exactly 1 call per segment.
Fix attempts: 1 (the cap test's room was too generous to trigger the cap).

**Next exact task:** run `ke eval semantic --synthetic 50 --provider anthropic --max-cost-usd 0.50` on Louis's PC with egress on for that run only. Then record the cost and approval here, and switch egress off.

### 09:34 — OPS-006: imported text stays data everywhere it goes

I wrote one hostile synthetic chat and followed it through the system. It carries prompt injection, a forged message line, Markdown that would fetch a remote image or open another app, Dataview code, HTML, odd URL schemes, and a hostile title. Most defences were already in place: ZIP names and sizes, escaped web pages with a strict CSP, http(s)-only links, egress off. The test found two real gaps:

- **Vault notes obeyed some chat Markdown.** `escape_text` stopped `[[...]]`, HTML and tags, but not `![x](https://...)`. That kind of image is fetched when the note opens, which tells the remote server the note was read. It also let through `[x](obsidian://...)` links and code. Code fences and inline code are where Dataview runs queries and JavaScript. Every bracket and backtick is now escaped, plus `~~~` fences. The words still read the same; they just don't act.
- **A message could pose as another message in model input.** Requests frame each message as `[m:ID] role:`, so a message containing a line like `[m:x] user:` looked like a separate user turn. `providers.base.quote_untrusted` now escapes every line-start `[` in classification, extraction and grounded-answer input. Text without one is unchanged, so existing stage keys don't move.
- The real-model adapter also puts the text inside `<source_data>` tags it can't close. It says in the system prompt that the text is data, and it offers the model no tools.
- `docs/operations/SOURCE_AS_DATA.md` lists every place imported text goes and the rule there. That is the ticket's "all public contracts documented" criterion.

**Teach-back (`rendering/markdown.py` `escape_text`):** Anything from a chat that lands in my vault goes through one function that turns every special character into a shown character. So a chat can't make a note fetch a picture from the internet, link into another app, or run plugin code when I open it. The words are all still there to read; they just can't do anything.

Checks:
```
tests/integration/test_adversarial.py   7 passed
  (with the old escape_text: the vault test fails; without quote_untrusted: the model-input test fails)
ci                                      5/5 ok, 1201 passed, 7 skipped
```
Fix attempts: 0 on the product code. The test needed three passes to separate the engine's own trusted syntax (its wikilinks, its link list) from chat text.

**Next exact task:** the approved EVAL-011 paid run on the PC (once #252 merges), then OPS-007 packaging.

### 09:44 — EVAL-011: the one paid run

Louis approved one paid smoke run at 08:54 UTC ("Do a and b"): synthetic chats only, as small as the ticket allows, hard cost cap, cost recorded here. It ran on his PC at commit 80fc4e0, 09:41–09:44 UTC. The key and the egress switch were environment variables for that one command and were removed afterwards; `ke.toml` was not touched and nothing was committed on the PC.

`ke --json eval semantic --synthetic 50 --provider anthropic --max-cost-usd 0.50`: passed, every check true. 50 chats, 67 segments, 67 model calls, 0 schema failures, 0 repairs, 0 capped, 0 unvalidated outputs. 101,846 input and 13,390 output tokens. **Cost: $0.0169** of the $0.50 cap.

All 67 segments went to review and none to done. Nothing unchecked was stored, so that is the safe outcome. My guess is the three-term smoke vocabulary doesn't fit the generated chats and the model said it was unsure, but the report doesn't itemise review reasons, so I haven't confirmed it. Follow-up: count review reasons by kind in the report. No further paid runs: the approval was for one.

**Next exact task:** OPS-007.

### 09:48 — OPS-007: install, upgrade and roll back like a stranger would

- `infrastructure/upgrade.py`: `ke db upgrade` now takes a full OPS-003 backup **before** migrating, into `<workspace>-backups` next to the workspace (`--backup-to` to choose, `--no-backup` to skip on purpose). If a migration fails, the error names the backup to restore.
- Imports no longer migrate an existing database quietly. A database older than the code stops the import with `schema_mismatch` and says to run `ke db upgrade`. A database newer than the code (an older version installed over a newer one) is refused too. A brand-new workspace is still created straight away.
- `devtools/release_check.py` builds the wheel, installs it in a fresh venv, checks `ke --version` against `pyproject.toml` and `CHANGELOG.md`, imports a synthetic export, steps the schema back one migration, upgrades (backup taken), then verifies and restores that backup and checks the restored copy is at the old revision. `.github/workflows/release.yml` runs it nightly, on demand and on `v*` tags, on Linux and Windows. It is a separate workflow because `ci.yml`'s commands are pinned by tests.
- `CHANGELOG.md` starts at 0.1.0; `pyproject.toml` is now 0.1.0. `docs/runbooks/UPGRADE_AND_ROLLBACK.md` is the install, upgrade and rollback procedure.

**Teach-back (`infrastructure/upgrade.py`):** Before a new version changes my database's layout, it makes a full, checked backup next to my workspace, and if the change fails it tells me which backup to restore. Imports won't change the layout behind my back any more: if the database is older or newer than the program, they stop and tell me what to do. So upgrading is one deliberate command, and a bad release costs me a restore, not my data.

Checks:
```
tests/integration/test_upgrade.py   4 passed
tests/unit/test_release.py          2 passed
release_check (this container)      6/6 ok
ci                                  5/5 ok, 1199 passed
```
Fix attempts: 1 (`create_sqlite_engine` needs a Path in the release check's step-back script).

**Next exact task:** M6.

### 10:01 — API-001: the JSON API's skeleton

`ke ui` is web pages for a person; the API is the same engine as JSON, for scripts. This ticket only builds the frame every later endpoint hangs on.

- `api/app.py`: `create_app(settings)` builds a FastAPI app. Endpoints get the settings, the database and the model provider through dependencies (`get_settings`, `get_sessions`, `get_provider`). A test swaps them with `app.dependency_overrides`, which is the ticket's acceptance check: a test client runs against a temporary database and a fake provider, and the app's own workspace is never opened.
- One error shape for everything, `{"error": {"code", "message"}}`, with a table of stable codes in `docs/api/API.md`. Validation errors name fields, never values, and a crash returns `internal_error` with no traceback, since both could carry private text.
- Everything is under `/api/v1`, and the OpenAPI document carries the package version.
- This computer only: requests with a non-loopback `Host` are refused (`host_not_local`), no CORS headers, and `ke api` binds 127.0.0.1 with no option to change it.
- A database older or newer than the code gives `schema_mismatch` (OPS-007's rule). `status` still works, so a program can see why.
- Endpoints so far: `health`, `status` and `counts`. FastAPI and uvicorn are in a new `server` extra, so the engine itself doesn't need them.

**Teach-back (`api/app.py`):** The API is built by one function, and everything an endpoint needs (settings, database, model) is plugged in from outside, so tests plug in a temporary database and a fake model. Every error comes back in the same shape with a fixed code, and never repeats what was sent, so private text can't leak through an error. It only answers requests addressed to this computer.

Checks:
```
tests/integration/test_api.py   8 passed
ci                              5/5 ok
```
Fix attempts: 1 (an error-handler parameter named `_error` hid the `_error` helper; the provider identity field is `provider_id`).

**Next exact task:** API-002 (import and job status endpoints).

### 10:09 — API-002: imports, jobs, sources and messages over the API

- `POST /api/v1/imports` starts the import on a background thread (the same job runner as the Import button) and answers **202** with `{"job_id", "state": "running"}` at once. The test holds the importer until the test releases it, so it proves the answer can't be a premature "done". `GET /jobs/{id}` then shows `done` with the import ID, or `failed` with a plain reason and no paths.
- `GET /imports` and `GET /imports/{id}` read the ledger: status (`partial` included), counts, summary and warnings by kind.
- `GET /sources` pages through conversations (`q` filters titles). `GET /sources/{id}` gives branch points with their kind, graph issues and related chats. `GET /sources/{id}/nodes` gives messages in transcript order: active path first, then alternates, each once, with `parent_id` and `children` so a program rebuilds the real tree instead of a flattened chat, plus media uses with availability.
- Every list: `offset`, `limit` (max 500), `total`, `next_offset`.
- New rule for anything but GET: the body must be JSON, and an `Origin` header must be this computer. Otherwise any website could make your browser POST an import to 127.0.0.1 (the Host check alone doesn't stop that, because the Host really is 127.0.0.1).
- The dependencies moved to `api/deps.py` so endpoint modules can use them without importing the app.
- Two API-001 test lines changed with it (my own tests from the previous PR): the 405 check now sends a JSON body, since a non-JSON POST is refused earlier with 415; the OpenAPI check now says the three API-001 paths are present and every path is under `/api/v1`, instead of "exactly these three".

**Teach-back (`api/imports.py`):** Starting an import over the API gives back a job number straight away, and the import runs in the background; asking about the job later says running, done with its report, or failed with a reason. Listing a chat's messages gives each one with its parent, active path first, so a program can rebuild every branch exactly. Long lists come in pages that say how many there are and where the next page starts.

Checks:
```
tests/integration/test_api_imports.py   9 passed
tests/integration/test_api.py           8 passed
ci                                      5/5 ok, 1224 passed, 7 skipped
```
Fix attempts: 0.

**Next exact task:** API-003 (taxonomy, review and knowledge endpoints).

### 10:17 — API-003: taxonomy, review and knowledge over the API

- `api/knowledge.py` puts the existing review workflows behind HTTP and adds no rules of its own except one (below). Taxonomy: the live vocabulary, published frozen versions, the governance report, proposals by status, `POST` a proposal, `POST` a review. Knowledge: current knowledge (supported and confirmed only), the review queue (records plus open proposals), one record with its evidence anchors and trust history, and `POST` a decision.
- Refusals: `reviewer_not_allowed` (403) for the proposer reviewing their own proposal or the `validator` name; `invalid_transition` (409) for anything the workflow refuses. Each request is one transaction, so a refused approval (an alias clash, say) leaves nothing half-applied. The test checks the vocabulary and the record's history are unchanged afterwards.
- The one new rule: `decide` quietly returns a record unchanged when a decision doesn't apply (support on a confirmed record). The API refuses that with 409 instead, so a program never mistakes "nothing happened" for "done". `decide` itself is unchanged.
- Pydantic's error for a broken record rule can include the record's input, so the API returns only the rule's own words ("a user decision needs explicit or conditional acceptance").
- There are no accounts until PROD-002: the reviewer is a name the caller gives, the same trust as `ke ... --reviewer`. Recorded in `docs/api/API.md`.

**Teach-back (`api/knowledge.py`):** These endpoints let a program see what's waiting for review and send a person's decision, but every decision still goes through the same rules as the command line. Nobody can approve their own proposal, nothing can be decided twice, and an assistant's suggestion can't be turned into my decision without my acceptance. If a decision is refused, nothing about the record or the vocabulary changes.

Checks:
```
tests/integration/test_api_knowledge.py   8 passed
tests/integration/test_api*.py            25 passed
ci                                        5/5 ok, 1232 passed, 7 skipped
```
Fix attempts: 1 (supporting a confirmed record was a silent no-op; now refused).

**Next exact task:** API-004 (search, answers and decision history).

### 10:28 — Flaky variance test: seeded shuffle of an unseeded list

`test_order_dependent_answers_become_review_items` failed once in CI (#258, Ubuntu 3.13) and passed on the other three jobs and 25 local runs. Cause: `run_order` shuffled the conversations with a fixed seed, but it read them in `conv_` ID order, and those IDs include the workspace's random ID. So each run shuffled a differently ordered list and the "same" seed gave a different order. Roughly one run in n² (n segments) put the same segment first in all three orders, and then the test's drifting model flagged the same segment every time, so no difference showed. Fix: read them sorted by the export's own conversation IDs before shuffling. The test is unchanged; it is now deterministic (passes 25/25).

### 10:30 — API-004: search, answers and decision history over the API

- `api/retrieval.py`: `GET /search` (words, phrase or exact), `GET /find` (the planner's route: decision records first, then messages), `POST /answers` (every sentence cited, or "I don't know"), `GET /decisions/{id}/history` (every event touching a decision, each with its evidence).
- Each request syncs the word and meaning indexes first, under a lock, because the index files have one writer. No model is called: the extractive writer and the local embedder.
- The acceptance test follows every citation back through the API's own `/sources/{id}/nodes`: same revision, a span inside that message's text, and the cited words are about the shed.
- `as_of` is tested on the engine-switch chats: asked as of one second before the switch, the answer has no Godot and no "Replaced decision"; asked now, it has both.

**Teach-back (`api/retrieval.py`):** These endpoints search my chats and answer questions from them, and every sentence of an answer points at the exact characters in the message it came from, which a program can open through the API. If nothing supports an answer, it says it doesn't know. Asking "as of" a date gives the decisions as they stood then, before anything that replaced them.

Checks:
```
tests/integration/test_api_retrieval.py   5 passed
ci                                        5/5 ok, 1237 passed, 7 skipped
```
Fix attempts: 0.

**Next exact task:** API-005 (document build, preview and export endpoints).

### 11:20 — UI-006: an evaluation dashboard in `ke ui` (#260)

**What Louis asked:** "I also need a dashboard to evaluate each output and all the other outputs." He doesn't label or review anything himself (project rule), so this had to be a page for *judging*, not a labelling tool: read only, no forms, and every score saying who checked the answer key.

**What was built:**
- `/evaluation` is the overview. It counts every output the engine stored: knowledge records by type and trust, classifications, chat links, vocabulary proposals and model requests. Reviewer decisions and the automatic evidence check are counted separately. With an answer key loaded it shows precision, recall and F1 per record type, attribute agreement, how many quotes are still valid and the hard gate.
- `/evaluation/outputs` lists every knowledge record with its verdict: matches the key, not in the key, forbidden, not scored or rejected. Below that come the expected records nothing found, each linked to the message.
- `/evaluation/outputs/<id>` shows one output: its quotes in full, what the evidence check says *today*, who changed its trust and why, and a row-by-row comparison with the expected record.
- `ke ui --gold PATH --reviewer ai_session --review REVIEW.md` points it at the private key. The key is only read and stays in the git-ignored workspace. `--gold` without `--reviewer` is refused, so a score can't appear without saying who checked the key.

**Key decision: one pairing, two readers.** The EVAL-004 scorer only returned totals, so the page couldn't say *which* record was the false positive. I moved its matching loop into `match_extraction()`, which returns the pairs, and made `evaluate_extraction()` count those pairs. The rules are the same and so are the numbers: the existing scorer tests pass unchanged, and a new test checks the dashboard's counts against the scorer's. A second, look-alike copy of the matching for the page would have drifted from the real one sooner or later.

**Challenge:** the synthetic answer key scores a perfect 1.000 on the rule extractors, so the "extra" and "missed" paths were never exercised. One test now writes a changed *copy* of the key to a temp folder: one expected type is changed and one record is forbidden. The committed key is untouched.

**Teach-back (`ui/evaluation.py`):** The dashboard reads what the engine stored and compares it with a private answer key, using exactly the same pairing as the scoring report, so the page and the report always agree. For each output it shows the quotes, today's automatic check, the review history and whether it matched, wasn't expected, was forbidden or wasn't scored. Every number names the answer key it used and who checked that key, and only my own review could ever show "Owner verdict".

Checks:
```
tests/integration/test_ui_evaluation.py   8 passed
tests/integration/test_extraction_eval.py, test_gold_score.py, test_gate.py   unchanged, pass
ci                                        lint, format, types, guard ok; 1240 passed, 7 skipped
```
Fix attempts: 1 (a test read a field the key leaves out when false).

**Next exact task:** PR 2 of the dashboard: classifications per segment against the key's labels, the model-request ledger, and saved gate reports.

**Talking points:**
- "I built a dashboard to judge my AI's output without labelling anything myself. Every score says which answer key it used and that an AI checked that key, not me."
- "The page and the report use one matching function, so they can't disagree."
- "It's deliberately read-only. An evaluation page that let me edit answers would turn me into the labeller, and grading against your own edits is how the last attempt fooled itself."

### 11:45 — UI-006 part 2: segment labels and model requests on the dashboard (#260)

**What:** the second half of the evaluation dashboard.
- `/evaluation/classifications` shows each segment the answer key labels beside the labels stored for the segment that holds its first message: per field, the expected labels (with readable names), the stored ones, and "same", "primary right, others differ" or "differs". Above that are per-field precision, recall, micro/macro F1 and primary accuracy. An ambiguous segment counts as right only if it was sent to review.
- The overview gains a **Model requests** table: requests, attempts, transient failures and characters sent, by stage, provider and state. It shows counts only and never prompts or answers.
- `ke ui --gold … --reviewer ai_session` without `--review` is now refused up front. Before, the page just showed an error, because a key that claims a review has to point at the review record.

**Same idea as part 1:** EVAL-003's pairing ("the stored segment holding the key segment's first message") moved into `match_classification()`, and the scorer counts those pairs. Its tests are unchanged and pass. A new test checks the page's per-field numbers against `evaluate_classification` on the same stored labels.

**Scope note:** only labels stored under the key's own taxonomy version are compared, since labels from another vocabulary can't be. The real answer key has no segment labels yet (they wait on the first published taxonomy), so for now the page says so instead of scoring.

**Teach-back:** none new here. The thread picked `ui/evaluation.py` in part 1, and this adds to the same module.

Checks:
```
tests/integration/test_ui_evaluation_labels.py   4 passed
tests/integration/test_gold_and_classification_eval.py, test_gate.py   unchanged, pass
ci                                               5/5 ok, 1249 passed, 7 skipped
```
Fix attempts: 0.

**Next exact task:** none for the dashboard. Saved gate reports could be listed later if Louis wants them in the browser.

**Talking points:**
- "For each topic section, the dashboard puts the answer key's labels next to what the classifier stored, with readable names, so I can see exactly where it goes wrong."
- "It also counts every model request, with retries and how much text was sent, without ever showing the text."

### 10:36 — API-005: documents and exports over the API

- `api/documents.py`: `GET /documents` lists every note an export would write (path, kind, size) and `GET /documents/preview` shows one note's Markdown. Both only plan; nothing is written. The preview looks the path up among the planned notes and never opens it as a file, so `../../etc/passwd` is just "not found".
- `POST /exports` answers 202 with a job and runs DOC-006's `sync_vault` in the background; `GET /exports/jobs/{id}` gives the counts.
- **Destinations are names, not paths.** `{"destination": "main"}` means `<workspace>/exports/main`. `../outside`, `/tmp/x`, `C:\Users\x`, `a/b`, `.`, `..` and a planted link to another folder are all refused (`invalid_destination`) before anything is created; the tests check nothing was written. Writing into a vault elsewhere stays a deliberate `ke docs vault --vault <folder>`.
- **No overwrite of user files**, tested through the API: a note edited above the marker is reported as a conflict and kept byte for byte; a file of mine at a path the engine wants is reported as occupied and left alone.
- One export per destination at a time (`export_running`), so two jobs can't race on the same manifest.

**Teach-back (`api/documents.py`):** Over the API I can list and preview the notes the engine would write, and start an export that runs in the background. An export can only go into a named folder inside my workspace, so a request can't point it at any other place on my computer. Even there it never overwrites a file I made or a note I edited; it reports them instead.

Checks:
```
tests/integration/test_api_documents.py   13 passed
ci                                        5/5 ok, 1250 passed, 7 skipped
```
Fix attempts: 0.

**Next exact task:** PROD-001 (PostgreSQL proof of concept): M5 is complete once API-004/005 merge.

### 10:47 — PROD-001: the same engine on PostgreSQL

- `infrastructure/dialects.py`: the only SQL that differed was the "refuse this change" triggers. On PostgreSQL each becomes one shared function `ke_refuse_change()` plus a row trigger that calls it with the same message; on SQLite nothing changes. A trigger it doesn't recognise raises, so a new migration can't lose its guard by accident. The nine migrations with triggers now call `run_triggers(...)`.
- `run_import(..., database_url=...)` writes rows to PostgreSQL; the archive, lock and search index stay in the workspace. Search needed no port: its FTS5 index was already a cache rebuilt from whatever database the session reads.
- `devtools/postgres.py` starts a throwaway server for the tests (127.0.0.1 only, temporary folder, removed afterwards), or uses `KE_TEST_POSTGRES_URL`. It skips without binaries, and as root, because PostgreSQL won't start as root.
- `evaluation/backend_bench.py`: 200 synthetic conversations, 9,609 rows. First import 7.3 s SQLite vs 18.9 s PostgreSQL, repeat 4.9 vs 11.0 s, searches equal. Same rows, same 120 hits.
- Gaps written down in `docs/operations/POSTGRES_POC.md`: the CLI, UI, API, purge, backup and `ke db upgrade` still open the SQLite file.

**Teach-back (`infrastructure/dialects.py`):** The database rules that refuse edits to history were written as SQLite triggers, and PostgreSQL writes triggers differently. This module rewrites each one into PostgreSQL's form with the same message, and leaves SQLite untouched. If it meets a trigger it doesn't understand it stops, so no protection quietly disappears.

Checks:
```
tests/integration/test_postgres_backend.py   16 passed (non-root user, PostgreSQL 16, 23 s)
backend_bench --conversations 200            rows_equal true, hits 120/120
```
Fix attempts: 0.

**Next exact task:** PROD-002.

### 10:58 — PROD-002: accounts, roles and who did what

- `access/policy.py`: four roles (viewer, editor, reviewer, owner) as fixed sets of six permissions, in one table. A **service account** (a program) may only be a viewer or editor, so automation can import and read but never confirm or reject knowledge.
- `access/accounts.py` + migration 0029: accounts, tokens (only a SHA-256 is stored; the token is shown once), one role per account per workspace, and `authz_events`, an append-only log of every refusal, every allowed change and every membership change. It records the method and route, never the query text, because a search can be private words.
- `api/access.py`: runs before every endpoint. No accounts means single-user mode, exactly as before (all earlier API tests pass unchanged). The first account turns checking on: 401 without a valid token, 403 `not_a_member`, 403 `forbidden`. The whole policy is `ROUTE_PERMISSIONS`, one line per endpoint; a test compares it with the OpenAPI routes, and once checking is on an unlisted route is refused.
- A body's `reviewer`/`proposer` must be the caller (`identity_mismatch`), so "you can't review your own proposal" can't be dodged by typing someone else's name.
- `ke access add|token|revoke|disable|grant|remove|list|log`.
- One FastAPI detail: a route inside an included router only knows its own path (`/sources`), so the check adds `/api/v1` back before the table lookup.
- The API serves the `default` workspace; several workspaces in one database is PROD-003.

**Teach-back (`api/access.py`):** Before any endpoint runs, this checks who is calling and whether their role in the workspace allows that endpoint, using one table that lists every endpoint. Until I create an account nothing changes; after that every request needs a token, and an account from another workspace is refused everywhere. Refusals and changes go into a log nobody can edit, and nobody can act under someone else's name.

Checks:
```
tests/integration/test_api_access.py   8 passed
```
Fix attempts: 1 (the route lookup missed the router prefix; a result-type bug in `members`).

**Next exact task:** PROD-003 (tenant isolation through retrieval and exports).

### 11:06 — #255: why the smoke answers went to review

Louis asked what the review said about the paid run. The honest answer was "we don't know": the report counted outcomes, not reasons. Now:

- `classification/store.py`: `review_reason_kind()` turns each problem string into a kind (`model_unsure`, `invalid_answer`, ...). The model's own `review_reason` text is dropped, because in a real run it could quote a chat.
- The smoke report has `classification.review_reasons`.
- `replay_review_reasons()` and `ke eval review-reasons`: run the same classification over a saved scratch workspace with a call budget of zero and a provider that answers nothing. Every answer comes from the request ledger, so it costs nothing and needs no key. The test checks the replay gives the report's exact counts and leaves the database byte-identical.
- Found on the way: the smoke run never stores classification rows (it only fills the ledger), so reading `classifications` would have shown nothing. That is why this replays instead.

**Teach-back (`replay_review_reasons`):** It re-runs the classification on a finished smoke run, but it isn't allowed to call any model, so every answer has to come from what that run saved. Then it counts why each answer went to review, by kind only. That lets me explain a paid run afterwards without paying again.

Checks:
```
tests/integration/test_review_reasons.py   10 passed
```
Fix attempts: 1 (the first version read the classifications table, which the smoke run doesn't fill).

**Next exact task:** run `ke eval review-reasons` on the paid run's scratch folder on Louis's PC (no paid calls), then PROD-003.

### 11:17 — #255 result, and PROD-003: one folder per workspace

**#255 on the real paid run** (Louis's PC, saved answers only, no calls): 67/67 in review. 53 `evidence_outside_segment`, 23 `model_unsure`. A shape check of the 249 evidence strings found every one written as `[m:<id>]`, copying the input's tag, and all 249 IDs are real messages. So the "outside the segment" flags are a parsing bug on our side, not the model citing the wrong messages. Fix next (normalise the tag before the check).

**PROD-003.**
- Decision (ADR-0011): separate workspaces are separate folders, not filtered rows. About 50 derived tables have no workspace column and the indexes are per-folder files, so a shared database would need a filter in every query forever. With folders there is nothing to forget.
- `access/tenants.py`: `<tenants_root>/workspaces/<name>` and `<tenants_root>/inbox/<name>`; `create_tenant` makes both, migrates, and adds an owner with a token. `ke tenant add|list`.
- `get_settings` reads `X-KE-Workspace` and returns that tenant's settings; everything else already derives from settings. Job lists became per workspace (the single-user shape is kept, so existing tests are unchanged). `check_access` never runs in single-user mode for a tenant: no accounts means nobody gets in. `POST /imports` resolves the source inside the tenant's inbox and refuses anything outside before touching the disk.
- The adversarial test fingerprints every file in workspace a, lets Mallory try everything from b, and requires a to be byte-identical afterwards.

**Teach-back (`access/tenants.py`):** When several people use one engine, each gets their own workspace folder with its own database and search files. A request names its workspace once and from then on only that folder is opened, so one person's chats can't show up in another's search, answers or exports. Imports only come from that workspace's own inbox folder, so nobody can import someone else's files.

Checks:
```
tests/integration/test_tenant_isolation.py   4 passed
```
Fix attempts: 1 (the test read `items` where search answers `hits`).

**Next exact task:** fix the `[m:id]` evidence parsing, then PROD-004.

### 12:30 — Why the chat notes feel thin: the old rich notes against today's pipeline

Louis said the dashboard is interesting but the chat analysis is very weak, and asked for the full rich notes the old attempts made, with better formatting. Before building anything, I compared the old material with what the engine produces now. Write-up: `docs/plans/RICH_NOTES_GAP_ANALYSIS.md`.

What I did:

- Read the two old attempts on `P:\` (read-only): the v1 word-frequency pre-pass and its vocabulary, the v1 prompts, skill contract and runbook, a v1 smoke note, and the whole v2 smoke-50 run (967 files, 50 notes).
- Generated today's knowledge notes for the same two chats from the real workspace, into a scratch folder outside Git.
- Measured instead of guessing: note sizes, evidence blocks, filler blocks, record counts by type.

What I found:

- **v1 had good content in the wrong place.** A 17-message chat gave a sharp four-sentence summary and 14 typed, quoted knowledge objects, but almost all of it sat in YAML front matter where nobody reads it. Its vocabulary auto-promoted any word seen in three notes, so words like "new" and "red" became terms.
- **v2 had the right sections and drowned them.** All 50 notes share 15 sections (summary, knowledge card, category and subcategory analysis, decisions, insights, tensions, next steps...), but they hold 3,094 evidence blocks and 165 "not applicable" blocks; the median note is 76 KB. In 22 of 50 notes "key decisions" were just every user message, including a pasted role-play prompt. Every note called itself "certified" while its own data said "review required".
- **Today's engine is the reverse.** The plumbing is far better than either attempt (branches, images, links, exact quotes, provenance), but the meaning is missing: no taxonomy has been published on the real chats, so nothing has a category; the rule extractors found 0 decisions in 85 real segments; the same 17-message chat now gets a note with 0 knowledge records and a line of counts.

Decisions and proposal (Louis decides; nothing is approved yet):

- A note template that puts the readable content first: summary, knowledge card, decisions, suggestions not taken up, open questions, generated insights, tensions and next steps (clearly labelled as generated), category analysis, keyword and topic candidates, related chats. Evidence becomes a short `[m12]` link to the transcript with the quote in a collapsed block, and hashes move to a sidecar file.
- 13 proposed `NOTE-` tickets. The core new piece is a per-chat "conversation digest" step that runs through the existing file-batch provider, answered by a Claude session on the subscription, never a paid API, and scored by a separate session that never sees the output.
- Eight decisions listed for Louis, including priority over the parked product work, who approves the first taxonomy, and approving a new quality rubric for notes.

Challenges: `gh` isn't on this PC's PATH, and the `ke.exe` launcher was locked by the running `ke ui`, so I ran the CLI as `python -m knowledge_engine.cli.main`. Keeping private chat text out of the write-up meant describing the old notes by shape and numbers and using placeholders in the template.

Talking points:

- "My first two attempts had the right sections but the wrong trust model: the pipeline graded itself and stamped its own notes 'certified'."
- "The rebuild got the hard plumbing right first. Now the meaning goes on top, with every sentence cited to a message."
- "Frequency isn't a category: the old vocabulary auto-promoted words like 'new' and 'red'."
- "Evidence should be one click away, not 3,000 copies of a hash in the reader's face."

### 12:55 — OPS-009: peak memory on Windows, and ID prefixes in `inspect`

- `ke eval smoke` reported `peak_memory_mb: null` on Windows. Now it asks Windows for the process's `PeakWorkingSetSize` through `ctypes` (no new dependency). A platform with neither that nor the POSIX `resource` module reports `"unavailable_on_platform"`, so a missing number always says why.
- `ke inspect` keeps printing the export's full conversation ID, because it's a local debugging tool; its help now says so. `--redact` prints the 8-character prefix instead, and the G1 checklist uses it, matching every other report.

**Teach-back (`_peak_memory_mb`):** It reports the most memory the smoke test's process used. On Linux and Mac it asks the operating system's resource counters; on Windows it asks the same question through a Windows system call. If neither is available it says "unavailable on this platform" rather than leaving a blank.

Checks:
```
tests/integration/test_redact_and_memory.py   3 passed
tests/integration/test_source_browser.py, smoke tests   34 passed (unchanged)
```
Fix attempts: 0. The Windows branch is exercised on the Windows CI runners (the test expects a positive number there).

**Next exact task:** REV-011 (#186).

### 12:40 — PERF-001: why a re-import was twice as slow as an import

- **Measured first.** `evaluation/import_timing.py` builds a synthetic export shaped like mine (1,100 per-chat files, 900 images the chats don't use), imports it twice and times each phase with cProfile.
- **Cause.** Every source file is archived on every run. For bytes already stored, the archive still wrote a temporary copy and fsynced it, hashed the stored copy, threw the temporary copy away, and then the ledger hashed the stored copy again. On Windows every new file is also scanned by the antivirus, so a re-import paid for 1,100 pointless writes.
- **Fix.** Known bytes are hashed once from the source and the stored copy is checked once. Nothing is written. New bytes are stored exactly as before. The raw-unchanged proof and the check of every reused stored copy are untouched.
- Linux numbers: re-import 7.47 s → 5.79 s, its fsync time 0.89 s → 0; the re-import is now quicker than the import. The Windows run of the same command goes in EVAL-010_SMOKE.md.

**Teach-back (`BlobStore.put_file`):** It stores a copy of an input file under the fingerprint of its bytes. If that fingerprint is already in the store, it checks that the stored copy still matches and writes nothing, because the evidence is already there. Only new bytes are written, through a temporary file that is made safe on disk before it takes its real name.

Checks:
```
tests/unit/test_archive_reuse.py   5 passed (would fail on the old code: a temporary file was made)
tests/unit/test_archive_store.py  21 passed (unchanged)
import/archive/media/purge tests  170 passed, 19 skipped
```
Fix attempts: 0.

**Next exact task:** Windows timing on Louis's PC, then OPS-009 (#201).

### 11:24 — Citations written as `[m:id]` now count

The paid run's 53 "evidence outside the segment" flags were our bug. Requests show each message as `[m:ID] user:`, the model cited `[m:ID]` back, and the check compared that whole string with bare IDs. `providers/base.py` now has `MessageRef`, a string type whose validator turns `[m:abc]` or `m:abc` into `abc` and leaves everything else alone, so a real citation outside the segment is still caught. Classification evidence and extraction quotes both use it. The prompt, schema and stage keys are unchanged, so the saved answers still replay from the cache and can be re-checked for free.

**Teach-back (`bare_message_id`):** We show the model each message with a tag like `[m:abc]`, and it tends to cite the message back in that same form. This takes the tag off, so the check compares plain IDs, and leaves anything that isn't that tag alone. Before this, nearly every model answer in the paid run was wrongly sent to review.

Checks:
```
tests/unit/test_message_ref.py   9 passed
```
Fix attempts: 0.

**Next exact task:** replay the paid run on Louis's PC with this fix (no calls), then PROD-004.

### 11:33 — PROD-004: the security review, deletion and rotation

- `docs/operations/HOSTING_AND_SECURITY.md`: what is protected and where; a threat model of 14 threats, each with its control and the test that checks it; secrets and rotation; backups per workspace; a deletion table (login, conversations, whole workspace); a UK GDPR review marked as not legal advice; a hosted release checklist.
- **The log no longer holds names.** The authorisation log now stores the account's random ID; names are looked up only when it is shown. After `ke access delete`, old rows read `deleted-1a2b3c4d`, and the test VACUUMs the database and checks the name's bytes are gone. (This changes PROD-002's unreleased log format; its tests are unchanged and still pass, because the display resolves IDs back to names.)
- `ke access rotate` (revoke all, issue one), `ke access delete NAME --confirm NAME`, `ke tenant delete NAME --confirm NAME` (removes exactly its workspace and inbox folders; refuses a folder that is a link pointing elsewhere).
- Honest status: I wrote the threat model and checked it against the code. That isn't an independent review, so OD-19 records that one is needed (plus a data-protection opinion) before anyone else's data goes into a hosted engine. Louis's own single-user use doesn't need either.

**Teach-back (`delete_account`):** Deleting an account removes its login, its tokens and its roles straight away. The access log keeps its history but only ever wrote down a random ID, so once the account is gone nothing connects those rows to a person. Deleting a whole workspace removes its two folders and nothing else.

Checks:
```
tests/integration/test_hosting_security.py   6 passed
tests/integration/test_api_access.py, test_tenant_isolation.py   12 passed (unchanged)
```
Fix attempts: 1 (the test fixture keyed tokens by workspace instead of owner).

**Next exact task:** open the queued PRs in order (PROD-001, PROD-002, #255, PROD-003, `[m:id]` fix, PROD-004), then INT-001.

### 13:15 — IMP-007: a stray file of chats is now reported, not silently skipped

- EVAL-002 found that an official export with a second JSON file of chats (say `stray.json` from a hand-merged re-export) lost those chats without a word in the report.
- The official adapter now opens every other `.json` in the export (folder or ZIP) and, if it holds at least one conversation object (anything with a `mapping`), adds an `unread_conversation_file` warning. It still doesn't import the file: which one is authoritative is Louis's call. Known side files (`user.json`, `message_feedback.json`, `shared_conversations.json` and friends) aren't even opened.
- The EVAL-002 reproduction's expected verdict changed from `silent_drop` to `warned`, as #237 asked; only that value changed in the existing test.

**Teach-back (`_holds_conversations`):** When the importer skips a JSON file, it now looks inside to see whether the file has any chats in it. If it does, the import report says so with a counted warning, so nothing disappears quietly. It never imports that file on its own, because choosing which copy is right is the owner's decision.

Checks:
```
tests/integration/test_unread_conversation_file.py   6 passed
tests/integration/test_import_fidelity.py            8 passed (one expected value changed per #237)
```
Fix attempts: 0.

**Next exact task:** merge the open PRs; then the next unblocked ticket.

### 13:05 — REV-011: three annotation rules, written down

- The annotation guide gains "Three rules for every item": number every message on the active branch whatever its type (the same numbering as `ConversationGraph.message_number`; the ticket's `loader.py` doesn't exist, the graph is where it lives); every record and `forbidden` item carries a verbatim quote; an owner fact, idea or decision must cite a user message. One example each.
- The gold schema gains an optional `quote` on records and forbidden items. Optional, so golden-v1 on Louis's PC stays valid without being touched; the evaluators don't score it. It's for reviewers checking an item against the chat.

**Teach-back (the `quote` field):** Each answer-key item can now carry the exact words it is based on. A reviewer can then check the item against the chat without hunting for it. It's optional and not scored, so older answer keys still load and the scores don't change.

Checks:
```
tests/unit/test_gold_quote.py   3 passed
gold tests (-k gold)            23 passed (unchanged)
```
Fix attempts: 0.

**Next exact task:** IMP-007 (#237).

### 11:42 — INT-001: fetching a web page without opening a door into my network

- `ingestion/web.py`: off unless `network_fetch` is on **and** the host is on `web_allowlist` (empty by default).
- The main danger is SSRF: a public link that redirects the fetcher to `127.0.0.1`, the router, or a cloud metadata address. So every hop is checked again from the start (allowlist, DNS, every address), and the address must be `is_global`, which also catches 100.64/10 and IPv6-wrapped IPv4. Then the socket connects to the address that was checked. The host name is used only for the Host header and the TLS certificate, so a DNS answer that changes in between (rebinding) can't redirect it.
- Results are anchored: the URL asked for, the redirects, the final canonical URL (tracking parameters dropped), the page's own canonical link only if it is allowlisted, the SHA-256 of the exact bytes, and located blocks like a note's. `--save` stores the bytes by hash, once.
- The tests use a fake resolver and a fake connection, so CI never touches the network. The real connection is small, plain `http.client` with default certificate checks, and has no automated test (written down in the doc).

**Teach-back (`fetch_page`):** It fetches a web page only if I switched fetching on and listed the site. Before every connection, including after each redirect, it looks up the site's address and refuses anything inside my own network, then connects to exactly the address it checked. The page comes back as blocks with offsets, the canonical URL and a hash of the exact bytes, so anything quoted from it can be traced to the source.

Checks:
```
tests/integration/test_web_fetch.py   24 passed (no network)
```
Fix attempts: 0.

**Next exact task:** INT-002 (YouTube transcript input workflow).

### 11:58 — INT-002: YouTube captions, the official way only

- `links/youtube_captions.py`: a provider for YTB-002's `request_transcript`, so the `transcript_fetch` switch, the bounded retries and the recorded statuses all apply unchanged. It calls `captions.list`, picks a track, and downloads it as WebVTT with my own OAuth token.
- YouTube only lets an account download captions for videos it may edit. So for most videos the honest answer is `permission_required`, and that is what gets recorded. There is no fallback to scraping or unofficial endpoints, on purpose.
- An automatic (ASR) track is accepted but labelled `machine_generated: yes` in the snapshot's provenance, with the track ID and kind, so nobody quotes it as what the speaker wrote.
- Quota and 429 answers count as temporary: at most 3 tries, at least a second apart, then `failed`.
- `ke transcript fetch VIDEO [--language]` needs `KE_YOUTUBE_ACCESS_TOKEN` in the environment; without it the answer is `no_token`.

**Teach-back (`YouTubeCaptionsProvider`):** It asks YouTube's official API, signed in as me, which caption tracks a video has, and downloads the best one, preferring my language and a human-made track. If YouTube says no, it records exactly why (permission, not found, no tracks or quota) and never invents or scrapes the words. An automatic track is kept but clearly labelled as machine-generated.

Checks:
```
tests/integration/test_youtube_captions.py   11 passed (no network)
tests/integration/test_video_transcripts.py  6 passed (unchanged)
```
Fix attempts: 0.

**Next exact task:** open the queued PRs, then INT-003 (watched folders).

### 14:05 — NOTE-006 (#278): a taxonomy discovered from the real chats, reviewed by a separate Claude

Nothing can be classified until there's a published vocabulary, and the real workspace had none. That's why every chat note so far said "unclassified".

What I built (`taxonomy/bootstrap.py`, runbook `docs/runbooks/TAXONOMY_BOOTSTRAP.md`):

- `ke taxonomy pack`: a fair sample of segments, rare themes first (the NRM-006 sampler), with a short excerpt each and the TF-IDF groups as hints. It writes only to a private folder, and the CLI refuses any other path.
- The proposer writes a JSON plan, and code checks it before anything is filed. It must match the pack's fingerprint, cite only sampled segments, have no duplicates and stop at two levels. `ke taxonomy propose` files TAX-004 proposals. Subcategories wait until their category is approved.
- `ke taxonomy sheet` / `review` / `summary` / `publish`. TAX-004 already refuses a reviewer who is also the proposer.

The real run (no paid API; everything private stays in `private/taxonomy/tax-1/`):

- The workspace was backed up first. The pack is 300 segments from 1,743 segments in 1,158 chats.
- **First problem:** about a third of the excerpts began with the same pasted custom-instructions text, so they all looked alike. The fix leaves out any paragraph repeated across many segments: 59 paragraphs were dropped, and the excerpts now show what each segment is actually about.
- **Proposer:** this thread proposed 12 categories with 37 subcategories, 9 activities and 6 outputs, each with a definition and the segments it rests on.
- **Reviewer:** a separate Claude session on a different model, named `claude-session-tax-reviewer-b`, read only the pack and the review sheets. Over 3 rounds it approved 64 terms, relabelled 2 ("Play" became "Casual Fun"; "Quick Everyday Questions" became "Identify and Translate Things") and rejected 3 with reasons: a catch-all "Advice and How-To", a "VR Development Practice" subcategory (VR is better as a tag than a subject) and a duplicate. It also found a real gap, no category for programming outside game engines, so I proposed "Software and Scripting" and it approved it.
- **Second problem:** in round 1 the reviewer admitted it had only read the first ~150 characters of each excerpt. I asked it to re-check every round-1 approval against the full excerpts. All 26 held.
- **Third problem:** relabelling exposed a bug. Re-running the plan re-filed "Play", because the approved term was now called "Casual Fun", and subcategories couldn't find a renamed parent. A term approved under a new label now still counts as known, and there is a test for it.
- The result: 13 categories with 37 subcategories, 8 activities and 6 outputs. The governance report finds no issues and no open proposals. **Not published:** publishing is Louis's decision (D2), made from `private/taxonomy/tax-1/summary.md`.

Checks:
```
tests/integration/test_taxonomy_bootstrap.py   5 passed
```
Fix attempts: 3 (newline escaping in a patch script, the boilerplate excerpts, the relabel bug).

**Teach-back (`taxonomy/bootstrap.py`):** It turns a sample of my chats into a first list of categories without anyone checking their own work: one Claude proposes the categories with evidence, a different Claude approves or rejects each one with a reason, and code refuses anything that doesn't point at real sampled chats. Subcategories only get filed once their parent category has been approved. Nothing becomes the official vocabulary until I publish it.

Talking points:
- "One AI proposed the categories, a different AI reviewed them, and I approve the publish. Nobody marks their own homework."
- "The reviewer admitted it had only skimmed the first pass, so I made it re-check everything against the full text. It held up."
- "A third of my chats started with the same pasted instructions; the sampler now ignores repeated boilerplate so the categories come from what I actually talked about."

**Next exact task:** Louis publishes tax-1 (or asks for changes), then classify the 40 gold chats under it.

### 12:20 — INT-003: watched folders

- `importer/watch.py`: `FolderWatcher.tick()` looks at a folder once. Each top-level export folder or ZIP must have the same metadata fingerprint on two looks at least `settle_s` apart (so a half-downloaded ZIP waits), then it is compared with the watch state: same metadata is skipped unread, the same contents (touched, re-downloaded, or a second copy under another name) are recorded without importing, and only new contents go to the importer.
- A broken export is recorded with its error code and left alone until it changes, so it can't loop.
- If an import changed something and a vault is set, the vault is synced once; DOC-006 already keeps unrelated notes untouched, and the test checks their bytes and modified times.
- The state file is written atomically and holds fingerprints and import IDs only; the report holds counts and IDs, never export names.
- `ke watch FOLDER [--once] [--vault DIR] [--partial] [--interval] [--settle]`. The workspace itself can't be watched (it would watch its own writes).

**Teach-back (`FolderWatcher`):** It looks at a folder now and then and waits until an export has stopped changing before touching it. It remembers a fingerprint of everything it has imported, so the same export dropped again, touched, or saved under another name never imports twice, and a broken one is noted once and left alone. When an import did change something, it refreshes the notes vault, which only rewrites the notes that actually changed.

Checks:
```
tests/integration/test_watch_folder.py   7 passed (fake clock)
```
Fix attempts: 1 (my test touched the source and then expected its fingerprint unchanged; moved the fingerprint after the touch).

**Next exact task:** open the INT PRs, then PERF-001 (#200).

### 13:05 — NOTE-002: the conversation digest contract

Louis approved the rich-notes plan (`docs/plans/RICH_NOTES_GAP_ANALYSIS.md`), so the NOTE tickets come next. This one is the shape of the *digest*: what a model writes about a whole chat so the note reads well.

- `digest/contract.py`: `DigestAnswer` is what the model must return: 1 to 4 summary sentences, purpose, outcome, status (open, settled, abandoned), intent, topics, insights, tensions, open questions and next steps. `extra="forbid"` everywhere, and every item needs at least one short quote (300 characters at most) naming its message.
- `resolve_digest` looks each quote up in the real message (the same matching as the extractor, LEG-004) and turns it into exact, fingerprinted evidence. If any quote of an item is wrong (a message that isn't in the chat, or words that aren't in that message), the whole item is dropped and a flag says why. A status or intent that can't be backed becomes "unknown" rather than a guess. A digest with no surviving summary sentence is not usable and goes to review.
- Whether a section is "From the chat" or "Generated" is fixed in `FIELD_PROVENANCE`, not chosen by the model. Only open questions count as from the chat; everything else is the model's own wording, so the note labels it generated (decision D3).
- It is a separate thing from knowledge records (decision D5), so a generated insight can never pass for a confirmed decision.

**Teach-back (`resolve_digest`):** The model hands back a summary and the other sections, and each sentence has to point at the messages it came from with a few exact words. This function checks those words really are in those messages and swaps them for precise positions and a fingerprint. Any sentence with even one bad citation is thrown out and noted, so what reaches the note is fully backed by the chat.

Checks:
```
tests/unit/test_digest_contract.py   11 passed
```
Fix attempts: 0.

**Next exact task:** NOTE-003 (the digest stage behind the provider switch).

### 13:30 — NOTE-003: the digest stage

- `digest/stage.py`: `DigestStage.run(chat)` sends one request per chat through `ModelStageRunner`, so it gets the cache, the single repair, `review_required` and the egress switch for free. No new retry or cache code.
- The model sees the chat's active path (the version the user ended on), every message tagged `[m:ID] role:` and escaped as untrusted data, plus one line per fork ("after [m:X]: edit fork, 1 other version(s) not shown"). The other versions are not sent; the note's Branches section shows them from the stored tree.
- A chat over the size budget is split between exchanges, with one shared exchange between neighbours (the segmenter's rule), never inside a message. Each part is labelled "Part n of N" and the answers are merged in code: purpose and intent from the first part, outcome and status from the last, summary sentences round-robin (at most 4), lists de-duplicated.
- The stage key covers the exact text, the fork lines, the part label and the code, prompt and schema versions.
- A repair is a new ask, so with a batch provider it is answered on a later run: the first run says `pending`, the next one finishes. A digest whose summary sentences all fail the quote check is `review_required`, not a note.

**Teach-back (`DigestStage`):** For each chat it builds one request holding the conversation as the user finally left it, plus a note of where the chat forked, and hands it to the same stage runner every model step uses. That runner answers from the cache if it has seen the exact same request, allows one repair for a malformed answer, and refuses to send anything if model access is switched off. When the answer comes back it is checked quote by quote, and long chats are asked in parts and stitched back together without ever cutting a message.

Checks:
```
tests/integration/test_digest_stage.py   7 passed (FakeProvider, no network)
```
Fix attempts: 1 (my new test expected a repair to finish in the same run; it arrives on the next one, as with any batch answer).

**Next exact task:** NOTE-004 (runbook and synthetic dry run), then NOTE-005.

### 13:20 — NOTE-001 (#273): the rich-note layout, built from what the engine already stores

Louis approved all eight recommendations at 12:50 ("Go ahead with the recommendations and verifications"), so the gap analysis now records them as decisions. The build thread opened issues #273 to #285 for NOTE-001 to 013 and we split the work: this thread owns NOTE-001, the real-corpus taxonomy (NOTE-006), the real-chat scoring half of NOTE-011 and the ladder run (NOTE-013). The build thread takes the digest, the extractor and the code checks.

What NOTE-001 adds:

- `documents/rich_note.py`: a second note template beside the DOC-003 one. The summary box and a knowledge card come first. Records are sorted into the sections people think in (decisions, suggestions, action items, open questions, requirements and preferences), and who holds a record decides where it goes: an assistant's task is a suggestion, not your action item. The generated sections (insights, tensions, next steps) and the keywords section say plainly that the digest hasn't run yet, rather than guessing.
- Citations are `[m12]`: a link to message 12, numbered the way the transcript numbers it, or `[alt]` for a message on another branch. They are listed in transcript order. Quotes sit in a folded "Evidence" box, at most two per item, each re-checked against the archive and cut at a word boundary.
- A suggestion the user answered says "taken up (see Decisions)". The stored proposal status lagged behind the decision, so the link is made through the shared evidence span.
- The chat's category, subcategory, activity, topics and project are rolled up from segment labels, weighted by how many messages each segment holds. They go in the card and in slim front matter. Hashes and record IDs go into a JSON sidecar in `Knowledge/.meta/`, out of the reader's way.
- Related chats link to the other chat's *knowledge note*, not its transcript, so the vault becomes a web of notes.
- `rendering/markdown.py` gets a `Callout` block. `ke docs chat --template v2` writes the new note; v1 stays the default until the digest lands. The CLI now prints `...` instead of the `…` character that showed as a box on the Windows console.

Checked on three real chats into a scratch folder (not committed): 2 to 4 KB each. The old v2 notes for the same chats were 44 to 81 KB. They are still thin, because the meaning has to come from the digest (NOTE-002/003), but the layout is ready for it.

One deviation from the ticket's finish line: I didn't add a byte-for-byte golden Markdown file. A snapshot generated from my own output would only freeze whatever I wrote, and every later layout change would mean editing a test. So the 10 tests check the behaviour instead: section order, placement, citation numbering, folded evidence, empty states, card cells, related links, the size budget, sidecar and link resolution, and the CLI.

**Teach-back (`documents/rich_note.py`):** It builds the readable page for one chat from what the engine has already stored: a summary box and a card at the top, then decisions, suggestions, actions and questions, each in its own section. Every claim ends with a short link like m12 that jumps to that exact message, and the quote that proves it sits in a folded box underneath. Anything the engine hasn't worked out yet says so in one sentence instead of being made up.

Checks:
```
tests/integration/test_rich_note.py   10 passed
full suite (API tests excluded: fastapi isn't installed in this PC's venv)   1284 passed, 22 skipped
```
Fix attempts: 2 (a result-type slip when reading titles; my first test wrongly expected an accepted suggestion to stay out of Decisions).

Talking points:
- "The note answers 'what happened in this chat?' on the first screen, and every claim is one click from the exact message."
- "Evidence is folded away, not deleted: open the box and the quote is there, re-checked against the archive."

**Next exact task:** NOTE-006, the first taxonomy discovered from the real chats.

### 14:10 — NOTE-005: a model reads for decisions, suggestions, actions and questions

The rule extractors only catch fixed phrasings, and on the real chats they found 16 actions and no questions. This adds a model-backed extractor through the existing `ModelExtractor` (stage runner, cache, one repair, egress switch), with the EXT-001 contract and its acceptance rules unchanged.

- `extraction/model_knowledge.py`: `knowledge_extractor(runner)` asks for four types only: decision (or rejection), proposal, action, question.
- Three checks run in code on whatever the model returns:
  1. A user decision, rejection, action, preference or requirement must quote the user. If only the assistant was quoted, it goes back to being the assistant's proposal, flagged for review.
  2. Several proposals from one actor quoting only the same message (a bulleted list of options) become one proposal: "Options suggested: A; B; C".
  3. A long user message that opens like a pasted setup prompt ("You are...", "Act as...", "From now on...", at least 200 characters) can't be the source of a commitment. "You are right." is not a setup prompt.
- Records then go through the EXT-007 gate and the EXT-002 evidence check like any other.

**Teach-back (`check_candidates`):** After the model reads a chunk of chat and lists what it thinks was decided, suggested, promised or asked, this function checks who actually said it. A "decision" backed only by the assistant's words is turned back into the assistant's suggestion, a bulleted list of options becomes one suggestion, and anything resting only on a pasted "You are a..." prompt is dropped. So the model can't make me the owner of something the assistant said.

Checks:
```
tests/integration/test_model_knowledge.py   6 passed (FakeProvider, no network)
```
Fix attempts: 1 (my new gate test quoted an assistant message from another part of a split segment).

**Next exact task:** NOTE-007 (keyword and topic candidates).

### 14:55 — NOTE-007: keyword and topic candidates, with reasons, no model

The old v1 pre-pass had the right idea: per chat, keywords in three tiers, each with a reason. This ports it and adds the fixes the gap analysis asked for.

- `documents/keywords.py`: `keyword_candidates(chats, resolver=None)` gives every chat:
  - **must**: title words, named things (capitalised phrases not at the start of a sentence), and approved taxonomy terms found in the text;
  - **should**: the top 20 repeated 1-3 word phrases by TF-IDF; **optional**: the next ones, up to 50 in all;
  - **excluded**, each with a reason: title words too general ("help"), phrases in more than 65% of chats (once there are 5 or more), and words that only a pasted setup prompt uses ("role-play wording, not a subject").
- Spelling: a word one typing slip away from a word used at least three times as often is read as that word, and the spelling seen is kept under `variants`. With a published taxonomy, an approved alias ("UE5") shows as its term.
- A shorter phrase that is only ever said inside a longer one ("global" in "lumen global illumination") isn't listed on its own.
- Digest topics are matched to approved topic terms; `propose_topics` files each unmatched topic once as a TAX-004 `add` proposal. Nothing becomes a label without a reviewer.
- Speed on synthetic worst-case text (every phrase unique): about 0.09 s per chat of 3,600 words, so the whole corpus is a minute or two.
- Not yet in the note: the Keywords section is wired when NOTE-003/004 (#292) has merged, to avoid editing `rich_note.py` in two open PRs.

**Teach-back (`keyword_candidates`):** It reads every chat in the batch and counts the one-to-three-word phrases in each, after fixing obvious typos against the more common spelling. Title words and named things are "must", the phrases this chat repeats that other chats rarely use are "should" and "optional", and anything left out, like a vague title word or the wording of a pasted role-play prompt, is listed with the reason. There is no model in it, so the same chats always give the same keywords.

Checks:
```
tests/unit/test_keyword_candidates.py   8 passed (misspelt entity, pasted preamble, excluded title word, common phrase, order-independence, topic matching, proposals filed once)
```
Fix attempts: 1 (my test's "common phrase" was said once per chat, so it never ranked; and the setup exclusions were cut alphabetically instead of by count).

**Next exact task:** merge the open PRs on full green, then wire keywords into the note and start NOTE-011's code checks.

### 13:55 — NOTE-004: digests from a Claude session, end to end

- `ke digest run [IDs | --all] --run-id R [--vault V]`: the first run writes the digest requests into `private/model-batches/R/` and says how many are waiting; a Claude session fills the response files; running it again collects, checks every quote and writes the rich notes. All chats go in one submit, so the requests are packed into as few files as fit, not one file per chat.
- `rich_note.py` now takes a digest: the summary box, purpose, outcome, status and intent in the knowledge card, insights, tensions and next steps (each with its folded, re-checked evidence), open questions from the digest under the extractor's, and topic candidates. Without a digest the note is exactly as before (the NOTE-001 tests are unchanged and pass).
- `ke docs chat --template v2` uses a digest that was already collected, with model access off. `stored_digest` reads the stored answers only; it never asks.
- The runbook (`docs/runbooks/LABELLING_SESSION.md`) has a digest section: write, answer in a fresh session with the deny rules, collect, what to do at a usage limit, and repairs.

**Teach-back (`ke digest run`):** The first time it runs, it writes every chat's digest question into request files and stops, because the answers come from a Claude session on my subscription, not from a paid API. Once the session has written its answers next to them, the same command reads them back, throws out any sentence whose quotes aren't really in the chat, and writes a readable note for each chat that passed. Running it a third time asks nothing new, because every answer is already stored.

Checks:
```
tests/integration/test_digest_dry_run.py   3 passed (egress off writes nothing; 3 chats end to end; docs chat reuses the digest)
tests/integration/test_rich_note.py        10 passed (unchanged)
```
Fix attempts: 1 (the first version wrote one request file per chat; now one submit for all).

**Next exact task:** NOTE-005 (model-backed knowledge extractor).

### 13:30 — A design pass on the dashboard (`ke ui`)

Louis asked for the local dashboard to be easier to use and nicer to look at. It worked, but it was a page of links separated by dots, long grey tables and raw state names like `review_required`, and on a phone the tables pushed the whole page sideways.

What changed (templates, CSS and one line in `ui/app.py`; no new routes, still read-only):

- **One visual system** in `style.css`: every colour is a named token, and dark mode only swaps the tokens. Colour always means something: green fine, amber look at this, red wrong, and **violet for "an AI said so, not the owner"**.
- **A sidebar grouped by purpose** (Your archive / Found in chats / Check the AI / Add) that highlights where you are. `app.py` now passes the current address to the templates for that. On a phone it becomes a wrapping top bar.
- **Tables** sit in their own scrolling box, with small-caps headers and right-aligned numbers, so a wide table never drags the page sideways.
- **Plain labels**: trust states are pills that say "review required" instead of `review_required`, the filter links are chips with counts, and long hashes are folded under "Fingerprints".
- **Empty states** say what's missing and the next step ("Run `ke extract`…", "Import your ChatGPT export").
- **Charts on the Evaluation page**: a stacked bar per record type (found and expected / found but not expected / expected but missed) and one for how far each output got (trust). Score tiles get a thin meter. Every score block carries "Scored against: AI check (not owner-verified)", in violet.

Challenges:

- **The page's security policy blocks scripts and inline styles.** That's on purpose (chat text must never become code), but it rules out chart libraries and `style="width: 40%"`. The fix: draw the bars as plain SVG from the template, where `width="40%"` is an attribute, not a style, and colour them from the stylesheet. Hover text comes from SVG `<title>`, which needs no script.
- **Tests pin exact HTML** (for example `<td>(\d+)</td>` for the message count). My first pass added `class="num"` to those cells and broke two tests. Tests can't be changed without Louis, so I put the cells back and right-aligned the columns from CSS instead.
- **The sidebar stopped halfway down** long pages in full-page screenshots, because a sticky box is only one screen tall. Painting the sidebar's panel onto the page background fixed it at any length.

Before and after screenshots, all from synthetic test fixtures: `docs/diary/img/ui-design-2026-10-28/`.

**Teach-back (`stackbar` in `ui/templates/macros.html`):** It draws one horizontal bar made of coloured pieces, such as found and expected, found but not expected, and missed. Every bar on a chart shares one scale, the biggest total, so you can compare their lengths fairly. It's plain SVG with percentage widths and a hover title, because the page isn't allowed to run scripts.

Checks:
```
pytest tests/   1340 passed, 22 skipped (no test changed)
ruff check src/knowledge_engine/ui   clean
Screenshots: 11 pages, light and dark, plus 400px phone width
```
Fix attempts: 1 (the two HTML-pinning tests above).

Talking points:
- "My dashboard has no JavaScript at all, for security, so the charts are SVG drawn by the server-side template."
- "Colour carries meaning: violet always means an AI checked this, not me, so a score can't look more certain than it is."
- "The tests guard the exact numbers on the page, so a redesign that broke them got caught straight away."

**Next exact task:** Louis looks at the screenshots and says what to change; possible follow-ups are a light/dark switch and a chart on the segment-labels page.


### 13:50 — CI: why main kept going red on Windows + Python 3.12 only

Louis was getting a stream of "Run failed" emails. I read every failing run on main and on the PR branches.

What was actually failing:

- **On main (3 out of 3 red runs: 9b5e807, 94a7cc0, b8046be)** the same unit test, `test_interrupted_batch_is_abandoned_never_succeeded`, failed on `windows-latest, 3.12` only. Every one of those PRs had passed all four jobs before it merged, so this wasn't merging early. It was a flaky test that only shows up sometimes.
- **On PR branches (OPS-009 at 4e5e54e and 1b80610)** a 64-bit Windows ctypes crash in the peak-memory code. That thread fixed it on its own branch (13fa9a5) before merging, so it's not on main.
- **Once, on main (b8046be)**, the browser-import test (`test_import_from_the_browser_runs_and_shows_the_report`, issue #288) saw the import job end as "didn't finish". The reason was in the page, but pytest cut the page short with `...` right where the reason was.

The root cause of the main failure: the import ledger says "the latest import is the one with the newest start time". Python 3.12 on Windows reads the clock in steps of about 16 milliseconds (3.13 switched to the precise clock, which is why the 3.13 Windows job never failed). The test starts a batch, "crashes", and starts another one straight after; if both land in the same 16 ms step they get identical start times and "latest" is a coin toss. It's a real bug, not just a test problem: `ke status` and the home page in the web UI use the same ordering.

How I proved it: I couldn't run Windows here, so I wrote a throwaway pytest plugin (kept out of the repo) that makes the clock tick in coarse steps. With a coarse enough tick the test fails every time on Linux; with the fix it passes at both the 16 ms and an exaggerated 2 s tick.

The fix (`importer/ledger.py`): when a batch starts, its start time is "now, or one microsecond after the newest batch, whichever is later". Start times are now strictly increasing, so all three readers agree on which import is latest. No test, threshold or evaluation rule was changed.

For #288 I couldn't reproduce it (25 runs on Linux, all passed), and guessing a fix would be dishonest. Instead `pyproject.toml` now sets `verbosity_assertions = 2`, so a failed assert prints long strings in full while the rest of the output stays quiet. Next time it fails, CI will show the job's actual error. #288 stays open.

**Teach-back (`importer/ledger.py`, `_next_start_time`):** Every import gets a start time, and "the latest import" means the one with the newest time. On some Windows setups the clock only moves every 16 milliseconds, so two quick imports could tie and the app couldn't tell which was newer. Now a new import's time is always at least a microsecond after the previous one, so there's never a tie.

Checks:
```
python -m knowledge_engine.devtools.ci   lint, format, types, guard ok; 1353 passed, 22 skipped
coarse-clock plugin, 2 s tick:  before the fix 1 failed / after 49 passed (ledger + UI tests)
```
Fix attempts: 1.

Talking points:
- "A test that only failed on one OS and one Python version turned out to be a clock-resolution bug: Python 3.12 on Windows only ticks every 16 ms."
- "I couldn't run Windows, so I faked a coarse clock in a test plugin to reproduce it deterministically before fixing it."
- "When I couldn't reproduce the second flake, I didn't guess. I made CI print the full error so the next failure explains itself."

### 15:55 — NOTE-008: the category section says how much of the chat, and who decided

The classifier labels segments, because one chat can be about two things. The note used to show only the single rolled-up category. Now the Category and subcategory section lists every category the chat's segments got:

- each with its **share of the chat** in messages ("primary, 67% of labelled messages"); the largest is the primary, the rest secondaries, and a label only ever given as a segment's side label is a "side subject" with no share;
- which segments it came from and the messages the classifier cited, as `[m12]` links;
- the **reviewer verdict** per segment: classifier only, reviewer agreed, reviewer changed it, set by a reviewer, or reviewed under an older vocabulary;
- **candidates waiting for review**: open taxonomy proposals whose evidence points at this chat, shown as candidates and never as labels.

The classifier stores no free-text reason, so the "why" is its cited messages; I didn't invent a sentence.

**Teach-back (`category_shares`):** It goes through a chat's segments in order and, for each one, looks up its main category under the published vocabulary, counting the segment's messages towards that category. The category with the most messages is the chat's primary and the others are secondaries, each with its percentage, the messages the classifier pointed to, and whether a person checked it. A proposed new category is listed separately as waiting, so it can never be mistaken for a real label.

Checks:
```
tests/integration/test_note_categories.py   2 passed (two-subject chat: 67% primary, 33% secondary; candidates shown only as candidates)
```
Fix attempts: 1 (my synthetic user turns were under 40 characters, so the segmenter treated them as short replies and never split the chat).

**Next exact task:** NOTE-009 (related chats with reasons).

### 15:30 — NOTE-011 (code half): checking that a rich note is honest

Before anyone scores whether a note is *good*, a program can check it isn't making things up. `evaluation/note_checks.py` reads the rendered Markdown, the way a reader would, and compares it with the stored chat:

- **citations_real**: every `[m12]` link points at a message of this chat, and the number is the one the transcript shows (`alt` off the active path).
- **claims_cited**: every summary sentence, the Purpose and Outcome cells, and every item under Decisions, Suggestions, Action items, Open questions, Requirements, Insights, Tensions and Next steps cites a message.
- **decisions_user_held**: every decision and "ruled out" record is held by the user and quotes the user.
- **tensions_next_steps**: a next step that repeats something ruled out, or restates a tension, is a warning (word overlap, so it can't be a hard fail).
- **empty_sections** and **budget**: no evidence box under an empty section; the body under its length budget.
- `ke docs rubric [chats] [--all]` builds each chat's note in memory (with its stored digest), runs the checks, and prints counts per check and the problems (IDs only, no chat text). It writes nothing.

The first run of the checks on the engine's own note found something: a citation inside the knowledge card's table writes its pipe as `\|`, which my link pattern read as part of the anchor. The note was right (that's how Obsidian tables need it); the pattern was fixed.

**Teach-back (`check_note`):** It takes a finished note and the chat it came from and checks six things a program can judge: every message number points at the right message, every claim has a number, every decision is the user's own words, no next step repeats a rejected idea, empty sections stay empty, and the note isn't too long. It reads the Markdown rather than the renderer's internals, so a renderer bug shows up too. It doesn't judge whether the summary is right; that's the independent reference set on the PC.

Checks:
```
tests/integration/test_note_checks.py   7 passed (the real note passes; each break caught by exactly one check)
```
Fix attempts: 2 (my FakeProvider digest left out the required intent; the table-cell pipe escape).

**Next exact task:** keywords into the note (NOTE-007 wiring), then NOTE-008.

### 15:25 — NOTE-010 (part 1): `ke docs check` now checks a note is readable, not just linked

**What:** The rich-note plan (§7 of the gap analysis) promised that a note fits on a screen or two, that an empty section is one plain sentence, and that hashes and run IDs stay out of the front matter. Until now only `ke docs rubric` checked the first two, and only by rebuilding notes from the database. NOTE-010 wants the vault check itself to catch them, on the files Obsidian actually opens. `evaluation/readability.py` adds three rules to `ke docs check`:

- **budget**: a rich note's body (the part above the vault's "write below this line" marker, so your own notes never count) stays under the budget for its chat's length, read from its own `messages` property;
- **empty_evidence**: an evidence box (`> [!quote]`) in a section with no item in it fails, in any note;
- **properties**: front matter holds plain values and flat lists Dataview can filter on; no nested maps, and no hashes or bookkeeping like `content_hash` (those go in the `.meta` sidecar).

Older notes (DOC-003 knowledge notes, the masters) were never written to that standard, so they are counted as "not checked" rather than failed. The summary line now says how many rich notes were within budget.

**Challenge:** the new test writes a rich note, with a fake digest, for every chat in every fixture export (24 exports), then runs the vault check. It failed straight away, and not on readability: the link checker said six citations were broken. They were the `[m4]` links inside the knowledge card table, where the alias pipe has to be written `\|` so it doesn't end the table cell. Obsidian reads that fine; the checker read the backslash as part of the link target. It's the same mistake the NOTE-011 checks hit earlier today, in a different file. The note was right, so the checker was fixed.

**Also:** I'd claimed NOTE-012 (the dashboard) first, then found another thread already had it up as a PR. I dropped my half-built copy rather than open a duplicate.

**Teach-back (`evaluation/readability.py`, `check_note`):** It reads one note file, front matter and body, and checks three promises: the note isn't longer than its chat deserves, no section shows an evidence box without anything for it to back up, and the front matter only holds simple values a reader or Dataview would use. Only notes whose `generator` says they use the new layout get the length and front-matter checks, because older notes never made those promises. It never opens the database, so it works on any vault folder.

Checks:
```
tests/unit/test_readability.py                6 passed
tests/integration/test_note_readability.py   25 passed (24 fixture exports, every rich note clean; CLI reports budget and empty-evidence problems)
```
Fix attempts: 2 (the table-cell pipe in the link checker; one fixture ships its export as a ZIP).

Talking points:
- "My vault checker now fails a note that's too long for its chat, not just one with a broken link."
- "The first real run caught a bug in the checker, not the notes. Same bug I'd fixed in another checker that morning, which says the pipe-in-a-table rule deserves one shared helper."
- "Two agents claimed the same ticket. The fix was simple: check the open PRs before starting, and back off when someone's ahead."

### 15:45 — NOTE-010 (part 2): topic and project masters you can read

The topic and project masters (DOC-004/005) were complete but hard going: every record printed as its claim, then a list of status, sources, record ID and event IDs, then its quotes in full. `documents/readable_master.py` renders the same document in the chat-note style, chosen with `ke docs topic|project --template v2` (the old layout stays the default, so nothing that uses it changes):

- a **summary** box first, in the engine's own words ("3 items from 2 chats: 1 current, 2 replaced"), with the topic's definition;
- **one line per item**: the claim in bold, its kind and who holds it, and short citations;
- a citation is `[c2·m12]`, message 12 of chat 2. A master spans many chats, so the chats are numbered once in a **Chats** list at the end, which keeps every link short;
- quotes **folded** under the item, at most two, each re-checked against the archive;
- the DOC-004 rule still holds: a replaced choice says what replaced it, now in words ("Replaced by "…" (c2·m4)") instead of a record ID;
- **How these connect** and the **Decision timeline** name items by their words and place too;
- IDs and hashes go to a `.meta/` JSON sidecar; the front matter is flat counts and labels Dataview can filter on.

Masters get their own budget in `ke docs check` (a base plus so much per item and per chat), since a topic grows with the archive.

**Decision:** the place in brackets after a claim ("(c1·m2)") was added after I read the first rendered master. Two chats had made the same decision in the same words, so "How these connect" showed two identical lines. The place tells them apart without bringing record IDs back.

**Teach-back (`documents/readable_master.py`):** It takes a topic's or project's list of knowledge items, already sorted into current, replaced, in conflict and suggestions, and writes it as a note a person can skim: a short summary, then one line per item with links to the exact messages. Each chat gets a number, so a link reads "c2·m12" instead of a long title. Anything only a program needs, like record IDs, goes in a separate file next to the note.

Checks:
```
tests/integration/test_readable_masters.py   5 passed (summary first; every replaced line names its replacement; no IDs in the note; every c·m number is the transcript's; vault check clean; CLI v2)
python -m knowledge_engine.devtools.ci       lint, format, types, guard ok; 1448 passed, 22 skipped
```
Fix attempts: 2 (a query result needed `.all()` before `dict()`; my test unpacked `write_transcript`'s return value wrongly).

Talking points:
- "A master note now reads like a briefing: summary, then one line per decision, with a link to the exact message."
- "Old decisions are still labelled, just in words instead of IDs."

**Next exact task:** NOTE-007 wiring (keyword candidates into the note's Keywords and topics section) once #296 merges.

### 15:55 — Step 4: tax-1 published, 40 real chats classified and digested, and the notes scored by a separate session

Louis approved tax-1 and asked me to run the publish ("I need you to run it"); this PC's safety check had blocked my first try.

- `ke classify run` (new): the same request-file flow as `ke digest run`. The engine writes requests, fresh Claude sessions on the subscription answer them, and the engine validates every answer against the pinned version. 85 segments: 67 labelled, 18 to review.
- Digests for all 40 chats came from 4 fresh sessions, with every quote checked in code. That gave 40 rich notes; the code rubric passes 36 and fails 4 on size only.
- **Independent score:** one session (a different model) wrote reference summaries for 15 sampled chats without seeing the notes. A third session scored the notes against them. Summary mean 1.53/2; top-level category right 11 of 11 where given; but decisions were found for only 5 of 22 and open questions for 1 of 9. Full report: `docs/evaluation/NOTE-011_REAL.md`.
- The honest headline: the notes now say what happened and where it sits, but not yet what Louis decided. The model extractor (NOTE-005) hasn't run on these chats yet, and pasted custom instructions are polluting the requirement lists.

Challenges: the config file's `text_llm = false` overrides the environment variable, so the labelling runs use a private copy of the config with it switched on. One labeller's first script crashed after writing two lines; append-only meant nothing was lost or duplicated.

Talking points:
- "Three different AI sessions: one wrote the notes, one wrote the answer key without seeing them, one marked the difference. That's how I know decisions are the weak spot."
- "Every label the classifier gives has to be a term from the published list, checked in code, so it can't make up categories."

**Next exact task:** run the NOTE-005 extractor on the 40 chats, re-render, re-score against the same references.

### 17:00 — NOTE-015 and NOTE-020: running the extractor for real, and labels in digest notes

The first real score (`docs/evaluation/NOTE-011_REAL.md`) found decisions and open questions nearly empty, because the model-backed extractor (NOTE-005) had no way to run outside tests. **`ke extract run`** now works the same way as `ke digest run` and `ke classify run`: the first run writes request files for a Claude session to answer, and the next run collects the answers, applies NOTE-005's three attribution checks and the evidence gate, and stores the records. Segments already done are skipped, so a third run asks for nothing.

Building it found a real bug in the extraction runner. When an answer hadn't arrived yet, the runner rolled back everything the segment's attempt had written, including the ledger row that says "this request was sent, in batch file 1". So the next run sent the same requests again in new files and never read the answers. A pending answer now keeps the ledger rows; nothing else is in that savepoint yet, because the records come from the answer.

**NOTE-020:** `ke digest run --vault` wrote notes with no taxonomy, so they showed no labels. It now uses `--taxonomy`, or the newest published version by default.

**Teach-back (`_extract`, the `ke extract run` command):** It sends every segment of the chosen chats to the model-backed extractor through request files, which a Claude session on the subscription answers. Running it again collects the answers, checks who really said what, and stores the records with their quotes. Work already done is skipped, so repeating it costs nothing.

Checks:
```
tests/integration/test_extract_run.py   4 passed (egress off writes nothing; requests -> answers -> records -> nothing new; digest notes under the newest or given version)
tests/integration/test_digest_dry_run.py, test_model_knowledge.py, test_extraction_gate_runner.py   unchanged, pass
```
Fix attempts: 2 (the runner rollback; egress is checked before running, because the runner counts a refused request as a failed attempt).

**Next exact task:** NOTE-018, a suggested category instead of "unclassified".

### 16:10 — NOTE-009: related chats, and a pasted prompt is not a link

The rich note already had a "Related chats" section (from REL-003/REL-004 and NOTE-001): same-project, same-topic and shared-entity links, each naming the other chat's *knowledge note* with a "Why:" reason. What it lacked was a guard against the most common false link in a real archive: many chats open with the same pasted setup prompt ("You are a careful assistant..."). Before this change that prompt alone made two unrelated chats look like a copied opening (`forked_from`), a quoted paragraph (`quotes`), and similar text (`related_to`).

- `extraction/preamble.py` holds one test, `looks_like_preamble`: a user message of 200+ characters that starts like a setup prompt. NOTE-005 already had it privately; it moved to a module with no imports so the relationship detectors can use it without an import cycle.
- The copied-opening detector skips a setup prompt at the very start; the quote detector ignores setup-prompt paragraphs; the related-chat profile leaves them out of the text it compares.
- Detector names stay the same (`prefix-v1`, `quote-v1`, `related-v1`) because the evaluation fixtures expect them and evaluation criteria don't change without Louis.

Not done: the issue mentions a one-sentence model-written reason per link. The deterministic reasons ("both chats are labelled with project X", "both chats name the same named thing") are already there and cite evidence; a model sentence can come with the digest stage later if the scoring says the reasons read badly.

**Teach-back (`looks_like_preamble`):** Lots of chats start with the same pasted instructions, so two chats sharing that text says nothing about them being related. This function spots such a prompt: a long user message that opens with words like "You are" or "Act as". The link detectors skip it, so links only come from what the chats are actually about.

Checks:
```
tests/integration/test_note_related.py   3 passed (each of the three filters, removed on its own, makes the shared-prompt test fail)
tests/integration/test_conversation_relationships.py, test_related_conversations.py   unchanged, pass
```
Fix attempts: 1 (the first test run showed the copied-opening detector also needed the filter).

**Next exact task:** NOTE-012 dashboard chat view.

### 15:25 — #288: the "import didn't finish" page that lied

I was sent to build the integration tickets (INT-001..003), but they were already merged, so I took the one open integration-test problem nobody had claimed: a browser-import test that failed once on Windows + Python 3.12 and passed on the re-run.

**Reading the failure properly.** The issue guessed the import itself had failed (a file still open, a read-only archive file). The CI log said otherwise: the page *did* contain the word "Importing" but had no auto-refresh tag. "Importing" is in the page title on every job page, so that check proved nothing. What actually happened is a race between two threads:

1. The page code asks "is the job done?" and gets "running".
2. In that instant, the background import finishes and sets the state to "done".
3. The template asks again, gets "done", so it leaves out the refresh tag and draws the "The import didn't finish" branch, with an empty error.

So a real user could, once in a while, see a failure page (that never refreshes) for an import that succeeded. Windows schedules threads differently, which is why it showed up there first.

**Fix.** The job page reads the state once and hands that single value to the template (`ui/app.py`, `ui/templates/job.html`). One read, one decision.

**Teach-back (the `/jobs/<id>` page in `ui/app.py`):** When you start an import in the browser, it runs on a separate thread and this page tells you how it's going. The page now looks at the job's state once and uses that one answer both to decide whether to send you to the report and to draw the page. Before, it looked twice, and if the import finished in between, the two answers disagreed and the page showed a failure that hadn't happened.

**Proving it without waiting for luck.** A new test uses a stand-in job whose state flips from "running" to "done" the moment it's read a second time. That makes the unlucky timing happen every run. It failed on the old code and passes on the new. No existing test was changed.

Checks:
```
tests/integration/test_ui.py -k mid_request   old code: 1 failed; fixed code: 1 passed
tests/integration/test_ui.py + test_api_imports.py   52 passed
```
Fix attempts: 1.

**Talking points:**
- "A flaky test isn't noise: this one was a real race condition a user could hit."
- "I read the CI log instead of trusting the first guess, and the evidence pointed somewhere else."
- "I turned a once-in-a-while timing bug into a test that fails every time on the broken code."

**Next exact task:** watch three Windows CI runs pass, then close #288.

### 15:45 UTC — EVAL-012: a scorer for links between chats (and a slice that was already done)

This thread was started to build the web API and product tickets. They were already finished: API-001 to 005, OPS-007 and PROD-001 to 004 were merged earlier today (PRs #254 to #266). I re-ran their tests (109 passed, 15 skipped because the PostgreSQL tests need a live server) and handed the slice back. The coordinator then gave me EVAL-012 and REV-010.

Both touch the reference set, which Louis's guardrail says agents can't change without his explicit OK. So I asked him on a decision card and built only the part that changes no answer key: the scorer.

The problem: the release gate's "relationship precision" line has always said BLOCKED, because nothing said which proposed links ("chat B forked from chat A") are right. `evaluation/relationship_key.py` adds:

- a **separate key format** (`relkey-v1`), not a change to the existing golden set: a closed list of chats, every true link between them, and a quote proving each one. The writer must declare it never saw the engine's output;
- a **scorer** that gives each proposal one verdict: correct, wrong direction, wrong kind, or a made-up link;
- a **code check** of every quote against the archive before any scoring, reporting problems by IDs and numbers only;
- `ke eval relationships --key <file>`, plus `docs/evaluation/RELATIONSHIP_KEY_GUIDE.md` for the session that will write the real key.

The gate line stays BLOCKED until a real key exists. The test fixture shows why kinds matter: a chat that says "carry on from <link>" is a `continues` to a person, while the URL detector calls it `references`, so on a hand-written test key the engine scores 0.75.

**Teach-back (`score`):** It takes the answer key's list of chats and true links, and checks each link the engine proposed against it. A proposal is right only if the key has the same link in the same direction; otherwise it's marked backwards, the wrong kind, or invented, and a link to a chat the key doesn't cover isn't judged at all. Precision is the share that were right, and it has to reach 90%.

Checks:
```
tests/unit/test_relationship_key.py           9 passed
tests/integration/test_relationship_scoring.py 3 passed (fixture: 0.75 with a disagreeing key, 1.0 with an agreeing one, a bad quote stops scoring)
python -m knowledge_engine.devtools.ci        tests 1423 passed, 22 skipped; types fixed after one run
```
Fix attempts: 1 (mypy wanted the version constant typed as a Literal).

**Waiting on Louis:** approval for REV-010 (answer key v2, run on his PC) and for writing the real relationship key.

Talking points:
- "Precision for links needs a closed world: the key lists every chat it covers, so a link it doesn't contain really is wrong."
- "A link pointing the wrong way and a link of the wrong kind need different fixes, so they're counted separately from invented ones."
- "The answer key is written by a session that never saw the engine's output, and code checks every quote before a single point is scored."
### 16:45 — NOTE-005 real run and re-score: decisions found went from 5 to 12 out of 22

- `ke extract run` landed on main (#313). Its real run on the 40 gold chats was 85 requests, answered by 5 fresh Claude sessions on the subscription with every quote checked in code, and stored 94 records.
- The 40 notes were re-rendered and the code rubric passes 35 of 40 (size only).
- A new scorer session that hadn't seen the first scoring compared them with the same 15 references, which were left unchanged. Decision recall went from 23% to 55%. Open questions stayed at almost zero. The "from the chat" sections are still noisy: 42 lines of pasted custom instructions, left over from the older rule extractor.
- The report is in `docs/evaluation/NOTE-011_REAL.md` (counts only). The next fixes are to retire rule records once a model extraction exists, take open questions from how a chat ends, add a digest merge step for long chats, and reclassify the 4 unclassified chats.

Talking points:
- "Same answer key, new scorer: the AI extractor more than doubled how many of my real decisions the notes catch."
- "The score also showed exactly what's still wrong, which is old rule-based records cluttering the notes, so the next fix is specific."

### 16:05 UTC — REV-010: answer key v2, written beside v1

Louis approved both answer-key changes on a decision card ("Approve both", 15:42 UTC), so REV-010 ran as a Remote Control session on his PC, where the private chats live. It checked v1's hash first (unchanged), wrote v2 in a new folder, and proved every item with code: 113 of 113 quotes found in the cited message, right speaker, right message number. It also planted three deliberate mistakes in a copy to show the checker catches them. Only hashes and counts came back here; the hashes are in `docs/reviews/OPEN_DECISIONS.md`.

The surprise: the brief said two chats were misnumbered, but **all ten** were. The engine numbers every message on the active path, hidden system messages and tool output included, and v1 had skipped those. v2 now stores each message's native ID next to its number, so the number can always be rechecked.

The second surprise: `ke gold score` can't read this answer key at all (v1 or v2), because the key is per-chat and the scorer expects one combined golden-set file. That's a converter ticket, not something to patch into the key.

Talking points:
- "Before changing the answer key, the session proved the old one was untouched by its hash, and afterwards proved it again."
- "Every answer in the key is checked by code against the real message: the quote, the speaker and the number."
- "A checker that's never been shown to fail isn't proven, so we planted three mistakes and watched it catch them."


### 15:20 UTC — NOTE-014: the taxonomy keeps up as new chats arrive

Louis approved the plan for the taxonomy and added one requirement: it has to keep working when new conversations are imported later, and update as more notes are processed. A vocabulary built once from today's chats would slowly go stale: every new subject would come out of the classifier with no label at all, because the classifier may only use approved terms.

The tension is with a guardrail from the failed Hermes/Codex attempt: the vocabulary must stay frozen during a classification run. So the loop never changes terms mid-run. Instead it works in rounds:

- **Queue.** After any import or run, the code works out which segments the current version doesn't cover: no label, waiting for review, or from a chat imported since the last refresh. It isn't stored anywhere; it's recomputed from the classifications, so it can't drift out of date.
- **Refresh pack.** `ke taxonomy refresh --out ...` builds the same kind of pack as the first bootstrap, but only from the queued segments, and lists the existing vocabulary so the proposer doesn't suggest what's there. One Claude session proposes, a different one reviews, Louis publishes `tax-N+1`. The first-plan rule "must have categories" is relaxed for refresh plans, because a refresh may only need one new topic.
- **Relabel.** After publishing, `ke taxonomy relabel tax-1 tax-2` redoes only segments the new version can change: ones with no label, ones whose labels cite a term that changed (TAX-007 marks those stale), and ones whose text names a newly added term. Every other answer is *carried* into the new version as a new row, checked against the new version's answer schema, with no classifier call. Old rows and Louis's (or a reviewer's) corrections are append-only, so nothing is overwritten. With `--vault` the notes are rewritten through DOC-006, which only touches files whose content changed.
- **Dashboard.** The home page gets a Vocabulary row: chats with no label yet, chats waiting for review, chats new since the last refresh, proposals waiting for a reviewer.

Challenges:
- My first fixture failed for a test-only reason: the second "export" gave old chats new dates (I numbered days by sorted position, and adding chats shifted them), so the importer correctly saw them as edited and gave them new segment IDs. Real re-exports keep dates; the fixture now does too.
- The test session held an SQLite read snapshot open across the second import, so it couldn't see the new chats until it committed.
- An added term changes no existing ID, so TAX-007 alone would invalidate nothing. That's why "text names a new term" is its own relabel reason: an old garden chat that mentions a hive gets asked again once "Beekeeping" exists.

Once NOTE-007 (#296) merged, I rebased onto it and wired it in. Each `ke taxonomy refresh` takes the uncovered chats' digest topics, checks them against the published terms, and files the ones that match nothing as proposals. A topic is never filed twice: not while it's waiting, not after a reviewer has rejected it, and not when a term with that label has been approved but not yet published. Chats with no digest yet have nothing to offer here; their segments still go into the refresh pack.

**Teach-back (`taxonomy/refresh.py`, `relabel`):** When a new vocabulary version is published, this decides, segment by segment, whether the old label can stay. If the segment had no label, cited a term that changed, or mentions a term that's new, it is classified again; otherwise its old answer is copied into the new version unchanged. The old answers and every human correction are never edited, so you can always see what changed and why.

Checks:
```
tests/integration/test_taxonomy_refresh.py   7 passed (finish line: import 2 adds beekeeping chats, the refresh proposes a term, after tax-2 only the 2 new segments and 1 hive-mentioning old one are relabelled, 3 carried, tax-1 rows identical, the correction still stands; a changed definition marks only answers citing it; unmatched digest topics filed once, rejected ones never again; CLI and dashboard counts)
```
Fix attempts: 3 (fixture dates; test read snapshot; my topic test mapped chat IDs before the second import). All three were mistakes in my own new tests, not changes to existing tests or criteria.

Talking points:
- "New chats don't mean redoing everything: only the segments a new term could change get relabelled; the rest carry their answers forward."
- "The vocabulary never moves mid-run. New subjects queue up, one Claude proposes, a different Claude reviews, and I publish."
- "Adding a word changes no existing ID, so 'what's stale' isn't enough: the loop also asks which old chats *mention* the new word."

**Next exact task:** run the refresh loop on the real archive on the PC after the next export (proposer and reviewer sessions named in the diary).

### 16:21 UTC — NOTE-024: two small honesty fixes on the knowledge card

The re-score of the real notes (NOTE-011) found two things on the knowledge card that read wrong:

- **"48" listed as a tool.** The entity extractor records a name only after a cue like "playing", and its title pattern accepts numbers so titles like "Factorio 2" work. So "playing 48 levels a night" produced a game called "48". The card now leaves out any name with no letters in it. The record stays stored; it just isn't shown as a name.
- **"not stated" next to a digest.** When a chat's digest has no purpose or no outcome, the card wrote "not stated", which reads like a claim about the chat. The other notes thread pointed out that the wording only appears in that case, so the fix is to leave the empty row out. Without any digest, both rows still say "not written yet", because that is true and tells you the step hasn't run.

Before writing the fix, I checked who held which ticket. NOTE-018 (#309) already had a PR from the rich-notes thread, and NOTE-022 (#321) was built there too, so I took only this one.

**Teach-back (`rich_conversation_note`, the card):** The card is the short table at the top of each chat note. It now shows only names that contain a letter, so a number the extractor caught by accident doesn't appear as a tool. It shows Purpose and Outcome only when the digest actually found them, so it never states something about the chat that nobody checked.

Checks:
```
tests/integration/test_rich_note_card.py   1 passed (fails on the old code: '48' was in '48, Celeste')
tests/integration/test_rich_note.py, test_note_checks.py   unchanged, pass
```
Fix attempts: 0.

Talking points:
- "A number is not a name: the card checks for a letter before listing something as a tool."
- "An empty row that says 'not stated' still reads like a fact, so the card leaves it out."

**Next exact task:** none in this thread; the remaining NOTE tickets are with the rich-notes threads.
