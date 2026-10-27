# Data Model, API Contracts, Provenance and Temporal Semantics

## 1. Canonical entities and relational tables
| Table | Primary identity | Essential fields and constraints |
|---|---|---|
| `workspaces` | workspace_id | name, owner, privacy_policy; single local workspace initially |
| `sources` | source_id | workspace_id, kind, external_native_id, title, source_uri |
| `source_snapshots` | snapshot_id | source_id, sha256, immutable blob path, imported_at, manifest_id; unique `(source_id,sha256)` |
| `import_runs` | import_id | input hash, importer_version, status, warnings JSON, counts |
| `content_nodes` | node_id | snapshot_id, native_id, parent_id, role, timestamp NULLABLE, content_type, canonical_text, raw_ref, branch metadata |
| `node_assets` | node_id+asset_id | asset SHA, available/missing, media_type, location |
| `segments` | segment_id | snapshot_id, boundary_version, sequence_index, context summary |
| `segment_spans` | segment_id+node_id+ordinal | start/end offsets, inclusion role |
| `taxonomy_versions` | version | published_at, author, status, hash |
| `taxonomy_terms` | term_id | canonical label, type, parent_id, definition, status, created/retired versions |
| `taxonomy_aliases` | alias_id | term_id, alias, norm_form, scope, active_version |
| `taxonomy_proposals` | proposal_id | candidate, evidence, operation, reviewer, outcome |
| `projects` | project_id | stable ID, name, aliases, status |
| `classifications` | classification_id | segment_id, taxonomy_version, primary term ID NULLABLE, secondary IDs/relation rows, actor, model policy |
| `knowledge_records` | record_id | record_type, assertion, asserted_by, origin, scope, state, created_from_run, revision |
| `evidence_refs` | evidence_id | record_id, snapshot_id, node_id, start, end, exact_text_sha256, support_mode |
| `relationships` | rel_id | from_id, predicate, to_id, state, review_status, evidence_ref IDs |
| `decision_events` | event_id | from_record_id, to_record_id, predicate, scope, evidence, timestamp |
| `review_items` | review_id | target, reason, status, reviewer, resolution, time |
| `jobs` | job_id | stage_name, key UNIQUE, input_versions, state, attempts, result, errors |
| `document_definitions` | document_id | type, scope, builder_version, output path, mode |
| `document_dependencies` | document_id+record_id | lineage, last_seen_revision |
| `document_builds` | build_id | content hash, status, completed_at, warnings |
| `index_entries` | index_id | record/segment ID, source revision, embedding model+dim, FTS/vector status |
| `domain_events` | event_id | type/schema version, payload, tx, happened_at; append only |

### Data storage rules
- Generated records reference source IDs, not bare display titles.
- Source content and raw metadata never modified; changed imports create new snapshot.
- Taxonomy merges create alias/redirection history, not destructive ID reuse.
- `record_id` persists across explanation edits if semantically same; otherwise new revision/supersession.
- Access-control context should be explicit in repository filters even for single-user implementation.
- For source evidence, actor refers to *speaker of cited text*, not extractor/model.

## 2. Knowledge record statuses
`candidate → supported → reviewed/confirmed` when evidence and review permit. `candidate → review_required` when ambiguous. A confirmed statement may be `superseded` in specific scope but remains historically visible. `rejected` records preserve genuine rejection, not processing failure. `unknown` is a projection outcome, not an invented source fact.

```text
candidate --evidence valid--> supported
candidate --ambiguous------> review_required
supported --approve--------> confirmed
supported --reject----------> rejected_as_invalid
confirmed --later supported scope-aware decision--> superseded
any review state --human correction--> new revision + audit event
```
Only service-layer transition functions can change state; save transition events atomically with record update. **Do not conflate an original rejected product proposal with a rejected extraction proposal.**

