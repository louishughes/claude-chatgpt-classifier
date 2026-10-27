# M1 consolidation: fewer, deeper modules for the source-fidelity slice

**Ticket:** REV-004 (#138), part of map #4 (M1) and #134 (direction review).
**Date:** 2026-10-27 · **Status:** adopted under *owner authority 22:10* (Louis asked for the review tickets to be implemented overnight and said "you have all the access and authority needed"). He can reverse it in the morning; nothing in `src/` or `tests/` has been changed by this note.
**Inputs:** the architecture review (`/mnt/project-files/reviews/architecture-review-2026-10-27.html`, diary 21:40), the direction review (diary 21:55, `docs/plans/REVIEW_ACTION_PLAN.md`), `docs/plans/IMPLEMENTATION_PLAN.md` §1–§7, `docs/plans/DEPENDENCY_MAP.md` §4, `docs/ARCHITECTURE.md` §7.1–§7.2, ADR-0003, ADR-0004, ADR-0005, and the foundation branch behind PR #3.
**Applied by:** the foundation thread ("Build chat import foundation"), at its next ticket boundary (before ING-002).

## 1. What changes, in one paragraph

The M1 plan describes about fifteen small classes, one ticket each, and a caller that must call them in the right order (lock, resolve, diff, commit, resume). The slice's most important promise, *"importing the same export again adds nothing and costs nothing"*, has no single owner, so no single test can check it. This note keeps **every ticket ID, every ADR-0003 key and every acceptance criterion**, but groups the code into four modules with small interfaces:

1. a pure **conversation graph** module (the message tree, its active path, message numbers, branches and integrity problems);
2. one **import** module whose whole public interface is `import_source(path, account_ns) -> ImportReport`; identity, hashing, snapshot dedup, media and the transaction rules are hidden inside it;
3. a narrow **source adapter** seam where the two export formats actually differ (finding the conversations), with one shared parser after it;
4. **rendering**, unchanged.

The in-process event system, a separate import lock and checkpoint-based crash resume are deferred, with a stated trigger for adding each one back (§5).

## 2. Target modules

```text
src/knowledge_engine/
├── domain/            # unchanged (PR #3): ids.py, enums.py, models.py
├── settings.py        # unchanged
├── infrastructure/    # unchanged: db.py, migrations/, jobs.py, workspace.py
├── orchestration/     # unchanged: stage_keys.py (used by M3, not by import in M1)
├── ingestion/         # the source seam: raw inventory + the two format adapters
│   ├── inventory.py   #   SRC-001  RawInventory (also behind `ke raw inventory`)
│   ├── source.py      #   ING-002  SourceAdapter protocol, NativeConversation, SourceListing
│   ├── chatgpt_export.py   # ING-004  official ZIP / directory / sharded JSON
│   └── chatgpt_split.py    # ING-011  one-file-per-conversation wrapper
├── graph/             # NEW: pure conversation graph, no I/O, no database
│   ├── conversation.py     # ING-005, NRM-002, REL-001  ConversationGraph
│   └── nodes.py            # ING-006, NRM-001  content parts, asset pointers, the two hashes
├── importer/          # NEW: the one deep Import module ("import" is a Python keyword)
│   ├── __init__.py    #   exports import_source, ImportReport and nothing else
│   ├── run.py         #   ING-003  the sequence, kept private
│   ├── archive.py     #   ING-001  snapshot store + checksums
│   ├── ledger.py      #   IMP-001  import_batches, source snapshots
│   ├── identity.py    #   IMP-002  logical keys, candidate matches
│   ├── delta.py       #   IMP-003  revisions, delta categories, not_seen
│   ├── commit.py      #   IMP-004  per-batch transactions under BEGIN IMMEDIATE
│   ├── media.py       #   MED-001..003  blobs, assets, occurrences, pointer resolution
│   └── report.py      #   ING-007, IMP-005  ImportReport, integrity counts, text/JSON output
├── rendering/         # DOC-002, MED-004, BRW-001 (as planned)
└── cli/               # `ke import`, `ke imports report`, `ke inspect` call the modules above
```

Folder names that the old plan proposed but M1 no longer creates: `identity/` (becomes `importer/identity.py` etc.), `media/` (becomes `importer/media.py`; MED-004's vault paths live in `rendering/`), and `relationships/` (REL-001 moves into `graph/`; the folder appears in M2 for REL-002's cross-conversation candidates, which are a different thing, see ADR-0005).

### 2.1 Conversation graph (pure)

```python
# graph/conversation.py
class ConversationGraph:
    """The native message tree of one conversation, worked out once.

    Why one class: the active path was planned in three places (adapter,
    BranchClassifier, integrity checker) plus the spike loader. M3's evidence
    checks depend on message numbers being stable, so they must be defined once.
    """
    @classmethod
    def from_mapping(cls, mapping: Mapping[str, dict], current_node: str | None) -> "ConversationGraph": ...
    active_path: tuple[str, ...]                 # native node IDs, root → current_node
    def message_number(self, node_id: str) -> int | None: ...   # 1-based position on the active path; None off-path
    branch_points: tuple[BranchPoint, ...]       # parent, children, kind: edit | regeneration | other
    def alternate_paths(self) -> Iterator[tuple[str, ...]]: ... # never spliced into the active path
    issues: tuple[GraphIssue, ...]               # missing parent, cycle, duplicate ID, orphan; content kept
```

Internal: children rebuilt from `parent` when `children` is missing (the `no_children` fixture), fork kind from sibling roles (user siblings = edit, assistant siblings = regeneration), cycle and orphan detection. `graph/nodes.py` turns one native node into a `CanonicalNode` (role, content parts, asset pointers, unknown payload kept) and computes `raw_payload_hash` and `canonical_content_hash` (OD-13 default: role + content parts + create_time).

Callers: the import module (to know nodes, edges and revisions), rendering and `ke inspect` (to show the active path and labelled alternates), and later M3 (message numbers). Nobody else walks the tree.

### 2.2 Import (one interface)

```python
# importer/__init__.py
def import_source(
    path: Path,
    account_ns: str,
    *,
    format: str | None = None,          # None = probe; "chatgpt-export-v1" | "chatgpt-split-v1"
    settings: Settings | None = None,
) -> ImportReport: ...

@dataclass(frozen=True)
class ImportReport:
    import_id: str
    status: ImportBatchStatus                     # succeeded | partial | failed
    conversations: Mapping[DeltaCategory, int]    # new, unchanged, revised, new_branch, not_seen, candidate_duplicate, failed
    messages: Mapping[DeltaCategory, int]
    media: MediaCounts                            # new_blobs, reused_blobs, occurrences, missing, ambiguous, unresolved
    integrity: IntegrityCounts                    # ING-007: source counts vs stored counts, unsupported fields
    warnings: tuple[ImportWarning, ...]           # codes and counts only, no private text
    changed_revisions: tuple[str, ...]            # message_revision IDs that are new or revised: the only outward seam
    raw_tree_hash_before: str
    raw_tree_hash_after: str                      # must equal "before"; import fails if not
    model_calls_triggered: int                    # always 0 in M1
```

Hidden inside: probing and choosing an adapter, snapshot hashing and dedup (ING-001, IMP-001), logical identity and candidate matches (IMP-002), revisions and delta categories (IMP-003), transactions (IMP-004), media (MED-001..003), the integrity reconciliation (ING-007) and building the report (IMP-005). `ke imports report latest` reads a stored report; it doesn't recompute anything.

The review sketched a second public function, `resume(import_id)`. It's not needed: resuming an interrupted import is running `import_source` again on the same path, which is idempotent (§5.3).

### 2.3 Source adapter seam (narrow)

```python
# ingestion/source.py
class SourceAdapter(Protocol):
    format_id: str                                     # "chatgpt-export-v1", "chatgpt-split-v1"
    def probe(self, path: Path) -> ProbeResult: ...    # cheap: reads file names and first keys only
    def open(self, path: Path) -> SourceListing: ...

@dataclass(frozen=True)
class SourceListing:
    files: tuple[SourceFile, ...]                      # every input file with its SHA-256 (for snapshots)
    media_files: MediaFileIndex                        # asset files found next to the export
    warnings: tuple[ImportWarning, ...]                # fidelity warnings, e.g. split format lacks account ID
    def conversations(self) -> Iterator[NativeConversation]: ...   # streamed, never all in memory

@dataclass(frozen=True)
class NativeConversation:
    native: Mapping[str, Any]                          # the conversation object exactly as exported
    locator: SourceLocator                             # which file / shard / ZIP entry it came from
    warnings: tuple[ImportWarning, ...]                # e.g. wrapper title disagrees with native title
```

Both adapters yield the same `NativeConversation`. Neither parses messages: that happens once, in `graph/`. This is why ING-011's "same conversations via the split format give the same logical records" check becomes a short equality test. The four later adapters (Document, Markdown, Transcript, WebPage) stay out of the M1 port until a milestone needs them.

### 2.4 Rendering (unchanged)

DOC-002, MED-004 and BRW-001 keep their plan. They read stored records plus a `ConversationGraph` built from stored nodes, and never write knowledge.

## 3. Dataflow after consolidation

```text
ke import <path> --account-ns <ns>
  └─ import_source(path, ns)                                   [importer]
       ├─ RawInventory.tree_hash(path)          (before)        [ingestion]
       ├─ adapter.probe / open → SourceListing                  [ingestion]
       ├─ snapshot per file hash (reuse if seen)                [importer/ledger, archive]
       ├─ for each batch of NativeConversation:
       │    ├─ ConversationGraph.from_mapping(...)              [graph]
       │    ├─ keys, revisions, delta categories                [importer/identity, delta]
       │    ├─ asset pointers → blobs/assets/occurrences        [importer/media]
       │    └─ one transaction (BEGIN IMMEDIATE) per batch      [importer/commit]
       ├─ not_seen marking for conversations absent this time
       ├─ RawInventory.tree_hash(path)          (after)
       └─ ImportReport (stored, returned)       ── changed_revisions ──► M3 later
```

Direct function calls only. No events.

## 4. The one test that owns the re-import guarantee

**`tests/integration/test_import_source.py::test_identical_reimport_adds_nothing`**, testing the `importer` module through `import_source` only.

It imports `tests/fixtures/chatgpt/reexport_v1` into a fresh workspace, snapshots the row count of every logical table (conversations, message_nodes, message_revisions, graph_edges, media_blobs, media_assets, asset_occurrences, identity_candidates, jobs), imports the same path again and asserts:

- the second report has every conversation and message in `unchanged`, and zero in every other category;
- `changed_revisions` is empty and `model_calls_triggered == 0`;
- every logical table has exactly the same row count (only `import_batches` gains one row, as IMP-001 requires);
- no new rows in `jobs` (nothing downstream was queued);
- raw tree hash before == after, for both runs.

Its property-based sibling, `tests/property/test_import_idempotence.py`, calls the same function over random repeat/permute sequences of generator output (IMPLEMENTATION_PLAN §7). These are new tests; no existing test or acceptance criterion changes.

## 5. Deferred, and what replaces it

| Planned | Replaced in M1/M2 by | Add it back when |
|---|---|---|
| In-process events and outbox (`ARCHITECTURE.md` §7.2: seven events incl. `ConversationDeltaCommitted`, `MediaOccurrencesCommitted`) | Direct calls inside the import module, plus `ImportReport.changed_revisions` as the one outward hand-off to the semantic layer | A second consumer appears that can't be a direct call, or work moves to a separate worker process |
| Separate single-writer import lock (`acquire_lock` / `LockToken`) | SQLite's own writer lock: each batch transaction opens with `BEGIN IMMEDIATE`, and unique constraints on the ADR-0003 logical keys make a duplicate insert impossible. A second `ke import` started at the same time waits, then sees the first one's rows as `unchanged`, or fails cleanly with a busy error | A second process genuinely writes the same workspace (API, watcher, worker) |
| Checkpoint-based crash resume (`resume(import_id)`, checkpoint rows) | Per-batch transactions: a crash loses only the uncommitted batch, and the batch row stays `running` and is marked `abandoned` by the next run. Resume = run the same import again; committed conversations come back `unchanged`, so it converges on the same final state | A single import takes long enough that re-scanning committed batches costs real time (measure in EVAL-010 at 100 real conversations) |

ADR-0003 still holds: it asks for a single-writer lock (SQLite's writer lock is one) and for interrupted batches to resume from the last committed point (re-running does exactly that, because committed batches are skipped as unchanged). No ADR is superseded. `ARCHITECTURE.md` §7.2 and the dataflow in `IMPLEMENTATION_PLAN.md` §2 describe the deferred design and should get a one-line pointer to this note when the foundation thread applies it.

## 6. M1 ticket mapping

Every M1 ticket keeps its ID and issue. "Closes with" names the behaviour slice whose test demonstrates the ticket's acceptance criterion; a ticket closes when its slice's finish line passes. Slices are cut by behaviour visible at a module's interface, and each is one PR of one or two tickets (REV-005).

| # | Ticket | Issue | Module | Closes with |
|---|---|---|---|---|
| 1 | FND-001 bootstrap | #10 | foundation | F (done in PR #3) |
| 2 | FND-002 settings | #11 | foundation | F (done) |
| 3 | FND-003 SQLite engine | #12 | foundation | F (done) |
| 4 | FND-004 Alembic baseline | #13 | foundation | F (done) |
| 5 | FND-005 domain + IDs | #14 | foundation | F (done) |
| 6 | FND-006 jobs, stage keys | #15 | foundation | F (done) |
| 7 | FND-008 CLI skeleton | #16 | foundation | F (done) |
| 8 | OPS-008 git guard | #17 | foundation | F (done) |
| 9 | EVAL-009 fixtures | #18 | foundation | F (done) |
| 10 | ING-001 archive store | #19 | importer (`archive`) | I1 |
| 11 | SRC-001 raw inventory | #20 | ingestion (`inventory`) | S0 |
| 12 | ING-002 adapter port | #21 | ingestion (`source`) | A1 |
| 13 | IMP-001 batch ledger | #22 | importer (`ledger`) | I1 |
| 14 | ING-003 coordinator → `import_source` | #23 | importer (`run`) | I2 |
| 15 | ING-004 export layouts | #24 | ingestion (`chatgpt_export`) | A1 |
| 16 | ING-005 mapping parser | #25 | graph | G1 |
| 17 | ING-006 content + attachments | #26 | graph (`nodes`) | G3 |
| 18 | ING-011 split adapter | #27 | ingestion (`chatgpt_split`) | A2 |
| 19 | ING-007 integrity counts | #28 | importer (`report`) | I6 |
| 20 | NRM-001 canonical node + hashes | #29 | graph (`nodes`) | G3 |
| 21 | NRM-002 graph integrity | #30 | graph | G2 |
| 22 | REL-001 branch kinds | #31 | graph | G2 |
| 23 | IMP-002 identity resolver | #32 | importer (`identity`) | I2 (keys), I4 (candidates) |
| 24 | IMP-003 delta engine | #33 | importer (`delta`) | I3 |
| 25 | IMP-004 commit / lock / resume | #34 | importer (`commit`) | I2 (repeat), I5 (concurrent + crash) |
| 26 | MED-001 media model | #35 | importer (`media`) | M1 |
| 27 | MED-002 pointer resolver | #36 | importer (`media`) | M2 |
| 28 | MED-003 media dedup | #37 | importer (`media`) | M1 |
| 29 | IMP-005 delta report | #38 | importer (`report`) | I6 |
| 30 | EVAL-010 batch smoke | #39 | evaluation | E |
| 31 | DOC-002 renderer core | #40 | rendering | R1 |
| 32 | MED-004 embeds | #41 | rendering | R2 |
| 33 | BRW-001 source browser | #42 | rendering + cli | R3 |
| — | REV-009 real-data checkpoint | #143 | cli (`ke inspect`, read-only) | after G1 |

A ticket split across two slices (IMP-002, IMP-004) closes when its second slice lands.

### 6.1 The slices, in order

| Slice | Tickets | Behaviour at the interface (finish line) |
|---|---|---|
| S0 | SRC-001 | `ke raw inventory <fixture>` prints counts and a tree hash; the tree is byte-identical afterwards |
| G1 | ING-005 | `ConversationGraph.from_mapping` gives the expected active path and message numbers for every EVAL-009 fixture, including `no_children` |
| G2 | REL-001, NRM-002 | `branches_edit` / `branches_regen` give the right branch kinds; an adversarial mapping gives explicit `issues` and loses no node (Hypothesis DAG test) |
| G3 | ING-006, NRM-001 | content parts and asset pointers extracted; unknown payload round-trips; `metadata_drift` changes the raw hash but not the content hash |
| A1 | ING-002, ING-004 | the official adapter lists the same `NativeConversation`s from `export_single`, `export_sharded` and `export_zip`; malicious ZIP names are rejected |
| A2 | ING-011 | split-wrapper and official fixtures give equal `NativeConversation.native` objects |
| I1 | ING-001, IMP-001 | same file bytes twice → one snapshot, two batch rows; corrupted checksum is rejected |
| I2 | ING-003, IMP-002 (keys), IMP-004 (repeat) | `import_source` exists; `test_identical_reimport_adds_nothing` passes (§4) |
| I3 | IMP-003 | `reexport_v1` then `reexport_v2` reports exact new / revised / new_branch / not_seen; the absent conversation is still there as `not_seen` |
| I4 | IMP-002 (candidates) | `id_collision`: same native ID, different content → candidate match, no merge; identical titles stay distinct |
| I5 | IMP-004 (rest) | a crash injected mid-run, then a re-run, ends in the same state as one clean run; two concurrent `ke import` processes give the same counts as one |
| M1 | MED-001, MED-003 | same image in two conversations → one blob, two occurrences; re-import adds none |
| M2 | MED-002 | `asset_problems`: missing, ambiguous and unresolved pointers reported with evidence, no invented path |
| I6 | ING-007, IMP-005 | `ke imports report latest` matches each fixture manifest exactly, as JSON and text, without private content |
| R1–R3 | DOC-002, MED-004, BRW-001 | as planned; DOC-002 can go any time |
| E | EVAL-010 | 50 and 100 conversations, synthetic and real (read-only), counts and timings only |

The G1 demonstration in `IMPLEMENTATION_PLAN.md` §6 is unchanged: it is now simply the sequence of `import_source` calls these slices make pass.

### 6.2 Critical path, before and after

Before (12): FND-001 → FND-002 → FND-003 → ING-001 → ING-002 → ING-004 → ING-005 → NRM-001 → IMP-003 → IMP-004 → IMP-005 → BRW-001.
After (by slice): F → G1 → A1 → I1 → I2 → I3 → I5 → I6 → R3. Graph slices (G1–G3) have no database dependency, so they can start straight away, and REV-009's real-data checkpoint can run as soon as G1 lands.

GitHub's "blocked by" lines on the issues still describe the old per-class chain. They stay valid as a conservative order; the foundation thread may work a later slice early when its tests only need already-merged slices.

## 7. What changes in PR #3

Nothing needs rewriting. Checked against branch `claude/project-thread-q0du34` at `03be5c5`:

- `domain/ids.py`: all ADR-0003 keys are already there and stay as they are (`snapshot_id`, `conversation_id`, `message_node_id`, `message_revision_id`, `graph_edge_id`, plus ADR-0004's `media_asset_id` and `asset_occurrence_id`).
- `domain/enums.py`: `DeltaCategory`, `PresenceState`, `ImportBatchStatus` (its `abandoned` value is exactly what a re-run marks a crashed batch as), `AssetAvailability`, `BranchKind`: unchanged.
- `settings.py`, `infrastructure/db.py`, `workspace.py`, migrations `0001`/`0002`, `jobs.py`, `orchestration/stage_keys.py`, `cli/main.py`, `devtools/git_guard.py`, all fixtures: unchanged.
- Folder names: create `graph/` and `importer/` instead of `identity/`, `media/` and `relationships/` when those tickets start. No existing file moves.
- `STATUS.md` says "ING-002 onwards waits for the owner's call on that proposal". With this note merged, that wait is over; the foundation thread updates that line itself (it owns `STATUS.md`).
- Boundary rule in `IMPLEMENTATION_PLAN.md` §1, "Only `orchestration` sequences stages", now reads as: across layers. The importer sequences its own internals.

## 8. Not decided here

- OD-01 (is the original export ZIP still available) and OD-03 (account namespace for the split format) are unchanged; `account_ns` is a required argument either way.
- Whether to add the event outbox, the lock or checkpoints later: §5 gives the trigger, not the decision.
- M2 module shapes (links, YouTube, social, structural relationships). Expect the same pattern: called directly from the importer for changed revisions only.
