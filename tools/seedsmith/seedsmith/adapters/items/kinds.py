"""seedsmith.adapters.items.kinds — the 15 item KindSpecs, ported from
`gk-forge/tools/ItemSeedValidator/Registries/KindCatalog.cs` (read fresh 2026-08-23, not from memory —
the corpus has changed under this program before).

Fifteen, not fourteen: `KindCatalog.cs` also carries `attribute` (`ShapeDefined: false` — its
shape has never been authored against, seed-contract.md has no §10 table for it), which the
corpus stats table quotes as "14 shipped kinds" because `attribute` ships zero rows. It is still
a real, allocated kind — one of the nine currently-empty partitions this program's Coverage
metric exists to catch — so it belongs in this list.

`required`/`optional` are transcribed once, directly from the C# source, because there is no JSON
registry that states them — unlike almost everything else an adapter reads, this is code, not
data, and the citation above is what keeps the port auditable against drift.

`id_pattern` and `runtime_id_fields` are left unset for every kind: encoding them precisely needs
each kind's `idTemplate`/minted-runtime-family rules from `naming.v1.json`, which is real work
with its own failure modes (this is exactly the class of thing that produced the tracking-id vs
runtime-id defects spec-foundation §1 describes) and no S2 acceptance criterion exercises it yet.
Left as an explicit, documented gap for whichever later task (S3's Linkage/Registration
absorption is the first candidate) actually needs it, rather than guessed at here.
"""
from __future__ import annotations

from ..base import KindSpec

COMMON_FIELDS = frozenset({
    "id", "nameKey", "name", "tags", "notes", "enabled", "overrides",
    "flavor", "flavorKey", "iconKey", "unlockGate",
})
COMMON_REQUIRED = frozenset({"id", "nameKey", "name"})


def _defined(kind: str, directory: str, namespace: str, *, required: "set[str]",
            extra: "set[str]", refs: "set[str] | None" = None) -> KindSpec:
    return KindSpec(
        kind=kind, directory=directory, namespace=namespace,
        required=COMMON_REQUIRED | required,
        optional=COMMON_FIELDS | extra,
        reference_fields=frozenset(refs or ()),
    )


def _undefined(kind: str, directory: str, namespace: str) -> KindSpec:
    return KindSpec(kind=kind, directory=directory, namespace=namespace,
                    required=COMMON_REQUIRED, optional=COMMON_FIELDS)


