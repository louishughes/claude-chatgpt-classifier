# Classification spike v3: discover, then classify

**Status:** proposed, 2026-10-27. Replaces the "one label per chat" design (spike 0.2/0.3) after the owner judged it "too simplistic".

## Why v0.2/0.3 was too simplistic
Run 1 (50 chats × 2, Haiku 5.5, $0.069) was reliable but answered the wrong question. Reading 20 of the chats showed four problems:
1. **One label per chat.** Chats drift: a thought experiment turns into a history question and ends with a joke request. One domain and one purpose can't describe that, which is why so many review verdicts were borderline.
2. **Categories too coarse.** A single "games" bucket held 40% of the sample. It mixed mechanics design, naming, marketing, crowdfunding and team roleplay.
3. **Most knowledge thrown away.** Only "decisions" were extracted, while the chats are full of ideas, frameworks, preferences, facts about the owner and produced artefacts.
4. **Checking anchored on the model.** The reviewer saw Haiku's answer and judged "is this OK?" instead of writing an independent answer first.

These match causes 1, 3, 4, 5 and 7 of the earlier post-mortem (`docs/reference/2026-10-27-why-the-classifier-failed.md`, PR #2). It recommended the same order as below.

## The process
| Step | What happens | Who | Cost |
|---|---|---|---|
| **1. Answer key** | For 10 varied chats, Claude reads the chat on the owner's PC and writes a *blind* reference: segments (message ranges where the goal changes), each with a two-level subject (e.g. games → naming), purpose and project tags, plus typed knowledge items that cite message numbers. The owner reviews it as evaluator (accept / fix / reject per item, ~15 min). | Claude, then owner | free |
| **2. Discovery** | Haiku reads the 50 chats with *no fixed list*. It returns segments, project names as written, subjects in its own words, and typed items: idea, requirement, preference, decision (with proposer, state, deciding message), artefact produced, fact about the owner, problem → fix, open question. Each item cites a message. | Haiku | ~$0.15 |
| **3. Consolidate** | Code groups names and subjects (exact and normalised matches). One stronger-model pass over the *discovery outputs only*, not the raw chats, proposes (a) a two-level taxonomy that reflects what is actually in the data and (b) a project registry with canonical names and aliases. The owner approves, merges or renames. Then the version is **frozen**. | code + Sonnet, then owner | ~$0.10 |
| **4. Classify** | Haiku labels each segment against the frozen taxonomy and registry (stable IDs, not display labels) and re-extracts typed items. Run twice in different orders. | Haiku | ~$0.25 |
| **5. Score** | Against the step 1 answer key: segment boundaries, subject (both levels), project, typed items (precision and recall by type), decision state and proposer, evidence checked by code. Run-to-run agreement and order independence as before. | code | free |

The total is under $1, inside the existing $2 cap.

## What carries over from 0.3
- Structured output validated by Pydantic.
- Message-number citations checked by code.
- Harmless overflows trimmed, not retried.
- Bounded retries for transport and format errors only.
- Checkpoint and resume, cost cap, outputs in git-ignored `private/`.
- Reports with counts only.

## Go / no-go after step 5
Targets to agree before step 4 runs:
- segment boundary agreement within ±1 message ≥ 80%;
- level-1 subject ≥ 90%, level-2 ≥ 75%;
- project tag ≥ 85%;
- typed items: precision ≥ 80%, recall ≥ 60%;
- decisions: state and proposer correct ≥ 85%;
- 0 unrecovered transient errors.

If these are met, scale to 100 chats, then M1. If not, change the method again before scaling.

## Guardrails
- The answer key is written blind (without seeing any model output) and approved by the owner.
- Agents never edit it after approval. It is fingerprinted like the review file.
- The taxonomy is frozen during each run.
- No private names or text in this repository.
