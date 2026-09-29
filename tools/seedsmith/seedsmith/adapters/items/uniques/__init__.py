"""seedsmith.adapters.items.uniques -- the seedsmith uniques extension (D4.29,
spec-unique-pipeline.md §1). Ships identity only for the boss-unique corpus's first 30 new
anchors, beside the 49 already at rung 80+; every magnitude is resolved later, in C#, by
`UniqueContainerBuild.From` (Items/Uniques/UniqueContainerBuild.cs) at roll time.

Four modules, one side of the P1 line each ("the model writes identity, deterministic code
writes magnitude" -- combogen's own precedent table, mirrored here):

| module | side | what it owns |
|---|---|---|
| `planner` | deterministic | the frame x axis x band grid (2x5x3=30), id minting per cell |
| `briefs` | the boundary | the per-cell JSON Schema (PLANNED consts, VALIDATED closed enums) and the prompt text; never a number |
| `pipelines` | the boundary | the call + self-heal + vote loop; `call` is always injected, never imported directly |
| `audit` | deterministic | the schema-level contract audit (numeric/set-stem/planned-const) plus the post-generation checks (stale ids, budget actual-vs-declared, source-lock cardinality) |

⚠ **What this package deliberately does NOT contain**, named rather than silently missing
(D4.29's own evidence in tasks/party-dungeon-todo.md carries the full account):

- **No `UniqueDomainListing` (theme -> climate resolver).** `UniqueSeed` carries no theme/climate
  field anywhere in the real shipped corpus; climate-affinity resolution is a cross-cutting,
  separately-tracked gap (dungeon-loot's own `DungeonLootTableGen`), not this package's job.
- **No `source-locked` anchors in the first-ship batch.** A source-locked unique needs a REAL
  domain table to lock against (`dungeonBinding`, both fields refused `none`), and
  `gk-data/packs/fusion/data/seed/dungeon/domains/` is empty -- authoring one now would mint a dangling reference to
  content that does not exist. The 30 new anchors use `acquisition: drop` at `firstseed` (rung 80,
  the only rung `drop` is legal at) and `acquisition: deterministic` at `sunwoven`/`almanac` (rung
  90/100) instead -- both legal with zero table reference required.
- **No CLI wiring** (`python -m seedsmith items uniques ...`). Confirmed by reading
  `report/cli.py`'s own `build_parser()`: neither `dungeon` (D1.9, already shipped) nor any
  `uniques` subcommand exists there today -- this package is invoked directly, exactly like
  `adapters/dungeon/planner.py`/`audit.py` already are, matching that module's own precedent
  rather than a wiring gap unique to this one.
"""
from __future__ import annotations
