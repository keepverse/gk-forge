"""seedsmith.adapters.items.basetypegen — the base-type generator (`base-types-gen`, item-seedgen
module 6/Phase 3, `docs/architecture/item-seedgen/spec-base-types-gen.md`).

A brief-and-answer generator authoring NEW entries into `gk-data/packs/fusion/data/seed/items/base-types/*.json`, the
740 real, hand/LLM-session-authored base-type identities (`authoring-fleet-plan.md`'s own words:
*"750 identities across 30 role-frames | W1 · 60 agents"*) that replace what was today a one-time
authoring wave with no generator behind it.

**The 30 role-frame taxonomy, found and cited (spec acceptance #4), never re-invented**:
`gk-data/packs/fusion/data/seed/items/_registry/core.v1.json` → `roles.list`'s 15 body `roleId` rows × the two body
frames (`humanoid`, `plant`) = 30 role-frames, matching `naming.v1.json`'s own
`idNamespaces.baseTypes.totalCombinations` ("15 roles × 2 frames × 2 bands = 60" — 60 partitions
covering those 30 role-frames, two bands each). The commander-only `standard` role
(`roles.commanderOnly`) is explicitly out of this scope, per that same file's own
`standardRoleNote`.

⛔ **P1, the same split every item-seedgen module sits on: the model writes identity, deterministic
code writes magnitude.** The model (via `brief.build_base_type_brief` and `schema.py`) picks a
base type's `name`, `flavor`, `class` (one class-ladder rung) and `implicitFamily` (one family from
the role's own closed slate), plus `tags`. It never picks `socketMax`, `implicit.powerBand`, an
`enhanceTrack` level, or any id — `tuning.py` resolves the first three deterministically from
`gk-core/data/tuning/base-types-gen.v1.json` and the real registries (the `sockets` revision's
`socketCeiling(role)`, `classes.v2.json`'s class ladders and implicit slates), and `emit.py` mints
every id.

**Two Hard references, resolved against real corpora, never invented** (spec's reference
manifest): `implicit.family` resolves against `affix-families-gen`'s real, closed per-role slate
(`classes.v2.json` → `implicitSlates[role].legalFamilies`, itself a role-scoped subset of the wider
`atom.*` corpus `affix-families-gen` mints into); `enhanceTrack[].family` resolves against
`enhancement-milestones-gen`'s real, CURRENT corpus (`tuning.load_milestone_families`, read fresh
every call, never a hardcoded copy — a family module 11 mints tomorrow is visible to this
generator's next run with no code change).

File split, mirroring `affixfamgen`'s and `milestonegen`'s proven shape (this is the third
generator built against the same harness):
- `tuning.py` — every closed vocabulary and every numeric resolution table, read fresh from the
  real registries and this module's own `gk-core/data/tuning/base-types-gen.v1.json`.
- `brief.py` — the model-facing brief (identity/theme pick only, per one `(role, frame, band)`
  partition) and the construction-time guard (`pipeline.model.audit_schema`).
- `schema.py` — the closed-enum answer schema, parameterized by the partition's own vocabularies.
- `emit.py` — ids, slugs, and the final entry shape, matching the real shipped corpus verbatim.
- `run.py` — wires `pipeline.run_ledger.RunLedger` (resume/reconcile/overwrite), open-ended draw
  slots per partition, mirroring `milestonegen.run`'s own shape (this corpus, like that one, has no
  pre-closed subject grid the way `setgen`'s themes or `affixfamgen`'s partitions do).

**`role`, `frame` and `band` are caller inputs, never a model choice** — see `brief.py`'s own
docstring for why: the spec's "Ask first: changing the 30-role-frame taxonomy" boundary would be
silently broken by a per-call model-chosen role/frame, and `band` is `naming.v1.json`'s own
"symbolic ... F4 owns what 'a' vs 'b' means" partition token, not an identity fact a model invents.
"""
from __future__ import annotations
