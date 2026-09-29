"""The structure anchor schema (base-defense `structure-schema`, module 23, spec-structure-schema.md).
Seventeen design-variable fields (plus `structureId`/`family`/`reason` bookkeeping the ideal doc's
own count did not include, and two DERIVED fields — the identical "N keys for M design variables"
shape `adapters/creatures/anchor/schema.py`'s own top comment already documents for the species anchor).
**The anchor holds no numbers at all.**

Ports `adapters/creatures/anchor/schema.py`'s exact pattern (`_enum_prop`/`_flag_array_prop`/
`_open_array_prop` helpers, an OWNERSHIP dict, `additionalProperties: False`, `required` = every
key) onto the structure anchor's own 17-field contract, with two additions the creature precedent never
needed: a per-row `_provenance.source` (AUTHORED vs GENERATED — structures mix hand-authored and
model-written rows in one corpus; creatures never did) and `ROLE_TO_STRUCTURE_KIND`, the P3-6 mapping
from this module's own 10-role vocabulary to the shipped 3-value `StructureKind` C# enum.
"""
from __future__ import annotations

from typing import Any, Optional

from .descriptions import DESCRIPTIONS
from seedsmith.ladders import RARITY_LADDER as _RARITY_LADDER

# Real, shipped vocabularies — never invented here. Sources:
#   REQUIRED_SLOT_KIND  gk-core/src/FusionRpg.Core/World/SlotTypeCatalog.cs:7-28 (SlotKind, 14 values)
#   ELEMENT             gk-core/src/FusionRpg.Core/Combat/Element/ElementTable.cs (same 6 as the creature anchor)
#   RARITY              gk-data/packs/fusion/data/seed/rarity/ladder.v1.json (ten-rung ladder, shared) — read via
#                       seedsmith.ladders, never re-transcribed (tier-propagation-contract T-2)
#   ACQUISITION_PATH    gk-core/src/FusionRpg.Core/World/Siege/Obstacles.cs:48-61 (AcquisitionPath, 4 values)
#   REACH               reused verbatim from adapters/creatures/anchor/schema.py's own REACH tuple
#   TEMPO               reused verbatim from adapters/creatures/anchor/schema.py's own ATTACK_TEMPO tuple
#
# Vocabularies this module authors fresh, because no C# enum or shared doc owns them yet — each is a
# defensible first pass per spec-structure-schema.md SS1's own table, not a guess presented as settled:
#   ROLE            the ten roles named by structure-seed-ideal.md:136 / spec-structure-corpus.md SS4
#   STRENGTH_BAND   decision 32's material tier — starts at the THREE rungs siege.v1.json's
#                   structure.tierMultiplierMilli already prices (1/2/3); structure-planner (c3) owns
#                   extending this ladder before any model call (decision 33), never this module
#   COST_PROFILE    a ratio-BAND name, never an amount (spec SS1: "which materials in what ratio band")
#   FOOTPRINT       spec SS1's own literal list: "one cell / small / large"
#   COVER_TIER      spec SS1's own literal list: "none - light - heavy - trench"
#   TARGET_PREFERENCE  base-defense-ideal.md:1891-1907's First/Last/Close/Strong

ROLE = ("Extract", "Refine", "Multiply", "Store", "Move", "Bank", "Enable", "Defend", "See", "Deny")
REQUIRED_SLOT_KIND = (
    "Wildland", "EssenceDeposit", "ShardVein", "MaterialSeam", "Lair", "Tear", "Vault",
    "Shrine", "Market", "Spire", "Anomaly", "Hazard", "Seat", "Rootbed",
)
ELEMENT = ("fire", "ice", "air", "earth", "light", "dark")
TEMPO = ("ponderous", "slow", "steady", "quick", "flurry")
REACH = ("melee", "short", "long", "siege")
STRENGTH_BAND = ("rubble", "timber", "stone")
RARITY = _RARITY_LADDER
COST_PROFILE = ("cheap", "moderate", "steep")
TARGET_PREFERENCE = ("First", "Last", "Close", "Strong")
ACQUISITION_PATH = ("built", "assembled", "summoned", "laboured")
FOOTPRINT = ("one-cell", "small", "large")
COVER_TIER = ("none", "light", "heavy", "trench")

# base-defense `structure-schema` SS1, "role (10) and StructureKind (3) - reconciled": StructureKind
# is DERIVED from role, never authored beside it. Extract/Multiply -> LoamSource; Store/Bank ->
# Storage; Refine -> Refinery; every other role -> None, meaning "no economic engine path" -- a real,
# named C# gap (StructureKind has no 4th value yet) that structure-catalog-import (c2) owns closing,
# not this module. A role mapped to None still raises, never returns a silent default (see
# `structure_kind_for` below) -- the same loud-over-silent stance `StructureCatalog.Validate` already
# takes for every other catalog rule.
ROLE_TO_STRUCTURE_KIND: "dict[str, Optional[str]]" = {
    "Extract": "LoamSource", "Multiply": "LoamSource",
    "Store": "Storage", "Bank": "Storage",
    "Refine": "Refinery",
    "Move": None, "Enable": None, "Defend": None, "See": None, "Deny": None,
}


class NoStructureKindMapping(Exception):
    """Raised by `structure_kind_for` for a role with no real StructureKind yet — never a silent
    default. Mirrors `StructureCatalog.Validate`'s own loud-over-silent stance in C#."""


def structure_kind_for(role: str) -> str:
    if role not in ROLE_TO_STRUCTURE_KIND:
        raise NoStructureKindMapping(f"role {role!r} is not one of the ten declared roles {ROLE!r}")
    kind = ROLE_TO_STRUCTURE_KIND[role]
    if kind is None:
        raise NoStructureKindMapping(
            f"role {role!r} has no StructureKind mapping yet — it needs a 4th C# StructureKind value "
            f"for 'no economic engine path', which is structure-catalog-import's (c2) job to add, "
            f"not this module's to guess at")
    return kind


