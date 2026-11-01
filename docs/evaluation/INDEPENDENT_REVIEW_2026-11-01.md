# Independent review of the rich conversation notes (2026-11-01)

**Asked by:** Louis, 2026-11-01 07:51 UTC: "Test, evaluate the quality and consistency of the conversations, check the YAML to the specification, check the formatting, and check the keywords and topics."
**Reviewer:** a fresh Claude Code cloud thread that did not build the notes, the digests or the references. It changed no code, tests, evaluation criteria, answer keys or reference set.
**Spec used:** `docs/plans/RICH_NOTES_GAP_ANALYSIS.md` §7 (note template, formatting rules), `docs/PRD.md` FR-13, `docs/TECHNICAL_REQUIREMENTS.md` (flat, escaped front matter), `src/knowledge_engine/evaluation/note_checks.py` (NOTE-011 code rubric).

## Status of this review

| Part | Status |
|---|---|
| 1. Test suite and nightly gate | Done (this file) |
| 2. Front matter, formatting and keywords on **synthetic** notes | Done (this file) |
| 3. The 40 real gold notes on Louis's PC, scored against the independent reference digests in `private/reference-digests/` | **Not done yet.** Waiting for read access to the PC folder. Will be added below as counts only. |

## 1. Tests

Run on `main` at `c7fde95`, Python 3.13, every model key removed, fake provider only.

