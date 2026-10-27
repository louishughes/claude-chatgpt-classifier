# Technical Requirements and Constraints
**Baseline:** Python 3.12+, Pydantic v2, SQLAlchemy 2, Alembic, FastAPI, pytest, Hypothesis, SQLite + FTS5 for MVP. Optional sentence-transformers/local vector store. PostgreSQL/pgvector only when multi-user scale is justified.

## TR-01 Domain integrity
- SourceSnapshot is immutable; unique `(source_id, sha256)`; original bytes/content path retained with authenticated hash.
- Each normalized node links to `snapshot_id`, precise native ID/position, parent ID, actor, timestamp (nullable), raw payload reference and content type.
- Alternative conversation branches are first-class. Never sort all nodes by date into one synthetic transcript.
- Evidence offsets are `[start,end)` relative to an unmodified canonical source text revision; hash both node text and cited quote.
- Every confirmed knowledge record has >=1 valid evidence reference. A generated recommendation must carry `origin=generated` and never be used as evidence for a user decision.

## TR-02 Layer boundaries
- Domain has no dependency on model SDK, database engine, web framework or Obsidian.
- Persistence and external adapters implement `Protocol` interfaces. Application services orchestrate transactions.
- Modules do not import other modules' repository implementations directly; use service contracts/dependency injection.
- Public events carry schema versions. Stage outputs and failures are persisted; no invisible mutating tasks.

## TR-03 Processing semantics
- Per-stage key = hash(stage ID + immutable input hash + code/prompt version + relevant taxonomy/config/model policy version).
- Repeated stage with same key is a cache hit; changed inputs/config invalidate only dependents.
- Retries max 2 for transient provider errors (3 attempts total), exponential backoff with jitter. Semantic uncertainty -> review queue, not retry loop.
- Each stage has explicit `pending/running/succeeded/failed/review_required/skipped` transitions and hard resource/time/token budgets.
- Long-running jobs checkpoint after atomic batches; interrupted job can resume from latest committed checkpoint.

## TR-04 Classification and extraction
- Classifier chooses only IDs from an approved registry at pinned taxonomy_version; no implicit creation of canonical terms.
- Support multiple projects/topics, primary/secondary and no-match cases.
- Differentiate user vs assistant vs quoted external content; record whether acceptance is explicit, inferred or absent.
- Temporal current-state projection requires scope-compatible evidence; later timestamps alone are insufficient for supersession.
- Semantic validation is independent of JSON/schema validation; high-impact uncertain records withheld from confirmed/current projections.

## TR-05 Persistence and migrations
- SQLite WAL mode, foreign keys ON, transactional writes and schema migrations managed by Alembic.
- Unique constraints on native source IDs within snapshot, stage idempotency keys and taxonomy IDs.
- Store event/decision transition history append-only; reject invalid transitions inside domain service before DB persistence.
- Configurable workspace root with private source storage outside repo; maintain backup/restore and restore verification.
- Database schema chosen to allow future tenant/workspace_id index; do not expose an unfiltered raw collection through application services.

## TR-06 Retrieval
- Lexical FTS5 for exact strings/aliases; structured SQL for actor/status/project/date; vector index is optional and abstract.
- Use controlled fusion of sources, calibrated against golden search queries, with permission/scope filters BEFORE and AFTER ranking.
- Retrieve source spans and hydrate surrounding context before generation; preserve original content anchors.
- If evidence insufficient, return an explicit unknown/uncertain answer; do not fabricate citations or source offsets.
- Index versions and embedding model dimensions must be recorded; a model change triggers a background reindex, not silent reuse.

## TR-07 Rendering and Obsidian
- Use a safe filename slug + stable ID; frontmatter keys flat, YAML escaped, URLs/links quoted as necessary.
- Render documents from queryable structured records; no manual postprocessing as source-of-truth.
- Maintain generated directory separate from source archive and user-authored notes. Atomic file replacement after successful rendering.
- Maintain a document-to-record dependency table; update only affected documents on changes.
- Obsidian links and message anchor names are stable across regenerated text as far as source identity is stable.

