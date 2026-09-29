"""seedsmith.adapters.actions.family_propose.prompts --- A-P2 "family-propose"'s own domain
knowledge (spec-family-propose.md SS2, action-corpus module). The model authors ONE action that
expresses a whole FAMILY of creatures: a name, a flavour line, which atom FAMILIES it is built
from, and which of the family's own motifs it expresses. Every magnitude of any kind -- rung,
cost, cooldown, duration, chance, weight, tier, stack count -- is a table's job, never the
model's (P1, restated for this content type; see also `general_propose/prompts.py`'s own
identical opening paragraph).

**A-P2 reads exactly one anchor shape: a FAMILY.** Never a species, never an element, never a
per-species motif (spec SS0/SS3, "it never sees a species... that second job belongs to A-P3").
`build_context` RAISES the moment a brief carries real species-scoped anchor content rather than
silently ignoring it -- silently accepting one is exactly how "family" quietly becomes
"signature" (spec SS3). This is the MIRROR of A-P1's own `_assert_no_anchor`
(`general_propose/prompts.py:174-197`): A-P1 must see NO anchor at all and raises on any content;
A-P2 must see a FAMILY anchor specifically and raises on species-shaped content instead.

Closely mirrors `general_propose/prompts.py`'s own shape (system prompt, schema, `build_context`,
`build_brief`, `entry_for`, validators) -- named by spec-family-propose.md SS1 as this module's
own closest structural precedent, itself modelled on `adapters/effects/affix/prompts.py`. Two
differences beyond the anchor: (1) `motifsExpressed` is a SECOND schema field with its own
permuted enum (`brief.anchor.familyMotifs + "none"`), and (2) it is deliberately NOT voted (spec
SS2 "Which fields are voted") -- only `atomFamilies` is.
"""
from __future__ import annotations

import copy
from typing import Any, Mapping, Sequence

from ....pipeline.model import BLOCKED_FIELD
from ...creatures.anchor.permute import order_for

__all__ = [
    "SYSTEM_PROMPT", "FAMILY_ACTION_SCHEMA", "schema_for_call",
    "build_context", "build_brief", "entry_for",
    "atom_families_are_allowed", "atom_families_not_forbidden",
    "motifs_expressed_are_known", "motifs_expressed_exclude_anti_motifs",
]

# ---------------------------------------------------------------------------------------------
# The system prompt --- one judgement, four negative clauses (spec SS2 "What the system prompt
# says"). Every clause is stated in the schema's own field descriptions too (F19's own reasoning,
# restated in `general_propose/prompts.py`: a description that lives only in prose beside a
# schema is a description the audit cannot read), but the model reads BOTH, and the two are meant
# to agree, never to say two different things.
# ---------------------------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You design an action that expresses one family of creatures -- what makes the WHOLE family "
    "recognisable, not what makes one member special. You never write a number: not a rung, not "
    "a cost, not a duration, not a chance -- tables you never see decide every magnitude. You "
    "never name a single species -- this action belongs to every member of the family; if it "
    "only makes sense for one of them, it is the wrong pipeline's job. You never express an "
    "anti-motif -- the anti-motif list is what this family must NOT be, not a hint. You never "
    "invent an atom family or a motif -- you pick from the lists given, or you set `blocked`."
)

# ---------------------------------------------------------------------------------------------
# The schema. Every `description` string below is copied byte-for-byte from spec-family-propose
# .md SS2's own JSONC block (review F19, 2026-09-03) -- written there specifically so this build
# would not have to (re-)derive them, each modelled on the hardened `blocked` description at
# `adapters/creatures/anchor/prompts.py:74-82`.
#
# Both `atomFamilies.items.enum` and `motifsExpressed.items.enum` ship EMPTY here on purpose: the
# real enums are filled at call time -- `atomFamilies` from the brief's own `allowedAtomFamilies`,
# `motifsExpressed` from `brief.anchor.familyMotifs + "none"` -- each permuted per
# (briefId, fieldName, sampleIndex) -- `schema_for_call` below fills both per call.
# `audit_schema(FAMILY_ACTION_SCHEMA)` (acceptance #1) therefore audits the SHAPE, never one
# call's own snapshot of a pool.
#
# `blocked` is a STRING here (the empty-string convention), matching `general_propose`'s own
# `GENERAL_ACTION_SCHEMA` and NOT the boolean+`reason` pair `affix/prompts.py`'s own `AFFIX_SCHEMA`
# and `validate_heal/schemas.py`'s fixture use -- spec SS2 states it explicitly for this pipeline.
# ---------------------------------------------------------------------------------------------