# Ownership level per field (spec SS1's four levels: AUTHORED, DERIVED, GENERATED, VALIDATED). A
# field with no entry here is a contract defect (P3-4). GENERATED never appears as a per-FIELD level
# below — per the spec's own prose, it describes a per-ROW fact ("a row produced by structure-pipeline
# is GENERATED; a row in structure-corpus is AUTHORED"), carried by `_provenance.source`'s own enum,
# not by any individual field's ownership entry.
OWNERSHIP = {
    "structureId": "AUTHORED", "family": "AUTHORED",
    "role": "VALIDATED", "roleSecondary": "VALIDATED",
    "requiredSlotKind": "VALIDATED",
    "elementPrimary": "VALIDATED", "elementSecondary": "VALIDATED",
    "tempo": "AUTHORED", "reach": "AUTHORED",
    "strengthBand": "AUTHORED",
    "rarity": "VALIDATED",
    "traits": "VALIDATED",
    "costProfile": "AUTHORED",
    "targetPreference": "VALIDATED",
    "variants": "AUTHORED",
    "acquisitionPaths": "VALIDATED",
    "footprint": "AUTHORED", "coverTier": "AUTHORED",
    "controlPoint": "DERIVED", "obstacleVerbs": "DERIVED",
    "reason": "AUTHORED",
}

CLASSIFIED_FIELDS = frozenset(k for k, v in OWNERSHIP.items() if v in ("AUTHORED", "VALIDATED"))
DERIVED_FIELDS = frozenset(k for k, v in OWNERSHIP.items() if v == "DERIVED")

# No field is an allow-listed integer -- structures carry NO numeric identifier field at all (unlike
# the creature anchor's `gameTypeId`), so this is deliberately empty rather than omitted, matching
# `audit.py`'s own expectation of an explicit (possibly-empty) allow-list.
ALLOWLISTED_INTEGER_FIELDS: "frozenset[str]" = frozenset()


def _desc(field: str) -> str:
    try:
        return DESCRIPTIONS[field]
    except KeyError:
        raise KeyError(f"structure anchor field {field!r} has no description in descriptions.py") from None


def _enum_prop(field: str, values: "tuple[str, ...]", *, nullable: bool = False) -> dict:
    enum_values = list(values) + (["none"] if nullable else [])
    return {"type": "string", "enum": enum_values, "description": _desc(field)}


def _flag_array_prop(field: str, values: "tuple[str, ...]", *, allow_empty: bool = False) -> dict:
    return {
        "type": "array",
        "items": {"type": "string", "enum": list(values)},
        "minItems": 0 if allow_empty else 1,
        "uniqueItems": True,
        "description": _desc(field),
    }


def _open_array_prop(field: str) -> dict:
    return {
        "type": "array",
        "items": {"type": "string"},
        "minItems": 0,
        "description": _desc(field),
    }


def build_structure_anchor_schema() -> dict:
    """The resolved JSON Schema for one structure anchor. Consumable directly as an LM Studio
    `response_format` once `structure-pipeline` (c4) exists; zero model calls happen in this module
    itself (spec success criterion 5).
    """
    properties: "dict[str, Any]" = {
        "structureId": {"type": "string", "description": _desc("structureId")},
        "family": {"type": "string", "description": _desc("family")},

        "role": _enum_prop("role", ROLE),
        "roleSecondary": _enum_prop("roleSecondary", ROLE, nullable=True),

        "requiredSlotKind": _enum_prop("requiredSlotKind", REQUIRED_SLOT_KIND),

        "elementPrimary": _enum_prop("elementPrimary", ELEMENT, nullable=True),
        "elementSecondary": _enum_prop("elementSecondary", ELEMENT, nullable=True),

        "tempo": _enum_prop("tempo", TEMPO, nullable=True),
        "reach": _enum_prop("reach", REACH),

        "strengthBand": _enum_prop("strengthBand", STRENGTH_BAND),
        "rarity": _enum_prop("rarity", RARITY),

        "traits": _open_array_prop("traits"),

        "costProfile": _enum_prop("costProfile", COST_PROFILE),
        "targetPreference": _enum_prop("targetPreference", TARGET_PREFERENCE, nullable=True),

        "variants": _open_array_prop("variants"),

        # decision 35: VALIDATED, `none` illegal — a structure no path can produce can never appear
        # on a board. `allow_empty=False` (the `_flag_array_prop` default) is what enforces minItems=1.
        "acquisitionPaths": _flag_array_prop("acquisitionPaths", ACQUISITION_PATH),

        "footprint": _enum_prop("footprint", FOOTPRINT),
        "coverTier": _enum_prop("coverTier", COVER_TIER),

        # DERIVED (from role + requiredSlotKind) — the importer computes these, never the model.
        # The exact derivation formula is a named, deferred gap (see this module's own todo.md
        # evidence): declaring the CONTRACT (these are real, typed, DERIVED fields) is this module's
        # job; a private, ungrounded formula for "what obstacleVerbs a Deny-role structure gets" is
        # not something to guess at without re-reading structure-seed-ideal.md's own worked examples.
        "controlPoint": {"type": "boolean", "description": _desc("controlPoint")},
        "obstacleVerbs": _open_array_prop("obstacleVerbs"),

        "reason": {"type": "string", "description": _desc("reason")},
    }

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "StructureAnchor",
        "type": "object",
        "properties": properties,
        "required": sorted(properties.keys()),
        "additionalProperties": False,
    }

