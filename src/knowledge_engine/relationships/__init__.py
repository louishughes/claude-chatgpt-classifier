"""Links between separate conversations (REL-002, ADR-0005).

Branches inside one chat are the message graph's job (REL-001). This package
handles links *between* chats: one continues, forks, quotes or points at
another. ``store`` keeps them with their review history; ``detect`` proposes
them from exact, structural evidence only.
"""
