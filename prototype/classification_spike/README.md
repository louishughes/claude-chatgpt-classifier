# Classification spike (throwaway)

**Question it answers:** can a cloud model label my ChatGPT conversations *consistently* and *reliably* at 50 and 100 chats, before we build the real pipeline?

The earlier attempts failed on three things: inconsistent labels, untyped output, and timeouts at batch sizes of 20–50. This spike measures exactly those. It is **not** the product. When it has answered the question, its lessons go into `docs/plans/IMPLEMENTATION_PLAN.md` and the code is deleted or left here as a reference. Nothing in `src/` will import it.

## What it does
1. Picks a reproducible random sample from `raw/` (read-only). The 100 sample always contains the 50 sample.
2. Follows each chat's active branch and keeps user/assistant text (no hidden reasoning, system or tool messages, no images).
3. Asks the model to fill in a fixed form (`schema.py`) with **one field per question**: primary and secondary *domain*, *purpose*, *project candidates*, *topics*, *knowledge types*, *outputs*, a short summary, and *decisions* (who proposed it, accepted/rejected/superseded, and a verbatim quote with its speaker). The old single "primary category" mixed subject, intent and output, which made consistent answers impossible.
4. Validates every answer. One repair attempt, then `review_required`.
5. Retries only transport and format problems: timeouts/rate limits/server errors at most 3 calls in total, with backoff; a broken schema gets one repair. A well-formed but wrong answer is never retried. Stops before every call if the cost cap is reached. Saves after every chat, so a rerun resumes.
6. Runs the whole sample twice, **in a different order each time**, and reports reliability, cost and run-to-run agreement per field (`report.md`, counts only). Because every call is independent, agreement across orders also checks processing-order independence.
7. Compares the model with **your own labels** for about 20 varied chats (a gold set, about an hour of labelling). The sheet shows title, date, size and your first message, with label columns left blank so the model's guess can't anchor you. The gold file's fingerprint goes into every report. Agreement between runs only proves consistency; a model can be consistently wrong.

## Files
| File | Role |
|---|---|
| `loader.py` | Read raw files, active branch, text extraction, sampling |
| `schema.py` | The output contract and the prompt (taxonomy `spike-0.1`) |
| `providers.py` | `AnthropicProvider` (real) and `FakeProvider` (tests), typed errors, prices |
| `runner.py` | Retries, repair, cost cap, checkpoint/resume, evidence-quote check |
| `report.py` | Metrics and the Markdown report |
| `gold.py` | Gold set: picks varied chats, writes the labelling sheet and instructions, scores accuracy, fingerprints the file |
| `spike.py` | Command line |
| `tests/` | 40 tests on synthetic data, including 50- and 100-chat batches with injected failures |

## Order of play (agreed 2026-10-27)
1. Schema with separate fields (done) → 2. gold set: you label ~20 chats → 3. run 50 chats twice, score agreement and accuracy, **you review** → 4. go/no-go: if targets are met, run 100, then start M1; if not, change the method (inputs, fields, segmenting), not the prompt wording.

Guardrails: agents don't change the tests or your gold labels without your OK; the category lists are frozen during a run (`TAXONOMY_VERSION`); a failing fix gets at most 3 attempts, then the agent stops and asks.

## Running it
```bash
cd prototype/classification_spike
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m pytest -q tests                         # free, offline

# Needs ANTHROPIC_API_KEY set in your shell. Never commit it.
python spike.py --raw-dir ../../raw --sample 50 --out ~/spike-out --dry-run          # cost estimate only
python spike.py --raw-dir ../../raw --sample 50 --out ~/spike-out --gold-template 20   # labelling sheet, ~1 hour
# fill in primary_domain and purpose (optionally secondary_domains and projects, ';'-separated), save as ~/spike-out/gold.csv
python spike.py --raw-dir ../../raw --sample 50 --runs 2 --out ~/spike-out --max-cost-usd 2 --gold ~/spike-out/gold.csv
python spike.py --raw-dir ../../raw --sample 100 --runs 2 --out ~/spike-out-100 --max-cost-usd 2
```
Defaults: model `claude-haiku-5-5` (Anthropic's cheapest current model, $0.10 / $0.50 per million input/output tokens), effort `low`, cost cap $2, 4 workers, 90 s timeout, 24,000 characters per chat. If Haiku misses the targets, compare `--model claude-sonnet-5-5` on the same sample and gold set before changing anything else. Server-side refusal fallback is used on Sonnet/Opus only (Haiku 5.5 doesn't support it); `--no-refusal-fallback` turns it off.

**Privacy:** the selected chat text is sent to the Anthropic API. Outputs contain summaries of your chats, so `--out` must be outside the repo (the script refuses otherwise). `report.md` has counts only.

## What "good enough" looks like (proposed, to agree before running)
| Metric | Target |
|---|---|
| ok after retries | ≥ 98% |
| first-try schema failures | ≤ 2% |
| transient errors left unrecovered | 0 at 50, ≤ 1% at 100 |
| primary domain agreement, run 1 vs run 2 | ≥ 90% |
| purpose agreement | ≥ 85% |
| secondary domains / knowledge types / outputs Jaccard | ≥ 0.75 |
| decision evidence quotes found verbatim, right speaker | ≥ 95% |
| primary domain matches your gold labels | ≥ 80% (≥ 90% counting secondaries) |
| purpose matches your gold labels | ≥ 75% |
| cost per 100 chats | reported, compared with the cap |

Topic and project-name overlap are reported but not gated: free text is expected to vary in wording. That is why the real system maps topics onto a locked taxonomy and projects onto a corpus-wide registry.

## What the spike does *not* prove
- **Project identity.** One call per chat, with no shared registry, is the pattern that gave one game several names last time. `project_candidates` shows how much names vary; it does not validate project labels.
- **Segment-level labels.** A chat that covers several subjects gets one set of labels here. The real pipeline classifies segments.
- **Decision recall.** The gold set covers domain and purpose. Checking that all of your decisions were found needs a fuller reference set (EVAL-001).

## Talking points
- "Before building a pipeline around an AI step, I measured whether the AI step was stable."
- "The model fills in a typed form. Validation, one repair, then a human: never a silent guess."
- "Same 50 chats, twice, in different orders. Agreement and accuracy against my own labels decide whether we go ahead."
- "Retry the network, never the judgement."
