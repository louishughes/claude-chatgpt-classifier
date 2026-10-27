"""The list of export-format adapters the importer knows about."""

from __future__ import annotations

from knowledge_engine.ingestion.chatgpt_export import ChatGPTExportAdapter
from knowledge_engine.ingestion.chatgpt_split import ChatGPTSplitAdapter
from knowledge_engine.ingestion.source import SourceAdapter


def default_adapters() -> tuple[SourceAdapter, ...]:
    """Return one instance of every built-in adapter.

    Returns:
        The official-export adapter and the split-wrapper adapter.
    """
    return (ChatGPTExportAdapter(), ChatGPTSplitAdapter())
