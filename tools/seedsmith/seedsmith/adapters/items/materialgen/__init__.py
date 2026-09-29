"""seedsmith.adapters.items.materialgen — the material DISPLAY/FLAVOR generator (item module 3,
`materials-gen`, docs/architecture/item-seedgen/spec-materials-gen.md).

⛔ **Scope, restated because it is the whole reason this package exists rather than a one-off
script.** This module authors `name` / `flavor` / `tags` for a material id — never a new material
id, never `MaterialClass`/`CatalystVerbs`/`SubstrateFrames`/`SubstrateGrades`. Those four are the
small, closed, fixed mechanical taxonomy `gk-core/src/FusionRpg.Core/Items/Materials/MaterialCatalog.cs`
owns, extending them is ask-first by that enum's own doc comment, and this package never imports,
edits, or re-derives that file's C# — it mirrors the 27-id vocabulary it *produces* (`vocab.py`)
and stops there.

| module | side | what it owns |
|---|---|---|
| `vocab`  | deterministic | the closed 27-id issuable vocabulary, mirrored from `MaterialCatalog.cs` |
| `schema` | the boundary  | the closed-enum answer schema — name/flavor/tags, nothing mechanical |
| `brief`  | the boundary  | one material id -> a brief; the closed tag pool is inline, no citation text |
| `emit`   | deterministic | `nameKey`/`iconKey` (one fixed mechanical pattern) + the full corpus entry |
| `run`    | deterministic | the run plan, wired to `pipeline.run_ledger.RunLedger` |
"""
from __future__ import annotations
