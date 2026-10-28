"""Alembic entry point: runs migrations on the engine passed in by the app.

Alembic imports this file itself; the app never imports it. It only supports
"online" mode (a live database connection), because the engine always has
its database file locally.
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import Engine

from knowledge_engine.infrastructure.migrations.tables import all_tables

# Every table module is imported, so autogenerate and the drift check see
# the full schema.
target_metadata = all_tables()

engine = context.config.attributes.get("engine")
if not isinstance(engine, Engine):
    raise RuntimeError("run migrations through knowledge_engine.infrastructure.migrations")

with engine.connect() as connection:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        # SQLite can't ALTER most things in place; batch mode copies the table
        # instead, so future column changes still work.
        render_as_batch=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()
