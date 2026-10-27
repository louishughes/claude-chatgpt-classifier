# Why the earlier classifier attempt failed (ChatGPT post-mortem)

| Field | Value |
| --- | --- |
| Source | ChatGPT shared conversation "Explain Classifier Failure" (`https://chatgpt.com/share/6ae0fabe-8afc-83ed-b430-c4b340f1ebb7`) |
| Captured | 2026-10-27. Louis pasted it and then uploaded it as a Markdown file, because the share page needs JavaScript and couldn't be fetched automatically |
| Speakers | Assistant only. Louis's original question to ChatGPT was not included in the paste. |
| Completeness | Complete. Part 2 is the uploaded Markdown export, with headings shifted down two levels to fit this file. Wording is unchanged. |
| Authority | Older narrative research (priority 5 in `CLAUDE.md` §1). It is useful reasoning input, not an accepted decision. Numbers quoted from the May 2026 PRD were not re-checked against that PRD. |

Part 1 is a reasoning summary written for this repository. Part 2 is the full transcript.

---

## Part 1: Reasoning summary

### The core claim

The old pipeline made many independent, probabilistic decisions (one LLM call per conversation, a vocabulary that changed during the run) without a stable, corpus-wide model of projects and concepts. Each fix (more prompts, keyword scripts, vocabulary files, agent repair loops) helped some cases and broke others, and nobody could tell whether version 12 was better than version 11 because there was no independent definition of "correct".

### The seven failure causes, in one line each

1. **Isolated classification.** Each conversation was labelled alone, so one project ended up with many names (for example several labels for the same Haggis game). Needed: corpus-wide discovery and a canonical project registry first, then classification against it. It must also tell a rename apart from a pivot or a different project.
2. **Unstable vocabulary.** Auto-promoting a term after three sightings made results depend on processing order (conversation 800 saw a different vocabulary from conversation 8). Needed: separate *discovery → normalisation → classification against a locked, versioned taxonomy → reviewed reconciliation and reprocessing*.
3. **Tests that rewarded the wrong thing.** Title-word coverage, tag counts and confidence thresholds check that the form is filled in, not that it is right. Agents writing their own tests created a self-verification loop. Needed: a human-reviewed reference set of 30–50 conversations, scored on precision, recall, decision recall, evidence accuracy and run-to-run consistency.
4. **Quantity over quality.** "Unlimited keywords, coverage over precision" produced junk tags (sentence fragments, schema words) and about 3,154 terms with 2,914 pending. Frequency can't tell a subject from a passing comparison. Needed: typed entity extraction with evidence and context.
5. **Documents instead of discussions.** A conversation is a sequence of proposals, rejections, corrections and agreements. Summaries flattened "proposed, then rejected" into "discussed". The assistant's suggestions were confused with Louis's decisions. Needed: every extracted decision carries speaker, source span, context and state.
6. **Endless agent loops.** Real engineering bugs (reasoning before JSON, batching compressing output, about 800-byte sub-agent summaries, stale processes writing to old folders, YAML parsing corrupting tags, unresolved template variables, buffered logs) piled up together. Codex was asked to design, implement, define correctness, write tests and judge itself. Retries were used for semantic mistakes, where they just repeat the same mistake.
7. **Too much system too early.** 28 scripts and many downstream features existed before anyone proved that a representative set could be classified accurately, consistently and with evidence. A single "primary category" mixed dimensions (project, research, decision, asset) that one conversation can hold at once.

### Recommended order of proof (from the conversation)

1. Preserve raw conversations and branches with accurate import accounting.
2. Build a 30–50 conversation human-approved reference set.
3. Discover and lock the first taxonomy.
4. Classify topical segments, not only whole conversations.
5. Extract typed knowledge with source evidence.
6. Measure semantic precision and recall on the reference set.
7. Test processing-order independence.
8. Generate documents deterministically from validated records.

### The closing advice

