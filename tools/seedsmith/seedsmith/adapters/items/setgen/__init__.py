"""seedsmith.adapters.items.setgen — the set generator (item module 13, `set-charm-gen`).

⛔ **P1 is the whole shape: the model writes identity, deterministic code writes magnitude.** Every
module in this package sits on one side of that line and says which:

| module | side | what it owns |
|---|---|---|
| `roles` | deterministic | THE TWELVE, and the cap applied *before* the call |
| `tuning` | deterministic | the pure parser over `gk-core/data/tuning/set-charm-gen.v1.json` |
| `vocab` | deterministic | the capability (60) and stat (242) pick vocabularies, **counted** |
| `schema` | the boundary | the closed-enum output schema, `audit_schema`-clean by construction |
| `brief` | the boundary | theme + aptitude + archetype -> a brief; motifs inline, no citation |
| `themes` | deterministic | the one-way theme bridge, the holdback and the coverage report |
| `distribute` | deterministic | capability low, stats above, `numerics` for every magnitude |
| `cells` | deterministic | the distinctness cell — `(capability, higher-threshold multiset)` |
| `emit` | deterministic | ids from `speciesId`, **never** the `themeKey` |
| `verdict` | deterministic | `pass` only when every gating metric both ran and cleared |
| `run` | deterministic | the run plan, the resume ledger, and the dry run |
"""
from __future__ import annotations
