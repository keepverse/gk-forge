"""seedsmith.adapters.items.basetypegen.schema — the closed-enum answer schema.

⛔ Same discipline every sibling module states: identity only, every magnitude resolved
afterwards. `pipeline.model.audit_schema` (run by `brief.BaseTypeBrief.__post_init__`) is the
mechanical proof this file cannot regress into offering a bare number — matching
`setgen/schema.py`'s and `affixfamgen/schema.py`'s own opening lines almost verbatim, because this
is the third generator built against the same harness and the shape is the point.

`class`, `implicitFamily` and `tags` are all plain string/array-of-string enums built from THIS
partition's own closed vocabulary (`tuning.load_class_choices` / `load_legal_implicit_families` /
`load_tag_vocab`) — never the deny-listed magnitude names (`tier`, `cost`, ...), and never a
pattern that would admit a bare digit string.
"""
from __future__ import annotations

from typing import Any

NAME_MIN_LEN = 3
NAME_MAX_LEN = 48
FLAVOR_MIN_LEN = 8
FLAVOR_MAX_LEN = 400


def _identity_fields() -> "dict[str, Any]":
    return {
        "name": {"type": "string", "minLength": NAME_MIN_LEN, "maxLength": NAME_MAX_LEN,
                 "description": "the item's display name, e.g. 'Honed Hatchet'. nameKey/iconKey/"
                                "flavorKey are derived from this afterwards — never authored."},
        "flavor": {"type": "string", "minLength": FLAVOR_MIN_LEN, "maxLength": FLAVOR_MAX_LEN,
                   "description": "one or two sentences of flavor text. Never a number, a tier, "
                                  "or a socket count — those are resolved after you answer."},
    }


def _blocked() -> "dict[str, Any]":
    return {
        "type": "string",
        "description": "Set this INSTEAD of the content fields if the brief cannot be satisfied — "
                       "say why. A blocked answer writes nothing and is reported, not retried "
                       "forever.",
    }


def base_type_schema(*, class_choices: "tuple[str, ...]", implicit_families: "tuple[str, ...]",
                     tags: "tuple[str, ...]") -> "dict[str, Any]":
    """The `base-type` answer schema for ONE `(role, frame, band)` partition. `class_choices` and
    `implicit_families` are that partition's own closed vocabularies (see `tuning.py`); `tags` is
    the whole registry vocabulary, shared across every partition."""
    if not class_choices:
        raise ValueError("base_type_schema requires at least one legal class choice")
    if not implicit_families:
        raise ValueError("base_type_schema requires at least one legal implicit family")
    if not tags:
        raise ValueError("base_type_schema requires at least one legal tag")

    return {
        "type": "object",
        "additionalProperties": False,
        "required": [],
        "properties": {
            **_identity_fields(),
            "blocked": _blocked(),
            "class": {"type": "string", "enum": list(class_choices),
                      "description": "one class-ladder rung legal for this role+frame"},
            "implicitFamily": {"type": "string", "enum": list(implicit_families),
                               "description": "one affix family from this role's own closed "
                                              "implicit slate (classes.v2.json)"},
            "tags": {
                "type": "array",
                "minItems": 1,
                "maxItems": len(tags),
                "items": {"type": "string", "enum": list(tags)},
            },
        },
    }


def schema_field_names(schema: "dict[str, Any]") -> "tuple[str, ...]":
    """Every property name in the schema — for a test asserting `socketMax`/`enhanceTrack`/`id`/
    `nameKey`/`band` are ABSENT (P1: the model never authors them)."""
    return tuple(sorted(schema.get("properties", {})))
