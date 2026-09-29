"""seedsmith.adapters.actions.signature_propose.prompts --- A-P3 "signature-propose"'s own domain
knowledge (spec-signature-propose.md SS2, action-corpus module). The model authors THE ONE action
that makes a single creature unlike its siblings in the same family: a name, a flavour line, which
atom FAMILIES it is built from, which of the SPECIES' own motifs it expresses, and -- the judgement
this whole pipeline exists to make -- the ONE axis it differs on from its family's own accepted
actions. Every magnitude of any kind -- rung, cost, cooldown, duration, chance, weight, tier, stack
count -- is a table's job, never the model's (P1, restated for this content type; see also
`general_propose/prompts.py`'s and `family_propose/prompts.py`'s own identical opening paragraph).

**A-P3 reads exactly one anchor shape: a SPECIES, plus its own family's accepted output.** Never a
bare family (that is A-P2's brief, spec SS0), and never a brief missing `familyActions` outright
(spec SS3: "A brief whose `familyActions` key is absent raises"). `build_context` raises the moment
a brief is not `scope: "species"`, or lacks the `familyActions` key A-S2 (`brief_assembly`) always
supplies on every signature brief it assembles -- silently defaulting an absent key to `[]` is
exactly how "no family round has run yet" quietly becomes "this species genuinely has no family"
(spec SS3, and `brief_assembly.derive.require_family_actions`'s own identical rule, restated here
for THIS module's own consumer side). A key present with an EMPTY list is legal and common for
species without family membership -- the two cases must never be collapsed.

Closely mirrors `family_propose/prompts.py`'s own shape (system prompt, schema, `build_context`,
`build_brief`, `entry_for`, validators) -- named by spec-signature-propose.md SS1 as this module's
own closest structural precedent, itself modelled on `adapters/effects/affix/prompts.py`. Three
differences beyond the anchor: (1) `motifsExpressed` reads the SPECIES' own motifs, not a family's;
(2) a THIRD schema field, `differentiator` -- a single enum string, not an array, and the ONE
judgement voted alongside `atomFamilies` (spec SS2 "Which fields are voted"); (3) a hard validator
this module alone has -- a draft whose `atomFamilies` (as a SET) exactly equals any of the brief's
own `familyActions` atom-family sets is rejected and the re-prompt names the colliding action
(spec's own most novel rule for this stage).
"""
from __future__ import annotations

import copy
from typing import Any, Mapping, Sequence

from ....pipeline.model import BLOCKED_FIELD
from ...creatures.anchor.permute import order_for

__all__ = [
    "SYSTEM_PROMPT", "SIGNATURE_ACTION_SCHEMA", "DIFFERENTIATOR_VALUES", "schema_for_call",
    "build_context", "build_brief", "entry_for",
    "atom_families_are_allowed", "atom_families_not_forbidden", "atom_families_differ_from_family",
    "motifs_expressed_are_known", "motifs_expressed_exclude_anti_motifs", "differentiator_is_known",
]

# ---------------------------------------------------------------------------------------------
# The system prompt --- one judgement, four negative clauses (spec SS2 "What the system prompt
# says"). Every clause is stated in the schema's own field descriptions too (F19's own reasoning,
# restated in `family_propose/prompts.py`: a description that lives only in prose beside a schema
# is a description the audit cannot read), but the model reads BOTH, and the two are meant to
# agree, never to say two different things.
# ---------------------------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You design the one action that makes a single creature unlike its siblings in the same "
    "family. You never write a number: not a rung, not a cost, not a duration, not a chance -- "
    "tables you never see decide every magnitude. You never repeat a family action -- the "
    "family's actions are listed for you to differ from, not to reuse or to re-skin with a new "
    "name. You never express an anti-motif, species or family. You never invent an atom family, "
    "a motif or a differentiator -- you pick from the lists given, or you set `blocked`."
)

