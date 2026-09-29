"""seedsmith.adapters.items.recipegen.schema — the closed-enum answer schema.

⛔ P1, the same opening line every sibling module states: **the model writes identity plus the
verb/output pairing; code resolves every magnitude.** The model picks `name`, `flavor`, `operation`
(closed to `opvocab.SUPPORTED_FOR_GENERATION`), `frame`, `costLines` (material + costBand pairs,
both closed enums), an optional `soulsCostBand`, and — only for a `container`-output (`forge`)
recipe — `outputTarget` from a small, partition-scoped candidate list. It never picks `outputKind`
(derived from `operation`, see `opvocab.OPERATION_OUTPUT_KIND`), `outputQty` (always `1` — every
one of the real 30 shipped entries carries `outputQty: 1`, never authored), or a resolved quantity
for any cost line (recipes author BANDS, `bands.v1.json`'s own formula resolves them to a number at
runtime, never at authoring time — `seed-contract.md` §1/§3, restated in `MaterialRecipeCatalog.cs`'s
own class doc: "authors write bands, never magnitudes").
"""
from __future__ import annotations

from typing import Any, Mapping

from seedsmith.pipeline.run import validate_against_schema

from ..materialgen import vocab as material_vocab
from . import opvocab
NAME_MIN_LEN = 3
NAME_MAX_LEN = 64
FLAVOR_MIN_LEN = 0
FLAVOR_MAX_LEN = 240

#: The real, closed cost-band vocabulary (`gk-data/packs/fusion/data/seed/items/_registry/bands.v1.json`, FROZEN v1;
#: mirrored into the shipped materials tuning's own `costBandMultiplierPerMille`, read fresh by
#: `load_cost_bands` below rather than hand-typed here — this tuple is only the fallback used when
#: no tuning path is supplied, e.g. by a caller that has already loaded the tuning once).
FALLBACK_COST_BANDS: "tuple[str, ...]" = ("cheap", "modest", "standard", "steep", "exorbitant")

#: The frame vocabulary a recipe's own `frame` field uses in the real corpus — `humanoid`, `plant`,
#: or `any` (every `mutation`-output row in the shipped corpus is `frame: "any"`, since it operates
#: on whatever instance the player already owns, not a fresh mint of a specific frame).
FRAMES: "tuple[str, ...]" = ("humanoid", "plant", "any")

#: The literal sentinel a model sets on a `container`-output (`forge`) recipe's `outputTarget` to
#: request a BRAND NEW base type rather than naming an existing, un-recipe'd one — resolved to the
#: exact next-mintable id in the caller-supplied `(role, frame, band)` partition by
#: `brief.py`/`emit.py`, never a string the model invents itself.
MINT_NEW_SENTINEL = "mint-new"


def _blocked() -> "dict[str, Any]":
    return {
        "type": "string",
        "description": "Set this INSTEAD of the content fields if the brief cannot be satisfied — "
                       "say why. A blocked answer writes nothing and is reported, not retried "
                       "forever.",
    }


def _cost_line_schema(material_pool: "tuple[str, ...]", cost_bands: "tuple[str, ...]") -> "dict[str, Any]":
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["material", "costBand"],
        "properties": {
            "material": {"type": "string", "enum": list(material_pool),
                         "description": "one of materials-gen's 27 issuable ids — never a legacy "
                                        "shard band, never an id outside the closed vocabulary"},
            "costBand": {"type": "string", "enum": list(cost_bands)},
        },
    }


