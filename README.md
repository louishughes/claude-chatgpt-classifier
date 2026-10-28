# Knowledge Engine — Repository Start Here

**Current status: specification audit and planning; not a completed application.**

This repository will become a local-first, evidence-backed second brain. It is designed to ingest your complete ChatGPT history and available images/media, relate separate conversations and branches, extract decisions/preferences/actions without inventing agreements, and produce searchable, reliably linked Markdown/Obsidian knowledge. Later inputs include documents, websites, YouTube transcripts and other source material. Repeat ChatGPT exports must update the existing corpus instead of starting from scratch.

## 1. Files and folders

Place these four files **at the repository root**, next to the existing `docs/` and `raw/` directories:

```text
KnowledgeEngine/
├── CLAUDE.md                          ← Claude Code standing instructions
├── AGENTS.md                          ← Guardrails for Claude, Codex and other agents
├── README.md                          ← This guide
├── CLAUDE_CODE_HANDOFF_PROMPT.md      ← Paste into your first Claude Code session
├── docs/                              ← Existing extracted blueprint documents
│   ├── PRD.md
│   ├── TECHNICAL_REQUIREMENTS.md
│   ├── ARCHITECTURE.md
│   ├── DATA_MODEL_AND_CONTRACTS.md
│   ├── ROADMAP_AND_TICKETS.md
│   ├── TICKETS.csv
│   ├── TEST_STRATEGY.md
│   ├── DECISIONS_AND_HISTORY.md
│   ├── README.md / HANDOFF.md / ADRs / skills / ...
│   └── ...
├── raw/                               ← Private source data: conversations, ZIPs, JSON, images
│   └── ...                            ← Keep original arrangement untouched
└── src/ / tests/ / generated/         ← Add later as agreed in the plan
```

Claude should discover actual nested paths rather than assuming your extracted ZIP has precisely this layout. If you copied the complete earlier ZIP beneath `docs/`, its own `docs/adr/`, `.claude/skills/`, `.agent-history/` and `prompts/` may now be nested beneath `docs/` too. That's fine for the audit; Claude should propose a canonical location instead of silently rearranging the folder tree.

### Privacy and version control

- **Do not commit `raw/`** to Git. It may contain private conversations, client data, secrets, images and other personal information.
- If source files are already tracked, propose a careful removal-from-tracking plan; don't delete the files. A `.gitignore` alone does not untrack committed content.
- Do not copy private passages or original image content into public Markdown reports, test fixtures or console logs.
- Local-only default; cloud-model calls, URL fetching, YouTube transcript retrieval and any public sharing require explicit later configuration/permission.
- Use synthetic/sanitised fixtures for tests. `raw/` stays read-only even during failed or repeated imports.

## 2. Product behaviour that must be designed now

| Capability | Expected result |
|---|---|
| Full ChatGPT export | Preserve all available conversation/message content, source IDs, relationships and processing fidelity warnings |
| Images/media | Associate images with their source messages, keep safe immutable references, report missing or inaccessible assets |
| Branched messages | Represent edits/regenerations as alternative paths; don't merge different assistant responses into one transcript |
| Similar/continued chats | Show evidence-backed related conversation links; distinguish known fork from guessed continuation |
| Re-export history | Same conversation/message/media produces no duplicate logical record or unnecessary AI processing |
| New messages | Add changed/new nodes and branch edges; keep earlier history and source snapshots |
| YouTube link | Capture canonical video identity and source mention; optionally obtain timed transcript lawfully when available |
| Social account mention | Add to a deduplicated platform/account reference list with every cited occurrence |
| Classification | Govern one versioned cross-corpus vocabulary; don't invent new accepted categories per conversation |
| Decisions and history | Distinguish proposals from agreement; retain revisions, rejected alternatives and outstanding tasks |
| Obsidian | Generate a linked vault with conversation notes, referenced media, related chats and project/topic masters |
| Search | Locate exact or semantic matches and follow back to original message, image or transcript segment |

### How repeat imports should work

Example: `raw/export_2026_10_01.zip` includes chats A, B and C. A later export includes A, B, C and D, but chat B has new messages and a new regenerated branch.

Expected: A and C remain one logical conversation each, B remains one logical conversation with additional immutable versions/nodes/branch edges, D is added once, source archives remain distinguishable, and the system reports the delta. If the same picture is attached in A and B, its stored bytes may be deduplicated but both chat-to-image occurrence links must survive. The second import must not create another copy of every conversation in the knowledge base.

A conversation absent from a later export is **not automatically deleted**. Deletion requires a separate, explicit operation.

### External links

Every discovered URL is a source-backed occurrence. For YouTube, create a video reference immediately and a separate transcript acquisition status, such as `not_requested`, `queued`, `available`, `unavailable`, `requires_authorization` or `failed`. Never synthesize a transcript from the video title. Social accounts should have canonical platform/handle identity where supported, but ambiguous `@mentions` must remain candidates until evidence permits resolution.

## 3. What to ask Claude Code to do first

Do **not** ask it to "build the whole app" as the first command. The existing specification has a substantial backlog and needs reconciliation with the new requirements.

The first run should:

