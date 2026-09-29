"""The seven dungeon anchor schemas (D1.6, spec-dungeon-seed-contract.md §1). Five ownership
levels — the item seed-contract's four (AUTHORED, VALIDATED, DERIVED, GENERATED) plus this
program's own PLANNED (§1: "the planner fixes it from the budget before the call; the model is
shown it and may not change it"). A field with no declared level is a contract defect
(`every_field_has_exactly_one_level`).
"""
from __future__ import annotations

from typing import Any

from .descriptions import DESCRIPTIONS
from .kinds import DOMAIN, ROOM, LAYOUT, EVENT, QUEST, ENCOUNTER, SUPPLY_EXTENSION

# ---------------------------------------------------------------------------------------------
# Real, shipped vocabularies — read from the registries reader, never re-typed by hand where a
# registry already owns the list (S1's own discipline). Vocabularies with no dungeon-registries
# home (element ids, theme ids, threat-band ids) are cited to their real source instead.
# ---------------------------------------------------------------------------------------------
from . import registries as _reg
from seedsmith.ladders import THREAT_BAND as _THREAT_BAND

ELEMENTS = ("fire", "ice", "air", "earth", "light", "dark")  # ActorElementTypes.cs:3-11
THREAT_BAND = _THREAT_BAND  # declaring read: data/tuning/creature-threat.v1.json (T-2)
BOSS_FLOOR_THREAT_BAND = _THREAT_BAND[6:]  # rungs 7-10, §1.1 bossSpeciesRef — a slice, never a retype
ENTRANCE_HINT = ("Lair", "Tear", "Vault", "Anomaly")  # SlotTypeCatalog.cs:14-20
VARIANTS = ("normal", "ancient", "mutated", "corrupted", "blessed", "cursed", "shiny")
EVENT_KIND = ("curio", "encounter-event", "shrine", "trap", "bargain", "story")
EVENT_REPEAT_SCOPE = ("per-delve", "per-domain", "once-per-player")
OUTCOME_ORDINAL = ("good", "mixed", "bad", "nothing")
OUTCOME_CONSEQUENCE = ("none", "loot", "encounter", "scout")
DROP_BAND = ("staple", "frequent", "occasional", "seldom", "exceptional")  # bands.v1.json:451-490, items registry
QUEST_SCOPE = ("delve", "domain", "roster")
BOSS_PHASE_TRIGGER = ("hp-threshold", "round", "ally-down", "none")
REACH = ("melee", "short", "long", "siege", "none")
TARGET_PREFERENCE = ("frontline", "backline", "swarm", "elite", "structure", "indiscriminate", "none")
ATTACK_TEMPO = ("ponderous", "slow", "steady", "quick", "flurry", "none")
POSTURE = ("Force", "Finesse", "Bastion")  # AptitudeCatalog postures, creatures/anchor/schema.py precedent

# The one structural integer this adapter allow-lists (§2): manifestCost, a dispatch-time count
# already carried by the base consumable record — never balance arithmetic.
ALLOWLISTED_INTEGER_FIELDS = frozenset({"manifestCost"})


def _dungeon_registries() -> dict:
    """Loaded fresh per call — the same `read, never transcribed` discipline `registries.py`'s
    own module docstring states."""
    return {
        "roomKind": frozenset(_reg.load_room_kinds()),
        "doorKind": frozenset(_reg.load_door_kinds()),
        "overrideTag": _reg.load_override_tags(),
        "objectiveTemplate": frozenset(_reg.load_objective_templates()),
        "interactionVerb": frozenset(_reg.load_interaction_verbs()),
        "raidMode": _reg.load_raid_modes(),
        "disposition": _reg.load_disposition(),
        "bands": _reg.load_bands(),
        "theme": _reg.load_theme_ids(),
    }


def _desc(field: str) -> str:
    try:
        return DESCRIPTIONS[field]
    except KeyError:
        raise KeyError(f"dungeon anchor field {field!r} has no description in descriptions.py") from None