| Check | Result |
|---|---|
| `python -m knowledge_engine.devtools.ci` (lint, format, strict mypy, git guard, pytest) | all green: **1,800 passed, 22 skipped** in 6 min |
| Skips | 15 PostgreSQL tests (Postgres refuses to run as root in this container) and 7 graph tests marked "covered through the official layouts". Not failures, but the Postgres path was not exercised here. |
| `--nightly` | EVAL-007 gate: 8 PASS, 2 REVIEW, 3 BLOCKED, 0 FAIL. Variance PASS (3 orders, 0 differences, 0 new requests). End-to-end PASS (13 notes, 35 links, 4 embeds resolve, matches golden). |
| Gate REVIEW items | `classification.ambiguous`: the synthetic set has no ambiguous segment, so "ambiguous gets flagged" is untested by the gate. `temporal.supersession`: 29 of 31 pairs as expected, 2 sent to review, 0 false supersessions. |
| Gate BLOCKED items | All three need real data or a paid model: relationship precision and the real golden set (on Louis's PC), real-provider smoke (parked by Louis). |

**Reading:** the code is healthy, but the gate can't say anything about real note quality. That is part 3.

## 2. Synthetic notes: method

Every rich note rendered during the note, digest and UI integration tests (164 tests) was captured by wrapping the renderer from outside the repo, without editing any file: **189 notes**, of which **115 are template v2** (`generator: note-001-v2`) and 74 are the older DOC-003 notes. An independent script parsed each front matter with PyYAML and compared keys, types and values with the spec, then counted section order, empty states and callouts. Test fixtures are made-up chats, so these findings are about the **renderer**, not about content accuracy.

## 2a. YAML front matter against the spec

| Check | Result |
|---|---|
| Front matter present and parses | 189 / 189 |
| Flat (FR-13: no nested objects, list items are scalars) | 189 / 189 |
| `tags` hold approved terms only | yes: every tag seen is an approved term; topic candidates never reach `tags` |
| `status` value | `open` / `settled` or null; never anything else |
| Keys the template promises | all present except `title` (below) |

**Findings (P0 = wrong data, P1 = spec mismatch a user would notice, P2 = polish):**

| # | Sev | Finding | Spec | Suggested fix |
|---|---|---|---|---|
| Y1 | P1 | **Spec contradicts itself on facets.** §7 shows nested `facets: {activity: [...], output: [...]}`, FR-13 says flat. The code writes flat `activity:` and `output:`, which is the right call for Obsidian/Dataview. | §7 vs FR-13 | Amend §7 to the flat form (doc change; Louis to confirm). |
| Y2 | P2 | **No `title` key.** §7 lists `title: "<chat title>"`; no note has it. Obsidian uses the file name, which includes a `(conv-…)` suffix, so Dataview tables show the suffixed name. | §7 | Add `title`, or drop it from §7. |
| Y3 | P2 | **Null values are written.** `project: null` in 113 of 115 v2 notes, `subcategory: null` in 103, `status: null` in 88. §7 says `project` appears "only if an approved project matches". Obsidian shows these as empty properties; Dataview treats `null` and "missing" differently in `WHERE` clauses. | §7 | Omit keys with no value, or document that null means "none". |
| Y4 | P2 | **`date` is a quoted string** (`date: '2024-01-01'`), §7 shows a bare date. Obsidian and Dataview usually still read it as a date, but YAML itself sees text. | §7 | Emit an unquoted ISO date. |
| Y5 | P2 | `digest` values (`generated, not scored`, `not written`, `no_content`) differ from §7's `generated · reviewed: no`. Mixed style (`no_content` uses an underscore, the others spaces). | §7 | Pick one vocabulary and record it in §7. |

## 2b. Markdown formatting and consistency

| Check | Result |
|---|---|
| One `# ` title per note | 115 / 115 |
| Section order | identical in all 115 v2 notes: Knowledge card, Decisions, Suggestions, Action items, Open questions, Requirements and preferences, Insights, Tensions and trade-offs, Next steps, Category and subcategory, Keywords and topics, Related chats, (Branches / Images / Links when present), Source |
| Provenance label under each section | present everywhere (*From the chat*, *Generated (check before relying on it)*, *Classification*, *Candidates*) |
| Evidence | always a collapsed `> [!quote]-` callout (131), never an open evidence box in an empty section |
| Pipes in titles inside the card table | escaped correctly (the fixture with a `|` in its title renders) |

**Findings:**

| # | Sev | Finding | Suggested fix |
|---|---|---|---|
| F1 | P1 | **Sections renamed or added versus §7, undocumented.** "Suggestions not taken up" became "Suggestions" (now listing taken-up ones too), and "Requirements and preferences" is new. Both are sensible, but §7 was never updated, so the spec no longer describes the product. | Update §7 (doc change). |
| F2 | P2 | **Seven different empty-state sentences** for the same idea: "None in this chat.", "None recorded.", "None found yet.", "No suggestions recorded.", "Nothing was decided in this chat.", "None suggested.", "Not written yet…". Each is fine alone; together they read as inconsistent. | One wording per meaning (e.g. "None in this chat." for absent, "Not written yet" for not run). |
| F3 | P2 | **Short chats are long.** A 1-2 message chat still prints 12 headed sections, mostly "None…", about 110 lines on average. §7 wants a 3-message note to fit on one or two screens. It passes the byte budget, but not the "first screen" rule in spirit. | Fold empty sections into one line ("Nothing recorded for: decisions, suggestions, …"). |
| F4 | P2 | **"(s)" plurals everywhere** in the card: "2 message(s)", "0 other branch(es)", "0 image(s)" (about 525 occurrences across 115 notes). Reads as machine output. | Pluralise properly; "no images" instead of "0 image(s)". |
| F5 | P2 | The Source line says "from a note-002-v1 digest, not yet scored" but not **which session or date** wrote the digest, which §7 asks for ("digest by a Claude session on <date>"). The sidecar doesn't hold it either. | Add digest author label and date to the sidecar and the Source line. |
| F6 | P2 | Code checks prove a quote **exists** in the cited message, not that it **supports** the claim. In three UI-test notes an open question "How thick should the boards be?" cites a quote that is the start of a different question. That is fake test data, but nothing in the rubric would catch it in real data either. | Keep as a scorer item in NOTE-011's independent half (it already is: "unsupported claims"). No code change proposed. |

## 2c. Keywords and topics

What the code promises (`documents/keywords.py`): tiers *must* / *should* / *optional* with reasons, corpus calibration, spelling repair, preamble and profile exclusion, and exclusions shown with a reason. What the note shows (`rich_note._keyword_lines`): the *must* tier plus the top *should* terms, as one flat list grouped by first message, then topics split into "approved terms" and "candidates (not tags)".

**Good:** a topic that matches no approved term is always shown as a candidate, never as a tag (taxonomy stays frozen). Approved topics and `tags` agree in every note.

**Findings (synthetic chats, so the words themselves are made up; the patterns are the point):**

| # | Sev | Finding | Example (synthetic) | Suggested fix |
|---|---|---|---|---|
| K1 | P1 | **Near-duplicates and case variants are listed side by side.** | "cedar", "Cedar boards", "boards", "cedar bed" in one list; "Timber" capitalised next to "pine" | Merge a term into a longer phrase that contains it; lower-case non-names. |
| K2 | P1 | **Title phrases are split into single words.** | title "raised bed" gives keywords "bed" and "raised" | Keep the title phrase as one keyword. |
| K3 | P1 | **Filler and stock words survive.** | "prefer", "choices", "deep", "curious", "user", "empty", and "Synthetic answer" / "Synthetic reply" from message text | Extend the filler list; a one-word keyword that is an adjective or verb rarely names a subject. |
| K4 | P2 | **Tiers, reasons and exclusions are computed but not shown.** §7 asks for "primary: …; secondary: …; left out: "<term>" (reason)". The note shows one flat list, so a reader can't tell a title word from a TF-IDF guess, and never sees what was left out and why. | — | Render `Primary` (must), `Secondary` (should) and `Left out` with reasons. |
| K5 | P2 | "Intent" is in the knowledge card, not the Keywords section as §7 shows. Fine, but §7 should say so. | — | Doc change. |

These are deterministic-code findings. Whether the keywords match what the chats are **really** about can only be scored on real chats against the independent references (part 3).

## 3. Real notes against the independent reference set

*Pending folder access to `V:\Programming\ChatGPT_Classifier`. Will be counts only, no chat text.*

## Summary of what needs a decision

Nothing here is a P0. The doc changes (Y1, F1, K5) bring §7 in line with what was built; they change the spec, so they need Louis's OK. The rest are small renderer tickets (Y2-Y5, F2-F5, K1-K4) that can be filed as GitHub Issues once Louis agrees.
