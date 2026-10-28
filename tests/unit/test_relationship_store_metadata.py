"""The relationship table's foreign keys resolve when `ke related suggest` loads it.

`ke related suggest` imports the relationship modules, and a relationship row
has a foreign key to ``import_batches``. When nothing had imported the import
ledger, SQLAlchemy failed with NoReferencedTableError on the real workspace.
In-process tests can't see this (other tests already imported the ledger), so
the check runs in a fresh interpreter.
"""

from __future__ import annotations

import subprocess
import sys

CODE = """
import knowledge_engine.relationships.related  # what `ke related suggest` loads
from knowledge_engine.infrastructure.db import Base

table = Base.metadata.tables["conversation_relationships"]
fk = next(fk for fk in table.foreign_keys if fk.parent.name == "first_import_id")
assert fk.column.table.name == "import_batches"
"""


def test_related_suggest_modules_resolve_the_import_batch_key() -> None:
    done = subprocess.run([sys.executable, "-c", CODE], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr[-2000:]