# ---------------------------------------------------------------------------------------------
# The schema. Every `description` string below is copied byte-for-byte from spec-signature-propose
# .md SS2's own JSONC block (review F19, 2026-09-03) -- written there specifically so this build
# would not have to (re-)derive them, each modelled on the hardened `blocked` description at
# `adapters/creatures/anchor/prompts.py:74-82`.
#
# `atomFamilies.items.enum`, `motifsExpressed.items.enum` and `differentiator.enum` all ship EMPTY
# here on purpose: the real enums are filled at call time -- `atomFamilies` from the brief's own
# `allowedAtomFamilies`, `motifsExpressed` from `brief.anchor.motifs + "none"`, `differentiator`
# from the closed six-value axis vocabulary below -- each permuted per
# (briefId, fieldName, sampleIndex) -- `schema_for_call` below fills all three per call.
# `audit_schema(SIGNATURE_ACTION_SCHEMA)` (acceptance #1) therefore audits the SHAPE, never one
# call's own snapshot of a pool.
#
# `blocked` is a STRING here (the empty-string convention), matching `general_propose`'s and
# `family_propose`'s own `*_ACTION_SCHEMA` and NOT the boolean+`reason` pair `affix/prompts.py`'s
# own `AFFIX_SCHEMA` and `validate_heal/schemas.py`'s fixture use -- spec SS2 states it explicitly
# for this pipeline.
# ---------------------------------------------------------------------------------------------

#: The closed six-value differentiator axis vocabulary (spec SS2) -- "none" is a REAL, honest
#: answer, never counted against the candidate (spec SS2, acceptance #11b), not an omission.
DIFFERENTIATOR_VALUES: "tuple[str, ...]" = (
    "atoms", "targetShape", "condition", "timing", "resource", "none",
)

SIGNATURE_ACTION_SCHEMA: "dict[str, Any]" = {
    "type": "object",
    "properties": {
        "name": {
            "type": "string",
            "description": (
                "The action's display name as a player sees it — two to five words, in the "
                "game's voice, reading as THIS creature's own. Do NOT restate the atom family ids "
                "you picked, and do NOT reuse or re-skin the name of any family action listed "
                "above. It is NOT a sentence — no imperative verb, no trailing punctuation."
            ),
        },
        "flavor": {
            "type": "string",
            "description": (
                "One line a player would read under the name, under 140 characters, evoking what "
                "makes this one creature unlike its siblings. It is NOT a rules description: "
                "never say what the action does mechanically, and never write a number, a "
                "duration, a chance or a range — tables you never see decide all of those. It "
                "never expresses an anti-motif."
            ),
        },
        "atomFamilies": {
            "type": "array", "minItems": 1,
            "description": (
                "Which of the atom families listed above this action is built from — choose one "
                "or more from that list. You are choosing WHICH families, never HOW MUCH of any "
                "of them: this is NOT a place for a magnitude, a weight or a count. Do NOT invent "
                "a family that is not in the list, do NOT write a concrete atom id — a family "
                "names a pool, resolved later by code, per player — and do NOT pick exactly the "
                "same set as any family action listed above."
            ),
            "items": {"type": "string", "enum": []},
        },
        "motifsExpressed": {
            "type": "array", "minItems": 1,
            "description": (
                "Which of THIS species' motifs listed above this action actually expresses, "
                "chosen only from that list — or the single value \"none\" when it expresses "
                "none of them, which is a real and acceptable answer. This is NOT the anti-motif "
                "list: a motif named there is a refusal, and naming one here is a rejection, not "
                "an expression. Do NOT invent a motif and do NOT leave the key out — \"none\" is "
                "a value, a missing key is a defect."
            ),
            "items": {"type": "string", "enum": []},
        },
        "differentiator": {
            "type": "string",
            "description": (
                "The ONE axis on which this action differs from the family actions listed above. "
                "It is NOT the action's category, NOT its power level, and NOT how good it is. "
                "Choose \"none\" when it does not meaningfully differ — saying \"none\" honestly "
                "is better than inventing a difference, it is never counted against this answer, "
                "and it is more useful to us than a guess. Do NOT name more than one axis and do "
                "NOT invent an axis outside the list."
            ),
            "enum": [],
        },
        "rationale": {
            "type": "string",
            "description": (
                "One sentence saying why these atom families make this creature's signature "
                "action, and how it differs from its family's. It is NOT a restatement of the "
                "name or the flavour, and it is NOT a justification of any number — you never see "
                "a number. Do NOT use it to add an effect you did not put in `atomFamilies`."
            ),
        },
        BLOCKED_FIELD: {
            "type": "string",
            "description": (
                "Leave this as the exact empty string \"\" when you WERE able to design the "
                "action above — this is the normal case for almost every brief. Only write a "
                "non-empty reason here when the brief genuinely gives you NOTHING to work from "
                "(for example, no motifs AND no eligible atom families). Do NOT put a name, a "
                "motif, a differentiator or any other real answer here — it is a blocked-flag, "
                "not a second answer field. Having no family to differ from is NOT a blocked "
                "case: it is stated in the brief and you design the action anyway. This is NOT a "
                "boolean — never write the word \"true\" or \"false\" here; those are not the "
                "empty string and would be read as a genuine decline."
            ),
        },
    },
    "required": ["name", "flavor", "atomFamilies", "motifsExpressed",
                "differentiator", "rationale", BLOCKED_FIELD],
    "additionalProperties": False,
}


