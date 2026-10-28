<!-- Generated from tests/fixtures/gold/synthetic-v1 with the rule extractors (2026-10-28). Numbers and IDs only. -->

> **Read this first.** This baseline uses the *synthetic* golden set: 29 records written so the rules can be checked. Perfect scores here prove the evaluator, the gate and the plumbing work, not that extraction is good on real chats. The real baseline needs the private golden set, annotated with `records_annotated: true`, and runs on the owner's machine. The gate line (nothing forbidden or unsupported in current truth) is the acceptance check for EVAL-004; `test_a_decision_that_skipped_the_gate_fails_the_evaluation` shows it failing when a forged decision bypasses the gate.

# Extraction baseline (golden-synthetic-v1)

## AI check (not owner-verified)

- Answer key: `golden-synthetic-v1 (gold-v1)`, SHA-256 `278c3ea9f1cc7d827f10c13cfd349a56f6596d042a818b6ca88dcd864c3a8235`
- Reviewer: agent-reviewed, not owner-approved (`ai_session`)
- Review file SHA-256: `3e25adcd519ca7698fde71bb31c4614ac698e9243b923eafe462e1a6c729cc82`

- Evaluator: `eval-004-v1`; gold schema `gold-v1`
- actions: `ext-005-rules-v1`
- decisions: `ext-003-rules-v1`
- entities: `ext-006-rules-v1`
- preferences: `ext-004-rules-v1`
- validator: `ext-002-v1`
- Produced records: 31; in conversations not annotated for records (unscored): 2
- Evidence anchor validity: 1.000
- Forbidden records produced: 0; in current truth: 0
- Unsupported user decisions in current truth: 0
- **Gate: PASSED**

| Record type | TP | FP | FN | Precision | Recall | F1 |
|---|---|---|---|---|---|---|
| action | 3 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| artefact | 2 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| decision | 3 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| preference | 4 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| proposal | 6 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| question | 2 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| reference | 6 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| rejection | 1 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| requirement | 2 | 0 | 0 | 1.000 | 1.000 | 1.000 |
| all | 29 | 0 | 0 | 1.000 | 1.000 | 1.000 |

- Truncated messages: 0 (must be 0)

| Chat length | Expected records | Found | Recall |
|---|---|---|---|
| short (<4k chars) | 29 | 29 | 1.000 |

| Attribute (matched records) | Checked | Right | Rate |
|---|---|---|---|
| acceptance | 19 | 19 | 1.000 |
| actor | 29 | 29 | 1.000 |
| attributed_to | 2 | 2 | 1.000 |
| strength | 6 | 6 | 1.000 |
