"""seedsmith.adapters.creatures.kinds — the four creatures-adapter KindSpecs, plus per-kind motif
expression rules (spec-adapter-creatures.md §2.2, §2.7).

`item` and `action` are deliberately ABSENT (audit A3): `Corpus.load` is single-root, so a creature
"item" here would be a different thing from a real item -- unequippable, outside the item corpus's
own role/frame/affix rules. A creature is a THEME; items and actions stay in their own corpus and
reference it (`creature-themes`, wave D4). `test_adapter_creatures.py` asserts this absence directly.

`id_pattern`/`runtime_id_fields` left unset for every kind, matching `adapters/items/kinds.py`'s
own documented reason: `speciesId` is already stable kebab-case, and no acceptance criterion here
exercises the pattern (spec-adapter-creatures.md §8 Q1, decided 2026-08-31).
"""
from __future__ import annotations

from ..base import KindSpec

CREATURE = KindSpec(
    kind="creature", directory="creature", namespace="creature",
    required=frozenset({"id", "nameKey", "name", "side", "gameTypeId"}),
    optional=frozenset({"flavorInfo", "flavorIntroduce", "sunCost", "cooldownSec",
                        "hp", "attack", "armor", "armorMax", "coverage", "lineage"}),
    # The creature is the SOURCE of its own motifs, not a consumer expressing someone else's — so its
    # rule is "stated directly": unlike aspect/commander-effect/environment, nothing translates a
    # motif into another part of speech here. Given anyway, not left absent, so "every KindSpec
    # this adapter declares carries an expression rule" stays one invariant with no special case.
    motif_expression="stated directly — the creature's own signature, not filtered through another kind's part of speech",
)

ASPECT = KindSpec(
    kind="aspect", directory="aspect", namespace="aspect",
    required=frozenset({"id", "nameKey", "name", "creatureId"}),
    optional=frozenset(),
    reference_fields=frozenset({"creatureId"}),
    motif_expression="a bias — what this element-typing leans toward",
)

COMMANDER_EFFECT = KindSpec(
    kind="commander-effect", directory="commander-effect", namespace="commanderEffect",
    required=frozenset({"id", "nameKey", "name", "creatureId"}),
    optional=frozenset(),
    reference_fields=frozenset({"creatureId"}),
    motif_expression="a doctrine — how the squad behaves",
    # `doctrine` is free prose (§2.4 of spec-commander-effect.md), the field where thesaurus
    # convergence actually shows up — `name` alone missed the two pairs found on the live corpus.
    dedup_fields=frozenset({"doctrine"}),
)

# Ships as a kind; nothing generates into it in v1 (audit A7). With no world host, a
# `sector:`-scoped binding is rejected `ScopeUnsupported`, so environment content would be flavour
# nothing reads -- and Coverage would report those partitions "covered", overstating how finished
# the feature is. So its partitions are excluded from coverage until a real consumer exists
# (`report.cli`'s own coverage call must pass `exclude_kinds={"environment"}` for this adapter).
ENVIRONMENT = KindSpec(
    kind="environment", directory="environment", namespace="environment",
    required=frozenset({"id", "nameKey", "name", "creatureId", "sectorId"}),
    optional=frozenset(),
    reference_fields=frozenset({"creatureId", "sectorId"}),
    motif_expression="terrain, weather, what the ground does",
)

KINDS: "tuple[KindSpec, ...]" = (CREATURE, ASPECT, COMMANDER_EFFECT, ENVIRONMENT)

# A kind with no shipped generator yet (aspect waits on aspect-scope being BUILT by the creature
# program, not merely approved -- audit S2; environment waits on a world host -- A7). Excluded
# from coverage the same way `report.cli` already excludes exemplars: named here once, read by
# both `dimensions()`'s applies_to computation staying honest and by `creatures` package coverage
# wiring, so the exclusion is a single fact rather than two places that can drift apart.
NO_GENERATOR_YET: "frozenset[str]" = frozenset({"aspect", "environment"})

assert len(KINDS) == 4, "creatures adapter ships four kinds: creature, aspect, commander-effect, environment"
assert len({k.kind for k in KINDS}) == 4, "duplicate kind id"
assert all(k.motif_expression for k in KINDS), "every kind must carry a motif expression rule (§2.7)"
assert not any(k.kind in {"item", "action"} for k in KINDS), "items/actions are theme consumers, never a creatures kind (A3)"
