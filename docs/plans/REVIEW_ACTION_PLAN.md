# Action plan from the direction review (27 Oct 2026)

**Source:** the independent direction review (verdict: adjust, not rethink). Diary entry 21:55. Report shared in the project thread.
**Status:** adopted. The owner asked for tickets and a plan and for agents to implement them (22:10 UTC), and gave blanket authority for the night ("do not ask me anything, you have all the access and authority needed"). Decisions taken under that authority are marked *owner authority 22:10* so he can reverse any of them in the morning.
**Tracker:** GitHub Issues. Tickets below use the `REV-` prefix (unused before). Map issue #134; agent tickets also sit under their milestone maps (#4 M1, #6 M3). Legacy CSV/Markdown are not updated (issue-tracker.md).

## Conflict rule

The foundation thread ("Build chat import foundation", branch `claude/project-thread-q0du34`) owns `src/`, `tests/`, `STATUS.md`, `.agent-history/` and `docs/TICKETS.csv` status columns. Review tickets touch only `docs/adr/`, `docs/plans/`, `docs/reviews/`, `AGENTS.md`, `CLAUDE.md` and `prototype/`. REV-004 produces a design note; applying it to code is the foundation thread's job.

## Who does what

| Ticket | Title | Owner | Kind | Blocked by | Finish line |
|---|---|---|---|---|---|
| REV-001 (#135) | Commit to M1 + M2; re-plan M3 at gate G2; park M5/M6 product tickets | agent (adopted under owner authority 22:10) | docs | — | Decision recorded in `OPEN_DECISIONS.md`; `IMPLEMENTATION_PLAN.md` §4/§10 amended; M3–M6 map issues carry a "planned, not committed" note; API/PROD/packaging tickets labelled `parked` |
| REV-002 (#136) | ADR-0009: the model step under the no-paid-API rule | agent | docs | — | ADR written (batch-file provider: session fills JSONL under `private/`, app validates as if from an API; throughput estimate; stability measurement; cost of the paid alternative); FND-009, EVAL-011, OD-04/05 annotated |
| REV-003 (#137) | Agent reviews the 10-chat answer key independently (owner opted out of tagging, 00:13 UTC 28 Oct) | Remote Control session | device | — | **Done 2026-10-28 00:46 UTC.** 113 checked: 82 ok, 29 fix, 2 drop, 28 add. Hash and counts in `OPEN_DECISIONS.md`, labelled agent-reviewed, not owner-approved |
| REV-004 (#138) | M1 service consolidation design | agent (design), foundation thread (code) | docs | — | Design note mapping the 33 M1 tickets onto fewer modules (conversation graph, import with one "import → report" interface, narrower adapter seam, events deferred); names the single test that owns "identical re-import adds nothing"; keeps ADR-0003 keys and ticket IDs |
| REV-005 (#139) | Process rules: one or two tickets per PR, teach-back before merge | agent | docs | — | Rule added to `AGENTS.md` and `CLAUDE.md` §4; diary template gains a "Teach-back" line |
| REV-006 (#140) | Close the record: ADR-0002..0008 and OD-01..16 defaults become `accepted (owner authority 22:10)`; GitHub Issues is the tracker; licence stays undecided | agent | docs | — | ADR statuses and OD defaults updated with the authority note; CSV/Markdown get a frozen "see GitHub Issues" banner; OD-08 closed; OD-16 (licence) left open with a one-line note that "no licence" currently means all rights reserved, because a licence is a legal choice the owner should make awake |
| REV-007 (#141) | Windows run and split-wrapper key check on the owner's PC | Remote Control session | device | — | `pytest -q` output from Windows recorded in SESSION_LOG; metadata-only list of split-wrapper top-level key names recorded; EVAL-009 fixtures corrected if they differ (owner approval, guardrail 1) |
| REV-008 (#142) | Spike paid-call opt-in guard | agent | code (prototype only) | — | `AnthropicProvider` refuses to construct unless `SPIKE_ALLOW_PAID=1`; a test proves the refusal; dry-run and fake provider unaffected |
| REV-009 (#143) | Early real-data checkpoint in M1: parse one conversation read-only and print its active branch | foundation thread | code | ING-005 | A `ke inspect` subcommand (or script) prints counts, roles and the active path of one real conversation, writing nothing; reported in the diary |

## Order

1. Now, in parallel and without touching the foundation thread's files: REV-001, REV-002, REV-004, REV-005, REV-006, REV-008.
2. REV-007 at the next Remote Control session (needs the owner's PC awake, not the owner).
3. REV-009 when ING-005 lands (foundation thread).
4. REV-003 done by a Remote Control session on the PC (owner opted out). Follow-ups REV-010 and REV-011 go to the coordinator for new threads.

## Not in this plan

Re-planning M3 itself. That happens at gate G2 with real-data results, per REV-001.
