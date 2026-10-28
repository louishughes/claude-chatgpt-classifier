# Semantic batch smoke test (EVAL-011)

`ke eval semantic` segments, classifies and extracts a batch of conversations on a **scratch copy** of the workspace (`<workspace>/smoke/semantic-…`). The real database is never written. Code: `src/knowledge_engine/evaluation/semantic_smoke.py`.

- Classification goes through the model path (`ModelStageRunner` with an OPS-002 `RunBudget`). The model is a **local fake** that answers with the free keyword classifier's answer. It misbehaves on purpose: every 7th request first answers with broken JSON (so it needs its one repair), and every 13th never answers (so it times out). No data leaves the machine.
- Extraction uses the rule extractors. The first pass is **interrupted** halfway by a stage deadline and then **resumed**.
- Classification runs twice to measure **run-to-run stability**.

```
ke eval semantic --synthetic 50          # generated conversations
ke eval semantic --limit 100             # the first 100 imported conversations (copied)
ke eval semantic --limit 50 --max-calls 10   # overload: stops with recorded, capped outcomes
```

## Results, 2026-10-28 (synthetic, seed 1, this container)

| Batch | Segments | Classified done | Review (timed out) | Calls | Schema first-try failure | Repaired | Extraction runs | Interrupted: done / deferred | Resumed: done / skipped / repeated | Unvalidated outputs | Stability | Passed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 50 | 67 | 62 | 5 (5) | 76 | 0.145 | 9 | 268 | 133 / 135 | 135 / 133 / 0 | 0 | 1.000 | yes |
| 100 | 145 | 134 | 11 (11) | 164 | 0.142 | 19 | 580 | 289 / 291 | 291 / 289 / 0 | 0 | 1.000 | yes |

The measured schema failure rate (about 0.14) matches the injected one-in-seven fault, which is a cross-check of the counting.

## What this does and does not show

- It shows the plumbing holds at 50 and 100 conversations. Every failure ends recorded: repaired, `review_required` with an error code, or `capped` and logged. Nothing invalid is stored, and a resumed run repeats no finished stage key.
- Stability is 1.000 because the fake model is deterministic and the second run is answered from the cache. Real label stability needs a real model.
- The generated conversations contain no decision or task cues, so extraction finds 0 records here. Extraction quality is measured by EVAL-004.
- The pinned real-provider run under a cost cap ran once, at 50 conversations, on 2026-10-28 (results below). The 100 batch was run with the fake only: Louis approved one paid run, as small as the ticket allows.

## The real-provider run (one approved run)

Louis approved **one** paid smoke run on 2026-10-28, as a single exception to the no-paid-API rule: synthetic chats only, as small as the ticket allows, with a hard cost cap. The adapter is `src/knowledge_engine/providers/anthropic_api.py`.

It is fenced three ways, and the command refuses (`refused`, exit 2) unless all of them are set:

1. `--synthetic N`: generated chats only, never imported ones.
2. A cap above zero in two places: `--max-cost-usd X` on the command line and `[limits] max_cost_usd_per_run` in `ke.toml`. The lower of the two is used. Before each request the adapter works out the most it could cost (all its input, the schema, and the full output allowance at list price). If that would go over what is left, the request is **not sent**. It stays pending and is counted as `capped_requests`.
3. `[egress] text_llm = true` in `ke.toml`. With it off, the model path refuses the provider before anything is sent.

The model is pinned (`claude-haiku-5-5` by default, the model the OD-05 spike used), with thinking off and low effort. Its answers go through the same schema check, single repair and review routing as the fake's.

```
pip install -e ".[api]"                        # the Anthropic SDK, only needed for this
# ke.toml: [egress] text_llm = true and [limits] max_cost_usd_per_run = 0.50
#          (turn egress off again afterwards)
# ANTHROPIC_API_KEY in the environment, never in a file in the repo
ke eval semantic --synthetic 50 --provider anthropic --max-cost-usd 0.50
```

The report's `provider` block gives calls, tokens, dollars spent, the cap, and how many requests the cap held back. It never includes any text.

### Result of the one paid run, 2026-10-28

Approved by Louis at 08:54 UTC ("Do a and b"). Run on Louis's PC at commit 80fc4e0, 09:41–09:44 UTC, with the key and egress set as environment variables for that one command and removed afterwards (`ke.toml` untouched):

```
ke --json eval semantic --synthetic 50 --provider anthropic --max-cost-usd 0.50
```

| Conversations | Segments | Model calls | Schema first-try failure | Repaired | Done | Review | Unvalidated outputs | Stability | Input / output tokens | Cost | Capped | Passed |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 50 | 67 | 67 | 0 | 0 | 0 | 67 | 0 | 1.000 | 101,846 / 13,390 | **$0.0169** of $0.50 | 0 | yes |

- Every answer was valid JSON for the schema first time: no repairs, no timeouts, nothing capped.
- **All 67 segments went to review, none to done.** That is the cautious outcome, not a failure: nothing unchecked was stored. The likely reason is that the smoke vocabulary has only three terms (Code, Images, Questions) and the generated chats don't fit them, so the model flagged itself unsure. This is **not confirmed**: the report counts outcomes but doesn't give the review reasons. Follow-up: give the report a count per kind of review reason (no text).
- Stability 1.000 is again from the cache: the second pass reused the first pass's answers, so no second paid call was made. Real label stability would need a second, uncached paid run, which was not approved.
