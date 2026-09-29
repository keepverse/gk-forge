"""seedsmith.adapters.creatures.effects — species-effects' own domain knowledge (T5.3,
spec-species-effects.md). Turns one species anchor into a `species-passive.{speciesId}` container
seed: the model judges WHICH affix families this species is eligible for and an affinity ordinal
per pick (`core`/`likely`/`occasional`); everything numeric — the fixed-core band, the pool weight
per affinity, `prefix_rolls`/`suffix_rolls` — is a TABLE, never the model (spec §3, §6).

**`threatBand` is deliberately absent from every context this module builds.** Strength is
`species-generator`'s, through one `P(Θ)` (spec §2's own table: "`threatBand` constrains nothing.
It is a `Θ` offset, so it belongs to magnitude, not to membership."). Grepping this file for
"threatBand" finds nothing outside this docstring — the property is enforced by omission, not by a
check that could itself have a bug.
"""
from __future__ import annotations

from typing import Any, Mapping

from .schema import AFFINITIES

__all__ = [
    "SYSTEM_PROMPT", "ID_PREFIX", "build_context", "build_brief", "entry_for",
    "fixed_core_within_band", "affix_ids_are_known",
]

ID_PREFIX = "species-passive."

SYSTEM_PROMPT = (
    "You design which shared affixes a creature species is eligible to draw from a common library — "
    "you never invent a new affix and you never write a number. For each affix family you judge "
    "eligible, give it exactly one affinity: 'core' (always present on every specimen of this "
    "species — reserve this for the ONE OR TWO effects that define what this creature IS), "
    "'likely' (a common pick, thematically strong), or 'occasional' (a rarer pick, thematically "
    "plausible but not central). Also name the container's own eligibility tags: which tag keys "
    "are REQUIRED on any drawn affix (requireTags), and which key:value pairs are an acceptable "
    "match for at least one (anyOfTags). Ground every pick in the species' own family, traits and "
    "lore — never invent lore the anchor does not support."
)


def build_context(anchor: "Mapping[str, Any]") -> "dict[str, Any]":
    """Read-only inputs the brief and the validators need. Deliberately does NOT read `threatBand` —
    spec §2's own table names it as constraining nothing here."""
    return {
        "speciesId": anchor.get("speciesId", ""),
        "rarity": anchor.get("rarity", ""),
        "elementPrimary": anchor.get("elementPrimary", ""),
        "elementSecondary": anchor.get("elementSecondary", "none"),
        "aptitudePrimary": anchor.get("aptitudePrimary", ""),
        "aptitudeSecondary": anchor.get("aptitudeSecondary", "none"),
        "posture": anchor.get("posture", ""),
        "resourceProfile": list(anchor.get("resourceProfile") or []),
        "family": list(anchor.get("family") or []),
        "traits": list(anchor.get("traits") or []),
        "flavorInfo": anchor.get("flavorInfo", ""),
    }


def build_brief(anchor: "Mapping[str, Any]", context: "Mapping[str, Any]") -> str:
    """Matches `container_authoring.py`'s own `(anchor_inputs, context) -> str` shape. Inlines the
    anchor's own fields literally — never cites a file, the same "cites nothing" discipline
    `commander_effect.py`'s own `build_brief` already states a reason for."""
    lines = [
        f"Species: {context['speciesId']} (family: {', '.join(context['family']) or 'none'})",
        f"Rarity: {context['rarity']}",
        f"Element: {context['elementPrimary']}"
        + (f" / {context['elementSecondary']}" if context['elementSecondary'] != 'none' else ''),
        f"Aptitude: {context['aptitudePrimary']}"
        + (f" / {context['aptitudeSecondary']}" if context['aptitudeSecondary'] != 'none' else ''),
        f"Posture: {context['posture']}",
        "Resources: " + ", ".join(context["resourceProfile"]),
        "Traits: " + ", ".join(context["traits"]),
        "",
        f"Lore: {context['flavorInfo']}",
        "",
        f"Eligible families / rarity bands / tag set this run may draw from: "
        f"{context.get('eligibleFamilies')} / {context.get('rarityBands')} / {context.get('tagSet')}",
        "",
        "Judge which affix families this species is eligible for, with an affinity ordinal "
        f"({', '.join(AFFINITIES)}) for each, and the container's own eligibility tags.",
    ]
    return "\n".join(lines)


def fixed_core_within_band(draft: "Mapping[str, Any]", context: "Mapping[str, Any]") -> "list[str]":
    """spec §4 (A2): a weight cannot express "always" — `core` is the fixed core, and the fixed
    core carries its OWN rarity band. A draft naming more `core` affixes than the band allows must
    repair, naming the conflict, never silently truncate (this repo's own no-silent-clamp rule)."""
    band = context.get("fixedCoreBand")
    if not band:
        return []  # band not supplied — caller's responsibility, not this validator's to assume one
    core_count = sum(1 for a in draft.get("eligibleAffixes") or [] if a.get("affinity") == "core")
    max_core = band.get("max")
    if max_core is not None and core_count > max_core:
        return [
            f"{core_count} affixes marked 'core', but this species' rarity band allows at most "
            f"{max_core} — 'core' means the fixed core, always present, and rarity bounds how many "
            f"guaranteed effects one species may carry"
        ]
    return []


def affix_ids_are_known(draft: "Mapping[str, Any]", context: "Mapping[str, Any]") -> "list[str]":
    """Every picked `affixId` must be one of the run's own declared eligible families — a model
    inventing an affix id outside the shared library is exactly the fork `eligibility-tags` (T5.2)
    exists to prevent."""
    known = set(context.get("eligibleFamilies") or [])
    if not known:
        return []
    unknown = sorted({a.get("affixId") for a in draft.get("eligibleAffixes") or []} - known)
    if unknown:
        return [f"affixId(s) {unknown} are not in this run's own eligible families {sorted(known)}"]
    return []