FAMILY_ACTION_SCHEMA: "dict[str, Any]" = {
    "type": "object",
    "properties": {
        "name": {
            "type": "string",
            "description": (
                "The action's display name as a player sees it — two to five words, in the "
                "game's voice, reading as something the WHOLE family would use. Do NOT restate "
                "the atom family ids you picked, and do NOT name a single species: if the name "
                "only makes sense for one member, it belongs to a different pipeline. It is NOT "
                "a sentence — no imperative verb, no trailing punctuation."
            ),
        },
        "flavor": {
            "type": "string",
            "description": (
                "One line a player would read under the name, under 140 characters, evoking what "
                "this family is like. It is NOT a rules description: never say what the action "
                "does mechanically, and never write a number, a duration, a chance or a range — "
                "tables you never see decide all of those. It never names one species and never "
                "expresses an anti-motif."
            ),
        },
        "atomFamilies": {
            "type": "array", "minItems": 1,
            "description": (
                "Which of the atom families listed above this action is built from — choose one "
                "or more from that list. You are choosing WHICH families, never HOW MUCH of any "
                "of them: this is NOT a place for a magnitude, a weight or a count. Do NOT invent "
                "a family that is not in the list, and do NOT write a concrete atom id — a family "
                "names a pool, and which member of the pool a player gets is decided later, by "
                "code, per player."
            ),
            "items": {"type": "string", "enum": []},
        },
        "motifsExpressed": {
            "type": "array", "minItems": 1,
            "description": (
                "Which of the FAMILY motifs listed above this action actually expresses, chosen "
                "only from that list — or the single value \"none\" when it expresses none of "
                "them, which is a real and acceptable answer. This is NOT the anti-motif list: a "
                "motif named there is a refusal, and naming one here is a rejection, not an "
                "expression. Do NOT invent a motif, do NOT name a species-specific one, and do "
                "NOT leave the key out — \"none\" is a value, a missing key is a defect."
            ),
            "items": {"type": "string", "enum": []},
        },
        "rationale": {
            "type": "string",
            "description": (
                "One sentence saying why these atom families express this family. It is NOT a "
                "restatement of the name or the flavour, and it is NOT a justification of any "
                "number — you never see a number. Do NOT use it to add an effect you did not put "
                "in `atomFamilies`, and do NOT use it to single out one member of the family."
            ),
        },
        BLOCKED_FIELD: {
            "type": "string",
            "description": (
                "Leave this as the exact empty string \"\" when you WERE able to design the "
                "action above — this is the normal case for almost every brief. Only write a "
                "non-empty reason here when the brief genuinely gives you NOTHING to work from "
                "(for example, a family with an empty motif list AND an empty list of eligible "
                "atom families). Do NOT put a name, a motif, a family id or any other real answer "
                "here — it is a blocked-flag, not a second answer field. This is NOT a boolean — "
                "never write the word \"true\" or \"false\" here; those are not the empty string "
                "and would be read as a genuine decline."
            ),
        },
    },
    "required": ["name", "flavor", "atomFamilies", "motifsExpressed", "rationale", BLOCKED_FIELD],
    "additionalProperties": False,
}


def schema_for_call(allowed_atom_families: Sequence[str],
                    motifs_expressed_enum: Sequence[str]) -> "dict[str, Any]":
    """A per-call COPY of `FAMILY_ACTION_SCHEMA` with BOTH enums filled from one brief's own
    (already permuted) lists -- never mutates the shared constant, a `deepcopy` so two calls in
    the same process never alias each other's enum. `motifs_expressed_enum` is taken AS GIVEN --
    it is `build_context`'s own `motifsExpressedEnum` (tested separately) that guarantees "none"
    is always present, never this function's job to add it back in."""
    schema = copy.deepcopy(FAMILY_ACTION_SCHEMA)
    schema["properties"]["atomFamilies"]["items"]["enum"] = list(allowed_atom_families)
    schema["properties"]["motifsExpressed"]["items"]["enum"] = list(motifs_expressed_enum)
    return schema