def schema_for_call(allowed_atom_families: Sequence[str], motifs_expressed_enum: Sequence[str],
                    differentiator_enum: Sequence[str]) -> "dict[str, Any]":
    """A per-call COPY of `SIGNATURE_ACTION_SCHEMA` with all THREE enums filled from one brief's
    own (already permuted) lists -- never mutates the shared constant, a `deepcopy` so two calls
    in the same process never alias each other's enum. Every enum is taken AS GIVEN -- it is
    `build_context`'s own job (tested separately) to guarantee `motifsExpressedEnum` always
    contains \"none\" and `differentiatorEnum` is always the full six-value vocabulary permuted,
    never this function's job to add either back in."""
    schema = copy.deepcopy(SIGNATURE_ACTION_SCHEMA)
    schema["properties"]["atomFamilies"]["items"]["enum"] = list(allowed_atom_families)
    schema["properties"]["motifsExpressed"]["items"]["enum"] = list(motifs_expressed_enum)
    schema["properties"]["differentiator"]["enum"] = list(differentiator_enum)
    return schema


# ---------------------------------------------------------------------------------------------
# What `build_context` reads off a brief, and the raises spec SS3 requires (AC5): a brief that is
# not `scope: "species"`, a brief missing the `familyActions` key A-S2 always supplies, or a brief
# missing a planner-owned slot field.
# ---------------------------------------------------------------------------------------------

#: A-S1's own species-scope anchor envelope (spec-distribution-planner.md SS3 step 2, measured
#: 2026-09-04 against every `scope: "species"` entry of `gk-data/packs/fusion/data/seed/actions/_briefs/round-1.json`):
#: `family` (nullable), `element`, `rarity`, `themeKey`, `motifs`, `antiMotifs` -- present as KEYS
#: on every species-scope brief, `family` legally `None` for a family-less species.
_REQUIRED_SPECIES_ANCHOR_KEYS: "tuple[str, ...]" = (
    "family", "element", "rarity", "themeKey", "motifs", "antiMotifs",
)

#: Group C, spec-distribution-planner.md's own brief envelope -- identical to
#: `general_propose/prompts.py`'s and `family_propose/prompts.py`'s own tuple; the planner-owned
#: mechanical slot is the same shape for every scope.
_REQUIRED_SLOT_FIELDS: "tuple[str, ...]" = ("category", "targetMode", "areaShape", "relation", "kind", "rungBand")

#: A-P3's own scope label. Rendered as a PLAIN LABEL, never the raw pair the model could copy into
#: its own answer as though it were a real magnitude. Identical convention to
#: `family_propose/prompts.py`'s own `_RUNG_BAND_LABELS`.
#:
#: ST3 (`spec-scope-window-tunables.md` contract 4): keyed by SCOPE, never by the window pair. The
#: pair form silently degraded on a retune -- a `[1,8]` species band (R7 fixes the signature window at
#: 1-10, but it is a tunable) would miss the `(1, 10)` key and render "a tier outside the three known
#: scope windows" into the prompt instead of the species label. Scope is a closed vocabulary
#: (`EligibilityScope`), so a direct index is the correct read: a missing entry is a code defect and
#: raises, and a retuned window changes nothing here. Byte-identical at the shipped windows.
_RUNG_BAND_LABELS: "dict[str, str]" = {
    "general": "an early tier, with few structural axes available",
    "family": "a mid tier, with several structural axes available",
    "species": "a late tier, with most structural axes available",
}