def recipe_schema(*, operations: "tuple[str, ...]", material_pool: "tuple[str, ...]",
                  cost_bands: "tuple[str, ...]", frames: "tuple[str, ...]" = FRAMES,
                  container_candidates: "tuple[str, ...] | None" = None,
                  max_cost_lines: int = 4) -> "dict[str, Any]":
    """The `recipe` answer schema for one generation call.

    `container_candidates` is `None` for a call that offers no `forge` target at all (the caller
    has not scoped a `(role, frame, band)` partition) — in that case `outputTarget` is omitted from
    the schema entirely and `operations` must not include `"forge"` (enforced by `brief.py`, not
    re-checked here: this function trusts its caller the same way `base_type_schema` trusts
    `class_choices`/`implicit_families` are already partition-scoped). When it IS a tuple,
    `outputTarget`'s enum is exactly `container_candidates + (MINT_NEW_SENTINEL,)` — small and
    partition-scoped, never the whole multi-hundred-entry base-types-gen corpus.
    """
    if not operations:
        raise ValueError("recipe_schema requires at least one legal operation")
    if not material_pool:
        raise ValueError("recipe_schema requires at least one issuable material id")
    if not cost_bands:
        raise ValueError("recipe_schema requires at least one legal cost band")

    properties: "dict[str, Any]" = {
        "name": {"type": "string", "minLength": NAME_MIN_LEN, "maxLength": NAME_MAX_LEN,
                 "description": "the recipe's authored display name, e.g. 'Forge: Cloth Armor'. "
                                "nameKey/id are derived afterwards — never authored."},
        "flavor": {"type": "string", "minLength": FLAVOR_MIN_LEN, "maxLength": FLAVOR_MAX_LEN},
        "operation": {"type": "string", "enum": list(operations),
                      "description": "the craft verb — outputKind is derived from this, never a "
                                     "second choice"},
        "frame": {"type": "string", "enum": list(frames)},
        "costLines": {
            "type": "array", "minItems": 0, "maxItems": max_cost_lines,
            "items": _cost_line_schema(material_pool, cost_bands),
        },
        "soulsCostBand": {"type": "string", "enum": list(cost_bands)},
        "blocked": _blocked(),
    }
    if container_candidates is not None:
        properties["outputTarget"] = {
            "type": "string",
            "enum": list(container_candidates) + [MINT_NEW_SENTINEL],
            "description": "an existing, un-recipe'd base-type id in this partition, or the "
                           f"literal {MINT_NEW_SENTINEL!r} to request a brand new one",
        }

    return {
        "type": "object",
        "additionalProperties": False,
        "required": [],
        "properties": properties,
    }


def schema_field_names(schema: "dict[str, Any]") -> "tuple[str, ...]":
    """Every property name in the schema — for a test asserting `outputKind`/`outputQty`/`id`/
    `nameKey` are ABSENT (P1: the model never authors them)."""
    return tuple(sorted(schema.get("properties", {})))


def validate_answer(answer: Mapping[str, Any], schema: Mapping[str, Any]) -> "list[str]":
    """Validate a complete recipe or a deliberate, descriptive refusal locally.

    The endpoint's constrained decoding is an optimization, not the acceptance boundary. This
    function rechecks the operation/material relation with the same material vocabulary and cost
    matrix used by the emitter before a response can reach a ledger or corpus write.
    """
    defects = validate_against_schema(answer, schema)
    blocked = answer.get("blocked")
    if "blocked" in answer:
        if not isinstance(blocked, str) or not blocked.strip():
            defects.append("field 'blocked' must be a non-empty reason string")
        if set(answer) != {"blocked"}:
            defects.append("a blocked answer must not include content fields")
        return defects

    # `emit.assemble_entry` deliberately defaults frame/costLines and omits an empty flavor,
    # matching the existing corpus and test-call contract. Do not turn those defaults into a
    # false local rejection; only the two fields assembly cannot derive are mandatory.
    required = ("name", "operation")
    defects.extend(f"missing required content field {name!r}" for name in required if name not in answer)
    operation = answer.get("operation")
    cost_lines = answer.get("costLines")
    if not isinstance(operation, str) or not isinstance(cost_lines, list):
        return defects
    for index, line in enumerate(cost_lines):
        if not isinstance(line, Mapping):
            defects.append(f"costLines[{index}] must be an object")
            continue
        material_id = line.get("material")
        if not isinstance(material_id, str):
            defects.append(f"costLines[{index}].material must be a string")
            continue
        material = material_vocab.ISSUABLE_BY_ID.get(material_id)
        if material is None:
            defects.append(f"costLines[{index}].material {material_id!r} is not issuable")
            continue
        try:
            opvocab.check_cost_class(operation, material.material_class, material_id)
        except ValueError as error:
            defects.append(str(error))
    return defects
