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
- **Not done: the pinned real-provider run under a cost cap.** It needs the owner to opt in (egress on, a key, a spending cap). The project rules forbid paid calls without that. Ticket EVAL-011 stays open for this half.
