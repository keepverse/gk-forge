"""The species anchor schema (creature-seed module 2, spec-anchor-contract.md). Twenty-two keys for
eighteen design variables — `speciesId`, `gameTypeId`, `pure` and `speciesKind` are bookkeeping the
ideal doc's count did not include, per §2 (`speciesKind` added 2026-09-17 by R-CS4). **The anchor
holds no numbers at all** except the one allow-listed identifier (`gameTypeId`), which is what makes
`audit.py`'s numeric audit mechanical rather than a judgement call.
"""
from __future__ import annotations

from typing import Any

from .descriptions import DESCRIPTIONS
from seedsmith.ladders import RARITY_LADDER as _RARITY_LADDER
from seedsmith.ladders import THREAT_BAND as _THREAT_BAND

# Real, shipped vocabularies — never invented here. Sources:
#   ELEMENTS      gk-core/src/FusionRpg.Core/Combat/Element/ElementTable.cs:125-130
#   APTITUDES     gk-core/src/FusionRpg.Core/Stats/Aptitudes/Aptitude.cs (AptitudeCatalog.All)
#   POSTURES      gk-core/src/FusionRpg.Core/Stats/Aptitudes/Aptitude.cs (enum Posture)
#   DEPLOY_MODE   gk-core/src/FusionRpg.Core/Creatures/CreatureRarity.cs (enum CreatureDeployMode)
#   ACQUISITION   gk-core/src/FusionRpg.Core/Creatures/CreatureRarity.cs (enum CreatureAcquisition, [Flags])
#   RARITY        gk-data/packs/fusion/data/seed/rarity/ladder.v1.json (ten-rung ladder, creatures adopted 2026-09-01)
#   THREAT_BAND   gk-core/data/tuning/creature-threat.v1.json (creature-seed module 4)
# Both are READ from their declaring files via seedsmith.ladders (tier-propagation-contract
# T-2) — never re-transcribed here.
#   VARIANTS      docs/architecture/creature-seed-ideal.md:274 (owner Q17)
#   RESOURCES     resource-hub-ssot.md — six actor resources incl. poise
#   SPECIES_KIND  creature-seed-ideal.md R-CS4 (owner, 2026-09-17) — declared below, code-owned

ELEMENTS = ("fire", "ice", "air", "earth", "light", "dark")

APTITUDES = (
    "Might", "Fortitude", "Vigor", "Onslaught",
    "Agility", "Composure", "Pierce", "Focus",
    "Bulwark", "Retribution", "Precision", "Ferocity",
)

# aptitude id -> posture, ported verbatim from AptitudeCatalog.All so `posture` derives correctly.
APTITUDE_POSTURE = {
    "Might": "Force", "Fortitude": "Force", "Vigor": "Force", "Onslaught": "Force",
    "Agility": "Finesse", "Composure": "Finesse", "Pierce": "Finesse", "Focus": "Finesse",
    "Bulwark": "Bastion", "Retribution": "Bastion", "Precision": "Bastion", "Ferocity": "Bastion",
}

POSTURES = ("Force", "Finesse", "Bastion")
THREAT_BAND = _THREAT_BAND
RARITY = _RARITY_LADDER
# The rank ladder mirrors the rarity ladder 1:1, row for row (spec-species-rank.md Assumption 1,
# owner-confirmed) — so it IS the rarity ladder's declaring read, never a retyped tuple
# (tier-propagation-contract T-2). `gk-core/data/tuning/creature-rank.v1.json` carries its own `ranks`
# table and the C# `CreatureRank` enum is the runtime vocabulary; all three must agree, and the
# C# loader + this module's own derive tests are what fail loudly if they drift.
RANK = _RARITY_LADDER
DEPLOY_MODE = ("PlantAvatar", "HypnoAlly")
ACQUISITION = ("Summonable", "CaptureOnly", "EventOnly")
VARIANTS = ("normal", "ancient", "mutated", "corrupted", "blessed", "cursed", "shiny")
RESOURCES = ("hp", "stamina", "hunger", "spirit", "qi", "poise")
BASIS = ("observed", "stated", "inferred", "blocked")

#: What a corpus ROW is, as opposed to what the creature on it is like (creature-seed R-CS4,
#: owner-ruled 2026-09-17: "just make closed enum for it"). A CLOSED vocabulary the code owns and a
#: human changes by review — the mirror image of the species roster itself, which is a derived
#: POPULATION and must never become an enum.
#:
#:   creature  a real creature whose `gameTypeId` resolves to a real PlantType/ZombieType member
#:   mimic     a real creature that deliberately BORROWS a lawn type id it does not natively own.
#:             R-CS2 exists so the corpus stays open to authored content: enforcing native
#:             resolution would refuse a new special species for the crime of being new. A borrowed
#:             id keeps spawn/render/dump joins working and makes the borrowing explicit and
#:             inspectable rather than an absence somebody later reads as a bug.
#:   excluded  NOT a creature. Never spawn, never draw, never count as roster. A positive statement
#:             about what the row is FOR (nothing, deliberately) — R-CS3 ruled marking over
#:             deleting because "a deleted id is untracked, and an untracked id can be silently
#:             re-used or re-derived."
#:
#: `mimic` implies `creature`; there is no meaningful excluded mimic, which is why R-CS2's id
#: provenance and R-CS3's what-is-this-row collapse into ONE enum rather than two axes.
#: Deliberately SEPARATE from BASIS: `basis: blocked` means "no text to derive power from" and a
#: real creature can legitimately be blocked — a different statement from "not a creature."
SPECIES_KIND = ("creature", "mimic", "excluded")
ATTACK_TEMPO = ("ponderous", "slow", "steady", "quick", "flurry")
REACH = ("melee", "short", "long", "siege")
TARGET_PREFERENCE = ("frontline", "backline", "swarm", "elite", "structure", "indiscriminate")

