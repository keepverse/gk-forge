"""The seven dungeon anchor kinds (D1.6, spec-dungeon-seed-contract.md §1). `reference_fields` are
what `seedsmith.planner.ordering.derive_kind_order` reads to compute the layer order in §3 — no
stage label exists anywhere in this tree; the order is a derived FACT, not a written one.
"""
from __future__ import annotations

from ..base import KindSpec

DOMAIN = KindSpec(
    kind="dungeon-domain", directory="domains", namespace="domain",
    required=frozenset({
        "domainId", "name", "flavor", "theme", "climate", "dangerBand", "entry",
        "layoutTemplateId", "bossSpeciesRef", "retinueFamily", "roomPalette", "questPool",
        "lootBinding", "entranceHint", "variants", "tags", "reason",
    }),
    optional=frozenset({"permadeathFromRung", "firstClearRef"}),
    reference_fields=frozenset({"layoutTemplateId", "roomPalette", "questPool"}),
    motif_expression="a place — a whole descent, its danger and the fiction that holds its rooms together",
)

ROOM = KindSpec(
    kind="dungeon-room", directory="rooms", namespace="room",
    required=frozenset({
        "roomId", "kind", "climate", "name", "flavor", "hazardBand", "sightBand",
        "dispositionBase", "encounterRef", "eventPool", "secretEligible", "tags", "reason",
    }),
    reference_fields=frozenset({"encounterRef", "eventPool"}),
    motif_expression="a place — what the room looks like and what it costs to cross",
)

LAYOUT = KindSpec(
    kind="dungeon-layout", directory="layouts", namespace="layout",
    required=frozenset({
        "layoutId", "sizeBand", "widthBand", "branchiness", "gateDensity", "secretDensity",
        "oneWayDensity", "raidModes",
    }),
    reference_fields=frozenset(),  # model-free, planner-emitted (§1.3) — no cross-kind ref
    motif_expression=None,  # carries no prose (§1.3: "a layout carries no prose")
)

EVENT = KindSpec(
    kind="dungeon-event", directory="events", namespace="event",
    required=frozenset({
        "eventId", "kind", "theme", "name", "flavor", "reason", "climateAffinity",
        "repeatScope", "eligibility", "outcomes", "supplyOverride", "chainRef",
    }),
    reference_fields=frozenset({"chainRef"}),
    motif_expression="an encounter with the place — what happens here, and what it costs to find out",
)

QUEST = KindSpec(
    kind="dungeon-quest", directory="quests", namespace="quest",
    required=frozenset({
        "questId", "objectiveTemplate", "scope", "name", "flavor", "targetRef", "countBand",
        "rewardBand", "repeatScope", "prereqRefs", "chainRef",
    }),
    reference_fields=frozenset({"prereqRefs", "chainRef"}),
    motif_expression="a task — what is asked, and why it would matter to the one asking",
)

ENCOUNTER = KindSpec(
    kind="dungeon-encounter", directory="encounters", namespace="encounter",
    required=frozenset({
        "encounterId", "formation", "elementSpread", "name", "reason", "slots", "threatWindow",
        "rankOrder", "tempo", "synergyHint", "affixRoll",
    }),
    optional=frozenset({"boss"}),
    reference_fields=frozenset(),  # a filter over the species corpus, never a list of species (S2-13)
    motif_expression="a fight — the shape of the opposition, never which species fill it",
)

SUPPLY_EXTENSION = KindSpec(
    kind="dungeon-supply-ext", directory="supplies", namespace="supply-ext",
    required=frozenset({"consumableRef", "overrideTags", "useContextAdds"}),
    # `consumableRef` names an item-corpus id -- a CROSS-CORPUS input (checked as a vocabulary,
    # §1.7 "VALIDATED against the consumable id vocabulary"), never an intra-corpus
    # `reference_fields` edge (§3: "Intra-corpus references are reference_fields; cross-corpus
    # inputs are vocabularies"). Marking it here would be a dangling edge `kind_edges` would
    # silently drop rather than the real ordering fact it is not.
    reference_fields=frozenset(),
    motif_expression=None,  # an extension record, not authored content (§1.7)
)

KINDS: "tuple[KindSpec, ...]" = (DOMAIN, ROOM, LAYOUT, EVENT, QUEST, ENCOUNTER, SUPPLY_EXTENSION)

# Kinds whose every field is PLANNED — model-free, emitted entirely by the planner (§1.3, §3).
MODEL_FREE_KINDS = frozenset({"dungeon-layout"})
