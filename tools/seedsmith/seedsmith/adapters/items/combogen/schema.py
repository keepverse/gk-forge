"""seedsmith.adapters.items.combogen.schema — closed-enum output, audit_schema-clean by construction.

⛔ P1: **the model writes identity, deterministic code writes magnitude.** The model picks the name,
the flavour, the four ingredient FAMILIES and the granted atom families. It never emits a number,
and that is enforced mechanically two ways: `test_strain_splice_gen.py`'s
`test_a_bare_integer_magnitude_field_fails_pipeline_construction` builds a real
`pipeline.model.Pipeline` around this function's output and proves `Pipeline.__post_init__` raises
at CONSTRUCTION for an injected numeric field; `test_the_schema_is_audit_schema_clean` proves the
un-tampered schema itself passes. **Note for whoever wires the live generation graph
(`workflow/graphs/item_combination.py`, `combogen/authored.py`):** neither of those two files
constructs a `Pipeline` — like `setgen.authored`/`workflow/graphs/item_set.py`, they drive the
model call through the `workflow.graphs` generation graph instead, which has no construction-time
audit hook of its own. `Pipeline` here is the mechanical PROOF this schema is clean, not the
runtime path a real batch takes; the graph path is proven clean by the SAME `audit_schema()` call,
run directly rather than through `Pipeline`.

Four names this schema avoids rather than allow-listing its way past
(`pipeline.model.MAGNITUDE_DENY_NAMES`): `tier` (the granted tier comes from tuning plus D22's
attunement bonus), `cost`, `duration` and `chance`. `minTier` never appears either — the P1 table
assigns it to code, and offering the model a per-ingredient tier is the shape most likely to be
mistaken for a magnitude the model may choose.

⚠ **`ingredients` is a flat array of four family strings, and repeats are legal.** D41 makes a
recipe an unordered MULTISET, so "two `atom.bulwark` and two `atom.vitality`" is a legal answer and
must be expressible; a schema with four distinct named slots would have re-introduced position by
the back door. `emit.ingredient_rows` folds the array into `(family, quantity)` rows — no tier (SSH7.3).
"""
from __future__ import annotations

from typing import Any

from .tuning import ComboTuning

#: The frames a combination may pin its host to. `""` is not offered — an unset host frame means
#: "any", and it is expressed by OMITTING the field, which is how the shipped corpus already
#: expresses it (18 of the 25 legacy entries leave `hostFrame` unset).
HOST_FRAMES: "tuple[str, ...]" = ("humanoid", "plant")


def _identity_fields() -> "dict[str, Any]":
    """`nameKey` is deliberately NOT here. `emit.name_key(cell)` already mints it — grid-derived,
    deterministic, `combination.{kind}-{key}` — before a single model call happens
    (`run.plan_run` assigns `Subject.name_key` from it). An earlier draft of this schema also
    offered `nameKey` to the model with a generic pattern, which is the exact P1 violation this
    module's own comment warns against one field over: an identity field the corpus needs unique
    and stable, left for the model to invent, is how two sources of truth for the same key start
    (naming.v1.json's own `nameKey.globalUniqueness` rule is corpus-wide, not per-run). Compare
    `kinds.py`'s `UNIQUE_OWNERSHIP["nameKey"] = "PLANNED"` — the same field is planned, not
    authored, on every other kind that mints one ahead of the call."""
    return {
        "name": {"type": ["string", "null"], "minLength": 3, "maxLength": 48},
        "flavor": {"type": ["string", "null"], "minLength": 8, "maxLength": 400},
    }


def _blocked() -> "dict[str, Any]":
    return {
        "type": ["string", "null"],
        "description": "Set this INSTEAD of the content fields if the brief cannot be satisfied — "
                       "say why. A blocked answer writes nothing and is reported, not retried "
                       "forever. When blocked is set, every other field must be null.",
    }


def combination_schema(tuning: ComboTuning, *,
                       supplied_families: "tuple[str, ...]",
                       host_roles: "tuple[str, ...]",
                       granted_families: "tuple[str, ...]") -> "dict[str, Any]":
    """The `combination` output schema.

    `ingredients` is fixed at exactly `tuning.ingredient_count` items — D20 as amended (§2f.2) — so
    a three-ingredient answer is not a lint finding, it is an invalid response the local schema
    check rejects before anything is written.

    `hostRole` is closed to the roles whose socket ceiling actually reaches the ingredient count.
    The model is therefore never offered a chassis that could not hold the combination it is
    authoring, which is the same "cap inside the schema" discipline module 13 applied to the twelve
    roles: a constraint enforced at LOAD is a re-run, a constraint enforced in the schema is free.
    """
    if not supplied_families:
        raise ValueError("no supplied ingredient families — run the gem-supply precheck first")
    if not host_roles:
        raise ValueError(
            "no role's socket ceiling reaches the ingredient count, so no combination could ever "
            "fire; refusing to build a schema for content nothing can host")
    # required + nullable: same 2026-09-08 / 2026-09-09 live-model fix as setgen/affixfamgen —
    # `"required": []` lets constrained decoding omit name/flavor forever through heal.
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["name", "flavor", "blocked", "ingredients", "grants", "hostRole", "hostFrame"],
        "properties": {
            **_identity_fields(),
            "blocked": _blocked(),
            "ingredients": {
                "type": ["array", "null"],
                "minItems": tuning.ingredient_count,
                "maxItems": tuning.ingredient_count,
                "items": {
                    "type": "string",
                    "enum": list(supplied_families),
                    "description": "an ingredient gem family. Repeats are legal — a recipe is an "
                                   "unordered multiset, so four of the same family is a real "
                                   "answer, not a mistake.",
                },
            },
            "grants": {
                "type": ["array", "null"],
                "minItems": 1,
                "maxItems": 2,
                "items": {
                    "type": "string",
                    "enum": list(granted_families),
                    "description": "the atom family this combination grants. Prefer a MECHANISM — "
                                   "a proc, a rider, a spawn — over a bigger number on a stat the "
                                   "ingredients already carry.",
                },
            },
            "hostRole": {
                "type": ["string", "null"],
                "enum": list(host_roles) + [None],
                "description": "null for any role; naming one pins the combination to that chassis",
            },
            "hostFrame": {
                "type": ["string", "null"],
                "enum": list(HOST_FRAMES) + [None],
                "description": "null for any frame",
            },
        },
    }


def schema_field_names(schema: "dict[str, Any]") -> "tuple[str, ...]":
    """Every property name in the schema, for a test that wants to assert an ABSENCE by name."""
    return tuple(sorted(schema.get("properties", {})))
