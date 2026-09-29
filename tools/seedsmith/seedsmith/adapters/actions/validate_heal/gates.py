"""seedsmith.adapters.actions.validate_heal.gates --- Stage 1's three per-candidate gate sets
(spec-validate-heal.md SS2 Stage 1): g1 (contract), g2 (brief conformance), g3 (quality). Pure
functions, zero I/O, zero model calls --- the caller (`derive.py`) supplies every table lookup
(rung ceiling budget, family-action atom sets, anchor tokens) already resolved, matching every
`derive.py` in this adapter family.

**Three separate gate sets, never one generic path** (SS3's own "never share one generic gate path
across the three pipelines"). `run_g2` branches on `pipeline_id` internally for the two
pipeline-specific rules (A-P1's anchor-token check, A-P3's family-action-set check) rather than the
CALLER picking a different function per pipeline, but the effect is the same: A-P1/A-P2 share no
special-cased behaviour, and A-P3's own rule never applies to the other two.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from ....pipeline.model import BLOCKED_FIELD

__all__ = [
    "BriefContext", "run_g1", "run_g2", "run_g3", "REACTION_AXIS", "RESTRICTION_AXIS",
]

REACTION_AXIS = "reaction"
RESTRICTION_AXIS = "restriction"

_TYPE_NAMES: "dict[str, object]" = {
    "string": str, "boolean": bool, "object": dict, "array": list,
    "number": (int, float), "integer": int,
}


@dataclass(frozen=True)
class BriefContext:
    """Everything g2 reads about the ONE brief a candidate answers --- resolved by the caller
    (`derive.py`), never re-derived here (SS3: "never invent a rung-band resolution")."""

    brief_id: str
    pipeline_id: str                              # "A-P1" | "A-P2" | "A-P3"
    allowed_atom_families: "frozenset[str]"
    forbidden_atom_families: "frozenset[str]"
    motifs: "frozenset[str]"                       # brief.motifs, or brief.familyMotifs for A-P2
    anti_motifs: "frozenset[str]"
    # The CEILING row's own structureBudget, already resolved via A-S1's collapse rule
    # (`distribution_planner.derive.structure_axes_for`) --- 'reaction' already excluded by that
    # function's own contract; 'restriction' is checked separately (passes, reported unchecked).
    structure_budget_ceiling: "tuple[str, ...]" = ()
    # A-P3 only: every already-accepted FAMILY action's own atomFamilies set, as a frozenset each.
    family_action_atom_sets: "tuple[frozenset[str], ...]" = ()
    # A-P1 only: the closed species/family/element token vocabulary a general-scope draft's own
    # name/rationale must not mention (checked case-insensitively, substring).
    forbidden_anchor_tokens: "tuple[str, ...]" = ()


# ---------------------------------------------------------------------------------------------
# g1 --- contract. Hard reject -> repair, closed-loop.
# ---------------------------------------------------------------------------------------------

def run_g1(draft: Mapping[str, object], schema: Mapping[str, object]) -> "dict[str, str]":
    """Schema-parses, every required key present, no extra key. `blocked` handling is the
    CALLER's job (`derive.build_verify_fn` short-circuits on `draft.get(BLOCKED_FIELD)` before this
    ever runs) --- this function is never called against a genuinely-declined draft, so it never
    second-guesses whether a decline was "genuine"."""
    defects: "dict[str, str]" = {}
    props = schema.get("properties") or {}
    required = schema.get("required") or ()

    for name in required:
        if name not in draft:
            defects[name] = "required key missing"

    for name in draft:
        if name in (BLOCKED_FIELD, "reason"):
            continue
        if name not in props:
            defects[name] = "not a field of this schema -- extra keys are refused"

    for name, value in draft.items():
        if name not in props:
            continue
        spec = props[name]
        if not isinstance(spec, dict):
            continue
        declared = spec.get("type")
        if isinstance(declared, str) and declared in _TYPE_NAMES:
            expected = _TYPE_NAMES[declared]
            if declared in ("number", "integer") and isinstance(value, bool):
                defects.setdefault(name, f"is a boolean, not {declared}")
                continue
            if not isinstance(value, expected):
                defects.setdefault(name, f"should be {declared}, got {type(value).__name__}")
                continue
        item_spec = spec.get("items") if isinstance(spec.get("items"), dict) else None
        allowed = (item_spec or {}).get("enum") if item_spec else spec.get("enum")
        if item_spec is not None and allowed is not None and isinstance(value, list):
            for v in value:
                if v not in allowed:
                    defects.setdefault(name, f"contains {v!r}, not one of {list(allowed)}")
                    break
        elif item_spec is None and allowed is not None and name in draft and not isinstance(value, list):
            if value not in allowed:
                defects.setdefault(name, f"value {value!r} is not one of {list(allowed)}")

    if BLOCKED_FIELD in draft and not isinstance(draft[BLOCKED_FIELD], bool):
        defects.setdefault(BLOCKED_FIELD, "must be a boolean")

    return defects


# ---------------------------------------------------------------------------------------------
# g2 --- brief conformance. Hard reject -> repair, closed-loop.
# ---------------------------------------------------------------------------------------------

def run_g2(draft: Mapping[str, object], ctx: BriefContext) -> "tuple[dict[str, str], bool]":
    """Returns `(hard_defects, restriction_claimed)`. `restriction_claimed` is never a defect ---
    it PASSES g2 (StructureBudgetGuard cannot detect it without the effect-atom program's per-atom
    payload data) and is reported UNCHECKED by the caller's round report, never silently claimed as
    verified conformance."""
    defects: "dict[str, str]" = {}

    atom_families = draft.get("atomFamilies")
    if isinstance(atom_families, list):
        outside_allowed = [a for a in atom_families if a not in ctx.allowed_atom_families]
        in_forbidden = [a for a in atom_families if a in ctx.forbidden_atom_families]
        if outside_allowed:
            defects["atomFamilies"] = (
                f"{outside_allowed} not in this brief's own allowedAtomFamilies "
                f"{sorted(ctx.allowed_atom_families)}"
            )
        elif in_forbidden:
            defects["atomFamilies"] = f"{in_forbidden} is in this brief's own forbiddenAtomFamilies"
        elif ctx.pipeline_id == "A-P3" and ctx.family_action_atom_sets:
            claimed = frozenset(atom_families)
            for fam_set in ctx.family_action_atom_sets:
                if claimed == fam_set:
                    defects["atomFamilies"] = (
                        f"{sorted(claimed)} exactly equals an already-listed family action's own "
                        f"atomFamilies set -- not a signature differentiation"
                    )
                    break

    motifs_expressed = draft.get("motifsExpressed")
    if isinstance(motifs_expressed, list):
        anti = [m for m in motifs_expressed if m in ctx.anti_motifs]
        if anti:
            defects["motifsExpressed"] = f"{anti} is one of this brief's own antiMotifs"

    structure_axes = draft.get("structureAxes")
    restriction_claimed = False
    if isinstance(structure_axes, list):
        axis_defects: "list[str]" = []
        for axis in structure_axes:
            if axis == REACTION_AXIS:
                axis_defects.append(
                    f"claims {REACTION_AXIS!r} -- unspendable (ActionKind has exactly three "
                    f"members, none reaction-shaped) -- a hard reject, never a flag"
                )
            elif axis == RESTRICTION_AXIS:
                restriction_claimed = True                # passes, unchecked -- never a defect
            elif axis not in ctx.structure_budget_ceiling:
                axis_defects.append(
                    f"claims {axis!r}, outside this brief's rung-band ceiling budget "
                    f"{list(ctx.structure_budget_ceiling)}"
                )
        if axis_defects:
            defects["structureAxes"] = "; ".join(axis_defects)

    if ctx.pipeline_id == "A-P1" and ctx.forbidden_anchor_tokens:
        haystack = f"{draft.get('name') or ''} {draft.get('rationale') or ''}".lower()
        hit = next((t for t in ctx.forbidden_anchor_tokens if t.lower() in haystack), None)
        if hit is not None:
            defects["name"] = (
                f"names {hit!r} -- a general-scope brief carries no anchor, so a species/family/"
                f"element token in the draft is a defect"
            )

    return defects, restriction_claimed


# ---------------------------------------------------------------------------------------------
# g3 --- quality. Advisory only -> review queue, open-loop, NEVER contributes to a pass/fail.
# ---------------------------------------------------------------------------------------------

def run_g3(draft: Mapping[str, object], *, motif_or_role_terms: Sequence[str],
          names_already_in_round: Sequence[str]) -> "list[str]":
    """Every note here is advisory. The caller must never fold this list into `hard`/`soft` for
    `call_with_self_heal`, and never let it block acceptance (SS3: "never auto-reject on g3")."""
    notes: "list[str]" = []

    name = draft.get("name")
    atom_families = draft.get("atomFamilies") or []
    if not isinstance(name, str) or not name.strip():
        notes.append("name is empty")
    else:
        normalized = name.strip().lower()
        family_ids_lower = {a.lower() for a in atom_families if isinstance(a, str)}
        joined = " ".join(sorted(family_ids_lower))
        if normalized in family_ids_lower or normalized == joined:
            notes.append("name is a bare restatement of the atom family ids it bundles")
        if normalized in {n.strip().lower() for n in names_already_in_round if isinstance(n, str)}:
            notes.append("name is not unique within this round's own candidates")

    rationale = draft.get("rationale")
    rationale_text = rationale.lower() if isinstance(rationale, str) else ""
    if motif_or_role_terms and not any(t.lower() in rationale_text for t in motif_or_role_terms):
        notes.append("rationale refers to none of the brief's own motifs (or role, for A-P1)")
    elif not rationale_text.strip():
        notes.append("rationale is empty")

    return notes
