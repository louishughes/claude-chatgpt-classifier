# Classification spike (throwaway)

**Question it answers:** can a cloud model label my ChatGPT conversations *consistently* and *reliably* at 50 and 100 chats, before we build the real pipeline?

The earlier attempts failed on three things: inconsistent labels, untyped output, and timeouts at batch sizes of 20–50. This spike measures exactly those. It is **not** the product. When it has answered the question, its lessons go into `docs/plans/IMPLEMENTATION_PLAN.md` and the code is deleted or left here as a reference. Nothing in `src/` will import it.

## What it does
1. Picks a reproducible random sample from `raw/` (read-only). The 100 sample always contains the 50 sample.
2. Follows each chat's active branch and keeps user/assistant text (no hidden reasoning, system or tool messages, no images).
3. Asks the model to fill in a fixed form (`schema.py`): primary category, up to 3 secondary categories, topics, a short summary, user decisions with verbatim evidence, confidence.
4. Validates every answer. One repair attempt, then `review_required`.
5. Retries timeouts/rate limits/server errors at most 3 calls in total, with backoff. Stops before every call if the cost cap is reached. Saves after every chat, so a rerun resumes.
6. Runs the whole sample twice and reports reliability, cost and run-to-run agreement (`report.md`, counts only).

## Files
| File | Role |
|---|---|
| `loader.py` | Read raw files, active branch, text extraction, sampling |
| `schema.py` | The output contract and the prompt (taxonomy `spike-0.1`) |
| `providers.py` | `AnthropicProvider` (real) and `FakeProvider` (tests), typed errors, prices |
| `runner.py` | Retries, repair, cost cap, checkpoint/resume, evidence-quote check |
| `report.py` | Metrics and the Markdown report |
| `spike.py` | Command line |
| `tests/` | 25 tests on synthetic data, including 50- and 100-chat batches with injected failures |

## Running it
```bash
cd prototype/classification_spike
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m pytest -q tests                         # free, offline

# Needs ANTHROPIC_API_KEY set in your shell. Never commit it.
python spike.py --raw-dir ../../raw --sample 50 --out ~/spike-out --dry-run          # cost estimate only
python spike.py --raw-dir ../../raw --sample 50 --runs 2 --out ~/spike-out --max-cost-usd 5
python spike.py --raw-dir ../../raw --sample 100 --runs 2 --out ~/spike-out-100 --max-cost-usd 10
```
Defaults: model `claude-opus-5-5`, effort `low`, 4 workers, 90 s timeout, 24,000 characters per chat. Server-side refusal fallback is on (the API retries a declined request on a fallback model and the report lists which model answered); `--no-refusal-fallback` turns it off.

**Privacy:** the selected chat text is sent to the Anthropic API. Outputs contain summaries of your chats, so `--out` must be outside the repo (the script refuses otherwise). `report.md` has counts only.

## What "good enough" looks like (proposed, to agree before running)
| Metric | Target |
|---|---|
| ok after retries | ≥ 98% |
| first-try schema failures | ≤ 2% |
| transient errors left unrecovered | 0 at 50, ≤ 1% at 100 |
| primary category agreement run 1 vs run 2 | ≥ 90% |
| secondary category Jaccard | ≥ 0.75 |
| decision evidence quotes found verbatim | ≥ 95% |
| cost per 100 chats | reported, compared with the cap |

Topic Jaccard is reported but not gated: free-text topics are expected to vary in wording. That is why the real system will map topics onto a governed taxonomy.

## Talking points
- "Before building a pipeline around an AI step, I measured whether the AI step was stable."
- "The model fills in a typed form. Validation, one repair, then a human: never a silent guess."
- "Same 50 chats, twice. Agreement is the number that decides whether we go ahead."
