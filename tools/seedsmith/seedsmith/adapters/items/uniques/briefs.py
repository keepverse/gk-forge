"""The uniques briefs (D4.29, spec-unique-pipeline.md §1) -- the boundary. Turns one planner
`Cell` into a per-call JSON Schema (PLANNED fields pinned `const`, VALIDATED fields a closed real
enum, AUTHORED fields free text) and the prompt text asking the model to fill in identity. Every
number the anchor will ever carry is resolved later in C# (`UniqueContainerBuild.From`) -- nothing
here is a magnitude, a weight or a probability (Law 2).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence

from ....briefkit.avoid_list import render_avoid_line
from .. import registries as _reg
from .planner import Cell

REPO_ROOT = Path(__file__).resolve().parents[6]
BASE_TYPES_DIR = REPO_ROOT / "data" / "seed" / "items" / "base-types"

#: `unique.counterPressure.kind` -- restricted to `narrow` only (core.v1.json:504-519's three
#: kinds are `narrow`/`drawback`/`conditional`, but `drawback` needs a `severityBand` + a
#: channel/family reference and `conditional` needs a named `condition`; every sampled real
#: anchor in the 144-corpus this session read used `narrow`). Named, not silently narrowed: a
#: `drawback`/`conditional` anchor is a real future enrichment, not required by this task's own
#: acceptance line, and picking a made-up severity/condition id here would be worse than not
#: shipping one.
COUNTER_PRESSURE_KIND: "tuple[str, ...]" = ("narrow",)

#: `unique.varianceSlot.variance` -- spec §1's own vocabulary (`narrow · normal · wide`).
VARIANCE: "tuple[str, ...]" = ("narrow", "normal", "wide")

#: How many `fixedAtoms[]` a first-ship anchor carries. `maxIdentityAtoms` (`uniques.v1.json`)
#: allows 1-3; every sampled real anchor in the 144-corpus carries exactly 2, so the new 30 match
#: the existing texture rather than exploring the tunable's own ceiling in the same batch.
FIXED_ATOM_COUNT = 2

#: `ssot-uniques.md §3.7`, enforced today by the ALREADY-SHIPPED
#: `gk-forge/tools/ItemSeedValidator/Checks/UniqueRuleCheck.cs`: at most 8 of the 15 roles per frame may
#: ever carry a unique, and this exact list is the owner's own 2026-08-23 decision (the four
#: heaviest + four lightest eligible roles, `jewel-minor` excluded separately). A `baseType` drawn
#: from any OTHER role fails real import with `UniqueRoleQuota` -- confirmed by reading the real
#: checker's own source before generating a single anchor, not assumed from the spec's prose alone
#: (the spec this task implements never names this constraint at all).
ALLOWED_ROLES: "tuple[str, ...]" = (
    "armament-primary", "core-guard", "ward-array", "jewel-major",
    "sense", "footing", "infusion", "retinue",
)


def role_for_cell(cell: Cell) -> str:
    """Which of the 8 allowed roles this cell's anchor is built on. `UniqueRuleCheck.cs`'s own
    `UniqueAxisCollision` keys on `(band, role, axis)` -- NOT frame -- so a plant cell and a
    humanoid cell shipping the SAME axis at the SAME band must pick DIFFERENT roles from each
    other or they collide with one another, not just with the existing 144-corpus. Offsetting the
    humanoid role by 4 (of 8) guarantees a plant/humanoid mismatch at every axis while every axis's
    OWN pair of roles reuses across axes freely (axis is part of the key, so a role repeating at a
    different axis is never a collision). Confirmed empirically 2026-09-06 against the real
    144-corpus: bands 80 and 100 hold ZERO existing entries on any of these 8 roles at any axis, so
    this assignment collides with nothing already shipped; band 90 is the opposite -- ALL 8 roles
    are already taken at EVERY axis, which is why this batch does not attempt band 90 at all (see
    the batch script's own skip, named in D4.29's evidence rather than forced through)."""
    from .planner import AXES
    i = AXES.index(cell.axis)
    return ALLOWED_ROLES[i] if cell.frame == "plant" else ALLOWED_ROLES[(i + 4) % 8]


def load_base_types_by_frame_and_role() -> "dict[tuple[str, str], frozenset[str]]":
    """`unique.baseType`'s real VALIDATED vocabulary, keyed by (frame, role) -- read fresh from
    `gk-data/packs/fusion/data/seed/items/base-types/**/*.json` (62 files), restricted to `ALLOWED_ROLES` (every OTHER
    role is a real `UniqueRoleQuota` refusal at import, `UniqueRuleCheck.cs`) -- measured
    2026-09-06: 24 real base types exist for every one of the 8 allowed roles, in both frames,
    uniformly."""
    by_key: "dict[tuple[str, str], set[str]]" = {}
    for path in sorted(BASE_TYPES_DIR.rglob("*.json")):
        doc = json.loads(path.read_text(encoding="utf-8"))
        for entry in doc.get("entries") or ():
            frame, role, entry_id = entry.get("frame"), entry.get("role"), entry.get("id")
            if isinstance(frame, str) and isinstance(role, str) and isinstance(entry_id, str) and role in ALLOWED_ROLES:
                by_key.setdefault((frame, role), set()).add(entry_id)
    return {key: frozenset(ids) for key, ids in by_key.items()}


def acquisition_for_band(band: str) -> str:
    """ssot-uniques.md §4.5: "ordinal >= 90 is never plain drop." `firstseed` (80) is the only
    band `drop` is legal at; `sunwoven`/`almanac` (90/100) get `deterministic` instead of
    `source-locked` because `source-locked` requires a REAL domain table to bind to
    (`dungeonBinding`, both fields refused `none`) and `gk-data/packs/fusion/data/seed/dungeon/domains/` is empty --
    `deterministic` needs no table reference at all (it is claimed later by a domain anchor's
    `firstClearRef`, D4.28), so it is the only >= 90 acquisition this batch can ship without
    minting a dangling reference to content that does not exist yet."""
    if band not in ("firstseed", "sunwoven", "almanac"):
        raise ValueError(f"unknown band {band!r}")
    return "drop" if band == "firstseed" else "deterministic"


#: One line per field the model actually sees, each with a negative clause (AI-native contract:
#: "every description needs a negative clause saying what the field is not") -- the dungeon
#: adapter's own `descriptions.py` precedent, kept local here rather than a fifth file since this
#: package briefs exactly one kind.
DESCRIPTIONS: "dict[str, str]" = {
    "id": "The minted tracking id for this anchor. NOT authored -- fixed by the planner before this call.",
    "nameKey": "The minted i18n key for this anchor's name. NOT authored -- fixed by the planner.",
    "iconKey": "The minted i18n key for this anchor's icon. NOT authored -- fixed by the planner.",
    "flavorKey": "The minted i18n key for this anchor's flavor text. NOT authored -- fixed by the planner.",
    "frame": "Which body this unique is built for. NOT a stat -- fixed by the planner's own grid cell.",
    "powerAxis": "Which of the five power vectors this unique leans into. NOT a strength value, only a category, and fixed by the planner's own grid cell.",
    "rarity": "The rung this unique ships at. NOT a strength claim -- on a unique the rung buys only the drop gate, fixed by the planner's own grid cell.",
    "acquisition": "How a player comes to hold this unique. NOT a weight or a chance -- fixed by the planner from the rung.",
    "name": "A short, evocative item name. NOT a description of its mechanics and NOT a number anywhere in the text.",
    "flavor": "One to two sentences of in-world flavor text. NOT a mechanics summary and NOT a number.",
    "baseType": "Which real base type this unique is built on. NOT a role noun -- must be one of the ids listed, never invented.",
    "fixedAtoms": "One to three fixed effect atoms this unique always carries, each a real atom family plus a power band. NOT a magnitude -- power band is a named tier, never a number.",
    "varianceSlot": "The one optional rolled effect slot this unique carries, or omitted entirely. NOT a second fixed core -- at most one slot, and it may be absent.",
    "counterPressure": "The one weakness this unique's design leans on. NOT flavor text -- `kind` must be one of the listed real values.",
    "massClass": "How much physical mass or bulk this item reads as carrying. NOT a second free-text tag list -- exactly one value, never two.",
    "materialNature": "What this item is physically made of. NOT a second free-text tag list -- exactly one value, never two.",
    "combatPosture": "This item's primary tactical intent. NOT a second free-text tag list -- exactly one value, never two.",
    "origin": "This item's biological or thematic origin, or 'none' if it has none. NOT required to have a real value -- 'none' is itself a legal answer.",
    "durabilityClass": "How this item wears compared to its class and rarity, or 'none' if unremarkable. NOT required to have a real value -- 'none' is itself a legal answer.",
}


def _enum(field: str, values: "tuple[str, ...] | frozenset[str]") -> dict:
    return {"type": "string", "enum": sorted(values), "description": DESCRIPTIONS[field]}


def _planned_const(field: str, value: Any) -> dict:
    return {"type": "string", "const": value, "description": DESCRIPTIONS[field]}


def build_unique_schema(
    cell: Cell,
    planned_ids: "dict[str, str]",
    *,
    role: "str | None" = None,
    base_types_by_frame_and_role: "dict[tuple[str, str], frozenset[str]] | None" = None,
    atom_families: "frozenset[str] | None" = None,
    atom_family_frames: "dict[str, frozenset[str]] | None" = None,
    tag_axes: "dict[str, tuple[str, ...]] | None" = None,
) -> dict:
    """One call's schema for `cell` -- `planned_ids` supplies the four PLANNED-minted string
    values (`id`, `nameKey`, `iconKey`, `flavorKey`) from the planner's `IdMinter`. Every closed
    vocabulary defaults to a fresh registry read when the caller does not supply one (tests supply
    a small fixture instead, so a schema test never depends on the live corpus's exact size).

    `role` overrides `role_for_cell(cell)`'s own default grid assignment -- needed because that
    default assumes a fresh, unoccupied (role, axis) space, and a REAL run measured 2026-09-06 that
    no such space exists for rung 80/100 at all: `naming.v1.json idNamespaces.uniques.bandAssignment`
    has rows only for ordinals 30/50/70/90, so a freshly-invented id prefix fails `IdOutsideNamespace`
    on every entry, and ordinal 90 (the nearest real row) is separately saturated on every (role,
    axis) pair. Shipping under a REAL registered ordinal (70, whose own real content already mixes
    heirloom(70) and firstseed(80) rarities under one prefix -- confirmed from the real corpus, not
    assumed) means the role per (frame, axis) must be picked from THAT ordinal's own actual free
    slots, not the grid's default rotation -- hence the override.
    `baseType`'s own candidates are restricted to `role_for_cell(cell)`'s own role, never the
    cell's whole frame, because `UniqueRuleCheck.cs`'s real 8-role-per-frame quota makes every
    other role an automatic `UniqueRoleQuota` refusal at import.

    **Tags are five SEPARATE single-valued fields here, never one flat array.** A real batch run
    (2026-09-06, `google/gemma-4-26b-a4b-qat`) measured a 15% (3/20) resolve rate against a flat
    `tags: string[]` field with a "one per exclusive axis" rule stated only in prose -- the
    overwhelming majority of failures were the model omitting a mass-class tag entirely or
    picking two from the same axis, which JSON Schema's `enum` cannot forbid inside one array
    (each individual string is legal; the CROSS-CUTTING one-per-axis rule is not expressible as a
    per-item constraint). Splitting the exclusive axes into their own fields makes the violation
    structurally unreachable: each field takes exactly one value from its own closed enum under
    constrained decoding, and `assemble_tags` (this module) combines them into the real `tags[]`
    array afterward -- code does the assembly, the model only ever answers one-of-N questions.

    **`fixedAtoms`/`varianceSlot` offer only families legal for `cell.frame`.** `atom_families`
    (from `load_atom_families()`) is the CATALOG question -- "does this family exist at all" --
    with no frame information; `gk-data/packs/fusion/data/seed/items/affix-families/*.json`'s own `frames` list (read
    by `load_atom_family_frames()`) is the SEPARATE, real constraint `UniqueFrameCheck.cs` enforces
    after the fact (ssot-uniques.md §3.5: a family whose channel is zombie-only/plant-only on the
    other frame is "dead, not daring"). Previously the model chose from the WHOLE catalog
    regardless of frame -- found live as 4 shipped uniques carrying a family the corpus restricts
    to the other frame (item-seed-regen cause 8, 2026-09-20). A family absent from
    `atom_family_frames` (no `frames` list at all) is offered on every frame, matching the C#
    check's own "no frames list -> skipped" rule."""
    role = role if role is not None else role_for_cell(cell)
    base_types_by_frame_and_role = (base_types_by_frame_and_role if base_types_by_frame_and_role is not None
                                    else load_base_types_by_frame_and_role())
    atom_families = atom_families if atom_families is not None else _reg.load_atom_families()
    atom_family_frames = (atom_family_frames if atom_family_frames is not None
                          else _reg.load_atom_family_frames())
    atom_families_for_frame = frozenset(
        f for f in atom_families
        if f not in atom_family_frames or cell.frame in atom_family_frames[f])
    tag_axes = tag_axes if tag_axes is not None else _reg.load_tag_axes(applies_to="unique")
    mass_class = tag_axes.get("mass-class", ())
    material_nature = tag_axes.get("material-nature", ())
    combat_posture = tag_axes.get("combat-posture", ())
    origin = tag_axes.get("origin", ())
    durability_class = tag_axes.get("durability-class", ())

    atom_item = {
        "type": "object",
        "properties": {
            "family": _enum("fixedAtoms", atom_families_for_frame),
            "powerBand": {"type": "string", "enum": ["low", "medium", "high"],
                         "description": "How strong this fixed atom's identity value is, as a named tier. NOT a number."},
        },
        "required": ["family", "powerBand"], "additionalProperties": False,
    }
    variance_slot = {
        "type": "object",
        "properties": {
            "family": _enum("varianceSlot", atom_families_for_frame),
            "variance": _enum("varianceSlot", VARIANCE),
        },
        "required": ["family", "variance"], "additionalProperties": False,
    }
    counter_pressure = {
        "type": "object",
        "properties": {
            "kind": _enum("counterPressure", COUNTER_PRESSURE_KIND),
            "note": {"type": "string", "description": "A sentence naming the weakness in-world. NOT a number, NOT a stat name."},
        },
        "required": ["kind", "note"], "additionalProperties": False,
    }

    properties: "dict[str, Any]" = {
        "id": _planned_const("id", planned_ids["id"]),
        "nameKey": _planned_const("nameKey", planned_ids["nameKey"]),
        "iconKey": _planned_const("iconKey", planned_ids["iconKey"]),
        "flavorKey": _planned_const("flavorKey", planned_ids["flavorKey"]),
        "frame": _planned_const("frame", cell.frame),
        "powerAxis": _planned_const("powerAxis", cell.axis),
        "rarity": _planned_const("rarity", cell.band),
        "acquisition": _planned_const("acquisition", acquisition_for_band(cell.band)),
        "name": {"type": "string", "description": DESCRIPTIONS["name"]},
        "flavor": {"type": "string", "description": DESCRIPTIONS["flavor"]},
        "baseType": _enum("baseType", base_types_by_frame_and_role.get((cell.frame, role), frozenset())),
        "fixedAtoms": {"type": "array", "items": atom_item, "minItems": 1, "maxItems": 3,
                       "uniqueItems": True, "description": DESCRIPTIONS["fixedAtoms"]},
        "varianceSlot": variance_slot,
        "counterPressure": counter_pressure,
        "massClass": _enum("massClass", mass_class),
        "materialNature": _enum("materialNature", material_nature),
        "combatPosture": _enum("combatPosture", combat_posture),
        "origin": _enum("origin", tuple(origin) + ("none",)),
        "durabilityClass": _enum("durabilityClass", tuple(durability_class) + ("none",)),
    }
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Unique",
        "type": "object",
        "properties": properties,
        "required": ["id", "nameKey", "iconKey", "flavorKey", "frame", "powerAxis", "rarity",
                     "acquisition", "name", "flavor", "baseType", "fixedAtoms", "counterPressure",
                     "massClass", "materialNature", "combatPosture", "origin", "durabilityClass"],
        "additionalProperties": False,
    }


