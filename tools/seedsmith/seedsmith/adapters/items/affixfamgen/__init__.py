"""seedsmith.adapters.items.affixfamgen — module `affix-families-gen`
(docs/architecture/item-seedgen/spec-affix-families-gen.md), item-seedgen module 2.

A brief-and-answer generator authoring NEW entries into `gk-data/packs/fusion/data/seed/items/affix-families/*.json`,
the 109 real, hand/LLM-session-authored affix family definitions (channel, op, tier-band curve,
tags) that back `FamilyExpansion.cs`'s (E43) downstream expansion into ~490 per-tier atom rows.

Distinct from (never to be confused with):
- `effects generate --kind affix` — effect-pipeline's own module 9, a different corpus
  (`gk-data/packs/fusion/data/seed/atoms/**.json`), never writes to `gk-data/packs/fusion/data/seed/items/affix-families/`.
- `FamilyExpansion.cs` (E43) — the downstream C# transform from these 109 SOURCE families to
  per-tier atom rows; this module only authors the source families it reads.

File split, mirroring `adapters.items.setgen`'s proven shape:
- `opvocab.py` — the ONE place that knows the real, closed op-per-kind vocabulary
  (`stat.modify`: Flat/Increased/More; `stat.derived`: Flat/Increased/Replace/Flag), transcribed
  with citation from `AtomKindRegistry.cs` the same way `adapters.items.channels` already
  transcribes `BattleRuleset`'s formulas — there is no JSON export of the C# enum to read instead.
- `brief.py` — the model-facing brief (theme/name/channel/tag pick only) and the construction-time
  guard (`pipeline.model.audit_schema`) that refuses a bare numeric field before a call is ever
  made, mirroring `pipeline.model.Pipeline.__post_init__`'s own discipline.
- `schema.py` — the closed-enum answer schema, parameterized by `kindId` so `op`'s enum is always
  the correct one for the family's declared atom kind.
- `emit.py` — assembles and writes a real family JSON document matching the shipped shape.
- `run.py` — wires `pipeline.run_ledger.RunLedger` (resume/reconcile/overwrite).
"""
from __future__ import annotations