# ---------------------------------------------------------------------------------------------
# What `build_context` reads off a brief, and the two raises spec SS3 requires (AC5): a brief
# missing the family-motif DERIVATION keys A-S1 owns, or carrying species-scoped anchor content;
# plus the shared missing-planner-slot raise A-P1 already established.
# ---------------------------------------------------------------------------------------------

#: Group B, spec-distribution-planner.md SS3 step 2b's own family envelope -- present as KEYS on
#: every `family`-scoped brief A-S1 emits (measured 2026-09-04 against
#: `gk-data/packs/fusion/data/seed/actions/_briefs/round-1.json`, all 19 family entries). A brief whose `anchor`
#: carries this key ABSENT is a real A-S1 defect and raises (spec SS5 acceptance #5); a key
#: present with an EMPTY list is legal (F15's own correction) -- see `_require_family_anchor`.
_REQUIRED_FAMILY_DERIVATION_KEYS: "tuple[str, ...]" = (
    "familyMotifs", "familyAntiMotifs", "familyMotifBasis",
)

#: The species-scoped signals spec SS3 names explicitly: "a brief carrying `anchor.speciesKey`,
#: species motifs or an element token raises." `distribution_planner/derive.py:490-513`'s own
#: `brief_anchor` shows the real schema has no field literally called `speciesKey` -- `themeKey`
#: (e.g. `"creature.cherrybomb"`) is the real analog, populated ONLY for `species` scope and always
#: `None` for `family`/`general` scope, exactly mirroring how `anchor.motifs`/`anchor.element` are
#: populated only for species. `speciesKey` itself is still checked below, defensively, in case a
#: future schema revision adds it literally -- it can never fire against today's real data, but a
#: synthetic brief that sets it must still raise (spec's own literal wording).
_FORBIDDEN_SPECIES_ANCHOR_KEYS: "tuple[str, ...]" = ("speciesKey", "element", "motifs", "themeKey")

#: Group C, spec-distribution-planner.md's own brief envelope -- identical to
#: `general_propose/prompts.py`'s own tuple; the planner-owned mechanical slot is the same shape
#: for every scope.
_REQUIRED_SLOT_FIELDS: "tuple[str, ...]" = ("category", "targetMode", "areaShape", "relation", "kind", "rungBand")

#: A-P2's own scope label. Rendered as a PLAIN LABEL, never the raw pair the model could copy into
#: its own answer as though it were a real magnitude. Identical convention to
#: `general_propose/prompts.py`'s own `_RUNG_BAND_LABELS`.
#:
#: ST3 (`spec-scope-window-tunables.md` contract 4): keyed by SCOPE, never by the window pair. The
#: pair form silently degraded on a retune -- a `[1,6]` family band missed the `(1, 7)` key and
#: rendered "a tier outside the three known scope windows" into the prompt instead of the family
#: label. Scope is a closed vocabulary (`EligibilityScope`), so a direct index is the correct read:
#: a missing entry is a code defect and raises, and a retuned window changes nothing here. The
#: rendered text is byte-identical at the shipped windows.
_RUNG_BAND_LABELS: "dict[str, str]" = {
    "general": "an early tier, with few structural axes available",
    "family": "a mid tier, with several structural axes available",
    "species": "a late tier, with most structural axes available",
}


