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
- Batch/async throughput controlled by provider quota, cost ceiling and task concurrency.
- DB durability: transactional state; restart/resume without partial trusted records.
- Each emitted answer must have source IDs or declare no sufficient evidence.

## TR-10 API/CLI acceptance
Minimum CLI: `ke import <zip>`, `ke sources`, `ke inspect <source>`, `ke classify --taxonomy <version>`, `ke extract`, `ke review`, `ke search`, `ke build-notes`, `ke status`, `ke evaluate`.
Future FastAPI endpoints: `POST /imports`, `GET /jobs/{id}`, `GET /sources/{id}`, `GET /sources/{id}/nodes`, `GET /taxonomy`, `POST /taxonomy/proposals/{id}/review`, `GET /knowledge`, `GET /decisions/{id}/history`, `POST /documents/build`, `GET /search`, `POST /answers`, `GET /review`.
Responses include status/total/partial/warnings, request/trace ID and pagination. Background mutation endpoints return job IDs, not success before processing completes.

## TR-11 Quality gates
- Run `ruff`, `mypy` for selected domain contracts, pytest unit/contract/integration relevant to changed code; semantic eval only for changed stages plus bounded nightly/full gate.
- No time-consuming broad suite repeatedly without new relevant code or fixture change.
- Golden evaluation dataset is curated separately from implementation, representative and safe to version control only when anonymised.
- Report false positives for accepted decisions and supersession separately; benchmark release blocked on known unsupported confirmed decisions.

## Dependency decisions
No Kafka, Kubernetes, microservice decomposition, Neo4j, mandatory cloud provider, autonomous agent swarm or GraphRAG dependency in MVP. Evaluate trade-offs with ADRs and measured benchmarks before expanding stack.
