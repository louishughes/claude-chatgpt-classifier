# ADR-0007: Cloud-capable intelligence with schema-enforced output

```yaml
id: ADR-0007
kind: architecture_decision
status: proposed   # needs product-owner confirmation (OD-04, OD-05)
recorded_at: 2026-10-27
scope: providers/egress
supersedes: []     # refines, does not replace, PRD §11 and TR-08 "local-only by default"
related_tickets: [FND-002, FND-007, FND-009, CLS-001, EXT-008, EVAL-001, EVAL-011, OPS-002]
```

## Context
PRD §11, TR-08, README and AGENTS.md say "local-only by default; cloud calls opt-in". TR's dependency list rules out an "autonomous agent swarm". On 2026-10-27 the owner said the workflow does not have to be 100% local and that agents and cloud services should be used where they help.

Project history (owner's account, see `DECISIONS_AND_HISTORY.md` §Project history): the first proof of concept was built with Hermes and DeepSeek; a later Codex-built version used a model called Luna for classification. Results were inconsistent because (a) the local models were weak at extracting key information and (b) their output was not type-safe, so it varied run to run. Smoke tests one conversation at a time were inconsistent; OpenRouter API/model timeouts occurred; batches of 20–50 conversations had many failures.

## Decision (proposed)
1. **Two layers.** The source layer (import, identity, dedup, media, links, relationships detection, source browsing) is deterministic, local and never calls a model. The semantic layer (segmentation, discovery, classification, extraction, reconciliation help, answers) may use cloud models.
2. **Per-capability egress switches** in settings: `text_llm`, `embedding`, `vision`, `network_fetch`, `transcript_fetch`. Code ships with all off. The owner's workspace profile is expected to turn `text_llm` on once a provider is chosen (OD-05). `vision` and fetching stay separate, explicit switches.
3. **Type-safe outputs.** Every model call goes through FND-009: a JSON Schema generated from the Pydantic DTO, provider-native structured output/tool calling where available, validation before anything is stored, at most one repair attempt, then `review_required`. Invalid output is never persisted. Allowed taxonomy IDs are an enum inside the schema.
4. **Consistency is measured, not hoped for.** Pinned model ID, prompt version, explicit `effort` setting (current Claude models reject `temperature`/`top_p`, so stability has to come from the schema, the prompt and measurement), stage-key caching (an unchanged input is never re-sent), golden-set evaluation with run-to-run stability metrics (EVAL-001, EVAL-008) and batch smoke tests at 50 and 100 conversations (EVAL-010, EVAL-011).
5. **Bounded calls.** Per-call timeouts, 3 attempts total for transient errors, rate limits and a cost cap per run (TR-03, OPS-002). A timed-out batch resumes from its checkpoint instead of restarting.
6. **Agents.** Coding agents (Claude Code and others) build and review the system. At runtime the pipeline is a deterministic orchestrator calling models with typed contracts. Model-assisted review helpers are allowed, but no autonomous agent swarm decides taxonomy, merges or deletions.
7. Imported content stays untrusted data in every prompt; extraction calls get no tools.
8. **Where small local classifiers fit (owner, 2026-10-27).** The owner found BERT-style classifiers unreliable for this data. They are not part of the MVP. A later option is to train a small local classifier on LLM labels that a human has reviewed, to make re-runs cheaper, but only after the taxonomy is stable and only if it matches the LLM on the golden set. Embeddings are used for similarity and retrieval only, never as the evidence for a label or a link.
9. **Validated first by a spike.** `prototype/classification_spike/` measures schema failures, timeouts, cost and run-to-run agreement on 50 and 100 real conversations before FND-009 is built. Its results feed OD-05.

## Alternatives
- Stay strictly local: matches the old text, but repeats the failure mode the owner already hit.
- Cloud everything including images: simplest, but sends private images out by default. Rejected as a default.
- Route through an aggregator (e.g. OpenRouter): allowed behind the same adapter, but its timeouts were a past pain point, so measure it in EVAL-011 before relying on it.

## Consequences
FND-009 added; CLS-001 and EXT-008 depend on it. PRD §11 and TR-08 are annotated, not rewritten. Until the owner confirms OD-04/OD-05 this ADR stays `proposed` and the defaults remain "off".
