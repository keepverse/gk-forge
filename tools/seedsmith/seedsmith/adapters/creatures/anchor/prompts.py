"""The eight `classify-pipelines` prompt bodies (creature-seed module 7, spec-classify-pipelines.md).

**One shared judgement per pipeline** (§1) — not one attribute per pipeline. Every brief passes the
captured lore VERBATIM (Chinese, untranslated, §5) and **never a raw magnitude** (`hp`/`attack`/
`armor`) — seedsmith's founding P1 rule: a model has no calibrated sense of scale.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .schema import (
    ACQUISITION,
    APTITUDES,
    ATTACK_TEMPO,
    BASIS,
    DEPLOY_MODE,
    ELEMENTS,
    RARITY,
    REACH,
    RESOURCES,
    TARGET_PREFERENCE,
    THREAT_BAND,
    VARIANTS,
)


@dataclass(frozen=True)
class SpeciesLore:
    """Everything a classification pipeline may read — never `hp`/`attack`/`armor`."""

    species_id: str
    side: str
    display_name: "str | None"
    flavor_info: "str | None"
    flavor_introduce: "str | None"
    enrichment: "dict[str, Any] | None" = None


def _lore_block(lore: SpeciesLore) -> str:
    lines = [
        f"Side: {lore.side}",
        f"Name: {lore.display_name or '(unnamed)'}",
        f"Description: {lore.flavor_info or '(none captured)'}",
    ]
    if lore.flavor_introduce:
        lines.append(f"Introduction: {lore.flavor_introduce}")
    if lore.enrichment:
        e = lore.enrichment
        if e.get("typeClass"):
            lines.append(f"Type class: {e['typeClass']}")
        if e.get("description"):
            lines.append(f"Extra description: {e['description']}")
        if e.get("weaknessesText"):
            lines.append(f"Weaknesses: {e['weaknessesText']}")
        if e.get("qualities"):
            lines.append(f"Qualities: {', '.join(e['qualities'])}")
    return "\n".join(lines)


def _blocked_variant(schema: dict) -> dict:
    """Every pipeline schema carries a `blocked` escape (pipeline/model.py's guardrail #6) — a
    model that cannot judge must be able to say so with a reason, rather than inventing one.

    **Real-call finding, 2026-09-01 (T2.3 verification):** the first-draft description ("a reason
    this cannot be judged, or empty string if not blocked") let a real local model fill this field
    with something plausible-but-wrong ("plant", echoing the species' `side`) rather than leaving
    it empty for an unblocked answer — it never understood empty string as the "not blocked"
    signal. The description below states that explicitly, with a worked example of each case,
    matching anchor-contract's own negative-clause discipline (spec-anchor-contract.md §5).
    """
    props = dict(schema["properties"])
    props["blocked"] = {
        "type": "string",
        "description": (
            "Leave this as the exact empty string \"\" when you WERE able to judge the other "
            "field(s) above — this is the normal case for almost every species. Only write a "
            "non-empty reason here when the lore genuinely gives you NOTHING to judge from (e.g. "
            "a name with no description at all). Do NOT put a side, a category, or any other real "
            "answer here — it is a blocked-flag, not a second answer field."
        ),
    }
    return {**schema, "properties": props, "required": list(schema["required"]) + ["blocked"]}


@dataclass(frozen=True)
class PipelineSpec:
    id: str
    attributes: "tuple[str, ...]"
    judgement: str          # the one-sentence judgement this pipeline makes
    system_prompt: str
    schema: dict
    build_brief: "Any"      # Callable[[SpeciesLore, dict], str] — dict is already-decided context


# --- 1. element-primary -----------------------------------------------------------------------

def _brief_element_primary(lore: SpeciesLore, context: dict) -> str:
    return (
        "Judge this creature's ELEMENT: what is it made of, or aligned with? Not what beats it, "
        "not what it resists — its own dominant nature.\n\n" + _lore_block(lore)
        + f"\n\nChoose one: {', '.join(context.get('order', ELEMENTS))}."
    )


ELEMENT_PRIMARY = PipelineSpec(
    id="element-primary",
    attributes=("elementPrimary",),
    judgement="what is this creature made of / aligned with?",
    system_prompt=(
        "You classify a creature's dominant combat element from its captured lore. Read the "
        "description and pick the element its own identity and attacks lean on — NOT the element "
        "that would be strong against it, and NOT a resistance. Answer with exactly one element id.\n\n"
        "Being 'undead' or a 'zombie' is a CATEGORY, not an element — do not default to 'dark' just "
        "because a creature is undead. Judge its own concrete traits instead: an undead creature "
        "whose lore is genuinely about decay, shadow, necromancy, or death magic is dark; an undead "
        "creature who is otherwise mundane — an athlete, a worker, someone using an ordinary tool or "
        "vehicle, with no occult theming of its own — is not, and should be judged the same way a "
        "living creature with those same traits would be (e.g. 'earth' for a physical, grounded "
        "combatant). Audited 2026-09-03: a 28-species sample classified 9 of 12 zombies as dark — a "
        "real, checkable pattern worth resisting, not a rule to reverse into some other default."
    ),
    schema=_blocked_variant({
        "type": "object",
        "properties": {"elementPrimary": {"type": "string", "enum": list(ELEMENTS)}},
        "required": ["elementPrimary"],
        "additionalProperties": False,
    }),
    build_brief=_brief_element_primary,
)


# --- 2. element-secondary ----------------------------------------------------------------------

def _brief_element_secondary(lore: SpeciesLore, context: dict) -> str:
    primary = context.get("elementPrimary", "?")
    return (
        f"This creature's primary element is already decided: {primary}. Judge whether it has a "
        f"REAL second nature — a genuine secondary element its lore actually supports — or whether "
        f"it is 'pure' (single-element). 'none' is a complete, correct answer for most creatures; "
        f"do not invent a secondary just because the field exists.\n\n" + _lore_block(lore)
        + f"\n\nChoose one: {', '.join(context.get('order', ELEMENTS))}, or 'none'."
    )


ELEMENT_SECONDARY = PipelineSpec(
    id="element-secondary",
    attributes=("elementSecondary",),
    judgement="is there a real second nature, or is this pure?",
    system_prompt=(
        "You judge whether a creature has a genuine secondary element beyond its already-decided "
        "primary. Most creatures are pure (secondary = 'none'). Only name a secondary element if "
        "the lore actually supports a second, distinct nature — never to fill the field."
    ),
    schema=_blocked_variant({
        "type": "object",
        "properties": {"elementSecondary": {"type": "string", "enum": list(ELEMENTS) + ["none"]}},
        "required": ["elementSecondary"],
        "additionalProperties": False,
    }),
    build_brief=_brief_element_secondary,
)


# --- 3. aptitude-primary -----------------------------------------------------------------------

def _brief_aptitude_primary(lore: SpeciesLore, context: dict) -> str:
    return (
        "Judge this creature's COMBAT ROLE: what is it good at? This is a fighting style "
        "(offence, mitigation, evasion, control, ...), NOT an element and NOT a measure of raw "
        "power — a fragile, fast creature can still be Agility even if its hits are weak, because "
        "Agility is about evasion, not damage output.\n\n" + _lore_block(lore)
        + f"\n\nChoose one: {', '.join(context.get('order', APTITUDES))}."
    )


APTITUDE_PRIMARY = PipelineSpec(
    id="aptitude-primary",
    attributes=("aptitudePrimary",),
    judgement="what is it good at?",
    system_prompt=(
        "You classify a creature's dominant combat aptitude — its fighting role — from its "
        "captured lore. The twelve aptitudes are combat roles (offence, mitigation, evasion, "
        "guard, control, ...), never elements and never a power ranking."
    ),
    schema=_blocked_variant({
        "type": "object",
        "properties": {"aptitudePrimary": {"type": "string", "enum": list(APTITUDES)}},
        "required": ["aptitudePrimary"],
        "additionalProperties": False,
    }),
    build_brief=_brief_aptitude_primary,
)


# --- 4. aptitude-secondary ---------------------------------------------------------------------

def _brief_aptitude_secondary(lore: SpeciesLore, context: dict) -> str:
    primary = context.get("aptitudePrimary", "?")
    return (
        f"This creature's primary aptitude is already decided: {primary}. Judge whether it has a "
        f"real SECONDARY strength its lore supports, or 'none'. This is NOT a ranking of "
        f"importance versus the primary — most creatures legitimately have none.\n\n"
        + _lore_block(lore)
        + f"\n\nChoose one: {', '.join(context.get('order', APTITUDES))}, or 'none'."
    )


APTITUDE_SECONDARY = PipelineSpec(
    id="aptitude-secondary",
    attributes=("aptitudeSecondary",),
    judgement="what is its supporting strength, if any?",
    system_prompt=(
        "You judge whether a creature has a genuine secondary combat aptitude beyond its "
        "already-decided primary. Most creatures are singular (secondary = 'none'). Only name one "
        "if the lore actually supports a real secondary strength."
    ),
    schema=_blocked_variant({
        "type": "object",
        "properties": {"aptitudeSecondary": {"type": "string", "enum": list(APTITUDES) + ["none"]}},
        "required": ["aptitudeSecondary"],
        "additionalProperties": False,
    }),
    build_brief=_brief_aptitude_secondary,
)


# --- 5. threat-audit — the one exception: shown a RUNG NAME, never a number (§4) --------------

def _brief_threat_audit_measured(lore: SpeciesLore, context: dict) -> str:
    rung_id = context["rungId"]
    rung_ordinal = context["rungOrdinal"]
    return (
        f"This creature was measured as a \"{rung_id}\" (rung {rung_ordinal} of 10, where 1 is a "
        f"nuisance and 10 is a calamity). Does its description support that level of danger?\n\n"
        + _lore_block(lore)
        + "\n\nAnswer agree / too-low / too-high, with a one-sentence reason."
    )


def _brief_threat_audit_inferred(lore: SpeciesLore, context: dict) -> str:
    return (
        "This creature has no measured threat data. Choose the threat rung its lore best "
        "supports — how dangerous is it in a fight?\n\n" + _lore_block(lore)
        + f"\n\nChoose one: {', '.join(context.get('order', THREAT_BAND))}, with a one-sentence reason."
    )


THREAT_AUDIT_MEASURED_SCHEMA = _blocked_variant({
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["agree", "too-low", "too-high"]},
        "reason": {"type": "string"},
    },
    "required": ["verdict", "reason"],
    "additionalProperties": False,
})

THREAT_AUDIT_INFERRED_SCHEMA = _blocked_variant({
    "type": "object",
    "properties": {
        "threatBand": {"type": "string", "enum": list(THREAT_BAND)},
        "reason": {"type": "string"},
    },
    "required": ["threatBand", "reason"],
    "additionalProperties": False,
})

# Two schema/brief variants selected by the caller on `basis` (Q26) — not a single PipelineSpec,
# because the judgement genuinely differs: "does the number check out" vs "pick the number".
THREAT_AUDIT = PipelineSpec(
    id="threat-audit",
    attributes=("threatBand",),
    judgement="does the number's rung match the lore? (or, when unmeasured, what rung does the lore support?)",
    system_prompt=(
        "You audit a computed threat rating against a creature's lore, OR (when none was "
        "computed) choose the rating from lore alone. Never invent a number — you work only with "
        "the named rung, never the underlying score."
    ),
    schema=THREAT_AUDIT_MEASURED_SCHEMA,   # default; caller swaps to INFERRED for basis in {inferred,blocked}
    build_brief=_brief_threat_audit_measured,
)


# --- 6. deployment ------------------------------------------------------------------------------

def _brief_deployment(lore: SpeciesLore, context: dict) -> str:
    return (
        "Judge how this creature enters play: as a plant-side combatant in its own right "
        "(PlantAvatar), or as a hypnotised zombie fighting for the plant side (HypnoAlly)? Also "
        "judge how a player could add it to their roster (one or more of Summonable, CaptureOnly, "
        "EventOnly).\n\n" + _lore_block(lore)
        # `deployMode` is one of option-permutation's five voted fields (spec-option-permutation.md
        # §2) — it needs a shuffleable "Choose one" listing like every other voted field's brief,
        # not just the inline PlantAvatar/HypnoAlly prose above (order-invariant either way, but
        # the vote/permute machinery reads this key uniformly across all five fields).
        + f"\n\nChoose deployMode: {', '.join(context.get('order', DEPLOY_MODE))}."
    )


DEPLOYMENT = PipelineSpec(
    id="deployment",
    attributes=("deployMode", "acquisition"),
    judgement="how does this creature enter play?",
    system_prompt=(
        "You judge deployment mechanics from a creature's captured lore and side. deployMode "
        "describes HOW it fights (PlantAvatar or HypnoAlly), not its original side. acquisition "
        "names every legitimate way a player could add it — at least one flag is required."
    ),
    schema=_blocked_variant({
        "type": "object",
        "properties": {
            "deployMode": {"type": "string", "enum": list(DEPLOY_MODE)},
            "acquisition": {
                "type": "array", "items": {"type": "string", "enum": list(ACQUISITION)},
                "minItems": 1, "uniqueItems": True,
            },
        },
        "required": ["deployMode", "acquisition"],
        "additionalProperties": False,
    }),
    build_brief=_brief_deployment,
)


# --- 7. kit-shape --------------------------------------------------------------------------------

def _brief_kit_shape(lore: SpeciesLore, context: dict) -> str:
    return (
        "Judge how this creature fights: its attack rhythm (attackTempo), how far it can affect a "
        "target (reach), what it is built to threaten most (targetPreference), and which actor "
        "resources it meaningfully uses (resourceProfile — most creatures use at least hp).\n\n"
        + _lore_block(lore)
        + f"\n\nattackTempo — choose one: {', '.join(context.get('order', ATTACK_TEMPO))}."
    )


KIT_SHAPE = PipelineSpec(
    id="kit-shape",
    attributes=("attackTempo", "reach", "targetPreference", "resourceProfile"),
    judgement="how does it fight?",
    system_prompt=(
        "You judge combat shape from a creature's captured lore. attackTempo is RHYTHM, not raw "
        "power. reach is how far it can affect a target, not movement speed or area of effect. "
        "targetPreference is tactical focus. resourceProfile is which of the six actor resources "
        "it meaningfully draws from or protects.\n\n"
        "attackTempo has five real rungs, not a safe middle default — 'steady' is not a fallback "
        "for 'unsure', it means genuinely average pace and must be earned the same way the other "
        "four are: 'ponderous' is a heavy, deliberate strike with a long wind-up (a giant, a "
        "siege engine, something that visibly winds up before it hits); 'slow' is a real strike "
        "with a noticeable pause between swings; 'steady' is an ordinary, unremarkable pace with "
        "no notable pause or burst; 'quick' strikes faster than average with short gaps; 'flurry' "
        "is rapid, multi-hit, machine-gun-like — barely any gap between strikes. Read the lore for "
        "concrete cues (wind-up language, rate-of-fire language, size/weight implying inertia) "
        "before defaulting to 'steady'.\n\n"
        "Audited 2026-09-03: the ORIGINAL prompt (no explicit vocabulary listing, no permutation) "
        "produced 'steady' for 100% of 833 real species — a real, checkable failure this rewrite "
        "exists to fix, not a rule to reverse into some other default."
    ),
    schema=_blocked_variant({
        "type": "object",
        "properties": {
            "attackTempo": {"type": "string", "enum": list(ATTACK_TEMPO)},
            "reach": {"type": "string", "enum": list(REACH)},
            "targetPreference": {"type": "string", "enum": list(TARGET_PREFERENCE)},
            "resourceProfile": {
                "type": "array", "items": {"type": "string", "enum": list(RESOURCES)},
                "minItems": 1, "uniqueItems": True,
            },
        },
        "required": ["attackTempo", "reach", "targetPreference", "resourceProfile"],
        "additionalProperties": False,
    }),
    build_brief=_brief_kit_shape,
)


# --- 8. identity ----------------------------------------------------------------------------------

def _brief_identity(lore: SpeciesLore, context: dict) -> str:
    return (
        "Judge this creature's identity: what KIND of thing is it (family — open vocabulary, "
        "invent a reasonable tag if none fits), what specifically distinguishes it (traits — open "
        "vocabulary, distinct from family), which of the seven known variant forms it could "
        "plausibly have (variants — name WHICH exist, not how many will be offered), and how "
        "special/rare it is (rarity, the ten-rung botanical ladder — NOT how dangerous it is; "
        "that is a separate axis).\n\n" + _lore_block(lore)
        + f"\n\nrarity options: {', '.join(context.get('order', RARITY))}. "
          f"variants options: {', '.join(VARIANTS)}."
    )


IDENTITY = PipelineSpec(
    id="identity",
    attributes=("family", "traits", "variants", "rarity"),
    judgement="what kind of thing is it, and how special?",
    system_prompt=(
        "You judge identity from a creature's captured lore. family and traits are OPEN "
        "vocabularies — invent a reasonable tag rather than forcing a poor fit. variants names "
        "WHICH of the seven known forms are plausible for this species, never a count. rarity is "
        "how special/hard-to-obtain this species is, distinct from and never conflated with how "
        "dangerous it is.\n\n"
        "rarity has ten real rungs, not a safe middle default — each one is a distinct, earned "
        "judgment, not a fallback for 'unsure'. The canonical feel of each rung (this repo's own "
        "rarity ladder, item/ssot-rarity.md §3.3):\n"
        "  chaff — husks, clippings, a dented bucket; salvage fodder, nothing remarkable at all.\n"
        "  sprout — it works. That is all it does; the most basic real, functioning thing.\n"
        "  grafted — one graft took and held; a single deliberate improvement over the basic form.\n"
        "  cultivated — grown on purpose, to a plan; solid, intentional, unremarkable craftsmanship.\n"
        "  fused — two natures in one object, the game's own word for a real hybrid/combination.\n"
        "  chimeric — the fusion went further than intended; a hybrid that became something stranger.\n"
        "  heirloom — a line kept alive longer than its keepers; old, storied, deliberately preserved.\n"
        "  firstseed — from before the lawn; genuinely ancient, predates the current world.\n"
        "  sunwoven — solar power taken to its peak, not merely used: the ultimate, primordial, or "
        "supreme expression of sun-magic within its own family, where the name or signature ability "
        "itself marks it as sunlight weaponized or embodied (an 'ultimate'/'primordial'/'emperor'-"
        "tier being that converts light into raw force), not an ordinary plant that happens to "
        "produce or use sunlight as a resource. An everyday sun-producer is fused at most; the one "
        "species in a sun-themed line that IS the apex of that power — not just a member of it — is "
        "the concrete case sunwoven exists for.\n"
        "  almanac — it has a page, everyone knows its name; iconic, famous, universally recognised.\n"
        "Read the lore for concrete cues (age, craftsmanship, fame, hybrid origin, exceptional "
        "substance) before defaulting to a middle rung like 'cultivated' or 'fused'.\n\n"
        "Audited 2026-09-04: the ORIGINAL prompt (one generic sentence for all ten rungs) produced "
        "an 81‰ unresolved-vote rate — the worst of any classified field — and a corpus skewed "
        "toward 'fused'/'cultivated' with several rungs almost never used. This rewrite exists to "
        "fix that, not to reverse it into some other default. Follow-up same day: 'sunwoven' stayed "
        "at 0 of 840 even after this fix while 55 real sun/solar-themed species (SunFlower, "
        "AncientSunNut, TorchSunflower...) all landed on 'fused' or 'almanac' instead — checked, "
        "'sunwoven' WAS genuinely considered (it shows up as a recorded minority vote, e.g. for "
        "AncientSunNut) but consistently lost to 'almanac', a more legible high-tier option. "
        "Follow-up 2026-09-04: interrogated the model directly (a second chat turn asking it, in "
        "plain text, why not sunwoven) on AcientSunNut and SolarSunflower — both answers were "
        "coherent and consistent: the model reads 'OWN NATURE is solar/light energy itself' as a "
        "literal composition claim (made of light, not matter) that no biological PvZ creature can "
        "satisfy, SolarSunflower included, even though it is the most powerful sun-plant in the "
        "corpus. Not a model limit or a quota — the bar itself was unreachable by design. Rewritten "
        "same day into a superlative/degree bar ('the apex of solar power within its own family') "
        "grounded in what the anchor dump actually carries for these species — flavorIntroduce is "
        "None for every sun-plant checked, so the signal has to come from typeName/displayName/"
        "flavorInfo naming language ('ultimate', 'primordial', 'emperor'-class descriptors), not "
        "narrative flourish that doesn't exist in this corpus."
    ),
    schema=_blocked_variant({
        "type": "object",
        "properties": {
            "family": {"type": "array", "items": {"type": "string"}, "minItems": 1},
            "traits": {"type": "array", "items": {"type": "string"}, "minItems": 1},
            "variants": {
                "type": "array", "items": {"type": "string", "enum": list(VARIANTS)},
                "minItems": 1, "uniqueItems": True,
            },
            "rarity": {"type": "string", "enum": list(RARITY)},
        },
        "required": ["family", "traits", "variants", "rarity"],
        "additionalProperties": False,
    }),
    build_brief=_brief_identity,
)


PIPELINES: "dict[str, PipelineSpec]" = {
    p.id: p for p in (
        ELEMENT_PRIMARY, ELEMENT_SECONDARY, APTITUDE_PRIMARY, APTITUDE_SECONDARY,
        THREAT_AUDIT, DEPLOYMENT, KIT_SHAPE, IDENTITY,
    )
}

assert len(PIPELINES) == 8, "classify-pipelines is eight pipelines, per spec §1 — not more, not fewer"


def apply_threat_audit_verdict(computed_rung_id: str, verdict: str) -> "tuple[str, bool]":
    """Q16: 'Number wins, and the LLM audits the result.' The computed rung is returned
    UNCHANGED regardless of verdict — `too-low`/`too-high` only flags the species for the review
    queue (`needs_review=True`), it never mutates `threatBand` itself. A systematic pile of one
    verdict in one score range is a signal to retune `creature-threat.v1.json` once, not something
    904 individual model judgements should override."""
    return computed_rung_id, verdict != "agree"


def threat_audit_spec_for_basis(basis: str) -> PipelineSpec:
    """Q26: `inferred`/`blocked` species get a different judgement (choose the rung) and schema
    from `observed`/`stated` ones (audit the computed rung) — same pipeline id, two shapes."""
    if basis in ("inferred", "blocked"):
        return PipelineSpec(
            id="threat-audit", attributes=("threatBand",),
            judgement=THREAT_AUDIT.judgement, system_prompt=THREAT_AUDIT.system_prompt,
            schema=THREAT_AUDIT_INFERRED_SCHEMA, build_brief=_brief_threat_audit_inferred)
    return THREAT_AUDIT
