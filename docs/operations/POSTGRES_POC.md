# PostgreSQL proof of concept (PROD-001)

**Status:** proof of concept. SQLite stays the default and the only supported
backend for everyday use. This page records what runs on PostgreSQL today,
what was measured, and what still assumes SQLite.

## What was ported

| Piece | How it works on PostgreSQL |
|---|---|
| Schema (all 28 migrations) | The same Alembic migrations run unchanged, except the "refuse this change" triggers. `infrastructure/dialects.py` turns each SQLite trigger into one shared plpgsql function `ke_refuse_change()` plus a `CREATE TRIGGER ... FOR EACH ROW` that calls it with the same message. Any trigger shape it doesn't recognise raises, so a new migration can't silently lose its guard. |
| Importer | `run_import(..., database_url="postgresql+psycopg://...")` writes the database rows to PostgreSQL. The source archive, the import lock and the search index stay in the workspace folder. |
| Lexical query contract | Kept as is: the FTS5 search index was already a rebuildable cache file, and `sync_index` fills it from whichever database the session points at. Search results are identical on both backends. |
| Driver | psycopg 3 (`pip install -e ".[postgres]"`). `create_postgres_engine()` accepts only `postgresql+psycopg://` URLs. |

## Evidence

`tests/integration/test_postgres_backend.py` (16 tests) starts a throwaway
PostgreSQL server (`devtools/postgres.py`: `initdb` into a temporary folder,
listening on 127.0.0.1 only, deleted afterwards) and checks:

- 12 synthetic import fixtures, each imported twice into SQLite and into
  PostgreSQL: the import reports match (ignoring IDs and clock times), every
  table has the same row count, the same native conversations and message
  content hashes exist, and the same search hits come back;
- a re-export (v1 then v2) produces the same delta report on both;
- the migrations match the models (no drift), downgrade to empty and
  upgrade again;
- a guarded table (`purge_events`) refuses a delete on PostgreSQL;
- an unrecognised trigger shape is refused.

The tests skip, rather than fail, when no PostgreSQL binaries are found or
when run as root (PostgreSQL refuses to start as root). Set
`KE_TEST_POSTGRES_URL` to use an existing server instead.

Result in the build container, as a non-root user: **16 passed** (about 23 s).

## Benchmark

`python -m knowledge_engine.evaluation.backend_bench --conversations 200`
generates a synthetic export and times both backends. Measured in the build
container (PostgreSQL 16 on the same machine, so no network time):

| Step | SQLite | PostgreSQL |
|---|---|---|
| First import (200 conversations, 9,609 rows) | 7.3 s | 18.9 s |
| Repeat import (all unchanged) | 4.9 s | 11.0 s |
| Search index rebuild | 0.14 s | 0.15 s |
| 8 searches | 0.010 s | 0.011 s |

Row counts and search hits (120) were equal. PostgreSQL is about 2.5 times
slower to import, because the importer makes many small queries and each
one is a round trip to a server process instead of a function call. That is
fine for a nightly import; batching those queries is the first thing to do
if hosted scale ever needs it.

## Still SQLite-only (known gaps)

- **CLI, UI and API** open the workspace's `knowledge.db` through
  `database_path`; none of them takes a database URL yet.
- **Purge** (`retention/purge.py`) uses the `sqlite3` module directly for
  `VACUUM` and file-level checks.
- **Backup and restore** copy the SQLite file; PostgreSQL would need
  `pg_dump`/`pg_restore`.
- **`ke db upgrade`** backs up and migrates the SQLite file only.
- Downgrading to base leaves the `ke_refuse_change()` function behind (it is
  harmless and the next upgrade replaces it).

None of these change trust or mutate sources: they just haven't been ported.

## Talking points

- "The same migrations and importer run on SQLite and PostgreSQL, and a test
  proves twelve fixtures give identical results on both."
- "Search didn't need porting: its index was always a rebuildable cache."
