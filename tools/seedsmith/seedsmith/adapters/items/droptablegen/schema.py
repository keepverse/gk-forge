"""seedsmith.adapters.items.droptablegen.schema — the model's answer schema, `audit_schema`-clean.

⛔ Same opening line every sibling module states: identity and closed-enum bands only, every
concrete weight/count resolved elsewhere (here: never at all inside this module -- that is the
out-of-scope band→row expander's job). The model picks `name`/`nameKey` and one `dropBand` per
row slot CODE has already selected (`brief.py`'s `RowSlotPlan`); it never sees a role, a frame, a
material ref, a weight, or a curve id -- those are supplied by code and never re-offered as
choices, mirroring `gemgen`'s "which family a subject gets is decided by code, never the model."
"""
from __future__ import annotations

from ....pipeline.model import BLOCKED_FIELD, audit_schema


def drop_table_answer_schema(*, row_count: int, drop_band_enum: "tuple[str, ...]",
                             rarity_ids: "tuple[str, ...]", offer_rarity_floor: bool) -> dict:
    if row_count < 1:
        raise ValueError("drop_table_answer_schema requires at least one row")
    if not drop_band_enum:
        raise ValueError("drop_table_answer_schema requires a non-empty dropBand enum")

    properties: dict = {
        BLOCKED_FIELD: {"type": "string"},
        "name": {"type": "string", "minLength": 1, "maxLength": 48,
                 "description": "the drop table's display name, e.g. 'Compost Cache'. nameKey/"
                                "groupKeys are derived from this afterwards -- never authored."},
        "rowBands": {
            "type": "array", "minItems": row_count, "maxItems": row_count,
            "description": "one dropBand per row CODE has already selected, IN ORDER: every "
                           "equipment slot, then every material ref, then every consumable ref, "
                           "then every insert (gem) ref, then the currency row. Never a raw "
                           "weight or an integer -- always one of the closed band names below.",
            "items": {"type": "string", "enum": list(drop_band_enum)},
        },
    }
    if offer_rarity_floor:
        properties["rarityFloor"] = {
            "type": "string", "enum": list(rarity_ids),
            "description": "optional: a rarity_id floor for the FIRST equipment row only. Omit "
                           "this field entirely if no floor fits.",
        }
    return {"type": "object", "properties": properties, "additionalProperties": False}


def validate_answer(answer: dict, *, row_count: int, drop_band_enum: "tuple[str, ...]",
                    rarity_ids: "tuple[str, ...]", offer_rarity_floor: bool) -> "list[str]":
    """Structural checks over an already-received answer. A `blocked` answer is legal and
    short-circuits every other check."""
    if not isinstance(answer, dict):
        return ["answer is not an object"]
    if answer.get(BLOCKED_FIELD):
        return []

    errors: "list[str]" = []
    name = answer.get("name")
    if not isinstance(name, str) or not (1 <= len(name) <= 48):
        errors.append("name must be a 1-48 character string")

    row_bands = answer.get("rowBands")
    if not isinstance(row_bands, list) or len(row_bands) != row_count:
        errors.append(f"rowBands must be a list of exactly {row_count} dropBand values")
    else:
        for i, band in enumerate(row_bands):
            if band not in drop_band_enum:
                errors.append(f"rowBands[{i}] {band!r} is not one of {drop_band_enum}")

    rarity_floor = answer.get("rarityFloor")
    if rarity_floor is not None:
        if not offer_rarity_floor:
            errors.append("rarityFloor was answered but no equipment row offers one")
        elif rarity_floor not in rarity_ids:
            errors.append(f"rarityFloor {rarity_floor!r} must be one of {rarity_ids}")

    return errors


__all__ = ["drop_table_answer_schema", "validate_answer", "audit_schema", "BLOCKED_FIELD"]
