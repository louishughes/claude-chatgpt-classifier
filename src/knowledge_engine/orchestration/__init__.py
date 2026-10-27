"""Orchestration: deciding what work runs, in what order, and what can be skipped.

This layer sequences stages (import, normalise, link, classify...) and
never does the work itself. Its central idea is the *stage key*: a
fingerprint of everything that could change a stage's output. If the key
was already completed, the stage is skipped, which is why re-importing an
unchanged export costs nothing.

Talking points:
    - "Work is keyed by a fingerprint of its inputs and versions, so unchanged
      inputs are never processed twice."
"""