# Ownership level per field (spec §1). A field with no entry here is a contract defect.
OWNERSHIP = {
    "side": "CAPTURED", "speciesId": "CAPTURED", "gameTypeId": "CAPTURED",
    "elementPrimary": "CLASSIFIED", "elementSecondary": "CLASSIFIED",
    "aptitudePrimary": "CLASSIFIED", "aptitudeSecondary": "CLASSIFIED",
    "posture": "DERIVED", "pure": "DERIVED",
    "threatBand": "CLASSIFIED", "rarity": "CLASSIFIED",
    "rank": "DERIVED",
    "deployMode": "CLASSIFIED", "acquisition": "CLASSIFIED",
    "variants": "CLASSIFIED", "resourceProfile": "CLASSIFIED",
    "basis": "DERIVED", "speciesKind": "DERIVED",
    "family": "CLASSIFIED", "traits": "CLASSIFIED",
    "attackTempo": "CLASSIFIED", "reach": "CLASSIFIED", "targetPreference": "CLASSIFIED",
}

# The model authors CLASSIFIED fields only — CAPTURED is echoed from the dump, DERIVED is
# computed by code (never let the model author posture/pure/basis/speciesKind — boundaries).
CLASSIFIED_FIELDS = frozenset(k for k, v in OWNERSHIP.items() if v == "CLASSIFIED")
DERIVED_FIELDS = frozenset(k for k, v in OWNERSHIP.items() if v == "DERIVED")

# The one legal integer field — an identifier, never a magnitude (spec §4).
ALLOWLISTED_INTEGER_FIELDS = frozenset({"gameTypeId"})


def _desc(field: str) -> str:
    try:
        return DESCRIPTIONS[field]
    except KeyError:
        raise KeyError(f"anchor field {field!r} has no description in descriptions.py") from None


def _enum_prop(field: str, values: "tuple[str, ...]", *, nullable: bool = False) -> dict:
    enum_values = list(values) + (["none"] if nullable else [])
    return {"type": "string", "enum": enum_values, "description": _desc(field)}


def _flag_array_prop(field: str, values: "tuple[str, ...]") -> dict:
    return {
        "type": "array",
        "items": {"type": "string", "enum": list(values)},
        "minItems": 1,
        "uniqueItems": True,
        "description": _desc(field),
    }


def _open_array_prop(field: str) -> dict:
    return {
        "type": "array",
        "items": {"type": "string"},
        "minItems": 1,
        "description": _desc(field),
    }


def build_anchor_schema() -> dict:
    """The resolved JSON Schema for one species anchor. Consumable directly as an LM Studio
    `response_format: {"type": "json_schema", "json_schema": {"schema": build_anchor_schema()}}`.
    """
    properties: "dict[str, Any]" = {
        "side": {"type": "string", "enum": ["plant", "zombie"], "description": _desc("side")},
        "speciesId": {"type": "string", "description": _desc("speciesId")},
        # The one allow-listed integer — captured, an identifier, never arithmetic (spec §4).
        "gameTypeId": {"type": "integer", "description": _desc("gameTypeId")},

        "elementPrimary": _enum_prop("elementPrimary", ELEMENTS),
        "elementSecondary": _enum_prop("elementSecondary", ELEMENTS, nullable=True),

        "aptitudePrimary": _enum_prop("aptitudePrimary", APTITUDES),
        "aptitudeSecondary": _enum_prop("aptitudeSecondary", APTITUDES, nullable=True),

        "posture": _enum_prop("posture", POSTURES),
        "pure": {"type": "boolean", "description": _desc("pure")},

        "threatBand": _enum_prop("threatBand", THREAT_BAND),
        "rarity": _enum_prop("rarity", RARITY),
        "rank": _enum_prop("rank", RANK),

        "deployMode": _enum_prop("deployMode", DEPLOY_MODE),
        "acquisition": _flag_array_prop("acquisition", ACQUISITION),

        "variants": _flag_array_prop("variants", VARIANTS),
        "resourceProfile": _flag_array_prop("resourceProfile", RESOURCES),

        "basis": _enum_prop("basis", BASIS),
        "speciesKind": _enum_prop("speciesKind", SPECIES_KIND),

        "family": _open_array_prop("family"),
        "traits": _open_array_prop("traits"),

        "attackTempo": _enum_prop("attackTempo", ATTACK_TEMPO),
        "reach": _enum_prop("reach", REACH),
        "targetPreference": _enum_prop("targetPreference", TARGET_PREFERENCE),
    }

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "CreatureSpeciesAnchor",
        "type": "object",
        "properties": properties,
        "required": sorted(properties.keys()),
        "additionalProperties": False,
    }
