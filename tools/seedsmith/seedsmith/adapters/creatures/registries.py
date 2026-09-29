"""seedsmith.adapters.creatures.registries — closed vocabularies for the creatures feature.

Unlike `adapters/items/registries.py`, there is no committed JSON registry to read fresh: the
frozen vocabularies here mirror C# enums (`CreatureRarity.cs`, `ActorElementTypes.cs`,
`CreatureSpeciesCatalog.cs`, `CreatureTraitCatalog.cs`), which is exactly the "code, not data" case
`adapters/items/kinds.py`'s own docstring already established a precedent for: transcribed once,
with a citation, because there is no JSON file that states the same fact. Read the cited file
fresh if this ever drifts — `test_adapter_creatures.py` pins the exact counts so a future enum change
that isn't ported here fails loudly rather than silently.

`family` and `motif` are append-only and genuinely EMPTY in D1 — no registry file exists for them
yet (`family-consolidate`/`motif-derive` are D2). Declaring the keys now with empty sets, rather
than omitting them, is what lets `dimensions()` fall back to `side/rarity` partitioning honestly
(spec-creature-corpus-emit.md §9 Q1) instead of the adapter pretending to a grouping it cannot supply.
"""
from __future__ import annotations

# Citations, read 2026-08-31 — RARITY/DEPLOY_MODE ids are transcribed VERBATIM from an existing
# string-id producer; the rest have no id-string producer anywhere in the codebase (the enums are
# consumed as .NET names or flattened to booleans) and are kebab-cased by inference from the
# sibling conventions that DO exist, flagged as such rather than presented as a direct citation:
#   gk-core/src/FusionRpg.Core/Creatures/CreatureRarity.cs:30      — CreatureRarityIds.ToId(), the literal source
#   gk-core/src/FusionRpg.Server/CreatureEndpoints.cs:29        — the literal source for "plant-avatar"/"hypno-ally"
#   gk-core/src/FusionRpg.Core/Creatures/CreatureRarity.cs:13-19   — CreatureAcquisition enum names (INFERRED kebab-case;
#                                                       no id-string producer exists — CreatureEndpoints.cs:30-31
#                                                       flattens it to booleans instead of emitting a string id)
#   gk-core/src/FusionRpg.Core/Stats/Derived/ActorElementTypes.cs — ElementRoster.Concrete (+ OmniId, literal)
#   gk-core/src/FusionRpg.Core/Creatures/CreatureSpeciesCatalog.cs — KnownVariants (literal strings already)
#   gk-core/src/FusionRpg.Core/Creatures/CreatureTraitCatalog.cs   — CreatureTraitCatalog.All (TraitId literal already)
#
# `acquisition` is a REGISTRY vocabulary only, never a `dimensions()` entry: `CreatureAcquisition` is
# `[Flags]` (a creature can be Summonable|EventOnly at once), which doesn't fit a Dimension's
# one-value-per-entry shape — spec-adapter-creatures.md §2.1's dimensions table already omits it,
# listing only side/rarity/element/family.

RARITY: "frozenset[str]" = frozenset({"common", "rare", "epic", "legendary"})

ELEMENT: "frozenset[str]" = frozenset({"fire", "ice", "air", "earth", "light", "dark", "omni"})

DEPLOY_MODE: "frozenset[str]" = frozenset({"plant-avatar", "hypno-ally"})

ACQUISITION: "frozenset[str]" = frozenset({"summonable", "capture-only", "event-only"})  # inferred, see above

SIDE: "frozenset[str]" = frozenset({"plant", "zombie"})

VARIANT: "frozenset[str]" = frozenset(
    {"normal", "ancient", "mutated", "corrupted", "blessed", "cursed", "shiny"})

TRAIT: "frozenset[str]" = frozenset({
    "berserker", "regenerator", "soul-eater", "critical-hunter", "guardian", "swift",
    "immortal", "loyal", "greedy", "bloodthirsty", "coward", "genius", "void-touched",
    "chaos-marked",
})

# Append-only, empty until D2 (family-consolidate, motif-derive commit their first vocabulary).
FAMILY: "frozenset[str]" = frozenset()
MOTIF: "frozenset[str]" = frozenset()

# `Coverage/EmptyPartition` (spec-creature-corpus-emit.md §9 Q1's own stated reason to pick a
# partition key) reads `registries().vocabularies["partitions"]` as the ALLOCATED set and diffs it
# against what the corpus actually occupies — omitting this key silently disables the metric
# (`.get(..., frozenset())` makes `allocated - occupied` always empty, never a false negative you'd
# notice, which is worse than a crash). All 8 side×rarity combinations are legal (the only
# `legal_combinations()` rule this adapter declares is about element×rarity, not side×rarity), so
# all 8 are allocated — a creature-count-driven roster is expected to leave some empty, and that is
# real signal `EmptyPartition` should report, not something to hide by allocating fewer.
PARTITIONS: "frozenset[str]" = frozenset(f"{side}/{rarity}" for side in SIDE for rarity in RARITY)


def load_vocabularies() -> "dict[str, frozenset[str]]":
    return {
        "side": SIDE,
        "rarity": RARITY,
        "element": ELEMENT,
        "deployMode": DEPLOY_MODE,
        "acquisition": ACQUISITION,
        "variant": VARIANT,
        "trait": TRAIT,
        "family": FAMILY,
        "motif": MOTIF,
        "partitions": PARTITIONS,
    }


def load_versions() -> "dict[str, int]":
    # All at v1 — this is the first registry either has ever had. `family`/`motif` become
    # append-only-versioned in D2 when `family-consolidate.md §2.3`'s files first commit.
    return {name: 1 for name in load_vocabularies()}
