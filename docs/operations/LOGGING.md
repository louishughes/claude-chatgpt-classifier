# Structured run logs (OPS-001)

Jobs write one JSON object per line to `<workspace>/logs/events-YYYYMMDD.jsonl`. The workspace is git-ignored, so logs never reach Git. Code: `src/knowledge_engine/infrastructure/logs.py`.

## What an event holds

`at`, `event` (a dotted name such as `model.repair`), `log_version`, and only fields from the allow-list `FIELDS`: IDs (`stage_key`, `job_id`, `segment_id`, `record_id`...), versions, states, counts, `duration_ms`, `characters` and `cost_usd`. Anything else is refused with an error, so message text, titles and file names have no way in.

- Errors are logged by **type name** (`error_type`), never by message.
- Every string is scrubbed: API keys, bearer tokens, GitHub and AWS tokens, `key=value` secrets and the configured API key value become `[secret]`. Strings are capped at 200 characters.

## Events so far

| Event | Written by | Key fields |
|---|---|---|
| `model.submitted` | `ModelStageRunner.submit` | stage_key, stage_id, provider_id, prompt_version, characters, batch_id |
| `model.cached` | `submit` (answered from cache) | stage_key |
| `model.repair` | `collect` (one repair sent) | stage_key, attempts, characters |
| `model.stored` | `collect` (valid answer stored) | stage_key, attempts, model |
| `model.review_required` | `collect` (failed twice) | stage_key, attempts |
| `model.timeout` | `collect` (waited past `provider_timeout_s`) | stage_key, attempts |
| `limit.reached` | `RunBudget`, extraction `run` (OPS-002) | limit_name, limit, value, stage_key |
| `extract.run` | `extraction.runner.run` | stage_key, segment_id, extractor, version, state, records, attempts, error_type, duration_ms, outcome |

Done runs that are skipped aren't logged: nothing happened.

## Finding things

```
ke logs --stage-key stg_...     # one stage key's whole lineage
ke logs --event model.repair    # every repair
ke logs --job-id ... --json     # machine-readable, with summed characters, cost and time
```

Cost: `cost_usd` is an allowed field, but no provider reports a price yet (the only provider in use is the free fake one), so cost is tracked as `characters` for now. `totals()` sums cost, characters and time over any search. Filling `cost_usd` is follow-up work for the first paid provider.

## Limits (OPS-002)

Bounds live in `Settings.limits` (`KE_LIMITS__…`). Each is checked before the work, and reaching one is logged as `limit.reached`. Code: `src/knowledge_engine/orchestration/limits.py`.

| Limit | Default | What happens when it is reached |
|---|---|---|
| `max_source_file_bytes` / `max_media_file_bytes` | 2 GiB / 512 MiB | the file is refused (`SourceTooLargeError`) |
| `max_archive_entries` | 500,000 | the ZIP is refused before its members are listed or hashed |
| `max_model_calls_per_run` | 0 (no calls) | requests past the cap are not sent (`capped`, picked up next run); a repair with no budget left ends `review_required` / `limit:max_model_calls_per_run` |
| `max_input_tokens_per_request` | 100,000 (4 chars per token) | never sent; `review_required` / `limit:max_input_tokens` |
| `max_requests_per_batch` | 50 | requests go in several batches |
| `provider_timeout_s` | 86,400 | `review_required` / `timeout` |
| `stage_deadline_s` | 3,600 | no new extraction run starts; the rest is `deferred` to the next run |
| retries | 1 repair per model request; 3 attempts per extraction run | then `review_required` / `failed` |

Memory is bounded by the file-size limits (a conversations file is the largest thing read whole) and by `max_conversations_per_batch` per commit.