def assemble_tags(entry: "dict[str, Any]") -> "list[str]":
    """The real `unique.tags[]` array, assembled from the five separately-authored single-value
    fields `build_unique_schema` requests -- never authored as a flat list (see that function's
    own docstring for why). `notability=signature` is never asked of the model at all: every
    sampled real anchor in the 144-corpus already carries it, so this batch decides it in code
    (one less field the model could get wrong) rather than spending a schema slot re-deriving a
    near-constant. Pops the five intermediate fields off `entry` so the FINAL shipped JSON matches
    the real corpus's own `tags[]`-only shape -- `entry` is mutated and returned for convenience."""
    tags = [entry.pop("massClass"), entry.pop("materialNature"), entry.pop("combatPosture")]
    origin = entry.pop("origin")
    if origin != "none":
        tags.append(origin)
    durability = entry.pop("durabilityClass")
    if durability != "none":
        tags.append(durability)
    tags.append("signature")
    entry["tags"] = tags
    return tags


#: naming.v1.json's own three legal AUTHOR patterns for a `name` field (its own "why3": a 4th,
#: "combined" shape is deliberately withheld from authors because the ENGINE assembles that exact
#: shape for rolled magic-item names, and an author typing it by hand would collide un-detectably
#: with an engine-generated name of the same shape). Confirmed live 2026-09-06: a real generated
#: name, "Thorned Scepter of the Verdant Maw", is EXACTLY this forbidden 4th shape
#: (`<Adjective> <Base> of <Concept>` -- patterns 1+2 concatenated) and failed real import with
#: `GeneratedOnlyNamePattern`. A second real failure the same run, "Echo of the Deep Roots",
#: violated the separate `pluralsPossessivesConnectives` rule (no plural noun in a `name` field).
#:
#: 2026-09-26 (ip-censor T15): the opening sentence used to name a competitor franchise as its
#: style reference. The program's own ruling forbids that ("prompts never cite franchises",
#: `ip-censor-map.md:149`; `spec-avoid-list.md:34-35`, whose Boundaries list "cite another
#: franchise in a brief" under **Never**), and style is meant to arrive through this adapter's own
#: exemplars and anchor lines instead. The replacement states the item's SHAPE, which is the part
#: of the old sentence that was doing real work (it told the model what kind of artifact it was
#: authoring) and is strictly more informative about the artifact than a genre label was: a unique
#: is a named one-off, hand-placed at a fixed slot, built on a real base type, carrying its own
#: fixed effects. Nothing below this sentence was touched -- the eight PLANNED const fields, the
#: closed `baseType` list, the real atom-family list, the three one-of-N tag axes, the three legal
#: name shapes and the engine-reserved fourth shape all read exactly as they did.
#: `tests/test_unique_briefs.py::SystemPromptHygieneTests` pins both halves: no citation, and every
#: load-bearing clause still present.
SYSTEM_PROMPT = (
    "You author identity for a single hand-placed unique item — a named one-off built on a real "
    "base type, carrying its own fixed effects — in a JSON object matching the given "
    "schema. Every PLANNED field (id, nameKey, iconKey, flavorKey, frame, powerAxis, rarity, "
    "acquisition) is already fixed -- copy its const value verbatim, never change it. Choose a "
    "real baseType from the closed list that fits the power axis and frame. Choose fixedAtoms "
    "and, optionally, a varianceSlot ONLY from the real atom-family list given -- never invent a "
    "family. massClass, materialNature and combatPosture each take EXACTLY ONE value from their "
    "own list -- pick the single best fit, never think of these as a combined tag list. origin "
    "and durabilityClass are 'none' unless a real value clearly fits. "
    "The name field must use EXACTLY ONE of these three shapes, never a mix: "
    "(1) compound: two words, '<Adjective> <Base>' (e.g. 'Heartbloom Crown'); "
    "(2) of-construct: '<Base> of [the] <Concept>', where 'of' is the ONLY allowed connective and "
    "<Concept> is one or two words (e.g. 'Fang of the Hollow Crown'); "
    "(3) fusion: exactly two words joined with no space (e.g. 'Ashfang'). "
    "NEVER combine an adjective with an 'of' phrase in the same name (e.g. never 'Thorned Scepter "
    "of the Verdant Maw') -- that four-part shape is reserved for the game engine's own generated "
    "names and is not legal for an authored name. NEVER use a plural noun, a possessive ('s), or "
    "any connective other than 'of'/'the' in a name. Write one to two sentences of flavor text, "
    "and one sentence of counterPressure.note describing the item's built-in weakness. Never "
    "write a number anywhere in name, flavor, or counterPressure.note."
)


