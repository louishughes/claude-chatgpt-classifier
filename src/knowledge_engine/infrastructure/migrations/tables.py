"""Every module that defines tables, in one list (used by Alembic, the drift test and CI).

SQLAlchemy only knows a table once the module that defines it is imported.
Keeping the list here, instead of in each caller, means a new table module
added in one place is seen by migrations *and* by the schema-drift check.

Talking points:
    - "One list of table modules, so the drift check can't quietly look at
      a smaller schema than the migrations build."
"""

from __future__ import annotations

import importlib

from sqlalchemy import MetaData

TABLE_MODULES = (
    "knowledge_engine.access.accounts",
    "knowledge_engine.classification.store",
    "knowledge_engine.documents.dependencies",
    "knowledge_engine.extraction.runner",
    "knowledge_engine.extraction.store",
    "knowledge_engine.importer.corrections",
    "knowledge_engine.importer.identity",
    "knowledge_engine.importer.ledger",
    "knowledge_engine.importer.media",
    "knowledge_engine.importer.records",
    "knowledge_engine.importer.text_documents",
    "knowledge_engine.infrastructure.jobs",
    "knowledge_engine.infrastructure.workspace",
    "knowledge_engine.links.social_store",
    "knowledge_engine.links.store",
    "knowledge_engine.links.video_transcripts",
    "knowledge_engine.links.youtube",
    "knowledge_engine.providers.ledger",
    "knowledge_engine.reconciliation.conflicts",
    "knowledge_engine.reconciliation.equivalence",
    "knowledge_engine.reconciliation.relations",
    "knowledge_engine.reconciliation.timeline",
    "knowledge_engine.relationships.store",
    "knowledge_engine.retention.tombstones",
    "knowledge_engine.segmentation.overrides",
    "knowledge_engine.taxonomy.changes",
    "knowledge_engine.taxonomy.refresh",
    "knowledge_engine.taxonomy.registry",
)


def all_tables() -> MetaData:
    """Import every table module and return the shared metadata."""
    from knowledge_engine.infrastructure.db import Base

    for name in TABLE_MODULES:
        importlib.import_module(name)
    return Base.metadata