def entry_for(
    anchor: "Mapping[str, Any]", draft: "Mapping[str, Any]", *,
    affix_class_of: "Any",  # Callable[[str], str] -> "Prefix" | "Suffix" | "Mixed"
    affix_refs_of: "Any",  # Callable[[str], Sequence[str]] -> the affix's own real atom ids, in order
    pool_affinity_weight_milli: "Mapping[str, int] | None" = None,
    provenance: "Mapping[str, Any] | None" = None,
) -> "dict[str, Any]":
    """The committed seed entry.

    ⛔ **Fixed 2026-09-06 — the shape below never matched the real C# `ReadContainer`/
    `ContainerPoolRow`/`ContainerValidator` reader, found only because this task actually ran real
    content through the real importer rather than stopping at the in-process tests (the exact "never
    round-tripped through the real seed-file reader" trap `affix-authoring`'s own sibling `entry_for`
    already hit once, 2026-09-05). Three real mismatches, not one:**
    1. `ReadContainer` has no `fixedAffixes` field at all — a container's always-present half is its
       `atoms` list (`{"seq", "atom"}` objects, `effect_container_atom` at import — spec §4's own
       table: "`core` | `effect_container_atom` — always present"). A `core` affinity therefore
       flattens into ITS OWN real atom refs via `affix_refs_of` (looked up from the real committed
       affix catalog), not a bare affix id — the container never stores "this affix is fixed," only
       the atoms that make it so, mirroring exactly how a hand-authored container like `patron.aura`
       lists raw atoms directly.
    2. `ContainerPoolRow` is `(AffixId, Weight, Group)` — a real int `Weight` is REQUIRED to be a
       legal pool row at all, not "resolved at roll time": `SpeciesMaterialiser`/`Instantiator.Draw`
       have no independent path to `creature-species-effects.v1.json`'s own tuning at roll time, so
       spec §6's "no weight... resolved downstream" describes the MODEL never inventing a number
       (P1), not the committed container having none — the model still only ever writes an
       `affinity` ordinal; this function is what turns that ordinal into the real, table-derived,
       non-invented weight via `pool_affinity_weight_milli` (`creature-species-effects.v1.json`'s own
       `poolAffinityWeightMilli`), the same "table converts a judgement into a number, the model
       never does" contract every other tunable table in this program already uses.
    3. `ContainerValidator.Validate` derives a pool row's default `Group` (PoE's "at most one per
       group" mod-family rule) from a SOLE concrete ref's own `(family, variant)` — it has nothing to
       derive from for a multi-ref bundle and refuses the whole import rather than guess (found live,
       running this exact output through the real importer). Every pool row whose affix has more
       than one ref now names its own affix id as `group` explicitly — safe and non-colliding, since
       each named bundle is already its own atomic pick.

    `prefixRolls`/`suffixRolls` are the count of drawable pool groups per budget the pool ACTUALLY
    needs to cover its own `likely`/`occasional` entries — a `Mixed`-class affix counts against BOTH
    budgets simultaneously (A1), never doubling either count and never omitted from either.
    """
    species_id = anchor.get("speciesId", "")
    weight_table = dict(pool_affinity_weight_milli or {"likely": 700, "occasional": 300})

    fixed_atoms: "list[str]" = []
    for a in draft.get("eligibleAffixes", []):
        if a.get("affinity") == "core":
            fixed_atoms.extend(affix_refs_of(a["affixId"]))
    pool_entries = [a for a in draft.get("eligibleAffixes", []) if a.get("affinity") != "core"]

    prefix_needed = 0
    suffix_needed = 0
    for a in pool_entries:
        cls = affix_class_of(a["affixId"])
        if cls in ("Prefix", "Mixed"):
            prefix_needed += 1
        if cls in ("Suffix", "Mixed"):
            suffix_needed += 1

    def pool_row(a: "Mapping[str, Any]") -> "dict[str, Any]":
        row: "dict[str, Any]" = {"affix": a["affixId"], "weight": weight_table[a["affinity"]]}
        # `ContainerValidator.Validate` derives a default Group from a SOLE concrete ref's own
        # (family, variant) — it has nothing to derive from for a multi-ref bundle and refuses the
        # whole import rather than guess (found live, running this exact output through the real
        # importer: "is a multi-ref or slot-bearing bundle and must declare an explicit pool Group").
        # The affix's own id is a safe, non-colliding choice — each named bundle is already its own
        # atomic pick, so grouping it under its own identity can never accidentally exclude an
        # unrelated affix from rolling. Single-ref affixes keep the validator's own real default.
        if len(affix_refs_of(a["affixId"])) != 1:
            row["group"] = a["affixId"]
        return row

    entry: "dict[str, Any]" = {
        "id": f"{ID_PREFIX}{species_id}",
        "kind": "species-passive",
        "atoms": [{"seq": i, "atom": atom_id} for i, atom_id in enumerate(fixed_atoms)],
        "pool": [pool_row(a) for a in pool_entries],
        "prefixRolls": prefix_needed,
        "suffixRolls": suffix_needed,
        "tags": dict(draft.get("eligibilityTags") or {}),
    }
    if provenance:
        # The affix-level identity (which bundles were core vs. pool, before flattening) is real
        # authoring information a human reviewing this file would want — kept here, never read back
        # by the importer, so it can never silently diverge from what actually got imported.
        entry["_provenance"] = {
            **dict(provenance),
            "coreAffixIds": sorted({
                a["affixId"] for a in draft.get("eligibleAffixes", []) if a.get("affinity") == "core"
            }),
        }
    return entry