- Give Hermes or Codex **small, independently testable tasks with finite completion conditions**.
- Models interpret conversational meaning. Ordinary code controls identities, schemas, vocabulary, validation, storage and processing state.
- No agent decides that its own classification is correct.
- Ranked root causes: no stable corpus-wide semantic model, testing structure instead of accuracy, and conflating keywords/topics/projects/decisions (all very high). Next come lost conversational state and attribution, agents changing their own success criteria, and scope creep (high). Ordinary bugs and model limits rank medium.
- The core lesson: consistency has to be designed into the data model, vocabulary governance and evaluation. It can't be enforced by adding more prompts and repair loops.
- ChatGPT says this is a retrospective judgement from the PRD and the pitfalls registry, not an audit of the old code or logs.

### How this maps to the current plan

Most of these lessons are already written into the audited specification:

| Lesson | Where it is already covered |
| --- | --- |
| Raw fidelity and branches first | ADR-0008 (source-fidelity slice first); M1 in `docs/plans/IMPLEMENTATION_PLAN.md` |
| Human reference set | `docs/TEST_STRATEGY.md` §4 "Golden dataset construction" (manually annotated 30–50 conversations), EVAL-001 |
| Locked, versioned taxonomy; aliases | `docs/TEST_STRATEGY.md` taxonomy tests; Normaliser → Segmenter → Taxonomy → Classifier stages in the plan |
| Segment-level classification | Segmenter stage in M3 |
| Actor-aware decisions with evidence | `CLAUDE.md` §2E; extraction metrics in `TEST_STRATEGY.md` (speaker attribution, explicit-decision false positives) |
| Precision and recall, not tag counts | `TEST_STRATEGY.md` classification and extraction metrics |
| Order independence | `TEST_STRATEGY.md` §7 (at least 3 shuffled orders) |
| Retry only for transient or format errors | Plan rule "Semantic disagreement → review item, never a retry loop" |
| Separate classification dimensions (domain, project, purpose, topics, knowledge types, outputs) | OD-17 in `docs/reviews/OPEN_DECISIONS.md`; the spike schema uses separate fields |
| Small agent tasks with finite completion conditions | `CLAUDE.md` §4: one unblocked ticket at a time, at most one focused fix before filing a blocker, at most 3 attempts for transient errors |
| Code owns identity, schema, vocabulary and state; models only interpret meaning | ADR-0007 (hybrid split) and ADR-0006 (deterministic link registries) |

### Gaps raised, and what happened to them

These were open when this file was written. The spike work merged in PR #1 has since dealt with them:

- **Consistency vs. correctness.** The spike first only compared two runs. A hand-labelled gold set was added (diary 19:28), and an owner-approved answer key is now the stated bar for accuracy. See `docs/plans/SPIKE_VERDICT.md`, lesson 6. No owner-scored accuracy exists yet.
- **One call per conversation.** The spike confirmed that per-chat labels are "too simplistic". The plan now classifies segments against a discovered, owner-approved taxonomy and project registry (`docs/reviews/OPEN_DECISIONS.md`, OD-17 and the segment decision).
- **A single "primary category".** It was split into separate dimensions (domain, purpose, project candidates, topics, knowledge types, outputs) under OD-17.
- **Who writes the tests.** Still a principle to hold: *semantic* expectations come from Louis, never from the agent being judged.

---

## Part 2: Transcript

> **Assistant** (ChatGPT). Louis's original question was not included in the export.

### Why Your Hermes, Codex and ChatGPT Classifier Project Went Wrong

Having reconstructed our previous discussions and reviewed the original classifier PRD from May 2026, I think there are **six fundamental reasons the project struggled**, with several secondary problems that compounded them.

The biggest issue was architectural: **we attempted to build a consistent knowledge system using a pipeline that made independent, probabilistic decisions without an authoritative, globally consistent understanding of your conversations.**

That created a vicious cycle:

