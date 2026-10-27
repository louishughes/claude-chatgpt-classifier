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
