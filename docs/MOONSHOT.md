# MOONSHOT.md — Future Vision and Deferred Capabilities

> **Status:** FUTURE VISION / PARKED — NOT APPROVED FOR IMPLEMENTATION  
> **Scope:** Moonshots 6–10 only  
> **Audience:** Product owners, architects, contributors, Claude Code, Codex, and other development agents  
> **Last updated:** 2026-10-27  
> **Authority:** Exploratory reference document; **not** a PRD, delivery commitment, development instruction, or source of currently accepted requirements.

## 0. Mandatory instructions for agents and contributors

**This document describes ambitious, plausible future directions. None of these five features is in scope for the current MVP, implementation plan, milestone commitments, or acceptance criteria.**

When reading or using this document:

1. **Do not implement** these features, create implementation tickets for them, add dependencies on them, scaffold their services, or add their functionality to the current development plan unless the product owner explicitly approves a specific feature for promotion into scope.
2. **Do not silently treat proposals as decisions.** Every idea below is hypothetical until approved. Its inclusion does not mean the product owner has chosen a particular design, vendor, data model, algorithm, or workflow.
3. **Consider architectural compatibility only when it is low-cost and justified by approved requirements.** Prefer general-purpose capabilities already needed for the MVP: stable IDs, evidence links, typed records, provenance, source metadata, relationship records, status history, and pluggable adapters. Do not build speculative abstractions "just in case."
4. **Never let these features block or delay** reliable ingestion, deduplication, conversation/branch/asset linking, classification, structured extraction, document generation, or retrieval.
5. **Do not run continuing monitoring, connect accounts, collect social data, create work tickets, or execute actions** merely because a future feature describes them. All such activity requires explicit later authorization and appropriate access.
6. **If a future idea reveals a genuine defect in an already approved requirement**, document the concern as an architectural note. Fix the current requirement on its own merits; do not pull the moonshot into scope.
7. **Preserve this file as a vision/backlog reference.** Agents may suggest clarifications in a review report but should not unilaterally move a moonshot into `PRD.md`, `ROADMAP_AND_TICKETS.md`, or an active sprint.

### Promotion gate — the *only* path into implementation

A moonshot can enter the roadmap only after the product owner explicitly selects it. At that point, create a separate proposal that includes: problem validation; user journeys; measurable outcomes; scope/non-goals; privacy, rights and security review; dependencies; cost and performance estimates; data/model contracts; evaluation dataset; bounded implementation tickets; rollback plan; and an approved architecture decision record (ADR). Until that happens, **status remains PARKED**.

---

## 1. Moonshot 6 — Forgotten Gold Detector

**Working name:** Forgotten Gold / Opportunity Archaeologist  
**Status:** PARKED — long-term concept, not to be implemented  
**Goal:** Rediscover valuable but neglected ideas, decisions, experiments, and opportunities buried across older conversations, documents, and source material.

### User value

A large archive often contains promising work that was discussed enthusiastically, partially planned, and then left behind. The engine could surface these items at useful moments, with source links and clear reasoning about why they might now deserve attention.

Illustrative questions:

- "Which interesting game concepts did I explore but never prototype?"
- "What unfinished ideas connect to my current projects?"
- "What did I repeatedly say I wanted to revisit?"
- "Which proposals have a concrete next step but no recorded outcome?"
- "What older ideas have become more feasible given newer work?"

### Possible future behaviour

- Collect candidate concepts and actions previously extracted from evidence-backed sources.
- Identify explicit signals of interest (e.g., direct positive reactions), discussion depth, recurrence, decision status, and practical next steps.
- Find whether subsequent conversations or imported project artefacts show **evidence of progress** or completion.
- Rank opportunities using explainable criteria rather than keyword frequency alone.
- Group duplicates or variants of the same idea without erasing their development history.
- Produce an optional, user-requested "Forgotten Gold" report with original links, why each item matters, known blockers, and a small suggested experiment.

### Illustrative output

> **Candidate:** Prototype an autonomous creature economy  
> **Why surfaced:** Recurred in multiple design discussions; several explicit favourable reactions; at least one concrete prototype direction.  
> **Evidence of implementation:** None found in indexed sources (**not proof it has not been built**).  
> **Potential next step:** A narrowly scoped simulation experiment.  
> **Sources:** Exact conversation and message references.

### Possible scoring dimensions (future research, not a fixed algorithm)