1. Hermes/DeepSeek classified conversations inconsistently.
2. We introduced more instructions, Python scripts, keyword extractors and vocabulary files.
3. Those additions improved certain cases but introduced other inconsistencies.
4. Codex was tasked with fixing the classifications and verification systems.
5. Tests failed, so the agents rewrote code, adjusted checks or attempted another repair.
6. We consumed more tokens and development time without establishing whether the underlying classifications were actually becoming better.

By October, you'd spent dozens of hours and hundreds on model tokens, with around a thousand conversations processed and no consistently trustworthy output.

The frustrating part is that **quite a lot of the individual engineering worked**. You managed to extract conversations, generate metadata, apply categories and tags, and produce structured output. But those working components did not guarantee a working system.

I would separate the failure into three areas:

| Area | What went wrong | Severity |
|---|---|---|
| **Knowledge architecture** | No sufficiently stable, globally governed classification model | Critical |
| **AI reasoning and extraction** | Models missed relevant information, invented or polluted metadata, and lost context | Critical |
| **Development and verification** | Tests and agent repair loops failed to measure and converge on real semantic quality | Critical |

And there was a fourth underlying problem: we kept expanding the solution before conclusively proving that its core classification process worked.

---

#### 1. We Classified Conversations Independently When They Needed Shared Context

This was probably the single most important design mistake.

Your goal was to process approximately 1,158 ChatGPT conversations and extract a consistent understanding of projects, ideas, preferences, decisions, subjects and relationships.

However, the original architecture specified **one LLM classification call per conversation**, with its own relatively constrained output.

That approach can classify an isolated document reasonably well. It struggles when thousands of documents collectively define an evolving knowledge base.

##### Example: Your Haggis Project

Imagine three conversations:

| Conversation | Content | Possible isolated classification |
|---|---|---|
| A | Pied BagPiper shepherding haggis | Game Design / AI Behaviour |
| B | Haggis economy, resources and buildings | Strategy / Economy |
| C | Haggis utility AI and autonomous needs | Programming / Artificial Intelligence |

All three classifications could be individually defensible.

But your intended knowledge system needs to understand that these discussions are related to the same evolving project, while distinguishing different gameplay concepts and potentially different versions of the design.

The isolated classifier might create different project labels:

- `Pied BagPiper`
- `Haggis Game`
- `Haggis Kingdom`
- `AI Flock Simulation`

Without a canonical project registry and explicit relationships, those labels become separate identities.

**The critical missing component was a global discovery and reconciliation process.**

Before detailed classification, the system should have built a corpus-wide understanding of recurring projects, subjects, aliases and relationships. Subsequent classification should then have referenced that stable framework.

Importantly, that framework also needs to distinguish a project rename from a different project or a genuine design pivot.

The original pipeline tried to infer too much of this independently for each conversation.

---

#### 2. Our Vocabulary System Was Fundamentally Unstable

This explains why adding keyword files and further extraction passes didn't reliably solve the problem.

Your May 2026 PRD contained a particularly revealing decision:

> Novel terms would automatically enter the master taxonomy after appearing three times.

That sounds useful, but it introduces a serious consistency problem.

##### The Order-of-Processing Problem

Consider the terms:

- Unreal Engine
- UE5
- Unreal Engine 5
- Unreal
- UE Blueprints
- Visual Scripting

These are related, but they are not all interchangeable.

An LLM might produce different labels depending on the discussion, surrounding context and current vocabulary.

If terms are automatically promoted as the system processes conversations, then the approved vocabulary changes during the classification run.

Consequently:

**Conversation 800 is classified against a different vocabulary from conversation 8.**

Worse, a label that becomes canonical later might not be applied retrospectively to earlier documents.

The output becomes dependent on processing order.

This is called *order dependence*, and it is particularly damaging for your use case.

You also encountered the other side of this problem: a fixed keyword list would prevent new or uncommon concepts from being discovered.

Both concerns were valid.

The solution should have been to separate:

- **Discovery:** Identify new candidate concepts without committing them.
- **Normalisation:** Resolve aliases and duplicates into canonical concepts.
- **Classification:** Apply a locked, versioned taxonomy.
- **Reconciliation:** Review proposed vocabulary changes and reprocess affected classifications.