def _enum(field: str, values: "tuple[str, ...] | frozenset[str]", *, nullable: bool = False,
          const: bool = False, planned_value: "str | None" = None) -> dict:
    enum_values = sorted(values) + (["none"] if nullable and "none" not in values else [])
    node: dict = {"type": "string", "description": _desc(field)}
    if const:
        # PLANNED fields are pinned to ONE value per call, never offered as a free choice (§2).
        # `planned_value` is the planner's real minted/picked value for this call; absent one
        # (schema shown for audit/documentation, not an actual generation call) a placeholder
        # names itself as such rather than silently picking an arbitrary real member.
        node["const"] = planned_value if planned_value is not None else f"<planned:{field}>"
    else:
        node["enum"] = enum_values
    return node


def _planned_const(field: str, value_type: str, placeholder: Any) -> dict:
    """A PLANNED field whose shape is not a plain string enum (an id, an object, an array) — still
    pinned `const` per call, per the same rule `_enum(..., const=True)` enforces."""
    return {"type": value_type, "const": placeholder, "description": _desc(field)}


def _ref_array(field: str, *, min_items: int = 1, nullable: bool = False) -> dict:
    node: "dict[str, Any]" = {
        "type": "array", "items": {"type": "string"}, "minItems": 0 if nullable else min_items,
        "uniqueItems": True, "description": _desc(field),
    }
    return node


# ---------------------------------------------------------------------------------------------
# Ownership tables — one dict per kind, exactly the fields KindSpec.required | optional names.
# ---------------------------------------------------------------------------------------------

DOMAIN_OWNERSHIP = {
    "domainId": "PLANNED", "name": "AUTHORED", "flavor": "AUTHORED", "theme": "VALIDATED",
    "climate": "PLANNED", "dangerBand": "PLANNED", "permadeathFromRung": "VALIDATED",
    "entry": "PLANNED", "layoutTemplateId": "PLANNED", "bossSpeciesRef": "VALIDATED",
    "firstClearRef": "VALIDATED", "retinueFamily": "VALIDATED", "roomPalette": "VALIDATED",
    "questPool": "VALIDATED", "lootBinding": "PLANNED", "entranceHint": "VALIDATED",
    "variants": "VALIDATED", "tags": "VALIDATED", "reason": "AUTHORED",
}

ROOM_OWNERSHIP = {
    "roomId": "PLANNED", "kind": "PLANNED", "climate": "PLANNED", "name": "AUTHORED",
    "flavor": "AUTHORED", "reason": "AUTHORED", "hazardBand": "AUTHORED", "sightBand": "AUTHORED",
    "dispositionBase": "VALIDATED", "encounterRef": "VALIDATED", "eventPool": "VALIDATED",
    "secretEligible": "VALIDATED", "tags": "VALIDATED",
}

LAYOUT_OWNERSHIP = {
    "layoutId": "PLANNED", "sizeBand": "PLANNED", "widthBand": "PLANNED", "branchiness": "PLANNED",
    "gateDensity": "PLANNED", "secretDensity": "PLANNED", "oneWayDensity": "PLANNED", "raidModes": "PLANNED",
}

EVENT_OWNERSHIP = {
    "eventId": "PLANNED", "kind": "PLANNED", "theme": "PLANNED", "name": "AUTHORED",
    "flavor": "AUTHORED", "reason": "AUTHORED", "climateAffinity": "PLANNED",
    "repeatScope": "AUTHORED", "eligibility": "AUTHORED", "outcomes": "AUTHORED",
    "supplyOverride": "VALIDATED", "chainRef": "VALIDATED",
}

QUEST_OWNERSHIP = {
    "questId": "PLANNED", "objectiveTemplate": "PLANNED", "scope": "PLANNED", "name": "AUTHORED",
    "flavor": "AUTHORED", "targetRef": "VALIDATED", "countBand": "AUTHORED",
    "rewardBand": "AUTHORED", "repeatScope": "AUTHORED", "prereqRefs": "VALIDATED", "chainRef": "VALIDATED",
}

ENCOUNTER_OWNERSHIP = {
    "encounterId": "PLANNED", "formation": "PLANNED", "elementSpread": "PLANNED",
    "name": "AUTHORED", "reason": "AUTHORED", "slots": "AUTHORED", "threatWindow": "AUTHORED",
    "rankOrder": "AUTHORED", "tempo": "AUTHORED", "synergyHint": "VALIDATED",
    "affixRoll": "PLANNED", "boss": "AUTHORED",
}