| Signal | Interpretation | Caution |
|---|---|---|
| Expressed enthusiasm | Direct positive user response | AI praise is not user approval |
| Recurrence | Appears in separate discussions | Duplicated imports are not independent evidence |
| Discussion maturity | Has constraints, designs or next steps | Length alone does not imply value |
| Current relevance | Connects to an active project | Similarity does not imply usefulness |
| Apparent feasibility | Small useful experiment seems possible | LLM effort estimates may be unreliable |
| Evidence of progress | Has work, artefacts or completion references | Missing records do not prove inactivity |
| Staleness | Has not been mentioned recently | Old ideas may have been consciously abandoned |

### Important safeguards

- Label missing outcomes as **"completion unverified"**, not "unfinished" or "abandoned."
- Exclude or clearly mark ideas deliberately rejected or superseded; never present them as still-approved work.
- Separate existing user commitments from novel AI suggestions.
- Avoid generating intrusive unsolicited reminders or recurring activity without opt-in.
- Treat opportunity scores as ranking heuristics, not objective assessments of worth.

### Long-term prerequisites and possible approaches

Evidence-linked concept records; decision/action lifecycles; cross-conversation entity linking; provenance-aware deduplication; project status; and optional semantic retrieval. A first future experiment could use deterministic filters plus reranking, before attempting specialised agents or predictive models.

### Potential future success measures

- Percentage of recommended ideas that users judge genuinely relevant.
- Percentage of surfaced items with valid source links.
- False "unfinished" claims (target: zero; use uncertainty wording).
- Number of reports leading to intentionally chosen follow-up work.

**Current development instruction:** Do not build scoring, recommendation feeds, alerts, or discovery workflows for this moonshot.

---

## 2. Moonshot 7 — Personal Preference & Design DNA

**Working name:** Preference DNA / Principles Explorer  
**Status:** PARKED — long-term concept, not to be implemented  
**Goal:** Discover recurring *principles* behind a person's expressed preferences and decisions, while distinguishing what they explicitly said from what an AI merely infers.

### User value

The engine may eventually identify useful patterns across unrelated domains, such as the kinds of gameplay, working methods, writing styles, learning approaches or creative constraints a person consistently prefers. It could help evaluate new options and explain why something seems aligned or misaligned with that person's history.

Illustrative questions:

- "What design principles recur across my game projects?"
- "Where have I repeatedly preferred emergent behaviour over scripted sequences?"
- "Has my preference for a particular development approach changed?"
- "Which suggestions conflict with my repeatedly expressed constraints?"
- "Which of my assumptions should I reconsider?"

### Critical distinction: three evidence classes

1. **Explicit preference:** The person directly states they like, dislike, want, or reject something.
2. **Observed pattern:** Multiple choices or reactions suggest a recurring tendency; always show examples and counterexamples.
3. **Inferred principle:** An AI formulates a higher-level interpretation; it is a **hypothesis**, not an established personal fact.

A fourth distinction matters: **scope**. A preference for one game genre, project, mood, or period cannot automatically become a global preference.

### Possible future behaviour

- Link explicit preference statements to source messages with time, domain, project, and strength of expression.
- Cluster related preferences under human-reviewable principles.
- Show confirming evidence, counterexamples and exceptions.
- Compare historic periods without assuming permanent consistency.
- Generate a user-editable preference profile with the ability to reject an inference.
- Offer an optional "devil's advocate" mode: alternatives that may violate a habitual preference but fit a particular context.

### Illustrative output

> **Candidate principle:** "I tend to enjoy game systems that interact to produce unexpected consequences."  
> **Evidence class:** Inferred principle  
> **Supporting sources:** Several explicit selections in game-design conversations.  
> **Counterexamples:** [If found, linked here.]  
> **Scope:** Game design, not general life preferences.  
> **Confidence:** Provisional; user has not reviewed this inference.

### Safeguards and ethical boundaries

- No psychographic profiling presented as fact.
- Do not infer sensitive personal characteristics, health, political views or protected traits from conversations for this feature.
- Do not create a hidden, uneditable preference profile or quietly apply speculative preferences to unrelated tasks.
- Allow explicit correction, rejection, scope limits and suppression of an inference.
- Explicit user corrections outrank model-generated assumptions; preserve the history of what changed.
- When sharing workspaces later, preference profiles require strong privacy and permission boundaries.

### Long-term prerequisites and possible approaches

Evidence-linked preference records, role attribution (user vs assistant), time and scope metadata, contradiction/counterexample links, and consent-aware visibility controls. Initial future work should favour auditable rules and reviewable summaries over opaque personality scores.

### Potential future success measures

