"""seedsmith.adapters.items.recipegen — item-seedgen module 14/Phase 4
(docs/architecture/item-seedgen/spec-recipes-gen.md).

Authors the crafting-recipe corpus (`gk-data/packs/fusion/data/seed/items/recipes/recipes.json`, 30 entries today, read
by `MaterialRecipeCatalog.Load`). Built to end the 2026-09-05 failure mode named in the spec: a
schema/vocabulary change to `operation` was hand-patched string-by-string into the committed JSON
(`"reroll"` -> `"reroll-one"`/`"reroll-all"`) with no record of why. `opvocab.py` reads the real,
current operation vocabulary from its C# source of truth (`CraftOperation`/`CraftOperations` in
`gk-core/src/FusionRpg.Core/Items/Materials/CostClassMatrix.cs`) so a future rename is a `reconcile` run,
never a hand-patch.
"""
from __future__ import annotations