KINDS: "tuple[KindSpec, ...]" = (
    _defined("base-type", "base-types", "baseTypes",
            required={"frame", "role", "class", "band", "iconKey", "tags"},
            # species-gear-chain T38 (`item-upgrade-tree` b, spec-item-upgrade-tree.md revision 2 § Design 1):
            # `successorOf` is the AUTHORED successor edge — the owner's 2026-09-21 ruling made it a
            # per-base-type field for every upgradeable role, armour included, instead of deriving a
            # successor from the class ladder (a rung names a CLASS, and a class holds several chassis;
            # the corpus cannot narrow that). Optional, never required: zero rows are authored today by
            # design, and the separate content pass fills them. Never a brief field — it is authored
            # content code reads, not a model answer.
            extra={"frame", "role", "class", "band", "implicit", "socketMax", "enhanceTrack",
                   "successorOf"}),
    _defined("affix-family", "affix-families", "affixFamilies",
            required={"kindId", "powerBand", "tags"},
            extra={"kindId", "params", "variants", "frames", "side", "roles", "roleGroups",
                   "powerBand", "nameWords", "displayTemplate", "channel"}),
    _defined("unique", "uniques", "uniques",
            required={"frame", "baseType", "rarity", "fixedAtoms", "counterPressure", "tags",
                     "powerAxis"},
            # D4.29 (spec-unique-pipeline.md §1): `reason` and `actionGrantRef` amend this
            # KindSpec -- both are in the spec's own field-ownership table (AUTHORED and
            # VALIDATED respectively) but were absent from every prior port of this KindSpec.
            # Optional, not required: zero of the real 144-corpus's sampled entries use either
            # field, and `actionGrantRef`'s own "none legal" reading (spec §1) means absence is
            # itself a legal value, never a missing-field defect.
            extra={"frame", "baseType", "rarity", "fixedAtoms", "varianceSlot",
                   "counterPressure", "theme", "themeKey", "acquisition", "powerAxis",
                   "reason", "actionGrantRef"},
            refs={"baseType"}),
    _defined("set", "sets", "sets",
            required={"themeKey", "members", "thresholds"},
            # species-gear-chain T27 (set-species-binding a, spec-set-species-binding.md): `speciesId`
            # is optional, never required — a `build.*`/`theme.*` themed set carries none, which is
            # the correct, explicit-absent state for those 67 entries, not a schema violation.
            # `setClass` (T27's second half, spec rev 2) is likewise optional in the SCHEMA but
            # always written by the generator: emit + repair both go through
            # `setgen.topology.stamp_class`, so every entry it produces carries one. Optional rather
            # than required because a hand-authored or pre-repair row would otherwise be rejected by
            # the schema before the repair that exists to fix it could run.
            extra={"themeKey", "theme", "members", "thresholds", "speciesId", "setClass"},
            refs={"members"}),
    _defined("gem", "gems", "gems",
            required={"family", "powerBand"},
            extra={"family", "element", "powerBand", "affinityElement"}),
    _defined("material", "materials", "materials",
            required={"runtimeId", "materialClass"},
            extra={"runtimeId", "materialClass", "element", "frame", "grade",
                  "scope", "scopeKey", "slot"}),
    _defined("curve", "curves", "curves",
            required={"input", "points"}, extra={"input", "points"}),
    _undefined("attribute", "attributes", "attributes"),
    _defined("charm", "charms", "charms",
            required={"charmClass", "apCost", "axis", "frameHint", "fixedAtoms"},
            extra={"charmClass", "apCost", "axis", "frameHint", "uniqueCarry", "fixedAtoms",
                   "roleGroups", "poolRolls"}),
    # strain-splice-host SSH2.4: `socket-word` renamed to `combination` IN PLACE (rename bundle
    # #2, spec-combination-regen.md) -- same slot in this tuple, so the count assertion below holds
    # precisely because nothing was removed-then-re-added. Field shape transcribed directly from
    # `gk-forge/tools/ItemSeedValidator/Registries/KindCatalog.cs`'s own `combination` row (`Defined(
    # "combination", ...)`), not re-derived here — the C# row's own comment already cites
    # `combogen/emit.py`'s `assemble_entry` as the ONE place a real entry is assembled. `runtimeId`/
    # `fixedAtoms` (socket-word's own shape) are gone: a combination is never socketed as an item
    # itself and grants resolve to an atom at BIND time, so it has no runtimeId of its own and no
    # fixedAtoms — `shape`/`aptitudes`/`grants` are its real identity fields instead.
    #
    # ⛔ `grantedTier` is NOT a field any more (strain-splice-host SSH7.5/SSH7.6). The tier a shape
    # grants is TUNING's, filled by `CombinationCorpus` at import; a corpus row that carries one is
    # refused by the C# gate. This Python row still listed it in `required` and `extra` after the C#
    # row dropped it, so a `--write` re-emitted 35 rows WITH `grantedTier` that the C# validator then
    # rejected as `UnknownKey` (found live 2026-09-22 while regenerating the combination corpus).
    _defined("combination", "combinations", "combinations",
            required={"shape", "aptitudes", "minSockets", "ingredients", "grants"},
            extra={"shape", "aptitudes", "archetype", "hostRole", "hostFrame", "minSockets",
                   "ingredients", "grants"}),
    _defined("recipe", "recipes", "recipes",
            required={"operation", "outputKind", "frame", "costLines"},
            extra={"operation", "outputKind", "outputRef", "outputQty", "frame", "costLines",
                   "soulsCostBand"},
            refs={"outputRef"}),
    _defined("enhancement-milestone", "enhancement-milestones", "enhancementMilestones",
            required={"runtimeFamily", "kindId", "params", "powerBand"},
            extra={"runtimeFamily", "kindId", "params", "powerBand"}),
    _defined("consumable", "consumables", "consumables",
            required={"classId", "useContext", "family", "powerBand"},
            extra={"classId", "useContext", "family", "element", "powerBand", "manifestCost",
                   "grantsActionId", "cooldownKey"}),
    _defined("drop-table", "drop-tables", "dropTables",
            required={"sourceAllow", "groups"}, extra={"sourceAllow", "groups"},
            refs={"sourceAllow", "groups"}),
    _defined("display-template", "display-templates", "displayTemplates",
            required={"runtimeFamily", "groupId", "status"},
            extra={"runtimeFamily", "plantOverrideKey", "plantOverrideName", "groupId",
                   "status"}),
    # relic-item-kind (empire-development Task 1.3a, spec-relic-item-kind.md §Design 1):
    # a rolled, never-equipped item with no equip role and no base type. Required is
    # COMMON_REQUIRED + flavorKey only -- no frame, no baseType, no role, no
    # counterPressure, no powerAxis. fixedAtoms is OPTIONAL (many relics are pure
    # Wonder-build cost tokens with zero atoms). refs={} -- a relic never points at
    # a base type or role.
    _defined("relic", "relics", "relics",
            required={"flavorKey"},
            extra={"flavorKey", "theme", "themeKey", "acquisition", "fixedAtoms"}),
)