We attempted aspects of these operations, but the original architecture coupled them too tightly.

A genuinely reliable system must be able to classify the same dataset in different orders and produce materially equivalent knowledge records.

Your original design did not guarantee that.

---

#### 3. We Designed Verification Tests That Rewarded the Wrong Things

This is where I think Codex and Hermes ended up wasting the most effort.

The original PRD required:

- At least 80% title-word coverage.
- Specific minimum numbers of core and supporting tags.
- Ten structural verification checks.
- Minimum confidence thresholds.
- Automated retries when classifications failed.

These are useful structural checks, but **none proves that a classification is semantically correct**.

##### An Example of the Problem

Suppose a conversation was titled:

**"Unreal Engine VR Multiplayer Testing"**

The classifier outputs:

```yaml
category: Programming
tags:
  - Unreal Engine
  - VR
  - Multiplayer
  - Testing
  - Network
  - Game Development
confidence: 0.95
```

The output could pass every structural check.

But suppose the actual conversation was about a specific multiplayer replication bug, and the user ultimately discovered that an actor wasn't set to replicate.

The meaningful knowledge was:

**Problem:** Remote clients could not observe an interaction.

**Cause:** Actor replication was disabled.

**Resolution:** Enable replication and verify authority handling.

**Outcome:** User confirmed it worked.

Those distinctions matter far more than whether the output contains six tags.

Our tests were often checking whether the classifier had filled in its homework, rather than whether it understood the lesson.

##### The Self-Verification Problem

You also had AI agents writing or modifying the tests.

This creates a dangerous feedback loop:

**AI generates a classification → AI writes a test → classification fails → AI modifies the implementation or test → test passes.**

Passing the test doesn't necessarily mean the underlying result improved.

A test can become easier to satisfy without becoming more meaningful.

The missing piece was a **human-reviewed reference dataset**, where the expected classifications were established independently of the model being tested.

That would have given Codex something objective to optimise.

For example, if we manually reviewed 50 representative conversations and marked every important project, decision and keyword, we could measure:

| Metric | What it measures |
|---|---|
| Keyword recall | What percentage of important keywords were discovered? |
| Keyword precision | What percentage of extracted keywords were genuinely relevant? |
| Category agreement | Did the classifier assign the correct categories? |
| Decision recall | Did it discover important agreements and decisions? |
| Evidence accuracy | Could every claimed decision be traced to the source? |
| Consistency | Did repeat runs produce equivalent results? |

Without that reference, the agents had no reliable way to tell whether version 12 was better than version 11.

---

#### 4. We Prioritised Extracting More Keywords Rather Than Extracting Better Knowledge

This was another mistake visible in the original PRD.

It explicitly prioritised tag coverage over tag precision and requested essentially unlimited keyword extraction.

The intention was sensible: you didn't want important subjects missed.

But it meant the classifier was encouraged to collect almost anything that looked remotely relevant.

In a previous review, we identified examples of polluted metadata including:

`Rage Hook The`, `Core Loop Each`, `Like Terry Pratchett`, `Skill Name`, and `Failure Modes`.

Some were fragments of sentences. Others came from formatting or schemas rather than meaningful subjects.

The original PRD reported **3,154 unique taxonomy terms**, of which 240 had been promoted and 2,914 remained pending at that snapshot.

That's a sizeable vocabulary for a system that had not yet established consistent semantic classification.

##### Why Frequency Analysis Didn't Fix It

Your word-frequency passes and keyword extraction scripts could identify repeated strings.

But frequency doesn't tell you whether something is:

- A project name.
- A gameplay mechanic.
- A software technology.
- A fictional character.
- An agreed decision.
- An idea that was rejected.
- An incidental reference made by ChatGPT.

Consider a discussion about creating a game inspired by *Stardew Valley*.

The conversation might mention Stardew Valley 20 times.

That doesn't necessarily mean Stardew Valley is the subject of the conversation. It might simply be a reference used to explain another game.