## 3. Decision transition predicates
- `proposes`: source articulates an option, not necessarily adopted.
- `accepts`: user explicitly or sufficiently clearly adopts a proposal in scope.
- `rejects`: user explicitly rules out proposal in scope.
- `clarifies`: later evidence narrows meaning, does not automatically replace.
- `revises`: explicitly amends subset of earlier decision.
- `supersedes`: scope-compatible later decision replaces earlier one.
- `contradicts`: claims conflict but evidence of intentional revision insufficient.
- `related_to`: semantic association, not causal history.
Accept/reject links to original proposal where available. Later-time occurrence alone must never create `supersedes`.

## 4. Example Pydantic DTOs (guidance)
```python
from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field, model_validator

class RecordType(StrEnum):
    FACT='fact'; PROPOSAL='proposal'; DECISION='decision'
    REJECTION='rejection'; PREFERENCE='preference'
    REQUIREMENT='requirement'; IDEA='idea'; QUESTION='question'
    ACTION='action'; ARTEFACT='artefact'; REFERENCE='reference'
    RECOMMENDATION='recommendation'

class EvidenceInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    snapshot_id: str
    node_id: str
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    node_text_hash: str

    @model_validator(mode='after')
    def end_after_start(self):
        if self.end <= self.start:
            raise ValueError('Evidence offsets must form a nonempty half-open range')
        return self

class ProposedRecord(BaseModel):
    model_config = ConfigDict(extra='forbid')
    type: RecordType
    assertion: str = Field(min_length=1)
    actor: str
    project_ids: list[str] = []
    term_ids: list[str] = []
    evidence: list[EvidenceInput] = []
    origin: str = 'extracted'
    acceptance_mode: str | None = None
    review_reason: str | None = None

    @model_validator(mode='after')
    def require_evidence_for_extracted_claim(self):
        if self.origin == 'extracted' and not self.evidence:
            raise ValueError('Extracted claim requires source evidence')
        return self
```
Service-level checks then verify referenced source exists, offsets fit, current hash matches, speaker/quote context and entailment; *Pydantic alone cannot perform semantic evidence validation.*

## 5. Stage request/response contract
```json
{
  "stage": "classify.segment.v1",
  "job_id": "uuid",
  "inputs": {"segment_ids": ["s-001"], "taxonomy_version": "tax-1"},
  "versions": {"pipeline": "1.0", "prompt": "cls-001", "model_policy": "local-default"},
  "limits": {"max_attempts": 3, "max_tokens": 12000},
  "result": {"state": "succeeded", "output_ids": ["cl-001"], "warnings": []}
}
```
Stage signature: `execute(StageRequest) -> StageResult`, save via job repository; idempotency key includes input content hash and relevant version/config hashes. JSON payloads in persisted events include `schema_version`.

## 6. Evidence contract
For any confirmed extraction, all references must exist, cite the correct actor, fit `[start,end)` of canonical node text and pass quote-hash verification. A semantic claim can have multiple evidence spans. An evaluator/human may still mark it unsupported. The result then moves to review/rejected-as-invalid; no auto-promotion to current truth.

## 7. Historical/current projection
Projector takes `scope`, optional `as_of`, and a pinned knowledge revision. It returns confirmed, supported, conflicted or unknown records, including explicit reasoning paths. When records conflict without validated supersession, return `conflict` not a fabricated latest winner. A master document must display current decisions separately from historical exploration.

## 8. Incremental and rollback contracts
New snapshot never overwrites previous one. Derived records refer to snapshot and stage versions. New pipeline versions can coexist during evaluation; promote a version as published only after benchmarks pass. Rollback changes the read pointer to the previous vetted materialisation, not the raw source. Document builds commit atomically. Dependency invalidation recomputes the transitive closure of impacted materialisations, never whole corpus by default.

## 9. Ownership, security and deletion
Every source, chunk, relationship and derived note is scoped by workspace. Audit permission checks on structured/FTS/vector/context hydration. A deletion request identifies source and all dependent derivatives; produce a manifest of removals, remove index/cache entries and verify post-deletion queries. Immutable means not silently rewritten; legally required deletion is permitted and logged without retaining deleted personal content.

