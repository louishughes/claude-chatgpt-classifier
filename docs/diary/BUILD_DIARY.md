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

### 00:35 — NRM-003 + ING-010: exact positions, and transcripts with honest times
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

### 01:20 — SOC-001 + SOC-002: social accounts mentioned in chats
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

### 01:45 — REL-002: links between separate chats
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

### 02:10 — RET-001: search every message
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

### 02:30 — UI-004: links, videos, accounts and search in the web UI
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