A frequency-based extractor cannot reliably understand that relationship.

What we needed was **typed entity extraction with evidence and contextual relationships**, rather than merely identifying strings.

---

#### 5. We Treated Conversations as Documents Rather Than Evolving Discussions

This is probably the most important issue for the ultimate usefulness of your knowledge base.

A conversation isn't simply an article containing information.

It is a sequence of statements, suggestions, corrections, agreements, rejections and changing intentions.

##### Example: A Game Design Decision

Consider this simplified exchange:

**You:** "Maybe haggis should be directly controllable."

**Assistant:** "We could implement direct control through the Piper."

**You:** "Actually, no. I prefer indirect control through Utility AI."

**Assistant:** "Agreed. We'll use indirect influence."

A typical summariser might extract:

"Discussion of direct and indirect haggis control, including implementation through the Piper."

Technically, that's a defensible summary.

But the important information was:

| Information | Correct interpretation |
|---|---|
| Direct control | Proposed, then rejected |
| Indirect control | Explicitly preferred |
| Utility AI | Chosen implementation approach |
| Source of decision | User |
| Final state | Indirect control |

If those distinctions are lost, future master documents might incorrectly present rejected proposals as active features.

This was especially dangerous because your conversations frequently contain brainstorming, iterations and design pivots.

##### The Actor-Attribution Problem

Another related issue was the failure to consistently distinguish your decisions from the assistant's suggestions.

That matters because an assistant might propose ten game mechanics and you might only approve two.

The system mustn't turn the other eight into established design requirements.

**Every extracted decision should have a source, speaker, conversational context and state.**

Without those, a generated knowledge base can become an impressive catalogue of things you never actually agreed to.

---

#### 6. The Development Workflow Encouraged Endless Agent Loops

The original project documentation gives us concrete examples of this.

It records several real technical issues:

| Recorded issue | Consequence |
|---|---|
| LLM reasoning before JSON output caused missing fields | Invalid or incomplete classifier output |
| Processing multiple conversations per call compressed the classification | Missing metadata and shallow output |
| Sub-agents produced roughly 800-byte summaries | Significant knowledge loss |
| Stale Python processes wrote into archived output directories | Contamination between runs |
| YAML tag parsing stripped characters incorrectly | Corrupted vocabulary entries |
| Template variables failed to resolve during delegated work | Incorrect agent execution context |
| Background logging was buffered | Difficulty monitoring actual processing progress |

These aren't hypothetical. They're documented in the project's known-pitfalls registry.

Individually, these are fixable engineering problems.

Together, they meant we were simultaneously debugging data parsing, prompt behaviour, model output, agent orchestration, taxonomy management, verification and file integrity.

##### Codex's Role Became Too Broad

We were effectively asking a coding agent to:

Design the system, implement it, decide what correct output looked like, write the verification tests, repair failed outputs, modify the architecture, and determine when everything was sufficiently reliable.

That's too much responsibility without an external definition of correctness.

Coding agents are particularly effective when the requirements and acceptance tests are independently specified.

They are considerably less reliable when asked to invent both the implementation and the criteria by which that implementation is judged.

##### The Retry Architecture Made This Worse

The original system included automated Ralph loops, verification gates, retries and a 30% failure-rate abort threshold.

Those mechanisms were intended to improve reliability.

However, **retrying an unreliable semantic operation does not guarantee convergence**.

For example, if a model consistently misunderstands what constitutes a project decision, asking it to classify the same conversation five times may simply produce five variations of the same mistake.

And when the tests themselves contain flawed assumptions, those retries can reinforce the wrong behaviour.

The correct response to a persistent semantic failure should be to flag it for review, measure its failure category and improve the underlying method.

A retry is appropriate for malformed JSON or a transient API error. It isn't necessarily appropriate for a conceptual misunderstanding.

---

#### 7. We Created Too Much System Before Proving the Smallest Useful Result

This amplified every other problem.

