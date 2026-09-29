# ItemSeedValidator

The deterministic gate on the item seed corpus. `authoring-fleet-plan.md` §7.2 says the pilot is a
test *of the contract*, and a contract test with no mechanical check is an opinion — this is the
mechanical check. §8.2 makes it the build's reporting channel too: the orchestrator learns whether
the corpus is good from one run of this, not from 125 agent summaries.

It reads files and nothing else. **No database connection, no SQL** — `scripts/guard-dal.ps1` only
scans `src/`, so `tools/` is on the honour system and this tool stays on the right side of it.

## Running it

```powershell
dotnet run --project gk-forge/tools/ItemSeedValidator                       # defaults to gk-data/packs/fusion/data/seed/items
dotnet run --project gk-forge/tools/ItemSeedValidator -- <seed root>
dotnet run --project gk-forge/tools/ItemSeedValidator -- <seed root> --warnings-as-errors
```

Exit codes: `0` clean, `1` errors (or zero files scanned), `2` the tool could not run at all —
missing seed root, missing `_registry/`, unparseable registry.

**Zero files scanned is a failure, loudly.** A validator that reports success over an empty tree is
worse than none, so the report says so in block capitals and the exit code is non-zero.

Tests: `dotnet test gk-forge/tests/FusionRpg.ItemSeedValidator.Tests`. That project is not yet listed in
`.github/workflows/ci.yml`, which names its test projects one by one — add it there when the fleet
starts.

## Layout it expects

```
gk-data/packs/fusion/data/seed/items/
  _registry/          core.v1.json bands.v1.json tags.v1.json themes.v1.json
                      classes.v1.json naming.v1.json  [words.v1.json] [retired-ids.json]
  base-types/         affix-families/  gems/  materials/  curves/  attributes/     (stage 1a)
  uniques/  sets/  charms/  socket-words/  recipes/  enhancement-milestones/
  consumables/  drop-tables/  display-templates/                                   (stage 1b)
```

One directory per `kind`. Every `.json` outside `_registry/` is a seed file.

## What it checks

**Structural** — parses; `schemaVersion` known; duplicate JSON keys (which every reader resolves
silently by keeping the last); `kind` matches its directory; `_meta` carries the full provenance
set, and each `registryVersions` entry matches the registry actually loaded; every `override`
carries a note. Unknown keys reject.

**Ownership (§2, §3)** — the highest-value checks here.

- A DERIVED or GENERATED field at any depth is an error: `affixClass`, `atom_id`, `container_id`,
  tier magnitudes, pool weights, power vectors, price/weight/durability/salvage, role legality.
- **No magnitudes.** A JSON number in any field outside the structural-count allowlist
  (`socketMax`, `pieces`, `pool_rolls`, `rung`, `ordinal`, `seq`) is an error — and so is a number
  written as a string, because the rule is about the value, not the JSON type.
- `powerBand` / `costBand` / `dropBand` / `variance` must be members of the matching
  `bands.v1.json` enum.
- `kindId` is checked against `AtomKindRegistry` — the same closed vocabulary the importer uses.

**Identity (§4)** — id grammar; **a `container_id` body contains no dot**, reported with its own
code because two lanes learned it the hard way; every id sits inside a prefix allocated to a real
partition by `naming.v1.json`; sequences are 001–899, with 900–999 flagged as reserved; global id
uniqueness; retired ids are never reused. One file, one partition.

**Naming (§5, §6)** — `naming.v1.json`'s normalizer implemented step for step, including **rule 2a**
(whole-token resolution precedes fusion decomposition; the registry calls it load-bearing and it is
— without it the atomic seed word *Thistledown* decomposes into unrelated halves). Ashen Fang / Ash
Fang / Fang of Ash / Ashfang all reduce to `[ash, fang]` and the last three reject, naming both
offenders. Also: `nameKey` global uniqueness and grammar, the three legal name patterns, no
possessives, no invented connectives, no markup in a localized string.

**References (§7)** — `role`, `frame`, `class`, `theme`, `tag`, `rarity`, `element` and `category`
resolve against their registry or error, never warn. One tag per exclusive axis, and an axis only
where it applies. Cross-references resolve against authored ids or registry-shipped families;
**forward and cyclic references are errors, and so is a stage-1a file referencing another stage-1a
file** — a reference is legal only to a strictly earlier stage.

**Lints (warn, never fail)** — tier gaps inside a partition, a pool group with one member, an entry
nothing references, a class rung with no base types. Plus two fleet-level warnings: a registry still
carrying `frozen: false`, and `words.v1.json` absent.

## Output

A header (registry versions, allocated prefix count, word-pool size, the connective list and where
it came from), a summary table, then **errors grouped by partition** — so a fix pass re-runs exactly
the failing agents, which is the whole reason the grouping exists. Warnings follow in the same
shape.

## Where the tool makes a judgement call

Four places the wave-0 artifacts do not settle. Each is visible in the output rather than silent.

- **`kind` ↔ directory ↔ `idNamespaces` key.** Nothing in the registries states this mapping, so it
  lives in `KindCatalog`. If `naming.v1.json` grows a namespace the catalog does not cover, the run
  fails with `NamespaceUncovered` rather than validating those ids against nothing.
- **Undefined entry shapes.** `seed-contract.md` §10 specifies four kinds (base type, affix family,
  unique, set). For the other eleven, an extra key produces `UnknownKeyShapeUndefined` — a warning
  naming the gap — because rejecting it would be the validator inventing a schema the contract
  never wrote. Close the gap in §10 and those kinds tighten to reject automatically.
- **`element`.** No registry owns the element list. `themes.v1.json` is the only one that names
  elements at all, and `definitions.md` §1 fixes the shape at six plus `omni`, so the vocabulary is
  the union of every theme's `elementAffinity` plus `omni`. An explicit `elements` array in any
  registry overrides that derivation the moment one lands.
- **Role groups.** `roleGroups` is the authored input the role×family legality matrix derives from,
  but no wave-0 registry owns the role-group vocabulary — `manipulator-offense` in the contract's
  own example is not a role id. An unrecognised value warns as `RoleGroupUnknown` instead of
  asserting a rule nothing has written down yet.

Two smaller ones: the four closed connectives are read from `words.v1.json`
`reservedOutOfPools.connectives` when present, then from `naming.v1.json`'s algorithm step 4, and
only then from a built-in fallback — the report prints which source it used. And the plural check
needs F1's word pool to tell *Ashes* from *Moss*, so it is skipped when the pool is absent.
