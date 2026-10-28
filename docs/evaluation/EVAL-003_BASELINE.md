<!-- Generated from tests/fixtures/gold/synthetic-v1 with the keyword classifier (2026-10-28). Numbers and IDs only. -->

> **Read this first.** This baseline uses the *synthetic* golden set: six segments written so the rules can be checked, not to measure real quality. A perfect score here proves the evaluator and the plumbing work. It says nothing about accuracy on real chats. The real baseline needs the private golden set (`ke gold template`, then annotation; see ANNOTATION_GUIDE.md), and it is run on the owner's machine, where only numbers come back.

# Classification baseline (golden-synthetic-v1)

- Evaluator: `eval-003-v1`; gold schema `gold-v1`; taxonomy `tax-gold-1`
- classifier: `keyword`
- classifier_code: `cls-001-v1`
- scorer: `cls-003-v1`
- segmenter: `nrm-004-v1`
- Gold segments: 6; not found in the store: 0
- Ambiguous segments sent to review: 0; not sent: 0
- Project accuracy: 1.000

| Field | Segments | Micro P | Micro R | Micro F1 | Macro F1 | Primary acc. |
|---|---|---|---|---|---|---|
| projects | 1 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| topic | 6 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |

## Confusion: projects (gold primary -> predicted primary)

| Gold | Predicted | Count |
|---|---|---|
| proj_garden | proj_garden | 1 |

## Confusion: topic (gold primary -> predicted primary)

| Gold | Predicted | Count |
|---|---|---|
| term_baking | term_baking | 1 |
| term_gardening | term_gardening | 1 |
| term_godot | term_godot | 1 |
| term_packaging | term_packaging | 1 |
| term_shed | term_shed | 2 |

