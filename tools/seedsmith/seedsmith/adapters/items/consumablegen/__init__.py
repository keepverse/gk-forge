"""seedsmith.adapters.items.consumablegen — item-seedgen module `consumables-gen`
(docs/architecture/item-seedgen/spec-consumables-gen.md).

Authors `gk-data/packs/fusion/data/seed/items/consumables/*.json` rows: an item that is spent (never rolled, never
socketed) to grant an effect. Mirrors `setgen`'s split — `brief.py` (theme -> model prompt),
`schema.py` (closed vocabularies + answer validation), `emit.py` (answer -> a real corpus-shaped
entry), `run.py` (the ledger-backed run plan and the reconcile report) — because that split is
already the established shape for an item-seedgen generator (`setgen/__init__.py`'s own precedent).
"""
from __future__ import annotations
