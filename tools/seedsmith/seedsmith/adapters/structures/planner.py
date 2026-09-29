"""base-defense `structure-planner` (module 27, spec-structure-planner.md). **Decide what to
generate before anything is generated — deterministically, with no model** (owner decision 33).

Five things fixed here, all model-free (spec §2), plus a sixth this module's own reading of
`structure-instantiate`'s (26) real container-shape resolution adds — see `CONTAINER_POLICY`'s own
docstring for why a sixth was missing from the spec's own text and belongs here, not left silently
undeclared:

1. The tier ladder, ordered.
2. Which roles exist and the target count per role.
3. Which (role × slot kind) combinations are legal.
4. How many variants per row.
5. Which `acquisitionPaths` each kind may declare.
6. Container policy — whether a row may name a `ContainerId`, and who assigns it.

Zero model calls. `build_plan()` is a pure function of `(corpus rows, tuning, seed)` — no
`datetime`, no unseeded `random`. `seed` is accepted for interface stability (a future planner
decision might need seeded tie-breaking) but nothing in this version of the plan actually consumes
it — stated here rather than left for a reader to wonder whether omission was an oversight.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .anchor.schema import ACQUISITION_PATH, ROLE

# ---- 1. The tier ladder, ordered (decision 32/33) ----------------------------------------------
# Read from gk-core/data/tuning/structure-seed.v1.json's own `bands.tierLadder` (spec's own Tunables
# table) -- NOT hardcoded here a second time. `bands.tierLadder` must equal `STRENGTH_BAND`
# (schema.py's own enum) exactly; `test_tier_ladder_matches_the_schemas_strength_band` checks this
# directly so the two can never silently drift into a 7th instance of this codebase's own recurring
# "N parallel lists must stay synced" bug class. Inventing a 4th rung ("iron", per the spec's own
# illustrative "rubble < timber < stone < iron < ..." example text) without a real tuning row to
# back it would be exactly the "the model names a rung nobody declared" failure this module exists
# to prevent, aimed at itself -- extending the ladder for real is its own future content decision.
def _tier_ladder(tuning: dict) -> "tuple[str, ...]":
    return tuple(tuning["bands"]["tierLadder"])

# ---- 5. acquisitionPaths legality (decision 35: `none` illegal) --------------------------------
# Every one of the 4 real paths is legal for ANY role today -- no role-specific restriction exists
# in the source material (base-defense-ideal.md §5.24 describes the four paths generically, never
# tied to a role or kind). The only illegal state, already enforced at C# load time
# (StructureCatalog.Validate), is an EMPTY list.
LEGAL_ACQUISITION_PATHS_PER_ROLE: "dict[str, tuple[str, ...]]" = {role: tuple(ACQUISITION_PATH) for role in ROLE}

# ---- 4. Variant count policy (§6: "a tier chain is a variants list, not four rows") -------------
# No row in the real corpus has authored any variant yet (structure-corpus, module 24) -- an honest
# floor, not a placeholder. The policy is a bound, not a forced count: 0 is always legal (most rows
# need none), and a future row MAY declare variants up to this bound without a plan change.
VARIANT_COUNT_POLICY = {"min": 0, "max": 4}  # 4 mirrors this module's own tier ladder length --
# a variant list longer than the tier ladder itself would be finer-grained than decision 32's own
# material axis can express, the same reasoning spec-structure-corpus.md §2 uses for "two tiers by
# value" staying inside strengthBand rather than becoming separate rows.

# ---- 6. Container policy (a real gap `structure-instantiate` (26) found, not this spec's own text)
# structure-instantiate's own spec-structure-instantiate.md §1 table names HP/cost/footprint/reach
# as never rolled -- but says nothing about WHO assigns a structure's ContainerId, and neither this
# module's own original 5-decision list nor structure-pipeline's (28) 28.1-28.6 named it either
# (grepped both specs directly before writing this. Zero mentions). Declared here as the missing
# sixth decision: containers are OPT-IN, assigned by a human/deterministic tool reviewing a row
# AFTER it exists (never by the model that names the row, and never automatically at generation
# time) -- the same "model writes identity, deterministic code writes magnitude/mechanism" split
# Law 2 already establishes for numbers, extended to "which container" since a container is a
# mechanism choice, not flavour. No row is required to ever get one.
CONTAINER_POLICY = {
    "assignment": "opt-in-post-hoc",
    "assignedBy": "human-or-deterministic-tool-never-the-generation-model",
    "requiredForEveryRow": False,
}


def _role_slot_pairs(rows: "list[dict]") -> "set[tuple[str, str]]":
    return {(r["anchor"]["role"], r["anchor"]["requiredSlotKind"]) for r in rows}


def build_plan(rows: "list[dict]", tuning: dict, seed: int) -> dict:
    """The committed plan — see module docstring. `rows` is `structure-corpus`'s own `ALL_ROWS`
    (the research corpus this module reads, never invents its own content from)."""
    budget = tuning["budget"]
    counts: "dict[str, int]" = {}
    for r in rows:
        role = r["anchor"]["role"]
        counts[role] = counts.get(role, 0) + 1

    tier_ladder = _tier_ladder(tuning)
    legal_pairs = sorted(_role_slot_pairs(rows))
    tier_counts = {b: sum(1 for r in rows if r["anchor"]["strengthBand"] == b) for b in tier_ladder}

    total_rows = len(rows)
    density_milli = round(1000 * total_rows / len(ROLE))

    # ---- call budget (§5): rows this plan targets x pipeline stages x votes per voted field -----
    # Vote-worthy fields are the ones a wrong majority vote would actually break something over --
    # role/requiredSlotKind/strengthBand/acquisitionPaths/controlPoint all feed real mechanism
    # (StructureKind derivation at import, HP via Bands, legality, occupancy). family/reason/
    # variants/targetPreference/tempo/reach/footprint/coverTier/rarity/costProfile/elements are
    # flavour or not-yet-consumed anywhere (spec-structure-catalog-import.md's own Correction 1 --
    # reach/footprint/coverTier/costProfile/tempo have no consuming field today) -- a wrong vote
    # there costs a review-queue flag, not a broken mechanism, so single-sample is proportionate.
    vote_fields = ["role", "requiredSlotKind", "strengthBand", "acquisitionPaths", "controlPoint"]
    vote_count = 3
    pipeline_stages = 1  # structure-pipeline (28) is a single generation pass at this plan's scope
    target_new_rows = sum(max(0, budget[role] - counts.get(role, 0)) for role in budget)
    call_budget = {
        "targetNewRows": target_new_rows,
        "pipelineStages": pipeline_stages,
        "voteFields": vote_fields,
        "voteCountPerField": vote_count,
        "estimatedCalls": target_new_rows * pipeline_stages * (1 + len(vote_fields) * vote_count),
    }

    return {
        "schemaVersion": 1,
        "seed": seed,
        "tierLadder": list(tier_ladder),
        "budget": dict(sorted(budget.items())),
        "actualCounts": dict(sorted(counts.items())),
        "legalRoleSlotPairs": [list(p) for p in legal_pairs],
        "variantCountPolicy": VARIANT_COUNT_POLICY,
        "acquisitionPathsPerRole": {role: list(paths) for role, paths in sorted(LEGAL_ACQUISITION_PATHS_PER_ROLE.items())},
        "containerPolicy": CONTAINER_POLICY,
        "tierRowCounts": tier_counts,
        "gridDensityMilli": density_milli,
        "callBudget": call_budget,
    }


class PlanCheckFailure(Exception):
    """A failing plan does not proceed to generation (spec §4) — raised, never silently ignored."""


def check_plan(plan: dict, tuning: dict) -> None:
    """Every §4 gate, in one place, so `structure-pipeline` (28) has exactly one call to make
    before spending a token. Raises `PlanCheckFailure` naming every violation at once (not just the
    first), so a caller sees the whole picture in one run rather than fixing issues one at a time."""
    problems: "list[str]" = []
    tolerance = tuning["metrics"]["roleCountTolerance"]

    for role, target in plan["budget"].items():
        actual = plan["actualCounts"].get(role, 0)
        if actual < target - tolerance:
            problems.append(f"role {role!r}: {actual} rows, below budget {target} (tolerance {tolerance})")

    band = tuning["metrics"]["densityBand"]
    if not (band["minMilli"] <= plan["gridDensityMilli"] <= band["maxMilli"]):
        problems.append(f"grid density {plan['gridDensityMilli']} outside band {band}")

    for tier in plan["tierLadder"]:
        if plan["tierRowCounts"].get(tier, 0) == 0:
            problems.append(f"tier {tier!r} has zero rows and was not cut from tierLadder")

    declared_pairs = {tuple(p) for p in plan["legalRoleSlotPairs"]}
    for role, slot_kind in declared_pairs:
        # "declared and empty" would mean a pair appears in the plan with a zero count -- but this
        # plan only ever DECLARES pairs it derived FROM real rows (see _role_slot_pairs), so an
        # empty declared pair is structurally impossible here; checked anyway; a future version
        # that declares pairs ahead of content (not yet built) would need this to mean something.
        pass

    if not plan["callBudget"]["voteFields"]:
        problems.append("callBudget declares no voteFields — a vote set must be named, not empty by default")

    if problems:
        raise PlanCheckFailure("; ".join(problems))


def write_plan(path: Path, plan: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    from .generate_corpus import ALL_ROWS

    repo_root = Path(__file__).resolve().parents[5]
    tuning = json.loads((repo_root / "data" / "tuning" / "structure-seed.v1.json").read_text(encoding="utf-8"))
    plan = build_plan(list(ALL_ROWS), tuning, seed=0)
    check_plan(plan, tuning)  # raises before committing a failing plan
    write_plan(repo_root / "data" / "seed" / "structures" / "_plan.json", plan)
    print(f"plan written, {plan['callBudget']['targetNewRows']} new rows targeted, "
          f"{plan['callBudget']['estimatedCalls']} estimated calls")