## TR-08 Security and privacy
- Local-first default; provider egress OFF unless configured and acknowledged. Encrypt transport to cloud providers; protect keys in OS env/secret storage.
  - *Audit amendment 2026-10-27 (proposed, ADR-0007):* egress is controlled per capability (`text_llm`, `embedding`, `vision`, `network_fetch`, `transcript_fetch`). The owner indicated cloud models are acceptable where they help; defaults stay off in code until OD-04/OD-05 are confirmed.
- Treat imported content and retrieved passages as untrusted data; never execute instructions from transcripts/pages.
- ZIP import: prevent zip-slip traversal, symlinks, decompression bombs, excessive nesting, malicious file paths and huge-file exhaustion.
- Web fetch: protect against SSRF, local/internal IP destinations, redirect chaining, hostile HTML and unbounded responses.
- Sanitise Markdown/YAML filenames and imported HTML; avoid unsafe shell interpolation.
- Future product: tenant policies on SQL, FTS/vector search, graph traversal, generation, exports, caches and deletion; adversarial cross-tenant tests.
- All uploads, outputs, logs and telemetry exclude or redact sensitive source content by default.

## TR-09 Performance/SLO targets (initial engineering budgets, not measured promises)
- Local fixture 1,000 normalised text conversations, parse throughput target >=100 messages/second excluding LLM calls on reference hardware; record benchmark machine.
- Incremental unchanged import must perform no LLM calls or embedding writes.
- Local keyword search p95 <500ms on 100k indexed passages in a benchmark environment, excluding cold-start.
- Memory bounded using streamed ZIP/JSON when feasible; configurable max bytes per source and per pipeline stage.
  - *Audit amendment 2026-10-27:* streaming is **required** for conversation JSON above a configurable threshold (the original export is sharded into 12 parts; a single `conversations.json` can be hundreds of MB).
- *(Added 2026-10-27)* Batch-scale smoke: the import path must complete 50- and 100-conversation batches in M1 (EVAL-010) and the semantic path in M3 (EVAL-011), with timings and peak memory recorded on the reference machine.
- Batch/async throughput controlled by provider quota, cost ceiling and task concurrency.
- DB durability: transactional state; restart/resume without partial trusted records.
- Each emitted answer must have source IDs or declare no sufficient evidence.

## TR-10 API/CLI acceptance
Minimum CLI: `ke import <zip>`, `ke sources`, `ke inspect <source>`, `ke classify --taxonomy <version>`, `ke extract`, `ke review`, `ke search`, `ke build-notes`, `ke status`, `ke evaluate`.
*(Added 2026-10-27)* Also: `ke raw inventory <root>` (metadata only, read-only), `ke import <zip-or-dir> [--format auto|chatgpt-export|chatgpt-split-v1]`, `ke imports report <batch>`, `ke inspect conversation <id> [--branches] [--assets]`, `ke render sources [--conversation <id>]`, `ke links [--youtube]`, `ke transcripts attach <video> <file>`, `ke accounts [--ambiguous]`, `ke relations [--candidates]`.
Future FastAPI endpoints: `POST /imports`, `GET /jobs/{id}`, `GET /sources/{id}`, `GET /sources/{id}/nodes`, `GET /taxonomy`, `POST /taxonomy/proposals/{id}/review`, `GET /knowledge`, `GET /decisions/{id}/history`, `POST /documents/build`, `GET /search`, `POST /answers`, `GET /review`.
Responses include status/total/partial/warnings, request/trace ID and pagination. Background mutation endpoints return job IDs, not success before processing completes.