SUPPLY_EXT_OWNERSHIP = {
    "consumableRef": "VALIDATED", "overrideTags": "VALIDATED", "useContextAdds": "VALIDATED",
}

OWNERSHIP_BY_KIND = {
    "dungeon-domain": DOMAIN_OWNERSHIP, "dungeon-room": ROOM_OWNERSHIP, "dungeon-layout": LAYOUT_OWNERSHIP,
    "dungeon-event": EVENT_OWNERSHIP, "dungeon-quest": QUEST_OWNERSHIP, "dungeon-encounter": ENCOUNTER_OWNERSHIP,
    "dungeon-supply-ext": SUPPLY_EXT_OWNERSHIP,
}

# The model authors AUTHORED fields; PLANNED are pinned const, shown but never a free choice;
# VALIDATED are named by the model against a frozen registry; DERIVED/GENERATED never appear.
AUTHORED_FIELDS_BY_KIND = {k: frozenset(f for f, lvl in own.items() if lvl == "AUTHORED") for k, own in OWNERSHIP_BY_KIND.items()}
PLANNED_FIELDS_BY_KIND = {k: frozenset(f for f, lvl in own.items() if lvl == "PLANNED") for k, own in OWNERSHIP_BY_KIND.items()}
VALIDATED_FIELDS_BY_KIND = {k: frozenset(f for f, lvl in own.items() if lvl == "VALIDATED") for k, own in OWNERSHIP_BY_KIND.items()}

#: §9 (spec-dungeon-generator-repair.md): the text keys a committer stamps beside each prose field.
#: DERIVED means the value is computed at commit from the string itself, so it is NEVER a model-facing
#: schema field — a generated key in a call schema is the defect this table names. Kept out of the
#: ownership tables above on purpose: those are constrained by the four-level vocabulary and by
#: `test_every_field_has_exactly_one_level`'s no-stray-entry rule to the KindSpec's real fields.
DERIVED_FIELDS_BY_KIND: "dict[str, tuple[str, ...]]" = {
    "dungeon-event": ("nameKey", "flavorKey"),
}


def build_domain_schema(*, planned_values: "dict[str, Any] | None" = None) -> dict:
    reg = _dungeon_registries()
    pv = planned_values or {}
    properties: "dict[str, Any]" = {
        "domainId": _planned_const("domainId", "string", pv.get("domainId", "<planned:domainId>")),
        "name": {"type": "string", "description": _desc("name")},
        "flavor": {"type": "string", "description": _desc("flavor")},
        "theme": _enum("theme", pv.get("themeCandidates", reg["theme"])),
        "climate": _enum("climate", ELEMENTS, const=True),
        "dangerBand": _enum("dangerBand", ("shallow", "mid", "deep", "abyssal"), const=True),
        "permadeathFromRung": {"anyOf": [{"type": "string", "enum": ["none"]}, {"type": "string"}], "description": _desc("permadeathFromRung")},
        "entry": _enum("entry", ("once", "many"), const=True),
        "layoutTemplateId": _planned_const("layoutTemplateId", "string", "<planned:layoutTemplateId>"),
        "bossSpeciesRef": {"type": "string", "description": _desc("bossSpeciesRef")},
        "firstClearRef": _enum("firstClearRef", (), nullable=True),
        "retinueFamily": _enum("retinueFamily", (), nullable=True),
        "roomPalette": _ref_array("roomPalette"),
        "questPool": _ref_array("questPool", min_items=2),
        "lootBinding": _planned_const("lootBinding", "object", {}),
        "entranceHint": _enum("entranceHint", ENTRANCE_HINT),
        "variants": _ref_array("variants", nullable=True),
        "tags": _ref_array("tags", nullable=True),
        "reason": {"type": "string", "description": _desc("reason")},
    }
    return _finish("DungeonDomain", properties, required=DOMAIN.required, optional=DOMAIN.optional)