def build_brief(cell: Cell, schema: dict, *, role: "str | None" = None,
                avoid_terms: "Sequence[str]" = ()) -> str:
    """The user-turn text -- the schema itself carries every closed vocabulary already (LM
    Studio's constrained decoding makes an out-of-enum value unsampleable, spec-pipeline.md's own
    "prove constrained decoding is on" rule), so the brief states only what a schema cannot: the
    axis's own flavor connotation, kept short because AUTHORED free text is the only thing the
    model is actually deciding here. `role` mirrors `build_unique_schema`'s own override -- must
    match whatever role that schema's `baseType` enum was actually restricted to, or the brief
    would name a role the model's own closed choices cannot legally build against.

    `avoid_terms` (ip-censor T15/IC-3) is the shared `briefkit.avoid_list` reading of the committed
    registry, passed in by the caller exactly as `nodegen.brief.render_brief` takes it -- this
    module decides nothing about what is forbidden. It renders as its OWN line, after the
    axis/role block, so it is never read as part of the per-cell instruction. Keyword-only with an
    empty default: a caller that passes nothing renders the pre-T15 text byte for byte, and no
    positional caller exists (every call site names `role=` as a keyword).
    """
    role = role if role is not None else role_for_cell(cell)
    ip_avoid_line = render_avoid_line(avoid_terms)
    ip_avoid_block = f"\n{ip_avoid_line}" if ip_avoid_line else ""
    return (
        f"Author one unique item.\n"
        f"Frame: {cell.frame}\n"
        f"Equipment role: {role} (choose baseType from the given list for this role)\n"
        f"Power axis: {cell.axis} (this item's build should read as leaning into {cell.axis})\n"
        f"Rarity band: {cell.band}{ip_avoid_block}\n"
        f"Return ONLY the JSON object."
    )