def _require_species_anchor(brief: Mapping[str, Any]) -> Mapping[str, Any]:
    """Spec SS0/SS3: this stage reads a SPECIES anchor, never a bare family or general brief. A
    brief whose own `scope` is not `\"species\"` belongs to a different pipeline entirely -- raised
    first, before the anchor object is even inspected, since a wrong-scope brief is simply not
    A-S1's real species-scope output at all (mirrors `family_propose/prompts.py`'s own
    `_require_family_anchor` ordering)."""
    scope = brief.get("scope")
    if scope != "species":
        raise ValueError(
            f"brief {brief.get('briefId', '?')!r} has scope={scope!r} -- signature-propose (A-P3) "
            f"reads a species-scope (signature) brief only (spec-signature-propose.md SS3); this "
            f"brief belongs to a different pipeline"
        )

    anchor = brief.get("anchor")
    if not isinstance(anchor, Mapping):
        raise ValueError(f"brief {brief.get('briefId', '?')!r} is missing its 'anchor' object")

    missing = [k for k in _REQUIRED_SPECIES_ANCHOR_KEYS if k not in anchor]
    if missing:
        raise ValueError(
            f"brief {brief.get('briefId', '?')!r} is missing species anchor key(s) {missing} -- "
            f"A-S1's own derivation owns these, never this stage's to invent or assume absent-"
            f"means-empty"
        )
    return anchor


def _require_family_actions(brief: Mapping[str, Any]) -> "list[dict]":
    """The absence-vs-empty rule spec SS3 states for THIS stage, and
    `brief_assembly.derive.require_family_actions` already states for its own producer side: a
    brief whose `familyActions` key is ABSENT raises -- A-S2 (`brief_assembly`) always supplies
    this key on every signature brief it assembles, so a missing key means something upstream is
    broken, never "this species has no family". A key present with an EMPTY list is legal and
    common for species without family membership -- collapsing the two is exactly how this
    stage could silently run before its family's P2 round is accepted (spec SS3)."""
    if "familyActions" not in brief:
        raise ValueError(
            f"brief {brief.get('briefId', '?')!r} is missing the required 'familyActions' key -- "
            f"A-S2 (brief-assembly) always supplies this key; its absence means this brief was "
            f"never really assembled by A-S2, and this stage must never run before that (spec-"
            f"signature-propose.md SS3: 'never run before its family's P2 round is accepted')"
        )
    family_actions = brief["familyActions"]
    if not isinstance(family_actions, list):
        raise ValueError(
            f"brief {brief.get('briefId', '?')!r}: 'familyActions' must be a list, got "
            f"{type(family_actions).__name__}"
        )
    return family_actions


def _require_slot(brief: Mapping[str, Any]) -> Mapping[str, Any]:
    slot = brief.get("slot")
    if not isinstance(slot, Mapping):
        raise ValueError(f"brief {brief.get('briefId', '?')!r} is missing its 'slot' object")
    missing = [f for f in _REQUIRED_SLOT_FIELDS if f not in slot]
    if missing:
        raise ValueError(
            f"brief {brief.get('briefId', '?')!r} is missing planner-owned slot field(s) "
            f"{missing} -- these are A-S1's to fix, never this stage's to invent"
        )
    return slot


def _rung_band_label(scope: Any) -> str:
    """ST3 (`spec-scope-window-tunables.md` contract 4): the label keys on the brief's SCOPE -- see
    `_RUNG_BAND_LABELS`. An unknown scope RAISES rather than rendering a fallback: a scope missing
    from a closed-vocabulary table is a code defect, and a fallback string is exactly what let a
    retuned window degrade every model-calling prompt silently."""
    if scope not in _RUNG_BAND_LABELS:
        raise ValueError(
            f"scope {scope!r} has no rung-band label -- the table must cover every scope the "
            f"planner emits (EligibilityScope: general, family, species)"
        )
    return _RUNG_BAND_LABELS[scope]


