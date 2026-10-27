# Decision Records, Change History, Deferrals and Non-Events
## Record types
1. **ADR** (`docs/adr/NNNN-title.md`): consequential architecture/product decision; Context → Decision → Alternatives → Consequences → Status → Supersedes.
2. **Decision Log** (`.agent-history/DECISION_LOG.md`): smaller specific engineering choices with date, ticket, why, alternatives, scope and references.
3. **Status** (`.agent-history/STATUS.md`): ticket status and blocker reasons; updated when verified transition occurs.
4. **Session Log** (`.agent-history/SESSION_LOG.md`): actual modifications, test commands/results, files changed, issues and next task.
5. **Deferred** (`.agent-history/DEFERRED.md`): intentionally unimplemented ideas and rationale, owner, reopen conditions and linked ticket.
6. **Changelog** (`CHANGELOG.md`): user-visible release changes, not a log of every agent thought.
7. **Handoff** (`HANDOFF.md`): single latest machine/human-readable state of repo and next unblocked ticket.

### Canonical locations *(audit amendment 2026-10-27)*
None of the files above existed when the audit ran, except this document. Proposed canonical locations, matching `docs/agents/domain.md`: ADRs in `docs/adr/` (created by the audit, see `docs/adr/README.md`); agent history in `.agent-history/` at the repo root (create on first implementation session); the latest handoff in `docs/HANDOFF_AFTER_AUDIT.md` until the first ticket starts, then `HANDOFF.md` at the root; `CHANGELOG.md` at the root once there is a user-visible release. The build-in-public diary requested by the owner lives in `docs/diary/BUILD_DIARY.md`. Owner decision OD-11 covers whether to restore the original package's skills and history files.

## Status semantics
`NOT_STARTED`: planned and untouched. `IN_PROGRESS`: code/ticket actively underway. `BLOCKED`: cannot satisfy acceptance until named dependency/issue resolved. `REVIEW_REQUIRED`: semantic/human judgement unresolved. `VERIFIED`: all acceptance criteria and required commands passed with evidence. `DEFERRED`: consciously postponed. `CANCELLED`: explicit removal from roadmap. `FAILED`: bounded attempt did not meet acceptance. `UNKNOWN`: insufficient evidence of what happened. Do not claim a task did not happen merely because no log exists.

## Exact record schema
```yaml
id: ADR-0001
kind: architecture_decision
status: accepted
recorded_at: 2026-10-27
scope: storage/local-mvp
decision: Use SQLite with FTS5 initially.
context: Need local-first, simple setup, eventual path to multi-user.
alternatives: [PostgreSQL day one, multi-service vector stack]
consequences: [simple local backup, later migrations needed]
supersedes: []
related_tickets: [FND-003, RET-001]
```
For session entries include: current commit/branch, ticket ID, **actual changed paths**, commands and exit codes, benchmark version, how many test failures remain, blockers, intentionally untouched tasks, next exact action.

## Supersession
Never edit history to pretend old decision never existed. Write a new ADR/decision with `supersedes: [ID]` and a scoped explanation. Preserve both. Database/domain events follow the same append-only pattern. A rollback changes currently published pointer, not earlier evidence.

## 'What hasn't happened' handling
- `not_started` is supported by a ticket created but never started.
- `deferred` has explicit rationale and reopen condition.
- `cancelled` has an explicit product decision.
- `blocked` has an identifiable blocker ID and owner.
- `unknown` means no decisive evidence; do NOT turn absence into a negative fact.
- Distinguish 'test not run', 'test failed', 'implementation not written', 'feature intentionally omitted', and 'source does not contain the feature'.

## Review and append-only workflow
Each ticket close:
1. Check dependencies/status and acceptance evidence.
2. Update status and append session record (do not rewrite earlier sessions).
3. If architecture changes, create ADR; if small choice, append decision log.
4. Move delayed requirements to deferred with rationale; explicitly state what is *not* done.
5. Update handoff next exact ticket and current workspace state; never write optimistic completion claims.

## Protection
Agents cannot edit a decision's rationale retroactively without preserving earlier revision. Review corrections are new audited operations (who, when, what evidence), and source data remains untouched unless legitimately removed through documented deletion workflow.

## Project history *(added 2026-10-27 from the product owner's account; not independently verified)*
Recorded so later decisions can be read against what already failed. These are the owner's descriptions, kept as context rather than requirements.
- **First proof of concept:** an early workflow built with Hermes and DeepSeek models, with some local pre-analysis before model calls.
- **Codex-built version:** used a model the owner calls "Luna" for part of the classification. Results were inconsistent.
- **Root cause as the owner sees it:** local models were weak at extracting key information, and their output was not type-safe, so results varied between runs.
- **Smoke tests:** one conversation at a time gave inconsistent output; API/model timeouts occurred via OpenRouter; batches of 20–50 conversations had many failures.
- **Leftovers in `raw/`:** two small derived JSON files (a classification output and an archive validation result) sit inside `raw/conversations/`. They look like outputs of the earlier attempt (inferred from their key structure only) and are excluded from import (ADR-0002, OD-09).
- **Responses in this plan:** ADR-0007 (cloud-capable models with schema-enforced output and measured stability), TR-16, FND-009, EVAL-010/EVAL-011 batch smoke gates at 50 and 100.

## ADR index
See `docs/adr/README.md`. ADR-0002..ADR-0008 were proposed by the 2026-10-27 specification audit and await owner approval.
