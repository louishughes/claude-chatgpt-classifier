"""Rendering: turning engine data into Markdown notes for Obsidian.

Rendering only reads; it never changes knowledge. Notes are deterministic
(the same data always gives the same bytes), so regenerating an unchanged
note doesn't touch the file, and Obsidian's history stays clean.

Talking points:
    - "Notes are a view of the data, rebuilt on demand, never the source of
      truth."
"""
