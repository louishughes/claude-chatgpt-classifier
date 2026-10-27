# Build Diary

A running, timestamped log of what is being worked on, the problems hit, how they were handled, and why each decision was made. It doubles as raw material for build-in-public posts and for explaining the project in job interviews.

**Rules for this file**
- Times are UTC.
- Never paste anything from `raw/` (conversation text, titles, filenames, images) or any secret, key or private ID. Counts and format descriptions are fine. The repository is public.
- Append new entries at the bottom. Don't rewrite old ones; add a correction entry instead.
- Each entry: **what happened**, **why** (the reasoning behind the plan), and **talking points** (2–4 short lines you could say out loud or post).
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

### 22:20 — Turning the review into tickets, with Louis asleep
**What:** Louis asked for tickets and a plan from the direction review, and for other agents to implement them. Then he went to bed with one instruction: don't ask, you have the authority. So the plan (`docs/plans/REVIEW_ACTION_PLAN.md`) records each decision taken tonight as "owner authority 22:10", so he can reverse any of them in the morning, and the one thing only he can do (marking the answer key) is a ticket assigned to him, not a question.
**Tickets:** REV-001 to REV-009 as GitHub Issues #135–#143 under map #134, with the M1 and M3 ones also under their milestone maps. Six are agent work tonight (scope commitment, ADR-0009 for the no-API model step, M1 consolidation design, PR-size and teach-back rules, closing the ADR/decision record, a paid-call guard on the spike). One needs the PC (Windows run, key-name check), one waits for the parser (early real-data checkpoint), one waits for Louis (answer key).
**Decision taken under authority:** commit to M1 and M2; M3 to M6 stay roadmap and get re-planned at gate G2. The licence was deliberately *not* chosen: it's a legal call he should make awake.
**Conflict rule:** the foundation thread owns `src/`, `tests/` and the status files. Review tickets touch only docs, ADRs and the throwaway spike, so several agents can run at once without stepping on each other.
**Talking points:**
- "Delegating overnight works if every decision is labelled with who made it and when, so it can be undone."
- "Tickets with a finish line and a 'don't touch' list are how you run several agents in parallel safely."