assert len(KINDS) == 16, "16 kinds (15 Defined incl. relic + 1 Undefined: attribute)"
assert len({k.kind for k in KINDS}) == 16, "duplicate kind id in this port"


# ---------------------------------------------------------------------------------------------
# D4.29 (spec-unique-pipeline.md §1) — one ownership level per `unique` field. Five levels: the
# item seed-contract's four (AUTHORED, VALIDATED, DERIVED, GENERATED) plus dungeon-seed-contract's
# PLANNED ("the planner fixes it from the budget before the call; the model is shown it and may
# not change it") — first use of PLANNED under `adapters/items/`. A field with no declared level
# is a contract defect (`every_field_has_exactly_one_level`, dungeon/audit.py's own precedent).
#
# Transcribed directly from the spec's §1 table, not re-derived: `id`/`nameKey`/`iconKey`/
# `flavorKey` are PLANNED because the corpus mints them from a cell before any call
# (`unique.<theme>-<band>-<nnn>`, three keys off the same slug), never from model output.
# `frame`/`powerAxis`/`rarity`/`acquisition` are PLANNED because they ARE the grid cell (frame x
# axis x band) plus the acquisition gate (ssot-uniques.md §4.5) -- a wrong one here is invisible
# in the same way a wrong ordinal is (dungeon-seed-contract.md §1). `fixedAtoms[].family`,
# `varianceSlot.family`, `baseType`, `counterPressure.kind`, `actionGrantRef`, `dungeonBinding`
# and `tags` are VALIDATED against real, closed registries -- never invented, never free text.
# `name`, `flavor`, `counterPressure.note` and `reason` are the only AUTHORED (free-text) fields.
# `powerBand` on a fixed atom is AUTHORED but VOTED (seed-contract §4), not a plain free write.
UNIQUE_OWNERSHIP: "dict[str, str]" = {
    "id": "PLANNED", "nameKey": "PLANNED", "iconKey": "PLANNED", "flavorKey": "PLANNED",
    "name": "AUTHORED", "flavor": "AUTHORED", "reason": "AUTHORED",
    "frame": "PLANNED", "powerAxis": "PLANNED", "rarity": "PLANNED", "acquisition": "PLANNED",
    "baseType": "VALIDATED",
    "fixedAtoms": "VALIDATED",           # family VALIDATED, powerBand AUTHORED+voted -- one level
    "varianceSlot": "VALIDATED",         # family VALIDATED, variance AUTHORED -- one level, per entry
    "counterPressure": "VALIDATED",      # kind VALIDATED; its own arguments VALIDATED -- never the note
    "actionGrantRef": "VALIDATED",
    "theme": "VALIDATED", "themeKey": "VALIDATED",
    "tags": "VALIDATED",
    # COMMON_FIELDS this kind does not use for identity (name/nameKey/id/tags/flavor/flavorKey/
    # iconKey are already assigned above): enabled, notes, overrides, unlockGate are structural
    # bookkeeping, not part of the anchor's own identity -- VALIDATED (closed true/false or a
    # frozen gate id, never authored free-form).
    "enabled": "VALIDATED", "notes": "AUTHORED", "overrides": "VALIDATED", "unlockGate": "VALIDATED",
}

VALID_OWNERSHIP_LEVELS = frozenset({"AUTHORED", "VALIDATED", "DERIVED", "GENERATED", "PLANNED"})

# DERIVED, never in the file (spec §1's own table, last row): climateAffinity (the theme's
# elementAffinity[]), budget_ae, the container id, extend-slot carriage, footprint. Listed for
# documentation -- there is no field in the seed file to assign a level to for any of these.
UNIQUE_DERIVED_FACTS = frozenset({
    "climateAffinity", "budget_ae", "containerId", "extendSlotCarriage", "footprint",
})
