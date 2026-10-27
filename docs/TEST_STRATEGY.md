# Test, Evaluation and Verification Strategy
## 1. Principles
Two independent kinds of quality exist: **software correctness** (parsers, persistence, hashes, transitions) and **semantic correctness** (what the user actually agreed to). Never treat JSON schema validity as semantic proof. Never make a failing semantic sample automatically justify rewriting unrelated architecture. Tests must be selective, reproducible and bounded.

## 2. Test levels
| Level | Fixtures | Target | How often |
|---|---|---|---|
| Unit | synthetic immutable models | stable IDs, offsets, aliases, transitions, rank fusion, escaping | ticket-level |
| Contract | fake adapters/providers | typed inputs/outputs, refusal/timeout handling, version mismatch | ticket-level |
| Integration | temporary SQLite and archive directory | importer → nodes → transaction, taxonomy and render persistence | stage-level |
| Property | Hypothesis-generated graphs/strings | idempotency, no cycles, bounds, round-trip, protected manual files | stage-level |
| Golden parser | real-format anonymised fixtures | ZIP variants, branches, unknown content, asset gaps | importer changes |
| Semantic golden | manually annotated 30–50 conversations | actor-aware classification/extraction, current/historical decisions | semantic changes |
| End-to-end | anonymised corpus + fake and real provider modes | ZIP → Obsidian note → source link; reimport → unchanged output | release |
| Security | malicious ZIP/page/prompt injection/tenant scope | no traversal, SSRF, untrusted instructions, cross-tenant leaks | security changes/release |
| Performance | reproducible synthetic 1k/100k corpus | throughput, p95 search, incremental rebuild proportion, model cost | pre-release |

## 3. Unit test catalogue
- **Identity:** same raw snapshot has same hash; IDs unique across two sources with same display title; stable under repeated import; changed bytes generate new snapshot.
- **Branches:** active branch uses ancestor chain; divergent assistant generations remain separate; missing/deleted parent is reported; cycle rejected/flagged; unconnected nodes retained.
- **Offsets:** `[start,end)` quote extraction matches original bytes/canonical text; invalid bounds rejected; empty text cannot be source support; Unicode/emoji/CRLF fixtures.
- **Taxonomy:** alias normalisation handles case/whitespace; approved term IDs stable after rename; rejected proposal never accessible as approved classification; published taxonomy immutable.
- **Classification:** multiple topics allowed; unknown category not fabricated; primary chosen from assigned approved IDs; user emphasis outranks mere word count in hand-designed fixtures.
- **Speech acts:** assistant proposal + user's curiosity ≠ accepted decision; explicit 'yes' can accept when exact antecedent is resolved; sarcasm/quote/hypothetical produce review as appropriate.
- **Temporal:** later question does not supersede earlier decision; scope mismatch does not supersede; explicit revision links are preserved; no source deletion by reconciliation.
- **Documents:** YAML parses; quote/link escaping; stable slugs; no collisions; generated rewrite does not alter hand-authored notes; deterministic output ordering.
- **Pipeline:** transient 2 retries then fail; semantic ambiguity 0 retries; idempotency keys; stage checkpoint recovery; dependent-only invalidation.
- **Retrieval:** exact-match priority on unique codes; tenant/workspace filters; RRF stable ordering; no invented citation IDs.

## 4. Golden dataset construction
Each case stores `case_id`, anonymised source, expected node topology, segment boundaries, accepted taxonomy IDs, expected/forbidden knowledge records, expected evidence spans, expected temporal transitions, acceptable uncertainty flags and query-answer pairs. Include at least 2 cases of every record type, 5+ ambiguous decision cases, 3+ true revisions and 3+ false supersession traps, multilingual/non-text/role confusion, and cases containing *no* durable decisions.

Expected labels come from a reviewed human annotation, not the model being tested. Corrections append new fixture versions, never silently change baseline. Include explicit **forbidden outputs**, particularly unsupported accepted decisions.

## 5. Metrics
- Classification: domain/topical macro and micro F1, project precision/recall, primary category accuracy, calibration/review rate.
- Extraction: per-type precision/recall/F1, speaker attribution accuracy, explicit-decision false-positive count, evidence validity.
- Reconciliation: supersession precision/recall, conflict-detection recall, `current_state` accuracy under scope, historical retention.
- Retrieval: Recall@5/@10, MRR, nDCG, exact-code hit rate; split keyword/semantic/structured question sets.
- Answering: all material factual claims traceable to valid evidence; abstention when no support; source fidelity and freshness.
- Operations: reimport duplicates (target 0), unchanged LLM calls (0), cache hit rate, changed-to-rebuilt dependency ratio, costs/timeouts.

## 6. Proposed release gates
Parser inventory and evidence offsets: 100% of supported fixtures accounted for. Every published confirmed record has valid exact evidence anchor. Zero known unsupported accepted decisions on golden benchmark. Initial primary category agreement >=90%, explicit decision recall >=90%, Recall@10 >=90%, directional relationship precision >=90% (calibrate based on representative dataset). Unresolved ambiguous cases must be flagged, not forced. For multi-user release: zero cross-tenant leakage in adversarial integration/e2e cases.

## 7. Order independence and model variability
Process same golden corpus in at least 3 shuffled orders under identical taxonomy/model/prompt versions. Compare canonical ID sets and confirmed knowledge projections; store diffs, false positives and reasons. Repeat selected classifications across multiple provider runs; measure disagreement. Lexical rendering may differ but canonical classifications and verified decisions should remain stable or be marked for review.

## 8. Incremental invalidation verification
Import 20 conversations spanning 3 projects. Capture hashes for all master notes. Change one related conversation; verify only dependent notes and search entries update. Reimport identical data; verify zero changed snapshot revisions and no model calls. Modify taxonomy version; verify reclassification targets affected segments and produces versioned records, not destructive mutations.

## 9. Security/abuse cases
- ZIP path `../../secrets`, symlink, too many files, oversized declared/uncompressed entry, invalid encoding and corrupted ZIP.
- Web redirects to loopback/metadata/private IP; oversized/binary HTML; malicious scripts.
- Imported text telling model to ignore instructions; extraction has no shell tools and prompt treats source as data.
- Query referencing workspace A while authorized to B; test SQL/FTS/vector/relation/answer/export containment.
- Deletion test queries every index and materialised document after purge.

## 10. Efficient execution and stop conditions
Ticket-level: run scoped unit/contract tests, then relevant integration. Stage-level: run stage package suite + targeted golden. Release-level: full suite once after final change plus any subsequent relevant changes. Limit auto-fixes to **one focused remediation loop per failing issue**; if still failing, mark `BLOCKED` with captured reproduction. Do not rerun unchanged suites to seek a different result. Outcomes: `PASS`, `FAIL`, `REVIEW_REQUIRED`, `BLOCKED`; stop and hand off.

## 11. Verification report format
```
Ticket: EXT-003
Commit: <hash or uncommitted>
Inputs/fixture version: golden-v1
Tests run: pytest tests/unit/extraction/test_decisions.py -q
Results: 17 passed, 1 failed
Semantic metrics: decision precision .96, recall .91
Known failures: assistant-only proposal fixture incorrectly accepted
Outcome: FAIL
Next action: fix acceptance antecedent matching (not arbitrary refactor)
Not run: full corpus benchmark (reason: stage gate only)
```
A test is not 'passed' unless a command/tool actually ran. For provider tests, retain model version, temperature and token/cost budgets; mask secrets/private text in logs.