## 10. Source identity, media, links and relationships *(added by the 2026-10-27 audit; proposed, see ADR-0002..ADR-0006)*

These tables refine §1 rather than adding competing copies. Reconciliation with §1:
- `import_runs` is kept and becomes the **ImportBatch** ledger (one row per attempt). Snapshot identity stays in `source_snapshots`.
- `sources` gains `source_system` and `account_ns`; for ChatGPT, one `sources` row = one logical conversation.
- `content_nodes` stays the per-snapshot observation of a node (what a given file said). The new `message_nodes` / `message_revisions` hold the logical identity that survives re-exports. Derived stages key on `message_revisions`, never on per-snapshot rows.
- `node_assets` is superseded by `media_blobs` + `media_assets` + `asset_occurrences`. It stays in §1 for history and should not be implemented.
- `relationships` (§1) remains for knowledge-record relationships. Conversation-level links use `conversation_relationships`.

| Table | Primary identity | Essential fields and constraints |
|---|---|---|
| `raw_roots` | raw_root_id | path (private, never rendered), format_detected, account_ns, read_only=true, last_tree_hash |
| `source_files` | file_id | raw_root_id, relative_path_hash, size, sha256, role (`conversation_json`/`conversation_shard`/`split_wrapper`/`manifest`/`media`/`derived_artifact`/`unknown`); unique `(raw_root_id, relative_path_hash, sha256)` |
| `import_batches` (= `import_runs`) | import_id | raw_root_id, started/finished, adapter+parser versions, status `running/succeeded/partial/failed/abandoned`, checkpoint, counts JSON, lock token |
| `message_nodes` | node_key | conversation source_id, native_node_id; unique `(source_id, native_node_id)`; first_seen_import, last_seen_import, presence `present/not_seen` |
| `message_revisions` | revision_id | node_key, canonical_content_hash, raw_payload_hash, role, create_time NULLABLE, content_type, snapshot_id of first observation; unique `(node_key, canonical_content_hash)` |
| `graph_edges` | edge_id | child node_key, parent node_key NULLABLE, observed_in_import; unique `(child, parent)`; parent change flagged as anomaly |
| `branch_points` | branch_point_id | parent node_key, kind `edit/regeneration/other`, child node_keys, active child (from current_node), classifier version |
| `identity_candidates` | candidate_id | entity kind, left/right keys, reason (`missing_native_id`/`id_collision`/`prefix_match`), evidence JSON, review_state |
| `media_blobs` | blob_sha256 | byte_size, mime (from header), width/height NULLABLE, storage_mode `copy/reference`, storage_ref (private), verified_at |
| `media_assets` | asset_id | native_file_id NULLABLE, blob_sha256 NULLABLE, source_system; unique `(source_system, native_file_id)` when present |
| `asset_occurrences` | occurrence_id | revision_id, part_index, pointer (verbatim), asset_id NULLABLE, availability `available/missing/unresolved/ambiguous/unsupported`, evidence JSON, declared size/dimensions; unique `(revision_id, part_index, pointer)` |
| `derived_media` | derived_id | blob_sha256, kind (`thumbnail`/`header_meta`), generator version |
| `link_targets` | target_id | canonical_url, host, kind (`web`/`youtube_video`/`social_profile`/`chatgpt_conversation`/`other`) unique canonical_url |
| `link_occurrences` | link_occ_id | revision_id, start, end, original_text, target_id, origin (`message_text`/`citation_metadata`), actor; unique `(revision_id, start, end, origin)` |
| `youtube_videos` | video_id (11-char) | first/last seen, mention_count (derived), transcript_status |
| `youtube_mentions` | mention_id | link_occ_id, video_id, t_seconds NULLABLE, playlist_id NULLABLE, channel_hint NULLABLE |
| `transcript_acquisitions` | acquisition_id | video_id, method (`user_supplied`/`provider:<name>`), status `not_requested/queued/succeeded/unavailable/permission_required/rate_limited/failed`, attempts, last_error, policy_version |
| `transcript_snapshots` | transcript_id | video_id, sha256, language, provenance JSON (source, retrieved_at, permission note), immutable |
| `transcript_cues` | cue_id | transcript_id, ordinal, start_ms, end_ms NULLABLE, text_offset range |
| `social_accounts` | account_id | platform, stable_platform_id NULLABLE, canonical_handle NULLABLE, profile_url NULLABLE, display_name NULLABLE (only if evidenced), identity_status `confirmed/probable/ambiguous/rejected`; unique `(platform, stable_platform_id)` and `(platform, lower(canonical_handle))` |
| `account_aliases` | alias_id | account_id, alias, kind (`handle`/`url`/`display_name`), evidence |
| `account_mentions` | mention_id | revision_id, start, end, raw_text, platform NULLABLE, account_id NULLABLE, resolution `resolved/ambiguous/rejected`, actor, origin |
| `conversation_relationships` | conv_rel_id | from_source_id, kind, to_source_id, direction semantics per kind, evidence_class, confidence, review_state, detector version; unique `(from, kind, to, detector)` |
| `relationship_reviews` | review_id | conv_rel_id, action `accept/reject/supersede`, reviewer, at, note (append-only) |
| `review_overrides` | override_id | target kind + logical key + revision_id, payload, reviewer, status `active/needs_review/retired` |