## TR-11 Quality gates
- Run `ruff`, `mypy` for selected domain contracts, pytest unit/contract/integration relevant to changed code; semantic eval only for changed stages plus bounded nightly/full gate.
- No time-consuming broad suite repeatedly without new relevant code or fixture change.
- Golden evaluation dataset is curated separately from implementation, representative and safe to version control only when anonymised.
- *(Added 2026-10-27)* Code must be readable by a Python beginner: module/class docstrings that explain what and why in plain English, why-comments on non-obvious invariants and a short "Talking points" block per module (`docs/CODE_STYLE.md`, created by FND-001). Avoid line-by-line comments that restate the code.
- Report false positives for accepted decisions and supersession separately; benchmark release blocked on known unsupported confirmed decisions.

## TR-12 Source identity and reimport *(added 2026-10-27, ADR-0003)*
- ImportBatch per attempt; SourceSnapshot per distinct file hash; logical Conversation keyed `(workspace, source_system, account_ns, native_conversation_id)`; MessageNode keyed `(conversation_id, native_node_id)`; MessageRevision keyed by canonical-content hash; raw-payload hash kept separately.
- Unique constraints on every logical key; single-writer import lock; per-batch transactions with checkpoints; resume never double-commits.
- Delta categories `new/unchanged/revised/new_branch/not_seen/candidate_duplicate/failed`; `not_seen` is unknown, never deletion.
- No identity from title, timestamp, embedding or perceptual similarity. Missing/colliding IDs produce `candidate_match` + `review_required`.

## TR-13 Raw sources and media *(added 2026-10-27, ADR-0002, ADR-0004)*
- Raw roots opened read-only; pre/post tree hash verified by inventory and import; nothing written under `raw/`; `raw/` stays git-ignored and untracked (OPS-008).
- Adapters: official export (ZIP or folder, single or sharded) and split-wrapper directory; non-conversation JSON reported as `derived_artifact`.
- Media: MediaBlob (SHA-256) / MediaAsset (native file ID) / AssetOccurrence (message revision + part index + pointer) / DerivedMediaArtifact. Availability `available/missing/unresolved/ambiguous/unsupported`. Storage mode `copy` or hash-verified `reference` (OD-02).
- Image dimensions/type read from headers only. No OCR, vision, face recognition or upload unless the `vision` capability is explicitly enabled per request.

## TR-14 Links, YouTube and social accounts *(added 2026-10-27, ADR-0006)*
- Deterministic URL detection on canonical text and citation metadata with `[start,end)` spans; original string preserved; canonical target normalised; untrusted; never fetched by detection.
- YouTube forms: `watch?v=`, `youtu.be/`, `/shorts/`, `/live/`, `/embed/`, `m.`/`music.` hosts; preserve `t`/`start`, `list`, `si`-stripped canonical. Video ID validated as 11 chars `[A-Za-z0-9_-]`.
- Transcript acquisition status machine with bounded attempts, provenance (source, retrieved_at, language, licence/permission note) and network gate. No synthetic transcripts.
- Social platforms configured as rules (initially X/Twitter, Instagram, TikTok, LinkedIn, YouTube channels, GitHub, Reddit, Bluesky, Threads, Mastodon, Facebook, Twitch). Bare `@name` = ambiguous candidate. No scraping, following or messaging.

## TR-15 Conversation relationships *(added 2026-10-27, ADR-0005)*
- Native branch kinds `edit/regeneration/other`; children derived from parent links when absent.
- Cross-conversation relationships typed, directional, evidence-classed, reviewable and append-only; `continues`/`forked_from` require native or human evidence to be accepted.

## TR-16 Model calls *(added 2026-10-27, ADR-0007)*
- JSON Schema generated from Pydantic DTOs; provider-native structured output where available; validate before persistence; max one repair attempt, then `review_required`.
- Pinned provider/model/prompt/schema versions in every stage key; temperature 0 where supported.
- Per-call timeout, max 3 attempts for transient errors, rate limit and run cost cap; checkpointed batches resume after timeouts.
- Run-to-run stability measured on the golden set; unstable labels go to review.

## Dependency decisions
No Kafka, Kubernetes, microservice decomposition, Neo4j, mandatory cloud provider, autonomous agent swarm or GraphRAG dependency in MVP. Evaluate trade-offs with ADRs and measured benchmarks before expanding stack.