- User acceptance/rejection rate for proposed principles.
- Evidence and counterexample coverage.
- Rate of erroneous cross-domain generalisations.
- Ability to identify changed preferences without overwriting history.

**Current development instruction:** Do not build personal profiling, preference inference, recommendation personalization, or "Design DNA" UI. Existing explicit preference extraction may proceed **only** if it is already approved in the core specification.

---

## 3. Moonshot 8 — Living Source Intelligence

**Working name:** Source Intelligence / Research Watchlists  
**Status:** PARKED — long-term concept, not to be implemented  
**Goal:** Evolve from indexing externally referenced sources into a permissioned, periodically refreshable research library that can identify new relevant information and changes over time.

### User value

A discussion might reference YouTube videos, creator channels, social accounts, websites or documents. The long-term vision is to let those references become connected source profiles and, eventually, opt-in research watchlists.

Illustrative questions:

- "Which YouTube channels have I referenced when researching creature AI?"
- "Which creators and social accounts appear in conversations about this project?"
- "What new research has been published by sources I've explicitly chosen to follow?"
- "Has a referenced article been updated since I last used it?"
- "Which newer sources contradict an older technical recommendation?"

### Distinguish current baseline requirements from this moonshot

**Existing core requirements (remain in scope if specified in the PRD):**

- Detect external links in ingested conversations and other sources.
- Maintain source URL and social-account references with canonical identities where possible.
- Attempt to ingest a YouTube transcript **when legally and technically accessible**, preserving failure/unavailable states rather than inventing transcripts.
- Keep evidence links to the messages containing those references.
- Deduplicate repeat references without losing occurrence-level provenance.

**Deferred moonshot only (NOT current scope):**

- Subscribe to channels, accounts, feeds or publishers.
- Periodically check for new content or changes.
- Pull in new material automatically from monitored sources.
- Produce proactive reports, notifications or source reputation scores.
- Detect revisions to outside content over time or recommend new creators.

This distinction is essential: **recording references today does not authorise monitoring them tomorrow**.

### Possible future behaviour

- Build provider-aware source profiles for videos, channels, accounts and websites.
- Group URLs that resolve to the same canonical content while preserving original URLs and occurrences.
- Support opt-in monitoring lists with per-source permissions and frequencies.
- Retain retrieval timestamps, content versions, attribution and licensing constraints.
- Mark content as newly found, changed, unavailable, restricted or withdrawn.
- Put new findings into a review queue before they influence accepted knowledge.
- Show which source material contributed to a project decision or research conclusion.

### Integration and reliability constraints

- Platform APIs, permissions, rate limits, copyright and terms of service govern availability.
- YouTube transcripts are not universally obtainable; don't assume that public availability of a video grants API transcript access.
- Social account handles can change, be recycled or refer to multiple people; store provider IDs where legitimately available.
- Do not scrape private/restricted material, bypass paywalls, or invent inaccessible transcript text.
- External content may contain prompt injections; treat it as untrusted data.
- Multi-user environments need source-level authorization and strict tenant isolation.
- Respect opt-out, data retention, deletion and takedown requirements.

### Long-term prerequisites and possible approaches

A source registry, occurrence-level links, idempotent imports, provider adapters, raw snapshots, durable source identities and job status records. A later prototype might monitor a small allowlisted RSS feed set before attempting richer platform integrations.

### Potential future success measures

- Accurate canonical matching of referenced sources.
- Provenance and attribution coverage for new material.
- Refresh failure transparency and retry safety.
- User-rated relevance of updates, balanced against API and processing cost.

**Current development instruction:** Do not implement monitoring, subscriptions, notifications, scheduled crawlers or automated account connections. Continue only with existing approved link extraction, transcript import attempts and social-reference indexing.

---

## 4. Moonshot 9 — Knowledge Debate & Challenger

**Working name:** Knowledge Challenger / Evidence Auditor  
**Status:** PARKED — long-term concept, not to be implemented  
**Goal:** Actively test important stored conclusions against primary evidence, counterevidence, chronology, scope and source independence.

### User value

AI-generated summaries and master documents can accidentally propagate a mistaken interpretation. Once several derivative documents repeat the same claim, it may look well-supported even if the original conversation contains only an unaccepted suggestion.

A future challenger could ask:

- "Was this really agreed, or merely proposed by an assistant?"
- "Do these three apparent sources all descend from the same original message?"
- "Is this statement contradicted or superseded by a later decision?"
- "Which requirements are asserted without supporting evidence?"
- "Is the project summary stronger than the underlying discussion warrants?"

