"""Recall: a read-only front door for asking questions of your own chat history (RCL-001).

``ke`` is the engine's full toolbox: importing, classifying, reviewing,
backing up. ``recall`` is the small, read-only command you (or an AI agent
working for you) use to *get answers out*: "where did I talk about X?",
"what do I keep asking?", "what did I decide for project Y?".

It never writes to the workspace's records and never calls a model. Every
answer points back to the original message (chat, message ID, date), so the
chats stay the source of truth and nothing is trusted second-hand.

Talking points:
    - "recall is a thin front end over the engine I'd already built, so it
      reuses the same search and gets the same answers, it just reads better."
    - "It's built for AI agents first: every command has --json, so Claude or
      Codex can ask my history a question instead of me pasting context."
"""
