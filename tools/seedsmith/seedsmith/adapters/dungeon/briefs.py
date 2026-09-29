"""D1.10's real remaining scope, quest half (2026-09-07): per-cell schema and brief construction
for `dungeon-quest` -- the SAME "generic schema for audit, cell-parameterized schema for real
generation" split `adapters/items/uniques/briefs.py` already established for uniques (`schema.py`'s
own `build_quest_schema()` is the documentation/audit view; this module builds the REAL, per-cell
version a live call actually uses).

Grows to cover the other four AUTHORED-field kinds (event, encounter, room, domain) as each one's
own real generation pass is built -- one file per this whole adapter, not one per kind, matching
this repo's own file list for D1.10 (`adapters/dungeon/pipelines.py`, singular).
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from . import registries as _reg
from .planner import Cell
from .schema import ELEMENTS, ENTRANCE_HINT, _enum
from ...workflow.validators.scripts import Policy

#: `ItemRole.cs`'s own fifteen real equip roles (no committed JSON registry exists for these --
#: the same "vocabulary with no dungeon-registries home, cited to its real source" shape
#: `schema.py`'s own `ELEMENTS`/`THREAT_BAND` already use). `Standard` (the sixteenth, reserved
#: commander slot) is excluded -- its own doc comment says "the generator emits nothing into it",
#: so a quest could never actually be satisfied by extracting one.
ITEM_ROLES: "tuple[str, ...]" = (
    "armament-primary", "core-guard", "ward-array", "armament-secondary", "jewel-major",
    "manipulator", "mantle", "head-guard", "girdle", "sense", "footing", "infusion",
    "retinue", "jewel-minor-a", "jewel-minor-b",
)

#: `QuestCatalog.cs`'s own fixed six-id set (`CountLessTemplates`) -- NOT derivable from
#: `targetKind` alone (`extract-with-item-kind` has a real `item-kind` targetKind yet is still
#: count-less), so it is its own named list here too, matching the C# side exactly rather than
#: re-deriving a rule that does not actually hold.
COUNT_LESS_TEMPLATES: "frozenset[str]" = frozenset({
    "kill-boss", "extract-with-item-kind", "bring-creature-home-alive",
    "finish-under-hunger", "survive-no-downed", "spend-no-provision",
})

#: `QuestCatalog.cs`'s own `needsTargetRef` check, verbatim: only these three `targetKind` values
#: ever need a real targetRef -- `kill-boss`'s own `targetKind: "boss"` does NOT (there is only one
#: boss per domain, nothing to disambiguate), so it is deliberately absent from this set even
#: though "boss" reads like it should need one.
TARGET_KIND_NEEDING_REF: "frozenset[str]" = frozenset({"room-kind", "curio-kind", "item-kind"})


def target_ref_candidates_for(
    target_kind: str, room_kinds: "frozenset[str]", event_kinds: "tuple[str, ...]",
) -> "tuple[str, ...]":
    """The real vocabulary a `targetKind` value draws from, confirmed against the real C# consumers
    rather than the spec's own looser "room kind, event kind, species family" prose:
    `room-kind` -> the eleven real room kinds (`RoomTableBinding`-adjacent, `QuestOffer.cs`'s own
    `RoomsOfKind` reads a room's ARCHETYPE, but `cleanse-fights`' own targetRef is a room KIND);
    `curio-kind` -> `EVENT_KIND` (`QuestProgress.cs:39`: `e.Kind == quest.TargetRef` compares
    against `DelveReportEvent.Kind`, itself an event's own six-member kind, not a curio sub-type
    despite the template's own name); `item-kind` -> `ItemRole` (`QuestProgress.cs:41`:
    `h.Role == quest.TargetRef`, `h` a haul entry). `none`/`boss` never reach here — the caller
    checks `TARGET_KIND_NEEDING_REF` first.
    """
    if target_kind == "room-kind":
        return tuple(sorted(room_kinds))
    if target_kind == "curio-kind":
        return event_kinds
    if target_kind == "item-kind":
        return ITEM_ROLES
    raise ValueError(f"target_kind {target_kind!r} never needs a targetRef -- check TARGET_KIND_NEEDING_REF first")


def build_quest_schema_for_cell(
    cell: Cell, quest_id: str, *,
    objective_templates: "dict[str, dict]", room_kinds: "frozenset[str]", event_kinds: "tuple[str, ...]",
    reward_bands: "frozenset[str]", count_bands: "frozenset[str]", repeat_scopes: "tuple[str, ...]",
) -> dict:
    """The REAL, per-cell schema a live call uses -- `schema.py`'s own `build_quest_schema()` stays
    the generic, unparameterized audit/documentation view (every PLANNED field a placeholder
    `const`); this function patches in the cell's own real `questId`/`objectiveTemplate`/`scope`
    and resolves `targetRef`/`countBand` to their template-conditional real shape, matching the
    spec's own field table (`spec-dungeon-seed-contract.md` §1.5) exactly rather than the loosely-
    worded prose alone.
    """
    template_id, scope = cell.dimension_values
    template = objective_templates[template_id]
    target_kind = template["targetKind"]
    needs_target_ref = target_kind in TARGET_KIND_NEEDING_REF
    is_count_less = template_id in COUNT_LESS_TEMPLATES

    if needs_target_ref:
        candidates = target_ref_candidates_for(target_kind, room_kinds, event_kinds)
        target_ref_node: dict = {"type": "string", "enum": sorted(candidates)}
    else:
        target_ref_node = {"type": "string", "const": "none"}

    if is_count_less:
        count_band_node: dict = {"type": "string", "const": "none"}
    else:
        count_band_node = {"type": "string", "enum": sorted(count_bands)}

    return {
        "type": "object",
        "properties": {
            "questId": {"type": "string", "const": quest_id},
            "objectiveTemplate": {"type": "string", "const": template_id},
            "scope": {"type": "string", "const": scope},
            "name": {"type": "string"},
            "flavor": {"type": "string"},
            "targetRef": target_ref_node,
            "countBand": count_band_node,
            "rewardBand": {"type": "string", "enum": sorted(reward_bands)},
            "repeatScope": {"type": "string", "enum": sorted(repeat_scopes)},
            "prereqRefs": {"type": "array", "items": {"type": "string"}, "minItems": 0, "uniqueItems": True},
            "chainRef": {"type": "string", "const": "none"},
        },
        "required": [
            "questId", "objectiveTemplate", "scope", "name", "flavor", "targetRef",
            "countBand", "rewardBand", "repeatScope", "prereqRefs", "chainRef",
        ],
        "additionalProperties": False,
    }


QUEST_SYSTEM_PROMPT = (
    "You are authoring one quest anchor for a party-dungeon crawl. Write only what the schema asks "
    "for. `name` and `flavor` are free text; every other field is a closed choice already fixed by "
    "the schema's own enum or const. Never invent a targetRef outside the schema's own enum -- an "
    "empty or unlisted value is a defect, not a creative choice. `flavor` is one or two sentences "
    "naming what the quest asks and why it would matter to whoever is asking -- never a rules "
    "explanation, never a citation of a game mechanic by name."
)


#: `spec-delve-quests.md:79-82`'s own real, mechanical definition of scope -- WHICH FACT SOURCE the
#: quest's completion predicate reads, never a difficulty or a narrative register on its own. Real
#: finding, 2026-09-07: a first live batch measured a HIGH `name_collision` rate specifically
#: between different scopes of the SAME template (`bring-creature-home-alive` at `delve` vs `domain`
#: vs `roster` produced the identical name twice) -- the brief gave the model no reason to write a
#: different name for the "same ask evaluated differently" shape scope actually is. This hint
#: grounds a real, accurate distinction (never an invented one) so `name`/`flavor` can legitimately
#: differ without pretending scope is a difficulty knob.
_SCOPE_HINT = {
    "delve": "Judged by what happens during this one descent alone -- an immediate task for this run.",
    "domain": "Judged across every attempt the player has made at this same domain -- a standing task tied to the place, not one run.",
    "roster": "Judged by what becomes of the party's own creatures at extraction -- a task about who comes home, not where.",
}


#: `spec-supplies-and-objects.md`'s own locked §11.5 mapping (read directly, not paraphrased):
#: "ration -> restore feeding hunger; bandage -> restore on hp; ... key -> utility (override only,
#: no atoms); ... bait -> utility." Real corpus finding, 2026-09-07: reading all 60 shipped
#: consumables (`data/seed/items/consumables/k{1,2,3}.json`) directly found every entry is
#: `restore`/`ward`/`draught` -- none is narratively a key, charm or bait item, so `overrideTags`
#: (herbs/key/holy/bait/watch) has no grounded value to offer for ANY of them today. Rather than
#: spend a real model call asking a question this corpus cannot honestly answer yet, this pipeline
#: fixes `overrideTags` to empty and asks the model only about `useContextAdds` -- the one question
#: the real corpus content actually supports (`ext_ref/schema.py`'s own generic `build_supply_ext_
#: schema` still offers the full `overrideTags` shape for whichever future consumable batch needs
#: it). `draught`-classed consumables are excluded entirely: their real `useContext` is `dispatch`
#: (a pre-run manifest binding), a different mechanic than a mid-delve rest/curio activation, so
#: extending them here would be guessing at a use they were never authored for.
SUPPLY_EXT_ELIGIBLE_CLASSES: "frozenset[str]" = frozenset({"restore", "ward"})

SUPPLY_EXT_SYSTEM_PROMPT = (
    "You are deciding whether an existing consumable item also makes sense to use at a delve's rest "
    "room, at a curio event, both, or neither. Write only what the schema asks for -- `overrideTags` "
    "is not yours to choose here, it is already fixed. Judge purely by what the item already does: "
    "a healing or defensive item that would help a party recovering between fights or resolving an "
    "event fits; do not force an addition that doesn't fit."
)


def build_supply_ext_schema_for_consumable(consumable_id: str) -> dict:
    """The REAL per-consumable schema a live call uses -- `overrideTags` fixed empty (see this
    module's own `SUPPLY_EXT_ELIGIBLE_CLASSES` doc comment for why), `consumableRef` pinned to the
    real id being extended, `useContextAdds` the one real open question."""
    return {
        "type": "object",
        "properties": {
            "consumableRef": {"type": "string", "const": consumable_id},
            "overrideTags": {"type": "array", "items": {"type": "string"}, "const": []},
            "useContextAdds": {"type": "array", "items": {"type": "string", "enum": ["rest", "curio"]},
                              "minItems": 0, "uniqueItems": True},
        },
        "required": ["consumableRef", "overrideTags", "useContextAdds"],
        "additionalProperties": False,
    }


def build_supply_ext_brief(consumable_id: str, name: str, class_id: str, family: str) -> str:
    return (
        f"Consumable: {name!r} (id {consumable_id}), class {class_id!r}, effect family {family!r}. "
        f"Decide `useContextAdds`: include \"rest\" if this item would genuinely help a party resting "
        f"between fights (healing, defensive prep); include \"curio\" if it would genuinely help "
        f"resolving a curio event (an offering, a defensive buff for a risky choice); include both, "
        f"one, or neither -- an empty list is a legitimate, honest answer if neither fits."
    )


def build_quest_brief(cell: Cell, template_id: str, scope: str, target_kind: str) -> str:
    """The user-facing brief -- names the cell's own fixed facts so the model writes `name`/
    `flavor` that actually fit the template, without repeating the schema's own enum lists (those
    are already enforced by constrained decoding; repeating them in prose only invites the model to
    treat them as suggestions rather than a closed set)."""
    kind_hint = {
        "none": "no specific target -- the objective itself is the whole ask",
        "boss": "the domain's own single boss -- never named, there is only one",
        "room-kind": "a kind of room the party must clear",
        "curio-kind": "a kind of event the party must find and resolve",
        "item-kind": "a kind of item the party must carry out of the domain",
    }[target_kind]
    return (
        f"Objective template: {template_id}. Target: {kind_hint}. "
        f"{_SCOPE_HINT[scope]} Write a `name` (a short quest title) and `flavor` (one to two "
        f"sentences) that fit this exact template, target and scope -- a quest at a different scope "
        f"needs a genuinely different name and flavor, even for the same objective template, since "
        f"what earns it and who it is about are different. Nothing else."
    )


#: D1.10's real remaining scope, event half (2026-09-07). `story`-kind events are EXCLUDED from
#: this first-ship batch -- `EventCatalog.cs`'s own real, enforced validator (`ChainRefRequiredFor
#: Story`) refuses any `story`-kind row whose `chainRef` is empty, and a real multi-part chain
#: needs sequencing infrastructure (which chapter comes first, how later chapters reference earlier
#: minted ids) this pass does not build -- the same "a real structural reason, named, not a
#: corner cut" posture `SUPPLY_EXT_ELIGIBLE_CLASSES` already established for `draught`. Excluding
#: `story` also removes `nothing` from the legal ordinal vocabulary for this whole batch (the real
#: validator's `NothingOnlyOnStory` rule), so every outcome in this pass is good/mixed/bad.
EVENT_KIND_FIRST_SHIP: "tuple[str, ...]" = ("bargain", "curio", "encounter-event", "shrine", "trap")

#: This batch's own outcome count -- FIXED at exactly 2, one narrower than the seed contract's real
#: 2-4 range (`spec-dungeon-seed-contract.md` §1.4). Named honestly: `outcomes[].ordinal`/
#: `outcomes[].dropBand` are the only two event fields the spec's own vote-set table marks "voted",
#: but voting a field WITHIN a variable-length array needs samples to agree on how many outcomes
#: exist and in what order before a position can be compared at all -- nothing in the schema
#: enforces either agreement, and no prior pipeline in this program has voted inside an array.
#: Rather than ship an unverified positional-correspondence assumption, this batch fixes the count
#: (so a per-index vote is well-defined) for a future pass to widen once it is actually needed;
#: `schema.py`'s own generic `build_event_schema()` keeps the full 2-4 range for documentation.
EVENT_OUTCOME_COUNT = 2


def build_event_schema_for_cell(
    cell: Cell, event_id: str, *,
    grantable_atom_families: "frozenset[str]", power_bands: "frozenset[str]", override_tags: "frozenset[str]",
    assigned_chain_ref: "str | None" = None,
    climate: "str | None" = None,
) -> dict:
    """The REAL, per-cell schema a live call uses -- `schema.py`'s own `build_event_schema()` stays
    the generic, unparameterized audit view. `eventId`/`kind`/`theme` pin to the cell's own real
    minted id and dimension values; `eligibility` pins to JSON `null` (`EventRow.Eligibility` is a
    nullable `PredicateNode?`, and 'none = always eligible' is the seed contract's own explicit
    legal value) -- no predicate-tree grammar exists anywhere in this pipeline yet, a real, named
    gap for a future pass that has a concrete reason to gate an event rather than authoring one
    speculatively. `chainRef` pins to `"none"` for every non-story kind (the same reason quest's
    own `chainRef` always does, `test_chainRef_is_always_pinned_none_quests_never_chain`'s own
    precedent). `outcomes` is fixed at exactly `EVENT_OUTCOME_COUNT` items (see that constant's own
    doc comment) and never offers `"nothing"` as an ordinal except on `story` (legal only there,
    the real validator's `NothingOnlyOnStory` rule).

    `assigned_chain_ref`, for `story` kind ONLY, pins `chainRef` to a real, planner-supplied
    string instead of asking the model -- the real, SHIPPED `EventCatalog.Load` validator refuses a
    `story` event with an empty `chainRef` (`ChainRefRequiredForStory`, found live: an earlier
    attempt authored `chainRef: "none"` for two standalone story events on the wrong assumption    that a nullable field was also an omittable one, and the real C# validator refused both). A
    `story` event's `chainRef` is therefore ALWAYS planner-assigned, never model-authored -- picking
    a coherent next-chapter id is a narrative/sequencing decision no model call is trusted with, the
    same reasoning `layoutTemplateId`/`roomPalette`/etc. already established for domain.
    """
    kind, theme = cell.dimension_values
    if kind == "story" and not assigned_chain_ref:
        raise ValueError(f"event {event_id!r}: kind 'story' requires a real assigned_chain_ref -- "
                          "the real EventCatalog.Load validator refuses an empty one (ChainRefRequiredForStory)")
    # `nothing` is legal ONLY on `story` (the real validator's `NothingOnlyOnStory` rule) -- a
    # standalone story beat legitimately has "nothing happens yet, the tale continues" as an
    # honest outcome, the same way `chainRef: none` legitimately means "no chain, one beat".
    ordinal_values = ["good", "mixed", "bad", "nothing"] if kind == "story" else ["good", "mixed", "bad"]
    outcome_item = {
        "type": "object",
        "properties": {
            "ordinal": {"type": "string", "enum": ordinal_values},
            "consequence": {"type": "string", "enum": ["none", "loot", "encounter", "scout"]},
            "dropBand": {"type": "string", "enum": ["staple", "frequent", "occasional", "seldom", "exceptional"]},
            "effects": {
                "type": "array", "minItems": 0, "maxItems": 2,
                "items": {
                    "type": "object",
                    "properties": {
                        "family": {"type": "string", "enum": sorted(grantable_atom_families)},
                        "powerBand": {"type": "string", "enum": sorted(power_bands)},
                    },
                    "required": ["family", "powerBand"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["ordinal", "consequence", "dropBand", "effects"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "eventId": {"type": "string", "const": event_id},
            "kind": {"type": "string", "const": kind},
            "theme": {"type": "string", "const": theme},
            "name": {"type": "string"},
            "flavor": {"type": "string"},
            "reason": {"type": "string"},
            "climateAffinity": _enum("climateAffinity", ELEMENTS, nullable=True, const=True,
                                    planned_value=climate),
            "repeatScope": {"type": "string", "enum": ["per-delve", "per-domain", "once-per-player"]},
            "eligibility": {"type": "null", "const": None},
            "outcomes": {"type": "array", "items": outcome_item,
                         "minItems": EVENT_OUTCOME_COUNT, "maxItems": EVENT_OUTCOME_COUNT},
            "supplyOverride": {"type": "string", "enum": sorted(override_tags | {"none"})},
            "chainRef": {"type": "string", "const": assigned_chain_ref if kind == "story" else "none"},
        },
        "required": [
            "eventId", "kind", "theme", "name", "flavor", "reason", "climateAffinity",
            "repeatScope", "eligibility", "outcomes", "supplyOverride", "chainRef",
        ],
        "additionalProperties": False,
    }


EVENT_SYSTEM_PROMPT = (
    "You are authoring one delve event for a party dungeon crawl. Write only what the schema asks "
    "for. `name`, `flavor` and `reason` are free text; every other field is a closed choice already "
    "fixed by the schema's own enum or const. `flavor` sets a scene the party finds -- never a rules "
    "explanation, never a hint about which outcome is best. Use at least one of the listed motif "
    "words somewhere in your text, and never use a listed anti-motif word anywhere. Each outcome's "
    "`effects` grants real stat atoms if and only if that outcome should mechanically reward or hurt "
    "the party beyond flavor -- an empty `effects` list is a legitimate, honest answer when an "
    "outcome is flavor-only."
)

#: ⛔ **The first versioned prompt in this program** (spec-dungeon-generator-repair.md §4). Bump this
#: on ANY change to `EVENT_SYSTEM_PROMPT`, `build_event_brief`, `build_event_schema_for_cell` or
#: `EVENT_SCRIPT_POLICY`. `event_prompt_fingerprint` hashes those four sources and
#: `test_dungeon_event_briefs.py` pins the digest next to this string, so an edit without a bump fails.
#: `/2` (NS11): the per-cell schema pins `climateAffinity` as a PLANNED `const` instead of offering it
#: as a free enum — the mechanism's first real exercise, caught by the pinned digest the moment the
#: schema moved.
EVENT_PROMPT_VERSION = "dungeon-event/2"

#: The declared target-script policy for every string leaf of an event draft (spec §3). `latin` for the
#: three prose fields and `none` for every field that carries no prose — a CLOSED map, so an undeclared
#: string field is itself a defect (`script_policy` refuses it) and a future event field cannot slip past.
EVENT_SCRIPT_POLICY: "dict[str, Policy]" = {
    "name": Policy.LATIN,
    "flavor": Policy.LATIN,
    "reason": Policy.LATIN,
    "eventId": Policy.NONE,
    "kind": Policy.NONE,
    "theme": Policy.NONE,
    "climateAffinity": Policy.NONE,
    "repeatScope": Policy.NONE,
    "eligibility": Policy.NONE,
    "supplyOverride": Policy.NONE,
    "chainRef": Policy.NONE,
    "outcomes[].ordinal": Policy.NONE,
    "outcomes[].consequence": Policy.NONE,
    "outcomes[].dropBand": Policy.NONE,
    "outcomes[].effects[].family": Policy.NONE,
    "outcomes[].effects[].powerBand": Policy.NONE,
}


def event_prompt_fingerprint(
    cell: Cell,
    motif_brief: "dict[str, list[str]]",
    *,
    event_id: str,
    grantable_atom_families: "frozenset[str]",
    power_bands: "frozenset[str]",
    override_tags: "frozenset[str]",
) -> str:
    """A digest of the CODE-OWNED prompt text an event call is built from: the system prompt, the
    rendered glossed brief, the rendered schema, and the script policy. A declaration (the digest of
    text this repo owns), never generated content — pinned by a test next to `EVENT_PROMPT_VERSION`."""
    payload = {
        "system": EVENT_SYSTEM_PROMPT,
        "brief": build_event_brief(cell, motif_brief),
        "schema": build_event_schema_for_cell(
            cell, event_id, grantable_atom_families=grantable_atom_families,
            power_bands=power_bands, override_tags=override_tags),
        "scriptPolicy": {k: v.value for k, v in sorted(EVENT_SCRIPT_POLICY.items())},
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


#: Grounded per-kind hint -- `spec-dungeon-seed-contract.md` §1.4's own six-kind vocabulary
#: (`curio · encounter-event · shrine · trap · bargain · story`), restated as what a player actually
#: DOES at one, so the model writes an event that fits the kind's own real shape rather than a
#: generic "something happens" scene.
_EVENT_KIND_HINT = {
    "curio": "an object or oddity the party can choose to interact with, or leave alone",
    "encounter-event": "a scripted twist on a fight -- not the fight itself, the choice around it",
    "shrine": "a place of ritual the party can spend something at, or walk past",
    "trap": "a hazard sprung by moving through it, not a choice offered",
    "bargain": "an explicit offer with a stated cost and a stated gain, agreed to or refused",
    "story": "a wild creature the party may talk to, offer to, or leave -- a single, self-contained beat, not part of a longer chain",
}


def build_event_brief(cell: Cell, motif_brief: "dict[str, list[str]]") -> str:
    """The user-facing brief -- names the cell's own fixed facts (kind, theme) and the cell's own
    allocated motif brief, never the schema's enum lists themselves (constrained decoding already
    enforces those).

    ⛔ **`motif_brief` carries GLOSSED WORDS, never raw motifs** (spec-dungeon-generator-repair.md
    §2). `pipelines.run_event_draws` resolves the slot's allocation through
    `briefkit.gloss.GlossTable.gloss_all` and refuses a slot with any unglossed motif before any
    call, so a Chinese motif character cannot reach this text -- which is what fixes the 53 of 54
    committed events that shipped raw motifs into prose.
    """
    kind, theme = cell.dimension_values
    motifs = ", ".join(motif_brief["motifs"]) or "(none allocated)"
    anti = ", ".join(motif_brief["antiMotifs"]) or "(none)"
    return (
        f"Event kind: {kind} -- {_EVENT_KIND_HINT[kind]}. Theme motif words to draw from: {motifs}. "
        f"Motif words this theme is explicitly defined AGAINST, never use them: {anti}. "
        f"Write `name`, `flavor` and `reason`, pick `climateAffinity`, `repeatScope` and "
        f"`supplyOverride`, and author exactly {EVENT_OUTCOME_COUNT} outcomes spanning a real spread "
        f"from favourable to unfavourable -- two outcomes that both read as 'good' is not a real "
        f"choice. Nothing else."
    )


#: D1.10's real remaining scope, encounter half (2026-09-07). No fixed slot count exists anywhere
#: in the spec or the real, already-shipped `EncounterAnchor` (`Encounter.cs:32-35` — `Slots` is
#: caller-sized) -- this is a real, named authoring decision, not a discovered fact: `pack`
#: (fight/wild rooms, many weak foes per the room-kind -> formation mapping, seed-contract §1.2)
#: gets 2 distinct slot types; `party` (elite rooms, fewer stronger foes) gets 3; `boss` gets
#: EXACTLY 1 -- that one slot IS the boss's own retinue (`BossKit.RetinueSlotIndex` names it by
#: POSITION in this SAME list, never a second vocabulary -- `Encounter.cs:44`'s own words, "the
#: retinue is one more §2 slot"); the boss combatant itself is `bossSpeciesRef`/`BossKit`, never a
#: `slots[]` entry. A real spec-vs-code drift found before writing this (recorded in full in this
#: program's own todo file, 2026-09-07): the spec's own §1.6 table still describes
#: `boss.retinue: {slotRef, countBand}`, but the real `BossKit` record takes a plain `int` index —
#: this schema follows the REAL type, and since a boss cell's own `slots[]` is fixed at exactly one
#: entry, that index is always `0`, pinned rather than asked.
SLOT_COUNT_BY_FORMATION: "dict[str, int]" = {"pack": 2, "party": 3, "boss": 1}

#: `posture` is deliberately ABSENT from this schema -- see `build_encounter_schema_for_cell`'s own
#: doc comment for the real, measured reason (a live 40-entry batch resolved only 12/40, then a
#: re-run with per-attempt enum permutation AND a strengthened retry message resolved only 1/4 on
#: a single retested cell: the model's own content prior for "one tank plus one support" is strong
#: enough that neither debiasing technique moved it). `pipelines.run_encounter_draws` assigns
#: posture BY INDEX from the planner's own pre-computed, guaranteed-distinct multiset
#: (`planner.posture_multisets_for`) after the model returns -- structurally impossible to collide,
#: never a property this schema offers the model to choose at all.
_SLOT_ITEM_SCHEMA = {
    "type": "object",
    "properties": {
        "reach": {"type": "string", "enum": ["melee", "short", "long", "siege", "none"]},
        "targetPreference": {"type": "string", "enum": [
            "frontline", "backline", "swarm", "elite", "structure", "indiscriminate", "none"]},
        "countBand": {"type": "string", "enum": ["lone", "few", "several", "many"]},
    },
    "required": ["reach", "targetPreference", "countBand"],
    "additionalProperties": False,
}


def build_encounter_schema_for_cell(
    cell: Cell, encounter_id: str, *, threat_band: "tuple[str, ...]", zomboss_pattern_ids: "frozenset[str]",
) -> dict:
    """The REAL, per-cell schema a live call uses -- `schema.py`'s own `build_encounter_schema()`
    stays the generic, unparameterized audit view. `slots`/`rankOrder` are FIXED-length at
    `SLOT_COUNT_BY_FORMATION[formation]` (see that constant's own doc comment for why a per-index
    vote is out of scope, matching event's own `EVENT_OUTCOME_COUNT` reasoning exactly: no prior
    pipeline in this program has voted inside a variable-length array, so this batch fixes the
    length and drops cross-sample voting for the whole entry instead, one call per encounter).
    `synergyHint` and `affixRoll` both pin to `"none"`: `synergyHint` needs a real
    `TraitBattleCatalog` id pair this pass has not grounded, and `affixRoll` needs a real elite-
    affix library D2.6 already found does not exist yet ("zero enemy-tagged rows exist anywhere") --
    both are legal `none` values per the seed contract, not corners cut. `boss` is present ONLY for
    `formation == "boss"`, with `retinue` pinned to `0` (see this module's own `SLOT_COUNT_BY_
    FORMATION` doc comment for why that index is always the same value).

    **`slots[].posture` is not part of this schema at all** (`_SLOT_ITEM_SCHEMA`'s own doc comment
    has the full measured story) -- `pipelines.run_encounter_draws` injects it by index after the
    model responds, from a pre-computed, guaranteed-distinct multiset. Asking the model for
    posture and retrying on collision was tried FIRST, empirically, and failed badly enough
    (12/40 then 1/4 even with per-attempt permutation and a strengthened message) that a structural
    fix replaced it, matching this program's own precedent for a model that cannot reliably honor a
    cross-field constraint no matter how it is asked (`unique-pipeline`'s own `tags` field, split
    into five single-value fields after an ~85% violation rate).
    """
    formation, element_spread = cell.dimension_values
    n_slots = SLOT_COUNT_BY_FORMATION[formation]
    properties: "dict[str, Any]" = {
        "encounterId": {"type": "string", "const": encounter_id},
        "formation": {"type": "string", "const": formation},
        "elementSpread": {"type": "string", "const": element_spread},
        "name": {"type": "string"},
        "reason": {"type": "string"},
        "slots": {"type": "array", "items": _SLOT_ITEM_SCHEMA, "minItems": n_slots, "maxItems": n_slots},
        "threatWindow": {
            "type": "object",
            "properties": {
                "floorRung": {"type": "string", "enum": sorted(threat_band)},
                "ceilRung": {"type": "string", "enum": sorted(threat_band)},
            },
            "required": ["floorRung", "ceilRung"], "additionalProperties": False,
        },
        "rankOrder": {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": n_slots - 1},
                      "minItems": n_slots, "maxItems": n_slots, "uniqueItems": True},
        "tempo": {"type": "string", "enum": ["ponderous", "slow", "steady", "quick", "flurry", "none"]},
        "synergyHint": {"type": "string", "const": "none"},
        "affixRoll": {"type": "string", "const": "none"},
    }
    required = [
        "encounterId", "formation", "elementSpread", "name", "reason", "slots", "threatWindow",
        "rankOrder", "tempo", "synergyHint", "affixRoll",
    ]
    if formation == "boss":
        properties["boss"] = {
            "type": "object",
            "properties": {
                "build": {"type": "string", "enum": sorted(zomboss_pattern_ids)},
                "phasing": {"type": "string", "enum": ["none", "breakpoint", "escalating"]},
                "phaseTrigger": {"type": "string", "enum": ["hp-threshold", "round", "ally-down", "none"]},
                "signatureAction": {"type": "string"},
                "retinue": {"type": "integer", "const": 0},
            },
            "required": ["build", "phasing", "phaseTrigger", "signatureAction", "retinue"],
            "additionalProperties": False,
        }
        required.append("boss")
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


ENCOUNTER_SYSTEM_PROMPT = (
    "You are authoring one encounter filter for a party dungeon crawl -- a shape of opposition, "
    "never a list of species. Write only what the schema asks for. `name` and `reason` are free "
    "text; every other field is a closed choice already fixed by the schema's own enum or const. "
    "Each slot's own posture (its combat role) is ALREADY DECIDED and named to you in the brief, in "
    "order -- your job is only its reach, targetPreference and countBand, describing a filter the "
    "runtime later draws real species against, never a species or a made-up creature name. "
    "`rankOrder` is a front-to-back ordering of slot INDICES (0-based) -- put tankier slots first, "
    "fragile/high-value slots last, and use every index exactly once."
)

_FORMATION_HINT = {
    "pack": "many weak, similar foes -- a fight or wild room's own shape",
    "party": "fewer, individually stronger and more varied foes -- an elite room's own shape",
    "boss": "one boss (handled elsewhere) plus a single retinue slot backing it up",
}
_ELEMENT_SPREAD_HINT = {
    "mono": "every drawn foe shares one element",
    "dual": "drawn foes span exactly two elements",
    "rainbow": "drawn foes may span any number of elements",
}


def build_encounter_brief(cell: Cell, slot_postures: "tuple[str, ...]") -> str:
    """The user-facing brief -- names the cell's own fixed facts (formation, elementSpread) AND the
    planner's own pre-assigned posture for each slot, in order (`_SLOT_ITEM_SCHEMA`'s own doc
    comment has the full measured reason posture is assigned here rather than asked). Never the
    schema's remaining enum lists themselves (constrained decoding already enforces those). Unlike
    event, no motif brief: `kinds.py`'s own `motif_expression` for this kind is "the shape of the
    opposition, never which species fill it" -- an abstract design register, not a literal-word
    constraint this brief needs to convey."""
    formation, element_spread = cell.dimension_values
    n_slots = SLOT_COUNT_BY_FORMATION[formation]
    postures_line = "; ".join(f"slot {i} is {p}" for i, p in enumerate(slot_postures))
    boss_note = (
        " This is a BOSS encounter: also fill `boss` with a pattern build, a phasing shape and a "
        "signature action; its retinue is the one slot named above."
        if formation == "boss" else ""
    )
    return (
        f"Formation: {formation} -- {_FORMATION_HINT[formation]}. Element spread: {element_spread} "
        f"-- {_ELEMENT_SPREAD_HINT[element_spread]}. Slot postures (already decided): {postures_line}. "
        f"Author each slot's reach, targetPreference and countBand to fit its OWN posture, a "
        f"`rankOrder` covering every slot index once, a `threatWindow` naming the band of foes this "
        f"fits, and a `tempo`.{boss_note} Nothing else."
    )


#: D1.10's real remaining scope, room half (2026-09-07). `fight`/`wild` -> `pack`, `elite` ->
#: `party`, `boss` -> `boss` (spec-dungeon-seed-contract.md §1.2's own words); every other kind
#: pins `encounterRef` to `"none"`.
ENCOUNTER_FORMATION_BY_ROOM_KIND: "dict[str, str]" = {
    "fight": "pack", "wild": "pack", "elite": "party", "boss": "boss",
}

#: The real, non-obvious "kind fits" mapping -- read directly from `spec-event-deck.md:88-90`, NOT
#: guessed from same-name matching (which would be WRONG for `merchant`/`wild`/`rest`, three of
#: these seven). A room kind absent from this dict (`fight`/`elite`/`boss`/`cache`) gets an EMPTY
#: `eventPool`, pinned -- not a missing entry to fill in later, the spec's own words are "none" for
#: those four. `"unknown"`'s own real value is the literal string `"any"`, matched here rather than
#: inventing a `None`-means-something-else sentinel a future reader would have to rediscover.
EVENT_KIND_BY_ROOM_KIND: "dict[str, str]" = {
    "curio": "curio", "shrine": "shrine", "trap": "trap", "merchant": "bargain",
    "wild": "story", "rest": "encounter-event", "unknown": "any",
}


def build_room_schema_for_cell(
    cell: Cell, room_id: str, *,
    room_kind_rows: "dict[str, dict]", hazard_band: "frozenset[str]", sight_band: "frozenset[str]",
    disposition: "frozenset[str]", tags: "frozenset[str]",
    encounter_ids_by_formation: "dict[str, frozenset[str]]", event_ids_by_kind: "dict[str, frozenset[str]]",
    assigned_disposition: "str | None" = None,
) -> dict:
    """The REAL, per-cell schema a live call uses -- `schema.py`'s own `build_room_schema()` stays
    the generic, unparameterized audit view. `secretEligible` pins to `"no"` for the 8 of 11 kinds
    whose OWN registry row (`room-kinds.v1.json`) carries `secretEligible: false` -- only `cache`/
    `shrine`/`merchant` ever offer the real yes/no choice. `dispositionBase` pins to `"none"` on
    every kind but `wild` (the seed contract's own words: "required on every kind but wild").
    `encounterRef`/`eventPool` resolve against the caller's own REAL, currently-shipped id sets
    (`encounter_ids_by_formation`/`event_ids_by_kind`) -- never a placeholder vocabulary -- and this
    function REFUSES LOUDLY (raises `ValueError`, never emits an unsatisfiable schema) if a kind
    that structurally NEEDS a non-empty pool has no real candidates yet: a real, live example is
    `wild`-kind rooms needing `story`-kind events, which this batch's own event pass deliberately
    never shipped (`EVENT_KIND_FIRST_SHIP`) -- calling this for a `wild` cell today is a genuine,
    named blocker, not a bug to silently paper over with an empty enum.

    `assigned_disposition`, when given, pins `dispositionBase` to that one value instead of
    offering the model the full 4-value enum -- a real live batch measured all 12 first wild rooms
    picking `hostile` uniformly, the SAME single-value-bias shape this session already found for
    encounter's posture and domain's entranceHint; the caller (`run_room_draws`) cycles a real
    assignment deterministically the same way those two fixes did, rather than gambling on retries.
    """
    kind, climate = cell.dimension_values
    kind_row = room_kind_rows[kind]

    secret_node = ({"type": "string", "enum": ["yes", "no"]} if kind_row.get("secretEligible")
                    else {"type": "string", "const": "no"})
    if kind != "wild":
        disposition_node = {"type": "string", "const": "none"}
    elif assigned_disposition is not None:
        disposition_node = {"type": "string", "const": assigned_disposition}
    else:
        disposition_node = {"type": "string", "enum": sorted(disposition)}

    formation = ENCOUNTER_FORMATION_BY_ROOM_KIND.get(kind)
    if formation is not None:
        candidates = sorted(encounter_ids_by_formation.get(formation, ()))
        if not candidates:
            raise ValueError(f"room kind {kind!r} needs a real {formation!r}-formation encounter, none exist yet")
        encounter_ref_node = {"type": "string", "enum": candidates}
    else:
        encounter_ref_node = {"type": "string", "const": "none"}

    event_kind = EVENT_KIND_BY_ROOM_KIND.get(kind)
    if event_kind is None:
        event_pool_node = {"type": "array", "items": {"type": "string"}, "minItems": 0, "maxItems": 0, "uniqueItems": True}
    else:
        candidates = (sorted({eid for ids in event_ids_by_kind.values() for eid in ids}) if event_kind == "any"
                      else sorted(event_ids_by_kind.get(event_kind, ())))
        if not candidates:
            raise ValueError(f"room kind {kind!r} needs a real {event_kind!r}-kind event for its eventPool, none exist yet")
        event_pool_node = {"type": "array", "items": {"type": "string", "enum": candidates}, "minItems": 1, "uniqueItems": True}

    properties: "dict[str, Any]" = {
        "roomId": {"type": "string", "const": room_id},
        "kind": {"type": "string", "const": kind},
        "climate": {"type": "string", "const": climate},
        "name": {"type": "string"},
        "flavor": {"type": "string"},
        "reason": {"type": "string"},
        "hazardBand": {"type": "string", "enum": sorted(hazard_band)},
        "sightBand": {"type": "string", "enum": sorted(sight_band)},
        "dispositionBase": disposition_node,
        "encounterRef": encounter_ref_node,
        "eventPool": event_pool_node,
        "secretEligible": secret_node,
        "tags": {"type": "array", "items": {"type": "string", "enum": sorted(tags)}, "minItems": 0, "uniqueItems": True},
    }
    required = [
        "roomId", "kind", "climate", "name", "flavor", "reason", "hazardBand", "sightBand",
        "dispositionBase", "encounterRef", "eventPool", "secretEligible", "tags",
    ]
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


ROOM_SYSTEM_PROMPT = (
    "You are authoring one room archetype for a party dungeon crawl. Write only what the schema "
    "asks for. `name`, `flavor` and `reason` are free text; every other field is a closed choice "
    "already fixed by the schema's own enum or const. `flavor` sets a scene the party walks into -- "
    "never a rules explanation, never a hint about hazard or difficulty. `hazardBand` is about "
    "hunger cost to cross, never danger -- a heavy-hazard room can still be an easy fight."
)

_ROOM_KIND_HINT = {
    "fight": "a straightforward fight room", "elite": "a tougher, smaller fight room",
    "cache": "a reward room with no fight", "curio": "a room built around one curio event",
    "wild": "a room where a wild creature may be talked to, bought from, prayed to, or caged",
    "shrine": "a room built around one shrine event", "rest": "a room to recover between fights",
    "merchant": "a room to trade with a merchant", "trap": "a room built around one trap event",
    "unknown": "a room whose true nature is hidden until entered", "boss": "the domain's own boss room",
}


def build_room_brief(cell: Cell) -> str:
    """The user-facing brief -- names the cell's own fixed facts (kind, climate), never the
    schema's enum lists themselves (constrained decoding already enforces those)."""
    kind, climate = cell.dimension_values
    climate_note = "climate-blind (no element)" if climate == "none" else f"{climate}-aligned"
    return (
        f"Room kind: {kind} -- {_ROOM_KIND_HINT[kind]}. Climate: {climate_note}. "
        f"Write `name`, `flavor` and `reason`, and pick `hazardBand` and `sightBand` that fit this "
        f"exact kind and climate. Nothing else."
    )


# ---------------------------------------------------------------------------------------------
# D1.10's real remaining scope, domain half (2026-09-07, D4.30's own real prerequisite chain) --
# the seventh and last AUTHORED-field kind. `roomPalette`/`questPool`/`lootBinding`/
# `layoutTemplateId` are ALL planner-computed (PLANNED here, a deliberate DEVIATION from
# `kinds.py`'s own DOMAIN_OWNERSHIP "VALIDATED" tag for the first two) -- the encounter posture
# lesson this whole session already proved once (structural-fix-over-retry: when a coverage
# requirement is hard and the candidate set is small enough to enumerate exhaustively, remove the
# field from the model's own choice space rather than gamble on a model achieving full coverage
# across retries). §2 row 3's own "every (kind,climate) cell needs >=1 archetype" and row 8's ">=2
# quest ids" are both trivially, deterministically satisfiable by including EVERY real matching id
# rather than asking a model to hand-pick a covering subset with no coverage guarantee. Only
# `theme`/`bossSpeciesRef`/`retinueFamily` stay model-authored (VALIDATED, single-value enum picks
# with no coverage requirement across domains) plus `name`/`flavor`/`reason` (AUTHORED, free text,
# the same triad every other kind already has).
#
# `entranceHint` ALSO moved to planner-computed after a live batch measured it, not assumed: the
# real first six-domain run picked `Anomaly` for all six -- the identical single-value-bias shape
# already proven for encounter's posture field this same session, on a field with no stated
# coverage requirement of its own but where a free, harmless deterministic cycle (mirroring
# `layoutTemplateId`'s own already-cycled assignment) costs nothing and avoids shipping a known,
# measured bias into content a later module (`world-generator`) will read to place map-door visuals.
# ---------------------------------------------------------------------------------------------

#: spec-dungeon-loot.md §5's own naming convention, verbatim, mirrored from
#: `DungeonLootTableGen.TableId` (C#, `gk-core/src/FusionRpg.Core/Delve/Loot/DungeonLootTableGen.cs`) --
#: the SAME four bound kinds that class's own `BoundRoomKinds` names, kept in sync by citation
#: since Python cannot call the C# formula directly.
DOMAIN_LOOT_BOUND_KINDS: "tuple[str, ...]" = ("fight", "elite", "boss", "cache")


def loot_binding_for_climate(climate: str) -> "dict[str, str]":
    return {kind: f"drop.dungeon.{climate}.{kind}" for kind in DOMAIN_LOOT_BOUND_KINDS}


def room_palette_for_climate(climate: str, room_rows: "dict[str, dict]") -> "list[str]":
    """Every real shipped room id whose own climate matches this domain's (or is climate-neutral,
    `none` -- legal for any domain per the seed contract's own §3.6 converse rule, already applied
    the same way in `test_dungeon_room_content.py`). Deliberately ALL of them, not a curated
    subset -- see the module-level note above."""
    return sorted(rid for rid, row in room_rows.items() if row["climate"] in (climate, "none"))


def build_domain_schema_for_cell(
    cell: Cell, domain_id: str, *,
    theme_ids: "frozenset[str]", boss_species_candidates: "frozenset[str]",
    retinue_families: "frozenset[str]", layout_template_id: str,
    room_palette_ids: "list[str]", quest_pool_ids: "list[str]", entrance_hint: str,
) -> dict:
    """The REAL, per-cell schema a live call uses -- `schema.py`'s own `build_domain_schema()`
    stays the generic, unparameterized audit view. `climate` is the cell's own dimension value
    (PLANNED, one domain per climate, spec-domain-catalog.md §7); `dangerBand`/`entry` pin to the
    first-ship shape's own two constants (`shallow`/`many`, §7 verbatim -- the six first-ship
    domains are ALL `many` at `shallow`, never a per-cell choice). `bossSpeciesRef` refuses loudly
    (raises `ValueError`) if the caller's own candidate set for this climate is empty -- a real,
    live possibility the boss-species measurement already ruled out for all six climates, but this
    function does not trust that measurement silently the way `build_room_schema_for_cell` does not
    trust an empty encounter/event candidate set either.
    """
    climate = cell.dimension_values[0]
    if not boss_species_candidates:
        raise ValueError(f"climate {climate!r} has no real boss-eligible species (threatBand >= tyrant) to name")
    if not room_palette_ids:
        raise ValueError(f"climate {climate!r} has no real rooms to fill roomPalette")
    if len(quest_pool_ids) < 2:
        raise ValueError(f"questPool needs >= 2 real quest ids, got {len(quest_pool_ids)}")
    if entrance_hint not in ENTRANCE_HINT:
        raise ValueError(f"entrance_hint {entrance_hint!r} is not one of {ENTRANCE_HINT}")

    properties: "dict[str, Any]" = {
        "domainId": {"type": "string", "const": domain_id},
        "name": {"type": "string"},
        "flavor": {"type": "string"},
        "reason": {"type": "string"},
        "theme": {"type": "string", "enum": sorted(theme_ids)},
        "climate": {"type": "string", "const": climate},
        "dangerBand": {"type": "string", "const": "shallow"},
        "entry": {"type": "string", "const": "many"},
        "layoutTemplateId": {"type": "string", "const": layout_template_id},
        "bossSpeciesRef": {"type": "string", "enum": sorted(boss_species_candidates)},
        "retinueFamily": {"type": "string", "enum": sorted(retinue_families)},
        "roomPalette": {"type": "array", "items": {"type": "string"}, "const": room_palette_ids},
        "questPool": {"type": "array", "items": {"type": "string"}, "const": quest_pool_ids},
        "lootBinding": {"type": "object", "const": loot_binding_for_climate(climate)},
        "entranceHint": {"type": "string", "const": entrance_hint},
        "variants": {"type": "array", "items": {"type": "string"}, "const": []},
        "tags": {"type": "array", "items": {"type": "string"}, "const": []},
    }
    required = [
        "domainId", "name", "flavor", "theme", "climate", "dangerBand", "entry",
        "layoutTemplateId", "bossSpeciesRef", "retinueFamily", "roomPalette", "questPool",
        "lootBinding", "entranceHint", "variants", "tags", "reason",
    ]
    return {"type": "object", "properties": properties, "required": required, "additionalProperties": False}


DOMAIN_SYSTEM_PROMPT = (
    "You are authoring one dungeon domain -- a whole descent, its danger and the fiction that "
    "holds its rooms together. Write only what the schema asks for. `name`, `flavor` and `reason` "
    "are free text; every other field is a closed choice already fixed by the schema's own enum or "
    "const. `flavor` sets the scene a player reads before entering -- never a rules explanation, "
    "never a number, never a difficulty hint. `theme` should genuinely fit the domain's own "
    "climate and the boss species you name; `retinueFamily` is the lineage backing up that boss, "
    "not the boss's own species."
)


def build_domain_brief(cell: Cell, boss_species_candidates: "frozenset[str]") -> str:
    """The user-facing brief -- names the cell's own fixed climate and the real boss-species
    candidates for it, never the schema's remaining enum lists themselves (constrained decoding
    already enforces those)."""
    climate = cell.dimension_values[0]
    species_line = ", ".join(sorted(boss_species_candidates))
    return (
        f"Climate: {climate}-aligned. This domain is `many` (a standing sub-world, re-rolled on "
        f"entry) at the `shallow` danger band -- the gentlest rung of six first-ship domains, one "
        f"per climate. Pick a `bossSpeciesRef` from: {species_line}. Write `name`, `flavor` and "
        f"`reason`, and pick a `theme` and a `retinueFamily` that fit this climate and boss. "
        f"Nothing else."
    )
