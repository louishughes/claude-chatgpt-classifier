"""Reconciling knowledge records with each other (REC-001 onward).

Extraction finds records one segment at a time. This package looks across
them: the same claim made twice (``equivalence``), and later, conflicts and
which decision replaced which. It only ever *proposes* and records review
decisions; the records and their evidence are never edited or merged.
"""
