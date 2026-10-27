# ADR-0009: The model step without paid API calls (batch file in, batch file out)

```yaml
id: ADR-0009
kind: architecture_decision
status: proposed   # decided under delegated authority (owner, 2026-10-27 22:10 UTC), revisitable
recorded_at: 2026-10-27
scope: providers/semantic-pipeline
supersedes: []     # refines ADR-0007 §3, §4, §5 and §9 for as long as the no-paid-API rule holds; ADR-0007's two-layer and egress-switch policy stands
related_tickets: [FND-007, FND-009, EVAL-008, EVAL-010, EVAL-011, CLS-001, EXT-008, OPS-002]
issue: "#136 (REV-002)"
```

## Context

ADR-0007, FND-009 (#53), EVAL-011 (#82) and OD-04/OD-05 were written for a model behind a paid API: native structured output, timeouts, a cost cap per run, and batch runs of 50 and 100 conversations started by a script.

On 2026-10-27 at 21:38 UTC the owner decided: **no more paid API calls; do the work locally or with Claude on his Claude subscription.** At 22:10 he delegated authority for the night. The project instructions repeat the rule: no Anthropic API or other paid model API with his key until he says otherwise; AI steps go behind a provider switch and are tested with fakes.

What we already know (from `docs/plans/SPIKE_VERDICT.md` and `prototype/classification_spike/README.md`):

- Run 1 (Claude Haiku 5.5 through the API, 50 chats × 2 runs = 100 calls) cost **$0.069**: about **$0.035 per 50 chats per run** for per-chat labels. Zero timeouts.
- The discovery dry run (sections and typed items, chats clipped at 200k characters) estimated **about $0.13 per 50 chats per run**. Its estimate is deliberately pessimistic and implies roughly 15–20k input tokens per chat on average.
- Fixed-list fields were fairly stable run to run (domain 87.5%, purpose 90%). Free-text topics were not (overlap 0.49).
- Accuracy was never scored by the owner. Claude checking Haiku is a smoke test, not a score.
- The owner found local BERT-style classifiers and earlier local models too weak (ADR-0007 §8), so "local" does not mean a local LLM for now.

So the question is how the semantic layer gets its model answers when the only model is Claude working inside Claude Code sessions on the owner's subscription.

## Decision

### 1. The provider is a batch file in and a batch file out

The app never talks to the session directly. It talks to files:

1. **The app writes a request file.** `private/model-batches/<run_id>/<batch_id>.request.jsonl`, one line per request. Each line holds a `request_id` (the stage key from FND-009: input hash + prompt version + schema version + taxonomy version), the segment text with message numbers, the instructions, and the JSON Schema generated from the Pydantic DTO. Allowed taxonomy IDs are an enum inside that schema, exactly as ADR-0007 §3 says. A small `<batch_id>.manifest.json` records the run ID, prompt/schema/taxonomy versions, the request count and a SHA-256 of the request file.
2. **A Claude Code session fills a response file.** `<batch_id>.response.jsonl`, one JSON object per request line, carrying the same `request_id`. The session also records which model served it and the session ID, as far as the session can report them.
3. **The app validates every response line** with the same Pydantic model and the same rules it would use for an API response (FND-009): parse, validate, trim harmless overflows in code (spike lesson 1), check cited message numbers, speakers and quotes in code (spike lesson 2), at most one repair, then `review_required`. **Invalid output is never stored.** The repair is a new line in a follow-up request file that includes the validation error, not a conversation with the session.

`private/` is git-ignored and lives on the owner's PC inside `V:\Programming\ChatGPT_Classifier` (folder rule). Request and response files contain private conversation text, so they never go into the repository or a cloud container. The labelling session therefore runs on the owner's PC: Claude Code in that folder, or a Remote Control session started from a project thread.

**Why files and not "Claude reads the database and writes labels":**
- The session becomes just another provider. The pipeline, validation, caching and review rules don't know or care that a human started it. If the owner later turns on an API provider, nothing else changes.
- The files are an audit trail: exactly what was asked, exactly what came back.
- Everything is checkable by code. The session is never trusted to have followed the schema.
- Checkpoint and resume come for free (section 3).

### 2. Provider interface and fakes (what FND-007 must allow)

A paid API answers one call at a time within seconds. A session answers a whole file, minutes or days later. So the provider protocol has two steps instead of one blocking call:

- `submit(requests) -> BatchHandle`: write the request file and manifest; return immediately.
- `collect(handle) -> list[ProviderResult]`: read whatever response lines exist; return each as `ok` (validated DTO), `invalid` (with the validation error), or `pending` (no line yet).

An API provider fits the same shape: `submit` makes the calls and `collect` returns them. Each provider declares its capability (`text_llm`) and identity (`provider_id`, served model, prompt version), as the FND-007 amendment already requires.

Providers planned:

| Provider | Purpose | Network |
|---|---|---|
| `FakeProvider` | Unit tests. Canned answers, configurable failures. | none |
| `ReplayProvider` | Re-reads stored response files; makes re-runs and tests deterministic. | none |
| `FileBatchProvider` | The real provider under this ADR. Writes request files, reads response files. | none from the app (the session does the model work) |
| API provider | Not built in M3. Stays possible behind the same interface and the `text_llm` switch, plus a separate paid-call opt-in (REV-008 sets that pattern for the spike). | only if the owner opts in |

Tests drive `FileBatchProvider` with a **fake session**: a test helper that writes response files, including malformed JSON, a missing line, a line for an unknown `request_id`, a forbidden taxonomy ID and a truncated last line. No test needs a real session or a network.

### 3. Throughput, batch size, checkpoint and resume

**Size of the job (estimate, not measured).** 1,158 conversations. Using the discovery dry run's figure, one full pass is in the order of **20 million input tokens**, before repairs and before classification and extraction calls on top of discovery. The batch builder will count characters before writing any file, which replaces this estimate with a real number.

**Batch size.** One request file holds at most **about 100,000 characters of segment text** (roughly 25–30k tokens) and never splits a segment. That keeps one batch well inside one fresh context, so later items aren't labelled in the shadow of earlier ones, and a failure costs one small file, not a run.

**How a session works through it.** The session processes one batch file at a time and gives each file a fresh context (a fresh sub-agent per file, or a fresh session). It appends one response line per request and never rewrites a line already written. It stops when it hits a usage limit.

**Checkpoint and resume.** Progress is simply "which `request_id`s have a valid response line". On resume the app re-reads every response file, accepts complete valid lines, ignores a truncated last line, and lists the rest as still pending. A changed request file (hash differs from the manifest) is refused, so a session can't answer a request that no longer exists. Identical inputs hit the stage-key cache and are never written into a new request file (CLAUDE.md §2C: zero redundant model requests).

**What that means in practice.** A full pass is roughly 600–800 batch files. Subscription usage limits are not published as token numbers, so we can't say how many session windows that takes. It is certainly more than one evening. Therefore:

- M3 and the gate work run on **samples**: the 10-chat answer key, then 50, then 100 conversations (EVAL-011). 50 conversations is about 1 million tokens, which is a session or two.
- The first 50-conversation run records characters processed, batches per session window and wall-clock time. That figure, not this estimate, decides how a full pass is planned.
- A full-corpus pass is a separate, explicit step after gate G3. It is not assumed to be cheap in time.

### 4. Run-to-run stability (EVAL-008) and the 50/100 smoke (EVAL-011) when each run is manual

- **A run** is one complete set of response files for one fixed set of request files under one frozen taxonomy version (guardrail: the vocabulary is frozen during a run; new terms go to a review list).
- **Two runs are two independent sessions.** Run 2 gets the same requests **in a different, seeded shuffled order and different batch groupings**, written by the app as new request files. Run 2's session never sees run 1's responses.
- **Stability is computed by code**, never by a session: per-field agreement for fixed-list fields, overlap for list fields, decision agreement by message number. Clipped and unclipped inputs are reported separately whenever clipping happens.
- **The served model is recorded per response line.** On a subscription, the model can't be pinned the way an API model ID can. If run 1 and run 2 were served by different models, the stability report says so in its header and doesn't compare them as a like-for-like pair. That is the main weakness of this approach and it is stated in every report.
- **Smoke-test metrics change.** Under this provider, "timeouts" and "retries" become: invalid-line rate, missing-line rate, repairs needed, `review_required` rate, batches per session window, and whether resume after a session stopped mid-file lost or duplicated anything.
- Every report names its reviewer. Code-computed stability is a measurement. Accuracy needs the owner's approved answer key (REV-003) and counts only when scored against it.

### 5. Separation of roles

The session that **labels** is never the session that **writes, edits or reviews** the answer key or gold set:

- Labelling sessions are told only about `private/model-batches/`. Their instructions forbid reading `private/answer-key/`, `private/gold/` or earlier runs' response files, and the labelling run is started with Claude Code permission deny rules for those paths. The manifest records that.
- Answer-key and gold-set changes need the owner's approval (guardrail 1). Their files record who wrote each item: `owner` or a named session, never anonymous.
- Scoring is code comparing response files with the answer key. A session may help run the scoring script. It does not decide whether an answer is right.

This is the spike's hardest lesson ("know the difference between 'Claude checked it' and 'I checked it'") turned into a rule.

### 6. The cost trade-off, written down

| | Subscription sessions (this ADR) | Paid API (Haiku 5.5, spike prices) |
|---|---|---|
| Money | No extra cost beyond the subscription | Per-chat labels about $0.035 per 50 chats per run, about **$0.80** per full pass. Discovery about $0.13 per 50, about **$3** per full pass. Two runs for stability, plus classification and extraction: **a few dollars to about $15** in total |
| Owner time | Sessions must be started and restarted, on the owner's PC, across usage windows. A full pass is likely days of sessions | One command; a full pass in about an hour at 4 workers |
| Model pinning | Served model recorded, not pinned | Pinned model ID |
| Validation | By code only; no native structured output | Native structured output, then the same code validation |
| Privacy | Text goes to Anthropic through Claude Code | Text goes to Anthropic through the API |

The money saved is real but small. The rule is mainly about not spending without the owner's say-so, and about learning. The cost is mostly the owner's time and weaker pinning. That is a fair trade for samples of 10–100 conversations. It may not be for the full corpus.

**Revisit triggers.** Bring the paid option back to the owner (OD-05) if: the first 50-conversation run shows a full pass would need more than about two weeks of sessions; or served-model changes make the stability numbers unusable; or invalid-line rates stay above 10% after the prompt is fixed. The switch is one provider setting, so revisiting it changes no pipeline code.

### 7. What does not change

- ADR-0007's two layers: the source layer (M1/M2) never calls a model.
- The `text_llm` egress switch still guards the semantic layer. Writing request files is the egress point, because their contents are handed to a cloud model, so `FileBatchProvider` refuses to write a request file while `text_llm` is off.
- Imported text stays untrusted data inside every request. A labelling session follows the instructions in the batch header, never instructions found in a conversation.
- Embeddings and vision stay separate switches (OD-06). Images are never put into request files.

## Alternatives

- **Paid API, small cap.** Cheapest in owner time and best for pinning. Ruled out by the owner for now. Kept as the documented fallback in section 6.
- **Claude reads the store directly and writes labels into it.** Fewer moving parts, but it skips validation, has no audit trail and ties the pipeline to one way of working. Rejected.
- **Local LLM or BERT-style classifier.** Free and fully private, but the owner's earlier attempts found these too weak for this data (ADR-0007 §8). Not part of M3. A local classifier trained on owner-reviewed labels stays a later option.
- **One long session labels everything in one context.** Simplest to run, but later items get anchored by earlier ones and a crash loses more. Rejected in favour of one fresh context per batch file.

## Consequences

- **FND-007 (#52):** the protocol has `submit`/`collect` with `pending` results instead of a single blocking call. Fakes include a fake session that writes malformed response files.
- **FND-009 (#53):** "provider-native structured output where available" becomes "schema in the request file, validation in code". Timeouts become batch staleness (a request with no response after a set time is listed as pending, never guessed). The cost ledger becomes a usage ledger: batches, characters, served model and session per response. Acceptance criteria are unchanged in intent: invalid output is never persisted, a disabled `text_llm` fails before any request file is written, and an identical stage key is served from cache with zero new requests.
- **EVAL-011 (#82):** fake provider first, then `FileBatchProvider` with a real session on 50 then 100 conversations. Metrics as in section 4. No cost cap is needed, because no paid call is made.
- **EVAL-008:** two independent sessions with shuffled order and new batch groupings; stability computed by code; served model compared first.
- **OPS-002:** stage deadlines apply to how long a batch may stay pending, not to call timeouts.
- **OD-04/OD-05:** annotated in `docs/reviews/OPEN_DECISIONS.md`. The ticket issues get one comment each; ticket text is not rewritten.
- **New work this creates (not yet ticketed):** a short labelling-session runbook (how to start a session, the permission deny rules, where files go) for the owner's PC. That belongs with FND-009.

## Status

Proposed, decided under delegated authority (owner, 2026-10-27 22:10 UTC) and revisitable. The owner can reverse it, or switch the provider back to the API, by saying so. Any change gets a new ADR that supersedes this one.
