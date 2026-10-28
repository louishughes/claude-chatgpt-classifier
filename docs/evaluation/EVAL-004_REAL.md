# Extraction baseline (golden-v1)

## AI check (not owner-verified)

- Answer key: `golden-v1 (gold-v1)`, SHA-256 `b63a7260d849eeb7de8528efc659ecc3df5b981835eef4fcccb51d4d1d6a0b3d`
- Reviewer: agent-reviewed, not owner-approved (`ai_session`)
- Review file SHA-256: `3936e5f1388ca7c2f33e726bafcade54dea7433a321ba161c3b0af0327b23fd5`

- Evaluator: `eval-004-v1`; gold schema `gold-v1`
- actions: `ext-005-rules-v1`
- decisions: `ext-003-rules-v1`
- entities: `ext-006-rules-v1`
- preferences: `ext-004-rules-v1`
- validator: `ext-002-v1`
- Produced records: 186; in conversations not annotated for records (unscored): 0
- Evidence anchor validity: 1.000
- Forbidden records produced: 0; in current truth: 0
- Unsupported user decisions in current truth: 0
- **Gate: PASSED**

| Record type | TP | FP | FN | Precision | Recall | F1 |
|---|---|---|---|---|---|---|
| action | 0 | 16 | 7 | 0.000 | 0.000 | 0.000 |
| artefact | 1 | 20 | 75 | 0.048 | 0.013 | 0.021 |
| decision | 0 | 0 | 12 | 0.000 | 0.000 | 0.000 |
| fact | 0 | 0 | 21 | 0.000 | 0.000 | 0.000 |
| idea | 0 | 0 | 37 | 0.000 | 0.000 | 0.000 |
| preference | 0 | 47 | 11 | 0.000 | 0.000 | 0.000 |
| proposal | 4 | 15 | 52 | 0.211 | 0.071 | 0.107 |
| question | 0 | 0 | 3 | 0.000 | 0.000 | 0.000 |
| recommendation | 0 | 0 | 9 | 0.000 | 0.000 | 0.000 |
| reference | 10 | 15 | 74 | 0.400 | 0.119 | 0.183 |
| rejection | 1 | 0 | 21 | 1.000 | 0.045 | 0.087 |
| requirement | 7 | 50 | 53 | 0.123 | 0.117 | 0.120 |
| all | 23 | 163 | 375 | 0.124 | 0.058 | 0.079 |

- Truncated messages: 0 (must be 0)

| Chat length | Expected records | Found | Recall |
|---|---|---|---|
| short (<4k chars) | 19 | 1 | 0.053 |
| medium (4k-16k) | 113 | 7 | 0.062 |
| long (16k-64k) | 266 | 15 | 0.056 |

| Attribute (matched records) | Checked | Right | Rate |
|---|---|---|---|
| actor | 23 | 23 | 1.000 |
| strength | 6 | 5 | 0.833 |
