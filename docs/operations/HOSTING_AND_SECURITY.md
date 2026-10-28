# Hosting and security review (PROD-004)

**Scope.** This covers the engine when it serves more than one person: `ke api` with `tenants_root` set (PROD-003, ADR-0011), accounts and roles (PROD-002), and an optional PostgreSQL backend (PROD-001, a proof of concept). One person using `ke` on their own computer is the default and needs none of this.

**Status.** The threat model and controls below were written and checked against the code and its tests on 2026-10-28. Nobody independent has reviewed them yet, and this is **not legal advice**. Before anyone else's data goes into a hosted engine, have someone independent go through the threat model and get a data-protection opinion on the UK GDPR section.

## 1. What is being protected

| Asset | Where it lives | Why it matters |
|---|---|---|
| Imported chats, images, extracted knowledge | each workspace folder (`knowledge.db`, `archive/`, `media/`, indexes, `exports/`) | private, often personal data about third parties too |
| API tokens | shown once; only their SHA-256 is stored (`account_tokens`) | a token is a login |
| Model API key | environment only (`KE_ANTHROPIC_API_KEY`), never `ke.toml` or git | it spends money |
| Model request batches | `model_batch_root` (git-ignored) | they hold chat text sent for a model step |
| Backups | `ke backup` folders, wherever the operator keeps them | full copies of everything above |
| Logs | `<workspace>/logs/*.jsonl`, `authz_events` | IDs and counts only, by design (OPS-001) |

## 2. Threat model

| # | Threat | Control | Checked by |
|---|---|---|---|
| T1 | Someone on the network calls the API | `ke api` listens on 127.0.0.1 only; non-loopback `Host` refused (DNS rebinding) | `test_api.py` |
| T2 | A web page in the user's browser drives the API | non-GET needs JSON and a local `Origin`; no CORS headers | `test_api.py` |
| T3 | A caller without a token | once accounts exist, 401 on every route but `/health`; hosted workspaces never run open | `test_api_access.py`, `test_tenant_isolation.py` |
| T4 | A user reads another workspace | one folder per workspace, chosen once per request; foreign tokens unknown there | `test_tenant_isolation.py` (folder byte-identical after an adversarial run) |
| T5 | A user imports another workspace's files | hosted imports only from that workspace's inbox, resolved before use | `test_tenant_isolation.py` |
| T6 | A user acts under someone else's name | `reviewer`/`proposer` must equal the caller | `test_api_access.py` |
| T7 | Automation promotes its own output to trusted | service accounts can't hold reviewer or owner | `test_api_access.py` |
| T8 | A stolen database or backup is used to log in | tokens stored as SHA-256 only | `test_api_access.py`, `test_hosting_security.py` |
| T9 | A leaked token keeps working | `ke access rotate` / `revoke` / `disable` take effect on the next request | `test_hosting_security.py` |
| T10 | Imported text tries to instruct the model or forge a message | source-as-data quoting (OPS-006) | `test_adversarial.py`, `docs/operations/SOURCE_AS_DATA.md` |
| T11 | Private text leaks through errors or logs | errors never echo input; logs hold IDs and counts; the authz log stores the route, never the query | `test_api.py`, `test_api_access.py`, `test_structured_logs.py` |
| T12 | Data leaves the machine unexpectedly | egress off by default; a provider that sends data needs its switch on | `test_anthropic_provider.py`, `test_segment_classifier.py` |
| T13 | Deleted data comes back on the next import | purge tombstones (ADR-0010) | `test_purge.py` |
| T14 | An admin's delete reaches outside its workspace | `ke tenant delete` needs the name twice, refuses links pointing outside `tenants_root` | `test_hosting_security.py` |

**Accepted for now.** Anyone who can run programs as the operator can read every workspace folder: this is not a defence against the machine's own administrator. There is no rate limiting and no TLS, because the API only listens on this computer. Putting it on a network needs a reverse proxy with TLS and rate limits in front, and re-reading T1 and T2.

