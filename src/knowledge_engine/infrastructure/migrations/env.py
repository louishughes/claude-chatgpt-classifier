"""Alembic entry point: runs migrations on the engine passed in by the app.

Alembic imports this file itself; the app never imports it. It only supports
"online" mode (a live database connection), because the engine always has
its database file locally.
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import Engine

# Import every module that defines tables, so autogenerate and the drift test
# see the full schema.
from knowledge_engine.classification import store as _classifications  # noqa: F401
from knowledge_engine.importer import identity as _identity  # noqa: F401
from knowledge_engine.importer import ledger as _ledger  # noqa: F401
from knowledge_engine.importer import media as _media  # noqa: F401
from knowledge_engine.importer import records as _records  # noqa: F401
from knowledge_engine.infrastructure import jobs as _jobs  # noqa: F401
from knowledge_engine.infrastructure import workspace as _workspace  # noqa: F401
from knowledge_engine.infrastructure.db import Base
from knowledge_engine.links import social_store as _social  # noqa: F401
from knowledge_engine.links import store as _links  # noqa: F401
from knowledge_engine.links import video_transcripts as _video_transcripts  # noqa: F401
from knowledge_engine.links import youtube as _youtube  # noqa: F401
from knowledge_engine.providers import ledger as _model_ledger  # noqa: F401
from knowledge_engine.relationships import store as _relationships  # noqa: F401
from knowledge_engine.taxonomy import changes as _taxonomy_changes  # noqa: F401
from knowledge_engine.taxonomy import registry as _taxonomy  # noqa: F401

engine = context.config.attributes.get("engine")
if not isinstance(engine, Engine):
    raise RuntimeError("run migrations through knowledge_engine.infrastructure.migrations")

with engine.connect() as connection:
    context.configure(
        connection=connection,
        target_metadata=Base.metadata,
        # SQLite can't ALTER most things in place; batch mode copies the table
        # instead, so future column changes still work.
        render_as_batch=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()
