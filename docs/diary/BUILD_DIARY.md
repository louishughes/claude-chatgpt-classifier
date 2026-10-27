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