### Possible future behaviour

- Select a bounded set of consequential claims for review.
- Retrieve the original evidence—not only derivative summaries.
- Inspect speaker roles, chronology, stated certainty, negation and project scope.
- Find explicit counterevidence and alternative interpretations.
- Trace document lineage so three summaries of one message count as one underlying source.
- Propose corrections, downgrades or unresolved flags for human review.
- Generate an audit report listing claim, evidence, finding and recommended disposition.

### Example failure caught

1. Assistant suggests a technical architecture.
2. Several later generated notes repeat that suggestion as "the selected architecture."
3. Challenger follows citations back to the original exchange.
4. No evidence shows the user approved it.
5. Proposed outcome: reclassify it as **unapproved proposal**, subject to review.

### Safe design constraints

- The challenger is an **auditor**, not an authority to silently rewrite historical records.
- Original sources remain immutable; changes to derived knowledge are versioned and reviewable.
- Citation lineage should distinguish independent corroboration from repeated paraphrases.
- LLM disagreement alone is not evidence of error.
- Unsupported claims must be flagged; absence of evidence is not always evidence of falsehood.
- Reviews must have strict budgets, bounded retries and explicit stopping conditions; no infinite "verify again" loops.
- Prefer targeted audits triggered by risk or explicit request, rather than applying expensive adversarial review to every imported sentence.

### Relation to core quality controls

**Current core quality requirements remain mandatory**: schema validation, source evidence links, traceability, deterministic identity/deduplication, bounded failures and clear review statuses. These do **not** require building this moonshot's dedicated adversarial reasoning system.

### Long-term prerequisites and possible approaches

Reliable evidence links, claim types, versioned lineage, relationship records, source-role attribution and reproducible retrieval. A future proof of concept might evaluate a finite set of known "assistant suggestion mistaken for user decision" cases, comparing challenger findings against human labels.

### Potential future success measures

- Precision of confirmed error findings.
- Detection rate on known unsupported or superseded claims.
- False-positive rate on legitimately supported decisions.
- Completeness of evidence lineage in audit reports.
- Processing cost and bounded termination rate.

**Current development instruction:** Do not build debate agents, autonomous correction loops, adversarial pipelines or challenger review interfaces. Core validation still applies as already specified.

---

## 5. Moonshot 10 — Knowledge-to-Execution Engine

**Working name:** Execution Compiler / Knowledge-to-Delivery  
**Status:** PARKED — long-term concept, not to be implemented  
**Goal:** Transform accepted, evidence-backed knowledge into coherent, reviewable implementation artefacts, and eventually compare intended work with actual delivery.

### User value

A mature topic or project can already contain substantial research, requirements, constraints, rejected directions and architectural decisions. Rather than asking a general AI model to invent a plan, the future engine could assemble a proposal from the source-backed knowledge already available.

Illustrative questions:

- "Generate a draft implementation plan from the approved design of this game system."
- "Which decisions are still needed before this plan is executable?"
- "Which requirements have no corresponding development ticket?"
- "What work was specified but does not yet have verified implementation evidence?"
- "Create a context package for a coding agent to work on one approved ticket."

### Possible future workflow

```text
Evidence-backed, approved project knowledge
              |
              v
    Requirement compiler (draft)
              |
              v
      Architecture proposal
              |
              v
    Dependency and ticket plan
              |
              v
   Acceptance criteria and tests
              |
              v
   Human review and approval gate
              |
              v
 Export to authorised delivery tools
              |
              v
Optional later import of implementation evidence
              |
              v
Compare intended / planned / observed / verified
```

### Possible future outputs

- PRDs and technical briefs with citations to supporting knowledge.
- Traceability matrices linking accepted requirements to systems and tickets.
- Sequenced tickets with blockers, stages, acceptance criteria and test plans.
- Agent-ready context packages limited to the task's relevant information.
- Reports comparing planned deliverables against observed code, tests and documentation.
- Gap reports showing where requirements remain ambiguous or lack acceptance criteria.

### Required distinction between knowledge and execution

- **Intended:** The source material says the user wants something.
- **Approved:** A requirement or plan has been explicitly accepted.
- **Planned:** A ticket or milestone exists.
- **Observed:** A repository, file or tool record suggests something was implemented.
- **Verified:** Appropriate tests or human review demonstrate the requirement is met.

An absent commit or ticket does not prove nothing was implemented. A merged pull request does not automatically prove a requirement is fully satisfied. Verification must depend on evidence appropriate to the claim.