### 10.1 Transactional responsibilities
- One import batch commits per conversation group (configurable, default 50 conversations) in a single transaction: `source_files` → `message_nodes`/`message_revisions`/`graph_edges` → `branch_points` → `asset_occurrences` → `link_occurrences`/mentions → checkpoint update. The outbox event for the group is written in the same transaction.
- `media_blobs` are hashed outside the DB transaction, then inserted with `ON CONFLICT DO NOTHING`; a blob row is only written after the hash is verified.
- An import lock row (`import_batches.lock_token`, unique while `running`) prevents two writers. A stale lock older than the configured timeout is taken over only after marking the old batch `abandoned`.

### 10.2 State transitions
```text
ImportBatch:          running → succeeded | partial | failed | abandoned   (never back to running)
MessageNode presence: present → not_seen (absent from a later full export) → present (seen again)
AssetOccurrence:      unresolved|missing → available (when bytes appear in a later import; new event, old state kept in history)
TranscriptAcquisition: not_requested → queued → succeeded | unavailable | permission_required | failed
                       queued → rate_limited → queued (bounded attempts)
ConversationRelationship: candidate → accepted | rejected;  accepted → superseded
SocialAccount identity: ambiguous → probable | confirmed | rejected (human or explicit evidence only)
```

### 10.3 Example DTOs (guidance, not code)
```python
class DeltaCategory(StrEnum):
    NEW='new'; UNCHANGED='unchanged'; REVISED='revised'; NEW_BRANCH='new_branch'
    NOT_SEEN='not_seen'; CANDIDATE_DUPLICATE='candidate_duplicate'; FAILED='failed'

class AssetAvailability(StrEnum):
    AVAILABLE='available'; MISSING='missing'; UNRESOLVED='unresolved'
    AMBIGUOUS='ambiguous'; UNSUPPORTED='unsupported'

class AssetOccurrenceDTO(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    revision_id: str
    part_index: int = Field(ge=0)
    pointer: str                       # verbatim from the export, never rewritten
    asset_id: str | None               # None when unresolved
    availability: AssetAvailability
    evidence: dict[str, str] = {}      # e.g. {"manifest": "listed", "disk": "absent"}

class ImportDeltaReport(BaseModel):
    import_id: str
    conversations: dict[DeltaCategory, int]
    messages: dict[DeltaCategory, int]
    new_branches: int; new_media: int; duplicate_assets: int; missing_assets: int
    candidate_duplicates: int; failed: int
    rebuild_footprint: dict[str, int]  # document/index kinds -> count to regenerate
    model_calls_triggered: int         # must be 0 for an identical re-import
```