def build_room_schema() -> dict:
    reg = _dungeon_registries()
    properties: "dict[str, Any]" = {
        "roomId": _planned_const("roomId", "string", "<planned:roomId>"),
        "kind": _enum("kind", reg["roomKind"], const=True),
        "climate": _enum("climate", ELEMENTS, nullable=True, const=True),
        "name": {"type": "string", "description": _desc("name")},
        "flavor": {"type": "string", "description": _desc("flavor")},
        "reason": {"type": "string", "description": _desc("reason")},
        "hazardBand": _enum("hazardBand", reg["bands"]["hazardBand"]),
        "sightBand": _enum("sightBand", reg["bands"]["sightBand"]),
        "dispositionBase": _enum("dispositionBase", reg["disposition"], nullable=True),
        "encounterRef": _enum("encounterRef", (), nullable=True),
        "eventPool": _ref_array("eventPool", min_items=0, nullable=True),
        "secretEligible": _enum("secretEligible", ("yes", "no")),
        "tags": _ref_array("tags", nullable=True),
    }
    return _finish("DungeonRoom", properties, required=ROOM.required, optional=ROOM.optional)


def build_layout_schema() -> dict:
    reg = _dungeon_registries()
    properties: "dict[str, Any]" = {
        "layoutId": _planned_const("layoutId", "string", "<planned:layoutId>"),
        "sizeBand": _enum("sizeBand", reg["bands"]["depthBand"], const=True),
        "widthBand": _enum("widthBand", reg["bands"]["widthBand"], const=True),
        "branchiness": _enum("branchiness", reg["bands"]["branchiness"], const=True),
        "gateDensity": _enum("gateDensity", reg["bands"]["density"], const=True),
        "secretDensity": _enum("secretDensity", reg["bands"]["density"], const=True),
        "oneWayDensity": _enum("oneWayDensity", reg["bands"]["density"], const=True),
        "raidModes": _planned_const("raidModes", "array", []),
    }
    return _finish("DungeonLayout", properties, required=LAYOUT.required, optional=LAYOUT.optional)


def build_event_schema() -> dict:
    reg = _dungeon_registries()
    outcome_item = {
        "type": "object",
        "properties": {
            "ordinal": _enum("outcomes", OUTCOME_ORDINAL),
            "consequence": _enum("outcomes", OUTCOME_CONSEQUENCE),
            "dropBand": _enum("outcomes", DROP_BAND),
            "effects": {"type": "array", "items": {"type": "object"}, "minItems": 0},
        },
        "required": ["ordinal", "consequence", "dropBand", "effects"],
        "additionalProperties": False,
    }
    properties: "dict[str, Any]" = {
        "eventId": _planned_const("eventId", "string", "<planned:eventId>"),
        "kind": _enum("kind", EVENT_KIND, const=True),
        "theme": {"type": "string", "const": "theme.<planned>", "description": _desc("theme")},
        "name": {"type": "string", "description": _desc("name")},
        "flavor": {"type": "string", "description": _desc("flavor")},
        "reason": {"type": "string", "description": _desc("reason")},
        "climateAffinity": _enum("climateAffinity", ELEMENTS, nullable=True, const=True),
        "repeatScope": _enum("repeatScope", EVENT_REPEAT_SCOPE),
        "eligibility": {"type": "object", "description": _desc("eligibility")},
        "outcomes": {"type": "array", "items": outcome_item, "minItems": 2, "maxItems": 4, "description": _desc("outcomes")},
        "supplyOverride": _enum("supplyOverride", reg["overrideTag"], nullable=True),
        "chainRef": _enum("chainRef", (), nullable=True),
    }
    return _finish("DungeonEvent", properties, required=EVENT.required, optional=EVENT.optional)


def build_quest_schema() -> dict:
    reg = _dungeon_registries()
    properties: "dict[str, Any]" = {
        "questId": _planned_const("questId", "string", "<planned:questId>"),
        "objectiveTemplate": _enum("objectiveTemplate", reg["objectiveTemplate"], const=True),
        "scope": _enum("scope", QUEST_SCOPE, const=True),
        "name": {"type": "string", "description": _desc("name")},
        "flavor": {"type": "string", "description": _desc("flavor")},
        "targetRef": _enum("targetRef", (), nullable=True),
        "countBand": _enum("countBand", reg["bands"]["countBand"], nullable=True),
        "rewardBand": _enum("rewardBand", reg["bands"]["rewardBand"]),
        "repeatScope": _enum("repeatScope", EVENT_REPEAT_SCOPE),
        "prereqRefs": _ref_array("prereqRefs", min_items=0, nullable=True),
        "chainRef": _enum("chainRef", (), nullable=True),
    }
    return _finish("DungeonQuest", properties, required=QUEST.required, optional=QUEST.optional)


