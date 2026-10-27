# Decision Records, Change History, Deferrals and Non-Events
## Record types
1. **ADR** (`docs/adr/NNNN-title.md`): consequential architecture/product decision; Context → Decision → Alternatives → Consequences → Status → Supersedes.
2. **Decision Log** (`.agent-history/DECISION_LOG.md`): smaller specific engineering choices with date, ticket, why, alternatives, scope and references.
3. **Status** (`.agent-history/STATUS.md`): ticket status and blocker reasons; updated when verified transition occurs.
4. **Session Log** (`.agent-history/SESSION_LOG.md`): actual modifications, test commands/results, files changed, issues and next task.
5. **Deferred** (`.agent-history/DEFERRED.md`): intentionally unimplemented ideas and rationale, owner, reopen conditions and linked ticket.
6. **Changelog** (`CHANGELOG.md`): user-visible release changes, not a log of every agent thought.
7. **Handoff** (`HANDOFF.md`): single latest machine/human-readable state of repo and next unblocked ticket.

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
