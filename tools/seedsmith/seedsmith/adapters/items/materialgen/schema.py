"""seedsmith.adapters.items.materialgen.schema — the closed-enum answer schema.

⛔ P1, same as `setgen.schema`: **the model writes identity, deterministic code writes the
mechanical, id-shaped fields.** The model picks `name`, `flavor`, and (optionally) `tags`. It never
picks `nameKey` or `iconKey` — those follow one fixed, mechanical pattern across all 21 shipped
entries (`material.{runtimeId with dots replaced by dashes}`, `icon.` + that), and asking the model
to also choose them is exactly the trap `setgen.schema`'s own `apCost` precedent names: "a model
asked for both would eventually disagree with itself." `emit.py` derives them instead.

`tags` is closed to the tag axes `tags.v1.json` actually lists `material` under (`mass-class`,
`material-nature`, `durability-class`, `origin`) — read fresh via
`adapters.items.registries.load_tag_axes`, never hand-duplicated, so a future registry edit (the
axis list has already widened once, per that file's own v3/v4 notes) is picked up automatically
rather than silently going stale here.
"""
from __future__ import annotations

from typing import Any

from ..registries import load_tag_axes

#: The entry shapes `tags.v1.json`'s own `appliesTo` marks each axis legal for. `material` is one
#: of them for four axes today (mass-class, material-nature, durability-class, origin) — see that
#: registry's own `v4Note`, which widened these four specifically because "a MATERIAL is the most
#: natural thing in the corpus to carry material-nature, mass-class and durability-class."
APPLIES_TO = "material"


def material_tag_axes() -> "dict[str, tuple[str, ...]]":
    """Axis id -> legal tag ids, for axes `material` may carry a tag from. Read fresh every call —
    registry facts are read, never transcribed (this program's own standing verification rule)."""
    return load_tag_axes(applies_to=APPLIES_TO)


def material_tags() -> "tuple[str, ...]":
    """The flat pool `tags` may draw from — every id from every axis `material_tag_axes` returns,
    in axis order, de-duplicated (an id belongs to exactly one axis in `tags.v1.json`, so dedup is
    defensive, not load-bearing)."""
    seen: "list[str]" = []
    for ids in material_tag_axes().values():
        for tag_id in ids:
            if tag_id not in seen:
                seen.append(tag_id)
    return tuple(seen)


def tag_axis_violations(tags: "list[str] | tuple[str, ...]",
                        axes: "dict[str, tuple[str, ...]] | None" = None) -> "list[str]":
    """Every axis marked `exclusive: true` in `tags.v1.json` from which `tags` draws MORE than one
    value. All four material-legal axes are exclusive today (checked directly against the registry,
    not assumed), so this is real enforcement, not a hypothetical branch — an answer with both
    `light` and `heavy` (both `mass-class`) is refused here rather than silently keeping the first."""
    by_axis = axes if axes is not None else material_tag_axes()
    membership: "dict[str, str]" = {}
    for axis, ids in by_axis.items():
        for tag_id in ids:
            membership[tag_id] = axis
    seen_axis: "dict[str, str]" = {}
    violations: "list[str]" = []
    for tag in tags:
        axis = membership.get(tag)
        if axis is None:
            continue  # not a material-legal tag at all — the schema enum already refuses this
        if axis in seen_axis and seen_axis[axis] != tag:
            violations.append(
                f"tags {seen_axis[axis]!r} and {tag!r} are both on the {axis!r} axis, which "
                f"tags.v1.json marks exclusive — an entry may carry at most one")
        seen_axis[axis] = tag
    return violations


def _blocked() -> "dict[str, Any]":
    return {
        "type": "string",
        "description": "Set this INSTEAD of the content fields if the brief cannot be satisfied — "
                       "say why. A blocked answer writes nothing and is reported, not retried "
                       "forever.",
    }


def material_schema(*, tag_pool: "tuple[str, ...] | None" = None) -> "dict[str, Any]":
    """The `material` answer schema. Closed by construction: `additionalProperties: False` and every
    string field that has a legal vocabulary is an `enum`, so `audit_schema`'s own discipline (a
    numeric field cannot reach a model call, and neither can a free-text field with a real closed
    vocabulary) applies to `tags` the same way it applies to `pieces`/`charmClass` in `setgen`."""
    pool = list(tag_pool if tag_pool is not None else material_tags())
    return {
        "type": "object",
        "additionalProperties": False,
        "required": [],
        "properties": {
            "name": {"type": "string", "minLength": 3, "maxLength": 48},
            "flavor": {"type": "string", "minLength": 8, "maxLength": 240},
            "tags": {
                "type": "array",
                "minItems": 0,
                "maxItems": 4,
                "items": {"type": "string", "enum": pool},
            },
            "blocked": _blocked(),
        },
    }