def build_encounter_schema() -> dict:
    reg = _dungeon_registries()
    slot_item = {
        "type": "object",
        "properties": {
            "posture": _enum("slots", POSTURE),
            "reach": _enum("slots", REACH),
            "targetPreference": _enum("slots", TARGET_PREFERENCE),
            "countBand": _enum("slots", reg["bands"]["countBand"]),
        },
        "required": ["posture", "reach", "targetPreference", "countBand"],
        "additionalProperties": False,
    }
    boss_item = {
        "type": "object",
        "properties": {
            "build": {"type": "string", "description": "ZombossPattern id"},
            "phasing": _enum("boss", reg["bands"]["phasing"]),
            "phaseTrigger": _enum("boss", BOSS_PHASE_TRIGGER),
            "signatureAction": {"type": "string"},
            "retinue": {"type": "object", "properties": {
                "slotRef": {"type": "string"}, "countBand": _enum("boss", reg["bands"]["countBand"]),
            }, "required": ["slotRef", "countBand"], "additionalProperties": False},
        },
        "required": ["build", "phasing", "phaseTrigger", "signatureAction", "retinue"],
        "additionalProperties": False,
    }
    properties: "dict[str, Any]" = {
        "encounterId": _planned_const("encounterId", "string", "<planned:encounterId>"),
        "formation": _enum("formation", reg["bands"]["formation"], const=True),
        "elementSpread": _enum("elementSpread", reg["bands"]["elementSpread"], const=True),
        "name": {"type": "string", "description": _desc("name")},
        "reason": {"type": "string", "description": _desc("reason")},
        "slots": {"type": "array", "items": slot_item, "minItems": 1, "description": _desc("slots")},
        "threatWindow": {"type": "object", "properties": {
            "floorRung": _enum("threatWindow", THREAT_BAND), "ceilRung": _enum("threatWindow", THREAT_BAND),
        }, "required": ["floorRung", "ceilRung"], "additionalProperties": False, "description": _desc("threatWindow")},
        "rankOrder": {"type": "array", "items": {"type": "string"}, "minItems": 1, "description": _desc("rankOrder")},
        "tempo": _enum("tempo", ATTACK_TEMPO),
        "synergyHint": _ref_array("synergyHint", min_items=0, nullable=True),
        "affixRoll": _enum("affixRoll", (), nullable=True, const=True),
        "boss": boss_item,
    }
    return _finish("DungeonEncounter", properties, required=ENCOUNTER.required, optional=ENCOUNTER.optional)


def build_supply_ext_schema() -> dict:
    properties: "dict[str, Any]" = {
        "consumableRef": {"type": "string", "description": _desc("consumableRef")},
        "overrideTags": _ref_array("overrideTags", min_items=0, nullable=True),
        "useContextAdds": {"type": "array", "items": {"type": "string", "enum": ["rest", "curio"]},
                           "minItems": 0, "uniqueItems": True, "description": _desc("useContextAdds")},
    }
    return _finish("DungeonSupplyExtension", properties, required=SUPPLY_EXTENSION.required, optional=SUPPLY_EXTENSION.optional)


def _finish(title: str, properties: dict, *, required: "frozenset[str]", optional: "frozenset[str]") -> dict:
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": title,
        "type": "object",
        "properties": properties,
        "required": sorted(required),
        "additionalProperties": False,
    }


SCHEMA_BUILDERS = {
    "dungeon-domain": build_domain_schema, "dungeon-room": build_room_schema,
    "dungeon-layout": build_layout_schema, "dungeon-event": build_event_schema,
    "dungeon-quest": build_quest_schema, "dungeon-encounter": build_encounter_schema,
    "dungeon-supply-ext": build_supply_ext_schema,
}


def build_schema(kind: str) -> dict:
    try:
        return SCHEMA_BUILDERS[kind]()
    except KeyError:
        raise KeyError(f"unknown dungeon anchor kind {kind!r}") from None
