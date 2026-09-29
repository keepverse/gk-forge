"""seedsmith.adapters.actions.validate_heal.schemas — the three pipeline draft schemas A-S4
audits and gates (spec-validate-heal.md SS2 Stage 0/1, binding constraint 2: "P-general, P-family,
P-signature... never one generic path with a `scope` switch").

**Real schemas, swapped in 2026-09-04** after the first real smoke batch proved the previous three
constants here were FIXTURES that never matched what A-P1/A-P2/A-P3 (`general_propose`,
`family_propose`, `signature_propose`) actually produce. Measured directly against real accepted
rows (`data/seed/actions/_candidates/{general,family}/round-1.json`, e.g. "Brace"/"Kinetic
Repulsion"/"Fickle Decay"/"Undead Volley") and each pipeline's own `prompts.py::entry_for`:

- **`flavor` was missing entirely** from every field set below, even though it is REQUIRED on all
  three real pipelines' own schemas (`general_propose/prompts.py::GENERAL_ACTION_SCHEMA`, etc.) and
  present on every real accepted draft. Added here, required on all three.
- **`structureAxes` was required everywhere**, but no real pipeline's own schema has ever asked the
  model for it — `structureAxes` is a rung-table-derived CEILING BUDGET the brief carries
  (`brief.slot.structureAxes`), never something A-P1/A-P2/A-P3 ask the model to answer. Downgraded
  to an allowed-but-optional property here (never required) — g2's own reaction/restriction checks
  (`gates.py`) still exercise it when a caller supplies it (e.g. a future pipeline that does ask),
  and its total absence from a real draft is correctly a no-op, never a defect.
- **`motifsExpressed` is real for A-P2/A-P3 only** (`family_propose`/`signature_propose`'s own
  schemas), never A-P1 (`general_propose` has no such field — no anchor, no motif to express).
  Required on `FAMILY_SCHEMA`/`SIGNATURE_SCHEMA`, never on `GENERAL_SCHEMA`'s own required list.
- **`differentiator` stays A-P3-only**, matching A-P3's own schema note
  (spec-signature-propose.md:160-162, quoted at spec-validate-heal.md SS2 Stage 1).

**What this schema validates is the ANSWER portion only** — `name`/`flavor`/`atomFamilies`/
`rationale`/`motifsExpressed`/`differentiator` — never the wrapper fields a real round file also
carries alongside a draft (`candidateId`/`briefId`/`scope`/`_provenance`, added by each pipeline's
own `entry_for` AFTER the model answers, or read straight off the round-row envelope). A caller
gating a real, on-disk candidate (`candidate_assembly.derive`, this program's newest module) strips
those wrapper keys before calling into `gates.run_g1`/`run_g2` — this file's own schema shape stays
the "one judgement" contract A-S4 was always meant to check, not a second copy of the envelope shape
`kinds.py`/`dedup_select` already own. `BLOCKED_FIELD`/`reason` stay declared below as a
boolean+`reason` pair for `audit_schema`'s own structural completeness check (every schema this
module owns must audit-pass) — `gates.run_g1` already exempts both names from its "extra key"
check unconditionally, regardless of a real pipeline's own different `blocked` convention (a bare
empty-string sentinel, `general_propose/prompts.py`'s own documented shape), so the two conventions
never conflict.

Three DISTINCT dict objects, on purpose, even though P-general and P-family end up structurally
close below (binding constraint 2, and SS3's own "never share one generic gate path across the
three pipelines" -- a coincidence of shape is not permission to alias the schema, since a future
P-general-only field must never silently also apply to P-family).
"""
from __future__ import annotations

from typing import Any

from ....pipeline.model import BLOCKED_FIELD

__all__ = [
    "STRUCTURE_AXES", "PIPELINE_IDS", "GENERAL_SCHEMA", "FAMILY_SCHEMA", "SIGNATURE_SCHEMA",
    "SCHEMAS_BY_PIPELINE", "VOTED_FIELDS_BY_PIPELINE",
]

#: The full structure-axis vocabulary, transcribed from the shipped rung table's own union across
#: all ten rows (`gk-core/data/tuning/action-rungs.v1.json` rows 3-10's `structureBudget` arrays) --- never
#: re-derived here, since `distribution_planner.derive.load_rung_table`/`structure_axes_for` already
#: own reading that file; this is the closed vocabulary a claimed `structureAxes` entry may be drawn
#: from, not a second copy of the budget-by-rung logic.
STRUCTURE_AXES: "tuple[str, ...]" = (
    "scopeSplit", "riderStatus", "condition", "sequence", "consumption", "reaction", "restriction",
)

#: The three pipeline ids this module audits/gates -- P-general/P-family/P-signature, per
#: spec-validate-heal.md's own binding constraint 2. Kept as a closed tuple so a caller iterating
#: "the three pipelines" never silently drops one.
PIPELINE_IDS: "tuple[str, ...]" = ("A-P1", "A-P2", "A-P3")