def build_context(brief: Mapping[str, Any], *, sample_index: int,
                  pairing_table: "Mapping[str, Sequence[str]] | None" = None,
                  family_glossary: "Mapping[str, str] | None" = None,
                  usage_weights: "Mapping[str, int] | None" = None) -> "dict[str, Any]":
    """Read-only inputs `build_brief` renders from and the validators check against -- exactly as
    `family_propose/prompts.py:254-315` does, so a validator always reads the SAME object the
    brief was rendered from. Raises per `_require_species_anchor`/`_require_family_actions`/
    `_require_slot` (acceptance #5) before reading anything else off `brief`.

    `family_glossary` (SMOKE BATCH criterion-2 fix, 2026-09-05): optional `id -> one-line gloss`
    mapping, identical contract to `general_propose/prompts.py`'s own parameter of the same name.

    `usage_weights` (roster-balance FC3, 2026-09-06): optional `id -> per-mille weight` mapping,
    identical contract to `general_propose/prompts.py`'s own parameter of the same name.

    `sample_index` is IN this call, never bolted on after (`adapters/creatures/anchor/permute.py`'s
    own module docstring) -- and it seeds THREE independent permutations here, one per enum field
    (`"atomFamilies"`, `"motifsExpressed"` and `"differentiator"`), so three votes over three
    identical orders is never possible for any of them."""
    anchor = _require_species_anchor(brief)
    family_actions = _require_family_actions(brief)
    slot = _require_slot(brief)

    brief_id = brief.get("briefId") or brief.get("id")
    if not brief_id:
        raise ValueError("brief is missing 'briefId'")

    pool = brief.get("pool") or {}
    allowed_raw = sorted(set(pool.get("allowedAtomFamilies") or ()))
    forbidden = sorted(set(pool.get("forbiddenAtomFamilies") or ()))
    permuted_allowed = list(order_for(brief_id, "atomFamilies", sample_index, allowed_raw))

    species_motifs = sorted(set(anchor.get("motifs") or ()))
    species_anti_motifs = sorted(set(anchor.get("antiMotifs") or ()))
    #: "none" is ALWAYS appended before permuting -- it is a real, legal answer (schema
    #: `minItems: 1` on `motifsExpressed`), never optional and never this stage's to omit even
    #: when `species_motifs` is empty (in which case the enum degenerates to exactly `["none"]`).
    motifs_enum = list(order_for(brief_id, "motifsExpressed", sample_index, species_motifs + ["none"]))

    #: The differentiator axis vocabulary is CLOSED and FIXED (spec SS2) -- never derived from the
    #: brief, unlike the other two enums; it is still permuted per (briefId, field, sampleIndex),
    #: same independent-seed discipline as the other two fields.
    differentiator_enum = list(
        order_for(brief_id, "differentiator", sample_index, list(DIFFERENTIATOR_VALUES))
    )

    #: `familyActions` arrives from A-S2 SORTED ordinally by `actionId` already
    #: (`brief_assembly.derive.index_accepted_family_actions`'s own guarantee) -- this stage never
    #: re-sorts it, only renders and validates it as given (a separate test asserts the ordering
    #: stays fixed through this stage, spec SS4).
    family_action_sets = tuple(
        frozenset(a.get("atomFamilies") or ()) for a in family_actions if isinstance(a, Mapping)
    )

    pairing = brief.get("pairing") or {}
    role = pairing.get("role", "none")
    paired_payoff_family = pairing.get("pairedPayoffFamily")

    context: "dict[str, Any]" = {
        "briefId": brief_id,
        "sampleIndex": sample_index,
        "speciesKey": brief.get("scopeKey"),
        "element": anchor.get("element"),
        "rarity": anchor.get("rarity"),
        "family": anchor.get("family"),
        "category": slot.get("category"),
        "targetMode": slot.get("targetMode"),
        "areaShape": slot.get("areaShape"),
        "relation": slot.get("relation"),
        "kind": slot.get("kind"),
        "rungBandLabel": _rung_band_label(brief.get("scope")),
        "allowedAtomFamilies": permuted_allowed,
        "forbiddenAtomFamilies": forbidden,
        "atomFamilyGlossary": dict(family_glossary) if family_glossary else {},
        "atomFamilyUsageWeights": dict(usage_weights) if usage_weights else {},
        "speciesAntiMotifs": species_anti_motifs,
        "motifsExpressedEnum": motifs_enum,
        "differentiatorEnum": differentiator_enum,
        "familyActions": list(family_actions),
        "familyActionAtomSets": family_action_sets,
        "pairingRole": role,
        "pairedPayoffFamily": paired_payoff_family,
        "avoidNeighbours": [
            n.get("fingerprint") for n in (brief.get("avoidNeighbours") or ())
            if isinstance(n, Mapping) and n.get("fingerprint")
        ],
    }
    if role == "payoff" and pairing_table and paired_payoff_family:
        allowed_set = set(permuted_allowed)
        context["enablerFamilies"] = sorted(
            f for f in pairing_table.get(paired_payoff_family, ()) if f in allowed_set
        )
    return context