## 3. Secrets

- **Model API key:** only in the environment of the one command that needs it (as for the EVAL-011 paid run), never in `ke.toml`, `.env` in the repository, or a log. The commit guard refuses `ke.toml` and `.env`. CI strips every key from the checks' environment.
- **API tokens:** `ke access token NAME` prints a token once. Hand it over by a channel the person controls; never paste one into a chat, an issue or a document.
- **Rotation:** `ke access rotate NAME` revokes all of that account's tokens and prints one new one. Rotate on any suspicion, when a device is lost, and when a person leaves. For the model key, make a new key with the provider, use it, then revoke the old one there.

## 4. Backups

- Back up each workspace on its own: `KE_WORKSPACE_ROOT=<tenants_root>/workspaces/<name> ke backup create --to <backups>/<name>`. Verify with `ke backup verify` and practise a restore (`docs/runbooks/UPGRADE_AND_ROLLBACK.md`).
- Backups are full copies, including token hashes and the authorisation log. Store them with the same care as the workspace, and keep them for a fixed time (suggested: 30 days), deleting older ones. A deletion (§5) doesn't reach existing backups; they age out.

## 5. Deleting a person's data

| Request | Command | What remains |
|---|---|---|
| Remove a person's login | `ke access delete NAME --confirm NAME` | the authorisation log keeps rows under a random ID that nothing links to a name any more (`deleted-1a2b3c4d`) |
| Remove some conversations | `ke purge plan` then `ke purge run --confirm TOKEN --reason ...` (ADR-0010) | tombstones (hashes) and a counts-only purge log |
| Remove a whole workspace | `ke tenant delete NAME --confirm NAME` | nothing in the engine; existing backups until they age out |

Known limit: reviews and decisions record the reviewer's name as part of the knowledge history (`reviewer` fields). Deleting an account doesn't rewrite that history. Deleting the workspace, or purging the conversations those reviews were about, does remove it.

## 6. UK GDPR review (not legal advice)

- **Personal use.** One person processing their own chats for themselves is likely within the household exemption (UK GDPR Art. 2(2)(a) as retained, "purely personal or household activity"). The chats can still contain other people's personal data, so the engine stays local-first and private by default.
- **Hosting for others** makes the operator a controller, or a processor for each user, so UK GDPR applies in full. Before that:
  - choose a lawful basis (likely contract or consent) and publish a privacy notice;
  - run a DPIA: chats can hold special-category data about the user and third parties;
  - have a processing agreement with any model provider the data goes to (egress stays off unless the user opts in);
  - keep a record of processing;
  - meet the 72-hour breach notification duty to the ICO.
- **Data subject rights** the engine can serve now:
  - access and portability: `ke docs vault` export and the API;
  - rectification: corrections and review;
  - erasure: §5;
  - restriction: disable the account and stop processing.
- **Minimisation and retention:** only what the user imports is stored. Raw exports are never modified. Logs hold no text. Retention of backups is the operator's policy (§4).
- **International transfers:** none unless a cloud model is switched on. That provider's terms then decide where data goes.

## 7. Release checklist (hosted)

1. CI is green on Linux and Windows. The nightly release check passes: clean install, upgrade with backup, rollback (OPS-007).
2. `CHANGELOG.md` has the version, and `ke --version` matches.
3. Back up every workspace, verify the backups, then run `ke db upgrade` in each workspace folder.
4. `ke tenant list` shows the expected workspaces. Every hosted workspace has an owner (`ke access list` in each).
5. No secret in `ke.toml`, the repository or the environment file of the service; the model key appears only where a model step runs.
6. `ke api` is bound to 127.0.0.1. Any network exposure goes through a TLS proxy with rate limits.
7. Spot-check isolation: a token from one workspace gets 401 on another.
8. Record the release in the diary with the commands run and their results.