def _common_properties() -> "dict[str, Any]":
    """Every field g1 (contract), g2 (brief conformance) or g3 (quality) actually reads --- shared
    by construction across all three schemas below, never by aliasing the dict itself (each caller
    builds its own copy)."""
    return {
        "name": {
            "type": "string",
            "description": (
                "The action's own display name --- never empty, and never a bare restatement of "
                "the atom family ids it bundles."
            ),
        },
        "flavor": {
            "type": "string",
            "description": (
                "One line of player-facing flavour text under the name --- never a rules "
                "description, and never a number, duration, chance or range (real on every one "
                "of A-P1/A-P2/A-P3's own schemas; measured 2026-09-04 against real accepted "
                "drafts, e.g. 'Brace'/'Kinetic Repulsion')."
            ),
        },
        "rationale": {
            "type": "string",
            "description": (
                "One or two sentences grounding the design in a motif the brief named (or, for "
                "the general pipeline, the brief's own role) --- never empty, and never a "
                "restatement of this schema's own field names."
            ),
        },
        "atomFamilies": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "description": (
                "The atom family ids this action bundles --- drawn only from the brief's own "
                "allowedAtomFamilies, never an id outside that pool, and never left empty."
            ),
        },
        "motifsExpressed": {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "Which of the brief's own motifs this action expresses --- never one of the "
                "brief's antiMotifs, and never a motif the brief did not name."
            ),
        },
        "structureAxes": {
            "type": "array",
            "items": {"type": "string", "enum": list(STRUCTURE_AXES)},
            "description": (
                "The structural axes this action claims --- never an axis outside the brief's own "
                "rung-band ceiling row, and never 'reaction' (unspendable --- ActionKind has no "
                "reaction-shaped member)."
            ),
        },
        BLOCKED_FIELD: {
            "type": "boolean",
            "description": (
                "True only when the model genuinely cannot design a legal action from this brief "
                "--- never a way to skip a real design, and never left unset just because the "
                "model is unsure."
            ),
        },
        "reason": {
            "type": "string",
            "description": (
                "Present only when blocked is true --- the reason a legal action could not be "
                "designed; never present, and never non-empty, when blocked is false."
            ),
        },
    }


def _required() -> "list[str]":
    """The floor every real pipeline shares --- `name`/`flavor`/`atomFamilies`/`rationale`, all
    required on every one of A-P1/A-P2/A-P3's own real schemas (`*_propose/prompts.py`).
    `motifsExpressed` is NOT in this floor (real for A-P2/A-P3 only, see module docstring) and
    `structureAxes` is never required by any real pipeline (module docstring) --- both stay allowed,
    optional properties via `_common_properties()`, never part of any schema's `required` list."""
    return ["name", "flavor", "rationale", "atomFamilies"]


#: P-general (A-P1). No anchor at all --- g2's own A-P1 rule ("the brief carried no anchor and the
#: draft names no species/family/element token") is a CONTENT check against the brief, not a schema
#: shape difference, so this schema carries no extra property for it. Real A-P1 has no motif concept
#: at all (`general_propose/prompts.py::GENERAL_ACTION_SCHEMA` carries no `motifsExpressed`
#: property) --- this schema still ALLOWS it as an optional property (never required), the one
#: place this module's own shape stays looser than the real pipeline's, so a shared test fixture
#: across all three pipelines never needs a fourth, general-only draft shape. Tightening this to a
#: true per-pipeline PROPERTY SET (reject `motifsExpressed` outright for A-P1) is a further real fix
#: a later pass can make; flagged here rather than silently done.
GENERAL_SCHEMA: "dict[str, Any]" = {
    "type": "object",
    "properties": _common_properties(),
    "required": _required(),
    "additionalProperties": False,
}

#: P-family (A-P2). No A-P2-specific g2 rule is named anywhere in spec-validate-heal.md --- the
#: schema is structurally identical to P-general's, save one thing: `motifsExpressed` is REQUIRED
#: here (real -- `family_propose/prompts.py::FAMILY_ACTION_SCHEMA`'s own required list), never for
#: P-general. The two stay separate objects regardless (module docstring).
FAMILY_SCHEMA: "dict[str, Any]" = {
    "type": "object",
    "properties": _common_properties(),
    "required": _required() + ["motifsExpressed"],
    "additionalProperties": False,
}

#: P-signature (A-P3). Adds `differentiator` --- A-P3's own schema note (spec-signature-propose.md
#: :160-162, quoted verbatim at spec-validate-heal.md SS2 Stage 1): "`none` means it does not
#: meaningfully differ, and saying `none` honestly is better than inventing a difference."
_signature_properties = _common_properties()
_signature_properties["differentiator"] = {
    "type": "string",
    "description": (
        "How this signature action differs from the species' already-accepted actions, or the "
        "literal 'none' when it does not meaningfully differ --- an honest 'none' is never "
        "penalised, and a difference is never invented when none genuinely exists."
    ),
}

SIGNATURE_SCHEMA: "dict[str, Any]" = {
    "type": "object",
    "properties": _signature_properties,
    "required": _required() + ["motifsExpressed", "differentiator"],
    "additionalProperties": False,
}

SCHEMAS_BY_PIPELINE: "dict[str, dict[str, Any]]" = {
    "A-P1": GENERAL_SCHEMA, "A-P2": FAMILY_SCHEMA, "A-P3": SIGNATURE_SCHEMA,
}

#: Stage 2's own voted-field set, per pipeline (spec-validate-heal.md SS2 Stage 2, binding
#: constraint 3): `atomFamilies` for A-P1/A-P2; `atomFamilies` + `differentiator` for A-P3. Adding a
#: field here is an "ask first" boundary (moves the call budget by a third of the run) --- pinned as
#: a literal mapping so a sixth field needs a deliberate code change, matching
#: `adapters/creatures/anchor/vote.py`'s own `VOTED_FIELDS` frozenset discipline.
VOTED_FIELDS_BY_PIPELINE: "dict[str, tuple[str, ...]]" = {
    "A-P1": ("atomFamilies",), "A-P2": ("atomFamilies",), "A-P3": ("atomFamilies", "differentiator"),
}