def build_brief(context: Mapping[str, Any]) -> str:
    """Inlines literal values and CITES NO FILE -- the same discipline
    `family_propose/prompts.py:318-379` follows (itself stating `affix/prompts.py:60-61`'s own
    reason). The species key, element and rarity ARE meant to appear (this stage's own anchor,
    spec SS2 "What the brief inlines") -- nothing family-only shaped (a family MOTIF list, a
    family anti-motif) ever does, since this stage reads the species' own motifs, not the
    family's."""
    species_key = context["speciesKey"] or "unspecified"
    lines = [
        f"Design THE signature action for '{species_key}' (element: {context['element'] or 'unspecified'}, "
        f"rarity: {context['rarity'] or 'unspecified'}) -- what makes THIS ONE creature unlike its "
        "siblings in the same family.",
        "",
    ]

    motifs_only = [m for m in context["motifsExpressedEnum"] if m != "none"]
    if motifs_only:
        lines.append("This species' motifs, in permuted order: " + ", ".join(motifs_only))
    else:
        # Same absent-vs-empty discipline `family_propose/prompts.py` already applies to a
        # family's own derived motif list: an EMPTY motif list is a legal value, not a raise --
        # rendered as an explicit sentence, never a silently missing section.
        lines.append("This species has no motif -- every axis is open.")

    if context["speciesAntiMotifs"]:
        lines.append(
            "This species' anti-motifs -- an action expressing any of these is rejected:"
        )
        for motif in context["speciesAntiMotifs"]:
            lines.append(f"  - {motif}: an action expressing this is rejected.")

    #: spec SS2 "What the brief inlines": "its family's accepted actions ... under the heading
    #: 'your action must differ from every one of these' -- and, when the species has no family,
    #: the explicit sentence 'this creature has no family; there is nothing to differ from'
    #: rather than an empty section the model can read as an omission."
    family_actions = context["familyActions"]
    lines.append("")
    if family_actions:
        lines.append("Your action must differ from every one of these:")
        for action in family_actions:
            fams = ", ".join(sorted(action.get("atomFamilies") or ()))
            lines.append(f"  - {action.get('name')} [{fams}] (fingerprint: {action.get('fingerprint')})")
    elif context.get("family"):
        lines.append(
            "This creature belongs to a family, but that family has no accepted sibling actions "
            "in this round; do not treat the missing list as proof that it has no family."
        )
    else:
        lines.append("This creature has no family; there is nothing to differ from.")

    lines += [
        "",
        f"Category: {context['category'] or 'unspecified'}",
        f"Target mode: {context['targetMode'] or 'unspecified'}",
        f"Area shape: {context['areaShape'] or 'unspecified'}",
        f"Relation: {context['relation'] or 'unspecified'}",
        f"Kind: {context['kind'] or 'unspecified'}",
        f"Power tier: {context['rungBandLabel']}",
        "",
    ]
    glossary = context.get("atomFamilyGlossary") or {}
    usage_weights = context.get("atomFamilyUsageWeights") or {}
    if glossary or usage_weights:
        # SMOKE BATCH criterion-2 fix, 2026-09-05 -- identical technique to
        # `general_propose/prompts.py`'s own `_render_eligible_family_lines`, kept local per this
        # pipeline family's own self-containment discipline.
        # `usage_weights` (roster-balance FC3, 2026-09-06): same local-inlining discipline; the
        # cue never affects `allowedAtomFamilies` itself.
        from ..usage_direction.weights import render_cue
        lines.append(
            "Eligible atom families -- choose one or more from this list, in this order. Each is "
            "shown as `id: name [tag] -- what it does`, given only so you can judge which ids "
            "actually fit this creature; you must still answer with the id alone, never the name "
            "or the description text:"
        )
        for family_id in context["allowedAtomFamilies"]:
            gloss = glossary.get(family_id)
            line = f"  - {family_id}: {gloss}" if gloss else f"  - {family_id}"
            if usage_weights:
                cue = render_cue(family_id, usage_weights)
                if cue:
                    line += f" ({cue})"
            lines.append(line)
    else:
        lines.append(
            "Eligible atom families -- choose one or more from this list, in this order: "
            + ", ".join(context["allowedAtomFamilies"])
        )
    if context["forbiddenAtomFamilies"]:
        lines.append(
            "Forbidden atom families -- never pick any of these, they would make a knowingly "
            "additive pairing multiplicative instead: " + ", ".join(context["forbiddenAtomFamilies"])
        )
    role = context["pairingRole"]
    if role == "payoff":
        line = f"Pairing role: payoff for {context['pairedPayoffFamily']}."
        enablers = context.get("enablerFamilies") or []
        if enablers:
            line += " Its enabler families: " + ", ".join(enablers) + "."
        lines.append(line)
    elif role == "enabler":
        lines.append(f"Pairing role: enabler for {context['pairedPayoffFamily']}.")
    else:
        lines.append("Pairing role: none -- this action pairs with nothing.")
    if context["avoidNeighbours"]:
        lines.append(
            "Do not produce anything like these already-accepted actions (fingerprints): "
            + "; ".join(context["avoidNeighbours"])
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------------
# Validators -- same `(draft, context) -> list[str]` shape as `family_propose/prompts.py`'s own,
# plus `atom_families_differ_from_family` (this stage's own hard rule, mirroring
# `validate_heal/gates.py:132-140`'s A-P3 branch of `run_g2` almost verbatim -- the SAME rule
# enforced independently at THIS stage, since spec SS3 says this stage never grades itself but the
# spec's own SS4 test list still requires this validator to exist and reject HERE, at generation
# time, not only downstream at A-S4) and `differentiator_is_known`.
# ---------------------------------------------------------------------------------------------

def atom_families_are_allowed(draft: Mapping[str, Any], context: Mapping[str, Any]) -> "list[str]":
    """Every picked family must be one of THIS brief's own `allowedAtomFamilies` -- a model
    inventing a family outside the brief's own pool is exactly the fork spec SS3 ("never invent
    an atom family") exists to prevent."""
    allowed = set(context.get("allowedAtomFamilies") or ())
    picked = draft.get("atomFamilies") or []
    unknown = sorted(f for f in picked if f not in allowed)
    if unknown:
        return [
            f"atomFamilies {unknown} not in this brief's own allowedAtomFamilies {sorted(allowed)}"
        ]
    return []


def atom_families_not_forbidden(draft: Mapping[str, Any], context: Mapping[str, Any]) -> "list[str]":
    """A family the planner forbade for this brief (e.g. one half of a known multiplicative pair)
    is a defect even when it is also allowed elsewhere -- forbidden always wins."""
    forbidden = set(context.get("forbiddenAtomFamilies") or ())
    picked = draft.get("atomFamilies") or []
    hit = sorted(f for f in picked if f in forbidden)
    if hit:
        return [f"atomFamilies {hit} is in this brief's own forbiddenAtomFamilies"]
    return []


def atom_families_differ_from_family(draft: Mapping[str, Any], context: Mapping[str, Any]) -> "list[str]":
    """Spec's own most novel rule for this stage: a draft whose `atomFamilies` (as a SET) exactly
    equals any of the brief's own `familyActions` atom-family sets is a HARD reject, and the
    re-prompt NAMES the colliding action -- never merely advice in the system prompt. Mirrors
    `validate_heal/gates.py:132-140`'s identical A-P3 check, enforced independently here (this
    stage never grades itself, spec SS3, but still owns catching its own most obvious failure mode
    at generation time rather than leaving it entirely to a later stage)."""
    picked = draft.get("atomFamilies")
    if not isinstance(picked, list) or not picked:
        return []
    claimed = frozenset(picked)
    for action in context.get("familyActions") or ():
        if not isinstance(action, Mapping):
            continue
        if claimed == frozenset(action.get("atomFamilies") or ()):
            return [
                f"atomFamilies {sorted(claimed)} exactly equals family action "
                f"{action.get('name')!r} ({action.get('actionId')!r})'s own atomFamilies set -- "
                f"not a signature differentiation"
            ]
    return []


def motifs_expressed_are_known(draft: Mapping[str, Any], context: Mapping[str, Any]) -> "list[str]":
    """Every picked motif must be one of THIS brief's own `motifsExpressedEnum` (the species' own
    derived motifs plus `"none"`) -- a model inventing a motif, or naming a family-specific one,
    is exactly what spec SS3 ("never invent a motif") exists to prevent."""
    known = set(context.get("motifsExpressedEnum") or ())
    picked = draft.get("motifsExpressed") or []
    unknown = sorted(m for m in picked if m not in known)
    if unknown:
        return [f"motifsExpressed {unknown} not in this brief's own motif list {sorted(known)}"]
    return []


def motifs_expressed_exclude_anti_motifs(draft: Mapping[str, Any],
                                         context: Mapping[str, Any]) -> "list[str]":
    """A motif named in `motifsExpressed` that is also one of this SPECIES' anti-motifs is a hard
    defect, not merely an unknown value -- spec SS2's own description text: "naming one here is a
    rejection, not an expression." The enum itself never OFFERS an anti-motif as a choice, but a
    self-healing model's free-text repair can still write one, so this is checked independently
    of `motifs_expressed_are_known` (spec SS4's own named planted-violation case: "a draft
    expressing a species anti-motif -> hard reject, re-prompt names it")."""
    anti = set(context.get("speciesAntiMotifs") or ())
    picked = draft.get("motifsExpressed") or []
    hit = sorted(m for m in picked if m in anti)
    if hit:
        return [f"motifsExpressed {hit} names this species' own anti-motif(s) -- a rejection, not an expression"]
    return []


def differentiator_is_known(draft: Mapping[str, Any], context: Mapping[str, Any]) -> "list[str]":
    """`differentiator` must be one of THIS brief's own permuted `differentiatorEnum` -- a model
    inventing an axis outside the closed six-value vocabulary is exactly what spec SS2 ("do NOT
    invent an axis outside the list") exists to prevent. `"none"` is always a member and is never
    treated any differently here -- it is a normal, legal value like any other (acceptance #11b).
    A `None`/missing value is ALSO rejected here (never silently exempted) -- `known` never
    contains `None`, so a caller that lost the key between construction and validation (rather
    than never having it at all, which `build_verify_fn`'s own required-key loop already flags
    separately) still gets a named defect, not a silent pass."""
    known = set(context.get("differentiatorEnum") or ())
    value = draft.get("differentiator")
    if value not in known:
        return [f"differentiator {value!r} not in this brief's own differentiator list {sorted(known)}"]
    return []


def entry_for(draft: Mapping[str, Any], *, candidate_id: str, brief_id: str,
              provenance: "Mapping[str, Any] | None" = None) -> "dict[str, Any]":
    """The candidate's own action-shaped payload -- NOT a committed seed entry (spec SS3: "Never
    write into `gk-data/packs/fusion/data/seed/actions/`. Acceptance is A-S3's; persistence is A-S6's."). `candidate_id`
    is a scratch identifier for this run, never a minted `action.species.NNNN` id -- those are
    assigned downstream, after acceptance. Also NEVER a promotion to `Innate` -- that is A-S6's
    job alone, model-free permanently (spec SS3), and nothing in this module ever reads or writes
    an innate flag."""
    motifs = draft.get("motifsExpressed")
    entry: "dict[str, Any]" = {
        "candidateId": candidate_id,
        "briefId": brief_id,
        "scope": "species",
        "name": draft["name"],
        "flavor": draft["flavor"],
        "atomFamilies": list(draft["atomFamilies"]),
        "motifsExpressed": list(motifs) if isinstance(motifs, list) else motifs,
        "differentiator": draft.get("differentiator"),
        "rationale": draft["rationale"],
    }
    if provenance:
        entry["_provenance"] = dict(provenance)
    return entry
