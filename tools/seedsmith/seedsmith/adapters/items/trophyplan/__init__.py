"""seedsmith.adapters.items.trophyplan — the deterministic trophy-id PLANNER (item module 3,
`materials-gen`'s own territory, docs/architecture/species-gear-chain/spec-species-materials.md
§ Design 4). Task T34 of the species-gear-chain program.

⛔ **Scope, restated because it is the whole reason this package is separate from `materialgen`.**
This module mints trophy MATERIAL IDS — `trophy.species.{speciesId}.{slot}` and
`trophy.family.{familyId}.{slot}` — and nothing else. It never authors `name`/`flavor`/`tags`
(`materialgen`'s own scope, `materialgen/__init__.py:1-10`, honoured rather than widened: id minting
and content authoring are two different jobs, and this package only does the first). No model call
happens anywhere in this package (`plan.py` is pure, deterministic arithmetic over three inputs —
the species corpus, the family map, and two tuning counts).

| module     | side          | what it owns |
|---|---|---|
| `tuning`   | deterministic | strict load of `gk-core/data/tuning/species-material-run.v1.json` (`perSpecies`/`perFamily`) |
| `species`  | deterministic | the non-excluded species roster (seed tree) + the species->families map (own loader — never `adapters.actions.vocab.load_family_map_keys`, see `species.py`'s own docstring for why) |
| `plan`     | deterministic | the append-only trophy id registry: mint, reconcile, report |
| `run`      | deterministic | the CLI entrypoint (`seedsmith items generate --kind trophy`), `--dry-run`/`--write`/`--check` |

**Ownership boundary with `materialgen` (spec § Design 4 "Who owns what").** The planner mints ids;
`materialgen` later authors name/flavor/tags for those same ids by extending its own issuable set
with this package's registry. Neither package imports the other's mint/author responsibility.
"""
from __future__ import annotations
