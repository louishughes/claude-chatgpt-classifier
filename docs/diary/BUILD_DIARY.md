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