1. Read every relevant file in `docs/`, including tickets, ADRs, skills, changelogs and any prior handoff.
2. Inspect `raw/` only to establish formats and metadata/structure; never modify it.
3. Audit the requirements, architecture, schema, tickets and tests against the new ingestion/asset/link/registry requirements.
4. Provide concrete feedback: contradictions, omissions, priority changes, engineering hurdles and recommended options.
5. Make defensible **documentation** changes, preserving IDs and logging each modification.
6. Write the revised dependency-aware implementation plan, including a first verifiable vertical slice.
7. Stop before application code and ask you to approve the plan.

This is documented in `CLAUDE_CODE_HANDOFF_PROMPT.md`, which you can paste into Claude Code in full.

## 4. Documents Claude should use

At minimum, it must reconcile the product overview, technical requirements, architecture/class contracts, data schema, 93-ticket roadmap and CSV, testing/evaluation strategy, decisions/history, handoff, relevant ADRs and development/testing/validation/final skills. The actual number of files can differ if your local copy is incomplete or has extra documents. Missing files should be reported, not imagined.

The existing specification previously treated YouTube transcript acquisition as a later integration (`INT-002`). That is a deliberate point to revisit: **link detection and reference preservation should be foundational**, while full transcript acquisition can remain a phased enrichment capability as long as every detected reference has status/provenance and can be processed later.

Likewise, the existing materials mention assets and conversation branches but require stronger acceptance contracts for image identity and links, repeat export deduplication, and related/forked chat relationships. Social-account discovery needs an explicit registry and tickets.

## 5. Expected audit outputs

Claude should create the following files (or record a justified alternative location):

```text
docs/reviews/SPEC_AUDIT.md
docs/reviews/REQUIREMENTS_TRACEABILITY.md
docs/reviews/SPEC_CHANGELOG.md
docs/reviews/OPEN_DECISIONS.md
docs/plans/IMPLEMENTATION_PLAN.md
docs/plans/DEPENDENCY_MAP.md
docs/HANDOFF_AFTER_AUDIT.md
```

The implementation plan must contain: phase gates; system boundaries and methods; schema/dataflow decisions; explicit ticket IDs and dependency graph; end-to-end fixtures; import-duplicate/branch/attachment/link tests; risks and alternatives; acceptance criteria; work estimates/ranges if useful; and the first exact unblocked task.

## 6. Acceptance criteria for the first Claude Code session

- It demonstrably inspected the available documents and reported any missing ones.
- It identified every major gap above and traced it to changes or unresolved decisions.
- The revised ticket Markdown and `TICKETS.csv` remain aligned; existing IDs are never casually renumbered and there are no new dependency cycles.
- New requirements explicitly cover *raw/ images*, distinct branch kinds, YouTube URL/reference versus optional transcript acquisition, social registry, and reexport idempotency.
- It produced an implementation plan anchored to actual specs and relevant code/interface contracts.
- It states clearly what has **not** been done; no application code is written as part of this first audit.

## 7. Subsequent development (only after approval)

Implement one dependency-unblocked ticket or approved vertical slice, test using sanitised fixtures, verify evidence/branch/asset fidelity, log changed paths and real test results, and update the handoff. Use the existing Development → Testing → Validation → Final skills when available. Avoid infinite verification/refactoring loops by sticking to scoped tests and finite retries.

## 8. Quick start

1. Open your project root in Claude Code (the folder containing `docs/`, `raw/` and `CLAUDE.md`).
2. Check that `raw/` is excluded from Git and is not already tracked.
3. Paste the content of `CLAUDE_CODE_HANDOFF_PROMPT.md` into Claude Code.
4. Review its audit, changes, revised tickets and plan before instructing it to start implementation.

**Note:** The files in this starter pack are agent guidance and planning instructions. They do not implement an importer, scraper, transcript fetcher or RAG service by themselves.

## 9. Developer setup (FND-001)

The package lives in `src/knowledge_engine/` and needs Python 3.12 or newer. From the project folder:

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
python -m knowledge_engine.devtools.ci            # lint, format, types, guard, all tests
python -m knowledge_engine.devtools.ci --nightly  # release gate, variance, end-to-end (fake model)
```

CI (`.github/workflows/ci.yml`) runs exactly these two commands, on Linux and Windows with Python 3.12 and 3.13 and a nightly schedule. It uses no secrets: every API key is removed from the checks' environment, so a check that needs a real model fails rather than passing on a machine that happens to have a key.

Installing a release, upgrading (`ke db upgrade` backs up first) and rolling back are in `docs/runbooks/UPGRADE_AND_ROLLBACK.md`, and what each version changed is in `CHANGELOG.md`. `.github/workflows/release.yml` runs `python -m knowledge_engine.devtools.release_check` nightly. It installs the built wheel on a clean virtual environment, then upgrades and rolls back.

Programs can read the same data as JSON with `ke api` (install the `server` extra first); see `docs/api/API.md`.

Turn on the commit guard once per clone (it refuses commits that would include `raw/`, `private/`, `workspace/`, `ke.toml` or `.env`, and checks fixtures are marked synthetic):

```bash
git config core.hooksPath .githooks
python -m knowledge_engine.devtools.git_guard   # run it by hand any time
```

Coding and comment rules are in `docs/CODE_STYLE.md`. Ticket progress is in `STATUS.md`.
