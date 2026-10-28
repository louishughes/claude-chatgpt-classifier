# The JSON API

`ke api` serves the engine's data as JSON for scripts and other programs. The web pages for a person are `ke ui`. Code: `src/knowledge_engine/api/`.

```
pip install -e ".[server]"     # FastAPI and uvicorn, only needed for the API
ke api                          # http://127.0.0.1:8766/api/v1/docs (Ctrl+C to stop)
```

## Rules for every endpoint

- **Versioned.** Everything is under `/api/v1`. The OpenAPI document is at `/api/v1/openapi.json`, and its `info.version` is the package version (`CHANGELOG.md`). A breaking change gets `/api/v2`; `v1` keeps working.
- **This computer only.** The server listens on 127.0.0.1 and nothing else. A request whose `Host` header isn't a loopback name (`127.0.0.1`, `localhost`, `[::1]`) is refused with `host_not_local`, which stops a web page elsewhere reaching the API through a DNS trick. No CORS headers are sent, so other sites' scripts can't read answers. There is no login: anyone who can run programs as you on this computer can already read your workspace. Accounts come with PROD-002.
- **One error shape.** Every failure is:

  ```json
  {"error": {"code": "schema_mismatch", "message": "one sentence for a person"}}
  ```

  Programs branch on `code`, which never changes meaning. Messages never repeat what was sent (it may be private text) and never include a traceback.

| Code | HTTP | Meaning |
|---|---|---|
| `invalid_request` | 422 | A parameter is missing or the wrong type. The message names the fields, not the values. |
| `not_found` | 404 | No such path (or, in later endpoints, no such record). |
| `method_not_allowed` | 405 | Wrong HTTP method for the path. |
| `host_not_local` | 400 | The request didn't name this computer. |
| `origin_not_local` | 403 | A POST came from a page on another site. |
| `json_required` | 415 | A POST body wasn't `application/json` (what an HTML form on another site would send). |
| `source_not_found` | 400 | `POST /imports`: the file or folder doesn't exist. The path is never repeated. |
| `source_in_workspace` | 400 | `POST /imports`: the path is inside the workspace, not an export. |
| `invalid_account` | 400 | `POST /imports`: account labels use letters, numbers, `-` and `_` only. |
| `no_database` | 503 | Nothing has been imported into this workspace yet. |
| `schema_mismatch` | 503 | The database is older than the code (run `ke db upgrade`) or from a newer version (OPS-007). |
| `internal_error` | 500 | An unexpected failure. Nothing about it is returned. |

## Endpoints (API-001)

| Method and path | Answers |
|---|---|
| `GET /api/v1/health` | `{"status": "ok", "version", "api_version"}`. Opens nothing. |
| `GET /api/v1/status` | The version, the database's schema revision and the newest one, which egress switches are on, and which model provider would be used and whether egress allows it. No folder paths. Works on a database of any version, so a program can see why other endpoints refuse. |
| `GET /api/v1/counts` | Conversations stored, present, not seen in the latest export, and imports. Numbers only. |

## Imports, jobs and sources (API-002)

| Method and path | Answers |
|---|---|
| `POST /api/v1/imports` | Body `{"source": "<export folder or ZIP>", "account": "label" (optional), "partial": false}`. Starts the import in the background and answers **202** at once with the job: `{"job_id", "state": "running", "import_id": null, "status": null, "error": null}`. It never waits for the import. The source is only read; the workspace lock still allows one import at a time. |
| `GET /api/v1/jobs/{job_id}` | The job: `state` is `running`, `done` (with `import_id` and the import's `status`) or `failed` (with `error`, a plain reason without paths). Jobs live in memory and are forgotten when the API restarts; the imports themselves are in the ledger. |
| `GET /api/v1/imports` | Past imports, newest first, with conversation counts. Paged. |
| `GET /api/v1/imports/{import_id}` | One import's stored report: `status` (`succeeded`, `partial`, `failed`...), counts, `summary` and `warnings` by kind. `partial` means some chats failed or were set aside, and the warnings say which kinds and how many. |
| `GET /api/v1/sources` | Stored conversations, newest first: ID, title, created, presence (`present` / `not_seen`), message count. `q` filters by title words. Paged. |
| `GET /api/v1/sources/{conversation_id}` | One conversation: native ID, title, presence, `current_node`, `branch_points` (parent, kind `edit` / `regeneration` / `other`, children, active child), graph `issues` by code, media uses, and related chats with their direction and review state. |
| `GET /api/v1/sources/{conversation_id}/nodes` | Its messages in transcript order: the active path, then each alternate branch, then anything a damaged tree left outside (`section`). Each message appears once, with `parent_id` and `children` so the tree can be rebuilt, its logical `node_key` and `revision_id`, role, content type, time, text, and media uses (`availability`, `blob_sha256` when the bytes are stored). The empty root node isn't listed but is still named as a parent. Paged. |

**Paging.** Lists take `offset` (from 0) and `limit` (1–500; default 100, or 50 for imports) and answer `{"items": [...], "total", "offset", "limit", "next_offset"}`. `next_offset` is null on the last page.

**Cross-site requests.** Anything but GET must have an `application/json` body, and if it has an `Origin` header that must be this computer. A web page on another site can make the browser send a form or plain text to 127.0.0.1, but not JSON (that needs a CORS preflight, which this API never grants).

Taxonomy, review, search, answer and document endpoints follow in API-003..005.

## Swapping parts in tests

`create_app(settings)` builds the app. Every endpoint gets the settings, the database and the model provider from *dependencies* (`get_settings`, `get_sessions`, `get_provider` in `api/app.py`), so a test replaces them:

```python
app = create_app(settings)
app.dependency_overrides[get_settings] = lambda: temporary_workspace_settings
app.dependency_overrides[get_provider] = lambda: FakeProvider(answer)
client = TestClient(app, base_url="http://127.0.0.1:8766")
```

The default provider is the file-batch one (ADR-0009). It writes nothing while `[egress] text_llm` is off. `tests/integration/test_api.py` shows each rule above.
