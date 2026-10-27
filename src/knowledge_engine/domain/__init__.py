"""Domain: the engine's core vocabulary, with no databases, files or SDKs.

Everything here is plain Python and Pydantic: the names of things
(conversation, message node, revision, asset, occurrence), the fixed lists
of states they can be in, and the rules for building their permanent IDs.
Because this package imports nothing else from the engine, it can be tested
in isolation and reused by every layer (TECHNICAL_REQUIREMENTS TR-02).

Talking points:
    - "The domain layer is the dictionary of the system. It has no idea a
      database exists."
    - "IDs are computed from what a thing *is*, not from when it was imported,
      so importing the same export twice can't create duplicates."
"""
