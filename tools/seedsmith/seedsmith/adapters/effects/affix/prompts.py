"""seedsmith.adapters.effects.affix — `affix-authoring`'s own domain knowledge
(spec-affix-authoring.md, effect-pipeline module 9). The model authors a NAMED, multi-atom bundle
— *"Master of Fire and Ice"* — by picking a name and which EXISTING atoms it bundles from the
shared atom library; every number (weight, tier, magnitude) is a table's job, never the model's
(P1, restated for this content type).

Two fields are 3-way voted, same machinery `creature-seed`'s `classify-pipelines` already proved
(Q25 precedent): the affix's own **name/identity** and its **ref bundle composition** — the two
judgement calls with the highest cost of being wrong.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from ....pipeline.model import BLOCKED_FIELD

__all__ = [
    "SYSTEM_PROMPT", "AFFIX_SCHEMA", "ID_PREFIX", "build_context", "build_brief", "entry_for",
    "refs_are_known_atoms", "bundle_has_at_least_two_refs",
]

ID_PREFIX = "affix.authored."

#: No magnitude field anywhere — `name` and `refs` only. `refs` names EXISTING atom ids from the
#: shared library; the model never invents an atom, only bundles ones that already exist.
#:
#: `blocked` (below) was added 2026-09-04 by `validate-heal` (A-S4, spec-validate-heal.md SS6
#: hazard 1): the shipped schema had `additionalProperties: false` and no `blocked` property, so
#: this pipeline's own model had NO WAY to decline — a live defect, not paperwork — and the schema
#: failed `pipeline.model.audit_schema`'s own "every schema needs a blocked variant" rule the
#: moment that rule was applied to it. Scope held tight per the spec: this property and its
#: description only, nothing else about the pipeline changed. `required`/`additionalProperties`
#: are untouched, so `name`/`refs` are still required even when `blocked` is true — a real,
#: separate functional gap this fix does not close (named follow-up: `affix-schema-blocked`,
#: SS6 hazard 1's own fallback if `python -m pytest gk-forge/tools/seedsmith/tests` had gone red, which it
#: did not).
AFFIX_SCHEMA: "dict[str, Any]" = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "refs": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 2,
        },
        BLOCKED_FIELD: {
            "type": "boolean",
            "description": (
                "True only when the model genuinely cannot bundle two or more of the given "
                "atoms into one coherent named affix — never a way to skip a real bundle, and "
                "never left unset just because the model is unsure."
            ),
        },
    },
    "required": ["name", "refs"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = (
    "You design named, multi-atom affix bundles for an RPG's item and effect system — for example "
    "'Master of Fire and Ice'. An affix bundle is an IDENTITY: a thematic pairing of two or more "
    "EXISTING effect atoms from the library you are given, given a name that reads as a real "
    "in-game affix. You never invent a new atom id — you only pick which of the given atom ids "
    "belong together, and name the bundle. You never write a weight, a tier, or a magnitude; those "
    "are decided by tables you never see. Ground the bundle in a real thematic connection between "
    "the atoms you pick — never bundle atoms that share nothing but being in the same list."
)


def build_context(eligible_atoms: "Sequence[str]", *, theme_hint: str = "") -> "dict[str, Any]":
    """Read-only inputs the brief and the validators need. `eligible_atoms` is the run's own
    declared pool this call may pick from — never the whole catalog, matching
    `species_effects.py`'s own `eligibleFamilies` convention."""
    return {
        "eligibleAtoms": list(eligible_atoms),
        "themeHint": theme_hint,
    }


def build_brief(context: "Mapping[str, Any]") -> str:
    """Inlines the eligible atom ids literally — never cites a file, the same "cites nothing"
    discipline `commander_effect.py`'s own `build_brief` already states a reason for."""
    lines = [
        "Eligible atoms this run may bundle (pick two or more): "
        + ", ".join(context["eligibleAtoms"]),
    ]
    if context.get("themeHint"):
        lines.append(f"Theme hint: {context['themeHint']}")
    lines += [
        "",
        "Design ONE named affix bundle: a name, and which of the eligible atoms it bundles.",
    ]
    return "\n".join(lines)


def refs_are_known_atoms(draft: "Mapping[str, Any]", context: "Mapping[str, Any]") -> "list[str]":
    """Every picked ref must be one of the run's own declared eligible atoms — a model inventing an
    atom id outside the shared library is exactly the fork `affix-schema` (module 1) exists to
    prevent."""
    known = set(context.get("eligibleAtoms") or [])
    picked = set(draft.get("refs") or [])
    unknown = sorted(picked - known)
    if unknown:
        return [f"ref(s) {unknown} are not in this run's own eligible atoms {sorted(known)}"]
    return []


def bundle_has_at_least_two_refs(draft: "Mapping[str, Any]", context: "Mapping[str, Any]") -> "list[str]":
    """A single-atom 'bundle' is what `affix-library` (module 3) already rule-generates — this
    module exists specifically for MULTI-atom identity, so one ref here is a defect, not a
    smaller-but-valid affix."""
    refs = draft.get("refs") or []
    if len(refs) < 2:
        return [f"bundle has {len(refs)} ref(s) — a named bundle needs at least two"]
    return []


def entry_for(
    draft: "Mapping[str, Any]", *, affix_id: str, affix_class: str,
    provenance: "Mapping[str, Any] | None" = None,
) -> "dict[str, Any]":
    """The committed seed entry. `affixClass` is passed in ALREADY DERIVED (via
    `derive.derive_affix_class`) — this function never computes it, so there is exactly one place
    in the whole pipeline that turns refs into a class.

    Key names and the `refs` shape match `AtomSeedFile.ReadAffix` exactly (`gk-core/src/FusionRpg.Core/
    Effects/Atoms/AtomSeedFile.cs`) — the real importer reads a top-level `class` key (not
    `affixClass`) and each `refs[]` entry as an OBJECT with an `atom` key (not a bare id string);
    a bare string fails `ValueKind != JsonValueKind.Object` and is silently skipped, so an affix
    with N real refs would import with zero and be refused as "needs at least one ref" — found by
    running this pipeline's own real output through the real `AtomImporter` for the first time,
    2026-09-05, not caught by any test because every test in this pipeline stubs the transport and
    never round-trips through the real seed-file reader."""
    entry: "dict[str, Any]" = {
        "id": affix_id,
        "name": draft["name"],
        "class": affix_class,
        "refs": [{"atom": atom_id, "seq": i} for i, atom_id in enumerate(draft["refs"])],
    }
    if provenance:
        entry["_provenance"] = dict(provenance)
    return entry
