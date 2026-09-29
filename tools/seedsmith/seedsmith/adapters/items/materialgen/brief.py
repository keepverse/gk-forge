"""seedsmith.adapters.items.materialgen.brief — one material id -> a brief.

Motifs inline, no citation text, same discipline `setgen.brief` states directly: a brief carries the
closed vocabulary the model must choose from and the id's own mechanical facts, and nothing else.
The model is never shown a material id outside `vocab.ISSUABLE` — `build_material_brief` requires a
`vocab.MaterialId`, which only `vocab.require_issuable` ever hands out, so an unauthorized id cannot
reach this function at all, the same way `setgen.brief` never shows the model a role outside the
twelve.
"""
from __future__ import annotations

from .schema import material_tag_axes
from . import vocab
from .vocab import MaterialId, SUBSTRATE_GRADES

PROMPT_VERSION = "material-gen/1"

_CLASS_SENTENCE = {
    "shard": (
        "It is a rarity-ceiling SHARD: a flat spend with no element and no frame, spent to raise "
        "how good an item's roll may be. It is not itself a flavour or a substance."
    ),
    "essence": (
        "It is an ELEMENT ESSENCE: pure elemental flavour, no magnitude, no frame. It says what "
        "direction an effect leans, never how strong."
    ),
    "catalyst": (
        "It is a CATALYST: what a crafter is DOING to an item (make / improve / re-randomise), "
        "never a material substance in its own right."
    ),
    "assurance": (
        "It is an ASSURANCE: a consumable spent to accept LESS variance on a craft attempt, never "
        "a material substance, an element, or an action performed ON the item. Its own id names "
        "which risk it covers (assure raises success odds, protect wards craft wear, repair wards "
        "repair coverage) — the name and flavor should read as insurance against chance, not as a "
        "component the crafted item ends up carrying."
    ),
}


def _identity_sentence(material: MaterialId) -> str:
    if material.material_class == "substrate":
        grade_ordinal = SUBSTRATE_GRADES.index(material.runtime_id.rsplit(".", 1)[-1]) + 1
        return (
            f"It is a SUBSTRATE: the {material.frame} frame, grade {grade_ordinal} of "
            f"{len(SUBSTRATE_GRADES)} ({SUBSTRATE_GRADES[grade_ordinal - 1]}). It says what an item "
            f"of that frame is physically made of at that grade — heavier/sturdier grades are later "
            f"in the ladder, and the name and flavor should read as a step up from the grade below "
            f"it, not a repeat of it."
        )
    if material.material_class == "trophy":
        # T33's own doc-comment question ("What did this come from?") IS the brief: a trophy never
        # carries a magnitude, an element, or a frame — only provenance.
        subject = "species" if material.scope == "species" else "family"
        return (
            f"It is a TROPHY: proof of provenance, nothing else. This one is a {subject.upper()} "
            f"trophy, tied specifically to the {subject} `{material.scope_key}` (slot "
            f"{material.slot} of that {subject}'s own trophies). It says WHERE an item's material "
            f"came from — it is never a substance, an element, or an action, and it carries no "
            f"magnitude of any kind."
        )
    return _CLASS_SENTENCE[material.material_class]


def _sibling_count(material: MaterialId) -> int:
    """How many other ids share this material's class — the population the authored name has to be
    distinct from. Read from `vocab.ISSUABLE` rather than hardcoded, because the trophy count is a
    population that grows whenever the trophy planner mints a row (`validation-ssot.md`: a derived
    population's size is a reading, never a pinned constant)."""
    return sum(1 for m in vocab.ISSUABLE if m.material_class == material.material_class) - 1


def build_material_brief(material: MaterialId) -> str:
    """One material id, one brief. `material` MUST come from `vocab.require_issuable` — this
    function does not itself check the vocabulary, so a caller that hands it a fabricated
    `MaterialId` has already bypassed the one gate this whole package exists to enforce."""
    axes = material_tag_axes()
    total_tags = sum(len(ids) for ids in axes.values())
    element_line = f"\nIts element is {material.element}." if material.element else ""
    siblings = _sibling_count(material)
    # One clause, parameterised by class, rather than a per-branch edit. Measured: a full `items fill`
    # run produced 747 `SemanticDedup/NearDuplicate` findings, every one a name used verbatim by 2 to 35
    # entries, and the substrate branch of `_identity_sentence` ALREADY carried the anti-repetition
    # clause its own eight members needed. So the gap was never "trophy forgot" — it was that the rule
    # lived in one branch, and `shard` (10 rungs) and `trophy` (3,602 ids, one per species slot) had no
    # copy of it. A rule that lives in one place can be narrowed back to one place; this one cannot.
    distinct_line = (
        f"\nThis id has {siblings} sibling(s) of its class in the corpus"
        f"{' — and for a trophy that is one per species slot, so thousands of them share a few hundred species' if material.material_class == 'trophy' else ''}."
        f"\nThe `name` must therefore be DISTINCT: it must not repeat, and must not be a near-variant of,"
        f" a name any other {material.material_class} already uses. The model cannot see those names, so"
        f" this is on you: pick something specific to THIS id rather than the obvious construction for its"
        f" subject.\n")
    return f"""Author DISPLAY content for the material `{material.runtime_id}`.

{_identity_sentence(material)}{element_line}{distinct_line}
Choose, and nothing else:
1. `name` — a short, evocative item name (not a restatement of the runtime id).
2. `flavor` — one to two sentences of flavor text. No numbers, no game-mechanical claims (no
   percentages, no stat names) — this is DISPLAY text, not a tooltip. The mechanics are already
   fixed by the id itself and are never yours to describe or invent.
3. `tags` — zero to four tags from the closed list below. At most one tag per axis shown
   (mass-class / material-nature / durability-class / origin) — the list is already grouped by axis
   so a legal combination is visible at a glance.

Never invent a tag outside this list, and never choose a number, a tier, or a magnitude of any
kind. Those are not yours to set.

Closed tag pool ({total_tags} ids, grouped by axis — at most one per axis):
{chr(10).join(f'  {axis}: ' + ', '.join(ids) for axis, ids in axes.items())}

If this id cannot carry content you would be happy to ship, set `blocked` and say why."""