By May, the architecture already included classification, message scoring, taxonomy promotion, relevance ranking, relationship generation, image handling, voice processing, Obsidian output and multiple verification stages.

There were also 28 active Python scripts listed in the PRD.

Some of that functionality was genuinely needed eventually.

But the critical dependency was never fully resolved:

**Could we classify a representative set of conversations accurately, consistently and with evidence?**

If the answer was no, everything downstream inherited unreliable data.

Relationship linking would link the wrong subjects. Master documents would combine incorrect decisions. Retrieval would surface polluted metadata.

Even an excellent RAG implementation would struggle if the underlying knowledge records were wrong.

We also mixed different classification dimensions. The original primary categories included *Ideas*, *Projects*, *Research*, *Decisions* and *Content Assets*.

A single conversation can be about a project, contain research, generate ideas, establish decisions and produce assets.

Forcing that discussion into one category creates an ambiguity that even a perfectly obedient LLM cannot resolve consistently.

The model needed separate fields for **domain, project, conversation purpose, topics, knowledge types and outputs**.

---

#### What I Would Change Now

The revised Knowledge Engine specification you developed on 27 October addresses many of these architectural issues. However, it's still a specification: it hasn't yet demonstrated that the implementation works.

I would make its first acceptance milestone considerably more demanding than successfully generating YAML files.

| Priority | Change | Proof it works |
|---|---|---|
| 1 | Preserve raw conversations and branches | No unsupported message loss; accurate import accounting |
| 2 | Create a 30–50 conversation reference dataset | Human-approved expected outputs |
| 3 | Discover and lock the initial taxonomy | Stable concepts and aliases across runs |
| 4 | Classify topical segments instead of only entire conversations | Correct handling of multi-topic discussions |
| 5 | Extract typed knowledge with source evidence | No unsupported decisions represented as confirmed |
| 6 | Evaluate semantic precision and recall | Measurable performance on the reference dataset |
| 7 | Test processing-order independence | Reordering conversations doesn't materially change their classifications |
| 8 | Generate documents deterministically | Repeatable output from validated records |

Most importantly, I'd give Hermes or Codex **small, independently testable development tasks with finite completion conditions**.

The models should interpret conversational meaning. Conventional code should control identities, schemas, vocabulary, validation, storage and processing state.

Neither agent should independently decide that its own classification is correct.

---

#### My Overall Diagnosis

Based on the previous discussions and the original PRD, I'd rank the causes as follows:

| Root cause | Contribution to failure |
|---|---|
| No stable, corpus-wide semantic model | Very high |
| Testing structure rather than actual knowledge accuracy | Very high |
| Conflating keywords, topics, projects and decisions | Very high |
| Insufficient preservation of conversational state and attribution | High |
| Agents modifying their own implementation and success criteria | High |
| Scope expansion and orchestration complexity | High |
| Ordinary implementation bugs and model limitations | Medium |

These are engineering judgements based on the architecture and recorded symptoms, rather than a fresh audit of the actual Python repository and execution logs.

##### The Most Important Lesson

I think we spent too much time trying to make the agents follow increasingly elaborate instructions.

Every time an output was wrong, the temptation was to create another rule, another verification condition, another agent skill or another Python pass.

But additional instructions cannot compensate for missing architecture or an undefined measure of correctness.

**The fundamental mistake was trying to enforce consistency through prompting and repeated correction, when consistency needed to be designed into the system's data model, vocabulary governance and evaluation process.**

And there's a fairly cruel irony in the whole exercise: we were trying to build a system that would reliably remember what we'd agreed, using agents that couldn't consistently remember what *they'd* agreed.

The good news is that this doesn't invalidate the project. Its underlying purpose is sound, and several of the original components are reusable.

What needs changing is how we establish correctness and manage knowledge across conversations. That's the distinction I would carry into the new implementation.

---

*Evidence reviewed: original May 2026 classifier `PRD.md`, associated known-pitfalls registry, and the later Knowledge Engine specification. This is a retrospective architectural analysis, not a direct audit of the full repository or runtime logs.*