def _require_family_anchor(brief: Mapping[str, Any]) -> Mapping[str, Any]:
    """Spec SS3: "Never read a species anchor. A brief carrying `anchor.speciesKey`, species
    motifs or an element raises." and spec SS5 acceptance #5: "A brief whose
    `anchor.familyMotifs`, `anchor.familyAntiMotifs` or `anchor.familyMotifBasis` key is absent
    raises; a key present with an empty list is legal." Both checks live here, in this order --
    absence of the DERIVATION this stage depends on is checked first, since a brief that fails
    that check is simply not A-S1's real family-scope output at all."""
    anchor = brief.get("anchor")
    if not isinstance(anchor, Mapping):
        raise ValueError(f"brief {brief.get('briefId', '?')!r} is missing its 'anchor' object")

    missing = [k for k in _REQUIRED_FAMILY_DERIVATION_KEYS if k not in anchor]
    if missing:
        raise ValueError(
            f"brief {brief.get('briefId', '?')!r} is missing family-motif derivation key(s) "
            f"{missing} -- A-S1's own derivation (spec-distribution-planner.md SS3 step 2b) owns "
            f"these, never this stage's to invent or assume absent-means-empty"
        )

    for key in _FORBIDDEN_SPECIES_ANCHOR_KEYS:
        value = anchor.get(key)
        if value:
            raise ValueError(
                f"brief {brief.get('briefId', '?')!r} carries species-scoped anchor content "
                f"(anchor.{key}={value!r}) -- family-propose (A-P2) reads a family anchor only "
                f"(spec-family-propose.md SS3); this brief belongs to A-P3 (signature-propose), "
                f"not this one"
            )
    return anchor


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
    `general_propose/prompts.py:220-269` does, so a validator always reads the SAME object the
    brief was rendered from. Raises per `_require_family_anchor`/`_require_slot` (acceptance #5)
    before reading anything else off `brief`.

    `sample_index` is IN this call, never bolted on after (`adapters/creatures/anchor/permute.py`'s
    own module docstring) -- and it seeds TWO independent permutations here, one per enum field
    (`"atomFamilies"` and `"motifsExpressed"`), so three votes over three identical orders is
    never possible for either.

    `family_glossary` (SMOKE BATCH criterion-2 fix, 2026-09-05): optional `id -> one-line gloss`
    mapping, identical contract to `general_propose/prompts.py:222-...`'s own parameter of the same
    name -- see that docstring for the full real-call evidence.

    `usage_weights` (roster-balance FC3, 2026-09-06): optional `id -> per-mille weight` mapping,
    identical contract to `general_propose/prompts.py`'s own parameter of the same name -- omitted
    or empty, output is byte-identical to before this parameter existed."""
    anchor = _require_family_anchor(brief)
    slot = _require_slot(brief)

    brief_id = brief.get("briefId") or brief.get("id")
    if not brief_id:
        raise ValueError("brief is missing 'briefId'")

    pool = brief.get("pool") or {}
    allowed_raw = sorted(set(pool.get("allowedAtomFamilies") or ()))
    forbidden = sorted(set(pool.get("forbiddenAtomFamilies") or ()))
    permuted_allowed = list(order_for(brief_id, "atomFamilies", sample_index, allowed_raw))

    family_motifs = sorted(set(anchor.get("familyMotifs") or ()))
    family_anti_motifs = sorted(set(anchor.get("familyAntiMotifs") or ()))
    #: "none" is ALWAYS appended before permuting -- it is a real, legal answer (schema
    #: `minItems: 1` on `motifsExpressed`), never optional and never this stage's to omit even
    #: when `family_motifs` is empty (in which case the enum degenerates to exactly `["none"]`).
    motifs_enum = list(order_for(brief_id, "motifsExpressed", sample_index, family_motifs + ["none"]))

    pairing = brief.get("pairing") or {}
    role = pairing.get("role", "none")
    paired_payoff_family = pairing.get("pairedPayoffFamily")

    context: "dict[str, Any]" = {
        "briefId": brief_id,
        "sampleIndex": sample_index,
        "familyId": anchor.get("family"),
        "familyMotifBasis": anchor.get("familyMotifBasis"),
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
        "familyAntiMotifs": family_anti_motifs,
        "motifsExpressedEnum": motifs_enum,
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
    `general_propose/prompts.py:272-312` follows (itself stating `affix/prompts.py:60-61`'s own
    reason). The family id IS meant to appear (it is this stage's own anchor, spec SS0); nothing
    species-shaped ever does -- no element, no `themeKey`, no per-species motif (acceptance #4)."""
    family_label = context["familyId"] or "unspecified"
    lines = [
        f"Design ONE family action: something the WHOLE family '{family_label}' would use. It "
        "belongs to every member of the family, never a single species -- that is a different "
        "pipeline's job.",
        "",
    ]

    motifs_only = [m for m in context["motifsExpressedEnum"] if m != "none"]
    if motifs_only:
        lines.append("This family's shared motifs, in permuted order: " + ", ".join(motifs_only))
    else:
        # F15's own correction (acceptance #5): an EMPTY derived motif list is a legal value, not
        # a raise -- rendered as an explicit sentence, never a silently missing section.
        lines.append("This family has no shared motif -- every member differs on this axis.")

    if context["familyAntiMotifs"]:
        lines.append(
            "This family's anti-motifs -- an action expressing any of these is rejected:"
        )
        for motif in context["familyAntiMotifs"]:
            lines.append(f"  - {motif}: an action expressing this is rejected.")

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
        # program's own self-containment discipline (see `derive.py`'s `canonical_family_key`
        # docstring for the identical reasoning applied elsewhere in this pipeline family).
        # `usage_weights` (roster-balance FC3, 2026-09-06): same local-inlining discipline, the
        # cue never affects `allowedAtomFamilies` itself -- only how a member is described.
        from ..usage_direction.weights import render_cue
        lines.append(
            "Eligible atom families -- choose one or more from this list, in this order. Each is "
            "shown as `id: name [tag] -- what it does`, given only so you can judge which ids "
            "actually fit this family; you must still answer with the id alone, never the name or "
            "the description text:"
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
# Validators -- same `(draft, context) -> list[str]` shape as `general_propose/prompts.py`'s own
# `atom_families_are_allowed`/`atom_families_not_forbidden`, plus two more for the field this
# module alone has: `motifsExpressed`. Deliberately narrow, same reasoning as A-P1: whether a
# draft's NAME/RATIONALE leaks a species token is A-S4's own gate, not this module's
# (spec SS3: "never grades itself") -- this checks only what it alone can know, against THIS
# brief's own lists.
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


def motifs_expressed_are_known(draft: Mapping[str, Any], context: Mapping[str, Any]) -> "list[str]":
    """Every picked motif must be one of THIS brief's own `motifsExpressedEnum` (the family's own
    derived motifs plus `"none"`) -- a model inventing a motif, or naming a species-specific one,
    is exactly what spec SS3 ("never invent a motif") exists to prevent."""
    known = set(context.get("motifsExpressedEnum") or ())
    picked = draft.get("motifsExpressed") or []
    unknown = sorted(m for m in picked if m not in known)
    if unknown:
        return [f"motifsExpressed {unknown} not in this brief's own motif list {sorted(known)}"]
    return []


def motifs_expressed_exclude_anti_motifs(draft: Mapping[str, Any],
                                         context: Mapping[str, Any]) -> "list[str]":
    """A motif named in `motifsExpressed` that is also one of this family's ANTI-motifs is a hard
    defect, not merely an unknown value -- spec SS2's own description text: "naming one here is a
    rejection, not an expression." The enum itself never OFFERS an anti-motif as a choice, but a
    self-healing model's free-text repair can still write one, so this is checked independently
    of `motifs_expressed_are_known` (spec SS4.3's own named planted-violation case)."""
    anti = set(context.get("familyAntiMotifs") or ())
    picked = draft.get("motifsExpressed") or []
    hit = sorted(m for m in picked if m in anti)
    if hit:
        return [f"motifsExpressed {hit} names this family's own anti-motif(s) -- a rejection, not an expression"]
    return []


def entry_for(draft: Mapping[str, Any], *, candidate_id: str, brief_id: str,
              provenance: "Mapping[str, Any] | None" = None) -> "dict[str, Any]":
    """The candidate's own action-shaped payload -- NOT a committed seed entry (spec SS3: "Never
    write into `gk-data/packs/fusion/data/seed/actions/`. Acceptance is A-S3's; persistence is A-S6's."). `candidate_id`
    is a scratch identifier for this run, never a minted `action.family.NNNN` id -- those are
    assigned downstream, after acceptance."""
    motifs = draft.get("motifsExpressed")
    entry: "dict[str, Any]" = {
        "candidateId": candidate_id,
        "briefId": brief_id,
        "scope": "family",
        "name": draft["name"],
        "flavor": draft["flavor"],
        "atomFamilies": list(draft["atomFamilies"]),
        "motifsExpressed": list(motifs) if isinstance(motifs, list) else motifs,
        "rationale": draft["rationale"],
    }
    if provenance:
        entry["_provenance"] = dict(provenance)
    return entry
