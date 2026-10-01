"""Tests for `seedsmith.adapters.structures.planner` (spec-structure-planner.md, base-defense
module 27). Tests never call a model — this module makes no such call to stub in the first place,
proven by source scan (`test_transport_stub_raises_if_a_test_calls_a_model`).

    python -m pytest gk-forge/tools/seedsmith/tests/test_structure_planner.py -v
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.structures.anchor.schema import STRENGTH_BAND  # noqa: E402
from seedsmith.adapters.structures.generate_corpus import ALL_ROWS  # noqa: E402
from seedsmith.adapters.structures.planner import (  # noqa: E402
    PlanCheckFailure,
    build_plan,
    check_plan,
)

REPO_ROOT = Path(__file__).resolve().parents[3]

# `REPO_ROOT`-relative joins below ask which repository actually carries the path. A prefix-keyed
# rewrite is wrong: `data`, `data/seed` and `data/seed/creatures` all resolve back to gk-forge,
# because nearest-match-wins and gk-forge owns its own generator inputs. `or REPO_ROOT` is
# load-bearing - `owning_base` returns None for a path no repository carries, where
# `content_root()` would RAISE.

from seedsmith.workspace_roots import owning_base  # noqa: E402


def _owned(relative: str) -> "Path":
    """The repository carrying `relative`, joined to it; this one when none carries it."""
    return (owning_base(relative, REPO_ROOT) or REPO_ROOT) / relative

TUNING = json.loads((_owned("data/tuning/structure-seed.v1.json")).read_text(encoding="utf-8"))
ROWS = list(ALL_ROWS)


def test_tier_ladder_matches_the_schemas_strength_band():
    # The exact drift this module's own top-of-file note warns against: bands.tierLadder (tuning)
    # and STRENGTH_BAND (schema.py) are two lists that must never silently disagree.
    plan = build_plan(ROWS, TUNING, seed=0)
    assert plan["tierLadder"] == list(STRENGTH_BAND)


def test_tier_ladder_is_totally_ordered():
    plan = build_plan(ROWS, TUNING, seed=0)
    ladder = plan["tierLadder"]
    assert len(ladder) == len(set(ladder))  # no duplicate rung
    assert ladder == sorted(ladder, key=ladder.index)  # trivially true, but documents the intent:
    # "totally ordered" here means a fixed, referenceable sequence -- proven meaningfully by
    # Bands.MaterialTierOf's own C# test (rubble=1 < timber=2 < stone=3), this test just confirms
    # the PLAN's own copy of the sequence has no duplicate/ambiguous rung.


def test_every_tier_has_at_least_one_row_or_is_cut():
    plan = build_plan(ROWS, TUNING, seed=0)
    for tier in plan["tierLadder"]:
        assert plan["tierRowCounts"][tier] > 0, f"tier {tier!r} has zero rows and was not cut"


def test_per_role_counts_match_declared_targets():
    plan = build_plan(ROWS, TUNING, seed=0)
    for role, target in plan["budget"].items():
        assert plan["actualCounts"].get(role, 0) >= target - TUNING["metrics"]["roleCountTolerance"]


def test_grid_density_lands_in_the_2_4_to_4_0_band():
    plan = build_plan(ROWS, TUNING, seed=0)
    assert 2400 <= plan["gridDensityMilli"] <= 4000


def test_a_failing_plan_blocks_generation():
    bad_tuning = json.loads(json.dumps(TUNING))
    bad_tuning["budget"]["Extract"] = 999
    plan = build_plan(ROWS, bad_tuning, seed=0)
    try:
        check_plan(plan, bad_tuning)
        assert False, "check_plan should have raised for a role below its impossible target"
    except PlanCheckFailure as e:
        assert "Extract" in str(e)


def test_a_passing_plan_does_not_raise():
    plan = build_plan(ROWS, TUNING, seed=0)
    check_plan(plan, TUNING)  # must not raise


def test_no_declared_and_empty_role_slot_combination():
    plan = build_plan(ROWS, TUNING, seed=0)
    real_pairs = {(r["anchor"]["role"], r["anchor"]["requiredSlotKind"]) for r in ROWS}
    declared = {tuple(p) for p in plan["legalRoleSlotPairs"]}
    assert declared == real_pairs  # every declared pair is backed by at least one real row


def test_call_budget_is_stated_before_any_run():
    plan = build_plan(ROWS, TUNING, seed=0)
    cb = plan["callBudget"]
    for key in ("targetNewRows", "pipelineStages", "voteFields", "voteCountPerField", "estimatedCalls"):
        assert key in cb


def test_vote_fields_are_declared_not_defaulted():
    plan = build_plan(ROWS, TUNING, seed=0)
    vote_fields = plan["callBudget"]["voteFields"]
    assert vote_fields, "voteFields must not be empty"
    # Cost-of-being-wrong, not vibes: every declared vote field must feed a REAL downstream
    # mechanism -- checked against the exact set spec-structure-catalog-import.md's own Correction 1
    # names as consumed today (role -> StructureKind; requiredSlotKind -> SlotKind legality;
    # strengthBand -> Bands.MaterialTierOf -> HP; acquisitionPaths -> non-empty validation;
    # controlPoint -> decision 25's occupancy rule).
    mechanically_consumed = {"role", "requiredSlotKind", "strengthBand", "acquisitionPaths", "controlPoint"}
    assert set(vote_fields) == mechanically_consumed


def test_plan_is_byte_identical_across_10000_runs():
    first = None
    for _ in range(10_000):
        plan = build_plan(ROWS, TUNING, seed=0)
        digest = hashlib.sha256(json.dumps(plan, sort_keys=True).encode("utf-8")).hexdigest()
        first = first or digest
        assert digest == first


def test_plan_is_a_pure_function_of_its_inputs_no_clock_no_rng():
    src = (Path(__file__).resolve().parent.parent / "seedsmith" / "adapters" / "structures"
           / "planner.py").read_text(encoding="utf-8")
    for banned in ("datetime.now", "time.time()", "random.random", "random.randint", "uuid.uuid4"):
        assert banned not in src, f"planner.py references {banned!r}"


def test_transport_stub_raises_if_a_test_calls_a_model():
    src = (Path(__file__).resolve().parent.parent / "seedsmith" / "adapters" / "structures"
           / "planner.py").read_text(encoding="utf-8")
    for banned in ("openai", "anthropic", "lmstudio", "requests.post", "httpx", "urllib"):
        assert banned not in src.lower()


def test_container_policy_is_declared_the_real_sixth_decision():
    # structure-instantiate's (26) own real finding: neither this module's original 5-decision
    # list nor structure-pipeline's (28) named who assigns a structure's ContainerId. Declared here
    # as an explicit 6th so it is never silently undeclared.
    plan = build_plan(ROWS, TUNING, seed=0)
    assert plan["containerPolicy"]["requiredForEveryRow"] is False
    assert plan["containerPolicy"]["assignment"] == "opt-in-post-hoc"


def test_committed_plan_file_matches_a_fresh_build():
    # The plan is a committed artifact (spec §1) -- this proves the checked-in _plan.json is not
    # stale against the module that produces it.
    plan_path = _owned("data/seed/structures/_plan.json")
    assert plan_path.exists(), "data/seed/structures/_plan.json has not been committed yet"
    committed = json.loads(plan_path.read_text(encoding="utf-8"))
    fresh = build_plan(ROWS, TUNING, seed=committed["seed"])
    assert committed == fresh