### Safeguards

- No creation of executable tasks or external tickets without user approval.
- No repository edits, agent launches, deployments, account actions or publishing without separately authorised workflows.
- Never fill specification gaps by presenting AI-generated assumptions as approved facts.
- Generated acceptance criteria must link back to requirements or be labelled as proposals.
- Restrict export and retrieval by workspace permissions for future multi-user deployments.
- Preserve original approval states and use idempotent sync to prevent duplicate tickets or outputs.

### Long-term prerequisites and possible approaches

Stable accepted requirements, decision and dependency relationships, traceable document generation, permissions, versioned plans, integration adapters and completion evidence. A safe future pilot could generate **draft plans only**, without external tool writes or execution.

### Potential future success measures

- Percentage of generated requirements traceable to approved source evidence.
- Human acceptance rate of proposed implementation plans.
- Missing-dependency and duplicate-ticket rates.
- Precision of "implemented" versus "verified" status classifications.
- Number of unapproved assumptions correctly flagged before export.

**Current development instruction:** Do not build execution compilers, task creators, coding-agent orchestration, GitHub sync, planned-vs-built dashboards or external writes for this moonshot.

---

## 6. Shared design principles — architecture awareness without scope creep

These are not new implementation tasks. They describe how a future proposal could reuse approved foundations.

| Existing approved foundation, if present | Potential future reuse | Do **not** add now solely for moonshots |
|---|---|---|
| Stable source/message/asset IDs | Trace evidence and avoid duplicated evidence | Moonshot-specific scoring systems |
| Provenance and speaker attribution | Separate user decisions from AI suggestions | Autonomous preference profiling |
| Typed knowledge records and statuses | Distinguish ideas, actions, decisions and revisions | Unbounded challenger agents |
| Occurrence-level URL and source metadata | Link creators, accounts and transcripts | Continuous social monitoring |
| Explicit, typed relationships | Explore dependencies and concept links | Full graph analytics platform |
| Versioned snapshots/derived documents | Analyse changes and historical context | Hypothetical time-travel UI |
| Idempotent incremental ingestion | Safely import fresh evidence | Background crawlers and subscriptions |
| Human review states | Prevent silent promotion of inference | Automatic approval of generated plans |

**Engineering principle:** Build today's required capabilities cleanly. Preserve optionality, but do not pay tomorrow's complexity cost before tomorrow's feature is approved.

## 7. Future exploration order (not the active roadmap)

This is an indicative research sequence **only**; it must not be converted into planned implementation tickets without explicit approval.

1. **Moonshot 6 — Forgotten Gold:** Small, optional opportunity report based on existing evidence-backed ideas.
2. **Moonshot 9 — Knowledge Challenger:** Targeted audit against a fixed human-reviewed contradiction dataset.
3. **Moonshot 7 — Preference DNA:** Opt-in, auditable inference with counterexamples and user corrections.
4. **Moonshot 8 — Living Source Intelligence:** Narrow, permissioned source watchlist prototype.
5. **Moonshot 10 — Knowledge-to-Execution:** Draft-only requirements-to-plan experiment with human approval.

These features can move independently. A later proposal should reassess order based on user value, actual product maturity, cost and legal/technical constraints.

## 8. Deferred status register

| ID | Feature | Current status | Implementation authorised? | Next allowed action |
|---|---|---|---|---|
| MS-006 | Forgotten Gold Detector | PARKED | **NO** | Discuss or refine concept only |
| MS-007 | Preference & Design DNA | PARKED | **NO** | Discuss or refine concept only |
| MS-008 | Living Source Intelligence | PARKED | **NO** | Discuss or refine concept only |
| MS-009 | Knowledge Debate & Challenger | PARKED | **NO** | Discuss or refine concept only |
| MS-010 | Knowledge-to-Execution Engine | PARKED | **NO** | Discuss or refine concept only |

### Review and change control

When product vision changes, update this register and record why. A status change to `CANDIDATE_FOR_RESEARCH` authorises research only—not implementation. Moving a feature to `APPROVED_FOR_IMPLEMENTATION` requires the promotion gate and a separate explicit product-owner decision. Existing approved core functionality takes precedence where a description overlaps with a moonshot.

---

**Final instruction for Claude Code, Codex and collaborators:** Read this file for future context. **Do not implement anything in it. Do not add its features to the active tickets or plan. Do not delay the core product because of it.** Raise relevant, inexpensive architectural compatibility notes during reviews, and otherwise leave these five ideas parked until explicitly authorised.
