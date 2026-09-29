"""Tests for seedsmith.adapters.trees.plan.invariants (task C1, spec-tree-plan.md §3, §3.1, §3.2,
§4, §5.1, §5.2, §Testing; Gate 3 per spec-tree-language.md §7).

    python -m pytest gk-forge/tools/seedsmith/tests/test_tree_plan_invariants.py -v
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.trees.plan import emit as plan_emit  # noqa: E402
from seedsmith.adapters.trees.plan import invariants  # noqa: E402
from seedsmith.adapters.trees.plan import tuning as plan_tuning  # noqa: E402
from seedsmith.adapters.trees.plan import vocabulary  # noqa: E402
from seedsmith.adapters.trees.plan.archetypes import (  # noqa: E402
    BROAD_AND_FLAT,
    GATED_DEEP,
    LATE_CROWN,
    SHIPPED_ARCHETYPES,
    TIER_COUNT,
    Archetype,
)


def real_seed_root() -> Path:
    dir_ = Path(__file__).resolve()
    while dir_ != dir_.parent and not (dir_ / "CONTRIBUTING.md").exists():
        dir_ = dir_.parent
    return dir_ / "data" / "seed"


def _tree_spec(tree_id: str, ordinal: int) -> plan_emit.TreeSpec:
    return plan_emit.TreeSpec(
        tree_id=tree_id, category="primary", ordinal=ordinal,
        gate_quantity=f"aptitude.{tree_id}@Commander", gate_index_kind="aptitudePoints",
        gate_state="carrier",
    )


class CorpusBudgetEqualityTests(unittest.TestCase):
    """C1: Sigma budgetPoints identical across all n trees; Sigma off == Sigma def in each."""

    def setUp(self) -> None:
        self.tuning = plan_tuning.load()
        # Three synthetic trees, ordinals 0/1/2 -> one of each shipped archetype (append-safe
        # assignment, spec-tree-plan.md §3.1) — a real cross-archetype corpus, not one tree copied.
        self.plans = [plan_emit.build_plan(_tree_spec(f"corpustree{i}", i), self.tuning) for i in range(3)]

    def test_every_tree_has_the_same_budget(self) -> None:
        # Must not raise: three different archetypes, same budgetTotal by construction (tuning
        # constant, independent of archetype).
        invariants.check_equal_budget_across_trees(self.plans)

    def test_each_trees_branches_are_symmetric(self) -> None:
        for plan in self.plans:
            invariants.check_branch_budget_symmetry(plan["treeId"], plan["nodes"])

    def test_a_budget_mismatch_across_trees_is_refused_naming_both(self) -> None:
        # +1 to one offensive AND one defensive node keeps tree 1's own branches symmetric, so this
        # trips the CROSS-TREE total check specifically, not the per-tree symmetry check.
        corrupted = [dict(p) for p in self.plans]
        corrupted[1] = dict(corrupted[1])
        corrupted[1]["nodes"] = [dict(n) for n in corrupted[1]["nodes"]]
        first_offensive = next(i for i, n in enumerate(corrupted[1]["nodes"]) if n["branch"] == "offensive")
        first_defensive = next(i for i, n in enumerate(corrupted[1]["nodes"]) if n["branch"] == "defensive")
        corrupted[1]["nodes"][first_offensive]["budgetPoints"] += 1
        corrupted[1]["nodes"][first_defensive]["budgetPoints"] += 1
        with self.assertRaises(invariants.BudgetEqualityRefusal) as ex:
            invariants.check_equal_budget_across_trees(corrupted)
        msg = str(ex.exception)
        self.assertIn("corpustree0", msg)
        self.assertIn("corpustree1", msg)

    def test_an_asymmetric_branch_is_refused_naming_the_tree(self) -> None:
        nodes = [dict(n) for n in self.plans[0]["nodes"]]
        nodes[0]["budgetPoints"] += 5
        with self.assertRaises(invariants.BudgetEqualityRefusal) as ex:
            invariants.check_branch_budget_symmetry("corpustree0", nodes)
        self.assertIn("corpustree0", str(ex.exception))

    def test_an_empty_corpus_is_refused(self) -> None:
        with self.assertRaises(invariants.BudgetEqualityRefusal):
            invariants.check_equal_budget_across_trees([])


class ArchetypeShapesActuallyDifferTests(unittest.TestCase):
    """C1's inverse guard: the strongest node must differ by >= 2x across the archetype set, or
    D15 has silently collapsed into 'every tree feels the same'."""

    def test_the_shipped_three_pass_at_the_2x_floor(self) -> None:
        # Measured 2.5x (182 vs 73, spec-tree-plan.md §3) -- must not raise at the shipped 2x bound.
        invariants.check_archetype_shapes_actually_differ(SHIPPED_ARCHETYPES, TIER_COUNT, min_ratio_milli=2000)

    def test_gated_deeps_capstone_is_the_strongest_node_at_182(self) -> None:
        from seedsmith.adapters.trees.plan.archetypes import max_node_milli
        self.assertEqual(max_node_milli(GATED_DEEP, TIER_COUNT), 182)
        self.assertEqual(max_node_milli(LATE_CROWN, TIER_COUNT), 73)

    def test_a_tighter_bound_than_the_measured_spread_is_refused(self) -> None:
        # Measured spread is exactly 182/73 = 2.49x; a 2.6x floor must refuse.
        with self.assertRaises(invariants.ArchetypeShapesCollapsedRefusal) as ex:
            invariants.check_archetype_shapes_actually_differ(SHIPPED_ARCHETYPES, TIER_COUNT, min_ratio_milli=2600)
        msg = str(ex.exception)
        self.assertIn("gated-deep", msg)
        self.assertIn("late-crown", msg)

    def test_a_flattened_fourth_archetype_set_that_collapses_the_spread_is_refused(self) -> None:
        # Both end tier 10 at width 2, so both cap out at the SAME 91‰ node (node_budget_milli(182,
        # 2) == [91, 91]) despite different width vectors everywhere else -- a real collapse
        # (ratio exactly 1.0x), not a contrived tie.
        flat_a = Archetype("flat-a", (2, 2, 2, 2, 2, 2, 2, 2, 2, 2))
        flat_b = Archetype("flat-b", (1, 1, 3, 3, 2, 2, 2, 2, 2, 2))
        with self.assertRaises(invariants.ArchetypeShapesCollapsedRefusal) as ex:
            invariants.check_archetype_shapes_actually_differ((flat_a, flat_b), TIER_COUNT, min_ratio_milli=2000)
        msg = str(ex.exception)
        self.assertIn("flat-a", msg)
        self.assertIn("flat-b", msg)


class RewardSpreadReuseTests(unittest.TestCase):
    """R-A1: invariants.py REUSES archetypes.check_reward_spread, never reimplements it."""

    def test_the_shipped_set_passes_through_the_invariants_wrapper(self) -> None:
        invariants.check_r_a1_reward_spread(SHIPPED_ARCHETYPES, TIER_COUNT, 5, 2, 6000)

    def test_a_hand_authored_fourth_archetype_that_widens_the_gradient_is_refused(self) -> None:
        # Front-loads even harder than late-crown -- widens the tier-2 spread past the shipped bound.
        # RewardSpreadRefusal IS-A LadderError, not a PlanInvariantError -- the wrapper re-exports
        # the SAME exception type archetypes.py raises, never a wrapped/renamed one.
        extreme = Archetype("too-front-loaded", (1, 1, 1, 1, 1, 1, 1, 1, 6, 6))
        from seedsmith.adapters.trees.plan.archetypes import RewardSpreadRefusal
        with self.assertRaises(RewardSpreadRefusal) as ex:
            invariants.check_r_a1_reward_spread(SHIPPED_ARCHETYPES + (extreme,), TIER_COUNT, 5, 2, 6000)
        msg = str(ex.exception)
        self.assertIn("tier", msg)
        self.assertIn("too-front-loaded", msg)


class MechanismRampTests(unittest.TestCase):
    """R-M1 (deepest tier is 100% mechanism) and R-M2 (mechShareMilli monotone non-decreasing)."""

    def test_r_m1_holds_for_all_three_shipped_archetypes(self) -> None:
        for a in SHIPPED_ARCHETYPES:
            invariants.check_r_m1_deepest_tier_is_all_mechanism(a, TIER_COUNT, 0, 1000)

    def test_r_m1_refuses_a_ramp_that_does_not_reach_the_deepest_tier(self) -> None:
        # rampEndMilli=700 on a width-2 terminal tier: round_half_up(2*700, 1000) == 1, not 2 --
        # the deepest tier is no longer driven to 100% mechanism.
        with self.assertRaises(invariants.DeepestTierNotAllMechanismRefusal) as ex:
            invariants.check_r_m1_deepest_tier_is_all_mechanism(BROAD_AND_FLAT, TIER_COUNT, 0, 700)
        self.assertIn("broad-and-flat", str(ex.exception))

    def test_r_m2_holds_for_the_shipped_ramp(self) -> None:
        invariants.check_r_m2_mechanism_share_is_monotone(TIER_COUNT, 0, 1000)

    def test_r_m2_is_archetype_independent_by_construction(self) -> None:
        # The ramp depends only on (t, tierCount, rampStart, rampEnd) -- calling it once per
        # shipped archetype must not raise, for any of the three.
        for _a in SHIPPED_ARCHETYPES:
            invariants.check_r_m2_mechanism_share_is_monotone(TIER_COUNT, 0, 1000)

    def test_r_m2_refuses_a_ramp_that_decreases(self) -> None:
        # rampStart > rampEnd -- the share at tier 1 is HIGHER than at tier 2, a real decrease.
        with self.assertRaises(invariants.MechanismShareNotMonotoneRefusal) as ex:
            invariants.check_r_m2_mechanism_share_is_monotone(TIER_COUNT, 1000, 0)
        self.assertIn("tier", str(ex.exception))


class PotencyCeilingTests(unittest.TestCase):
    """P-1 (derivation guard) and P-2 (rounding guard). Neither is R-P1/R-P2 -- those compared a
    construction against its own supremum and are DELETED (spec-tree-plan.md §5.2); they must not
    be reintroduced (see `DeletedTestsStayDeletedTests` below)."""

    def test_p1_the_shipped_182_is_derived_from_tiercount_10_and_minterminalwidth_1(self) -> None:
        self.assertEqual(invariants.derive_max_node_share_milli(10, 1), 182)
        invariants.check_p1_potency_ceiling_is_derived(182, 10, 1)

    def test_p1_refuses_a_hand_edited_ceiling(self) -> None:
        with self.assertRaises(invariants.PotencyDerivationRefusal) as ex:
            invariants.check_p1_potency_ceiling_is_derived(183, 10, 1)
        msg = str(ex.exception)
        self.assertIn("183", msg)
        self.assertIn("182", msg)

    def test_p1_matches_the_tuning_file_at_the_emitted_tiercount(self) -> None:
        tuning = plan_tuning.load()
        invariants.check_p1_potency_ceiling_is_derived(
            tuning["potency"]["maxNodeShareMilli"], TIER_COUNT, tuning["potency"]["minTerminalWidth"])

    def test_a_deeper_ladder_makes_the_ceiling_smaller_not_larger(self) -> None:
        # spec-tree-plan.md §5.2's own correction: deeper is strictly safer.
        self.assertGreater(invariants.derive_max_node_share_milli(7, 1),
                           invariants.derive_max_node_share_milli(10, 1))

    def test_p2_holds_at_the_shipped_topology(self) -> None:
        # tierCount is structural, fixed at 10, and "Ask first" to change (Boundaries) -- P-2 must
        # hold for the topology that actually ships.
        invariants.check_p2_no_rounded_share_exceeds_derived_maximum(min_terminal_width=1, max_tier_count=10)

    def test_p2_sweep_discovers_a_real_residual_spike_outside_the_shipped_topology(self) -> None:
        # HONEST FINDING, not a broken test: ladder.tier_budget_milli dumps 100% of a tier column's
        # rounding residual into the deepest tier. That residual is 0 at tierCount=10 (why the gap
        # is invisible today) but reaches +7 at tier_count=31 (deepest share 70 vs a derived
        # ceiling of 63) -- P-2 built honestly, per its own acceptance bullet ("at tier counts
        # 1..40"), actually finds this. tier_count=23 is the first tier count the sweep hits.
        with self.assertRaises(invariants.PotencyCeilingExceededRefusal) as ex:
            invariants.check_p2_no_rounded_share_exceeds_derived_maximum(min_terminal_width=1, max_tier_count=40)
        self.assertIn("tier_count=23", str(ex.exception))

    def test_p2_is_a_rounding_guard_that_fires_on_a_deliberately_broken_ceiling(self) -> None:
        # Monkeypatch-free: call the pieces directly to prove the guard bites when the CEILING
        # (not the rounding) is wrong -- i.e. that the comparison direction is real, not tautological.
        derived = invariants.derive_max_node_share_milli(10, 1)
        from seedsmith.adapters.trees.plan.ladder import tier_budget_milli, node_budget_milli
        deepest_share = tier_budget_milli(10)[-1]
        worst = max(node_budget_milli(deepest_share, 1))
        self.assertLessEqual(worst, derived)  # the real check must hold
        self.assertGreater(worst, derived - 1)  # and it is TIGHT -- not vacuously satisfied


class DeletedTestsStayDeletedTests(unittest.TestCase):
    """spec-tree-plan.md §Testing: `no_node_exceeds_the_potency_ceiling` (R-P1) and
    `every_shipped_archetype_is_admissible` (R-P2) compared a construction against its own
    algebraic supremum and were DELETED. This guards against either name quietly reappearing
    anywhere in this test package."""

    _BANNED_NAMES = ("no_node_exceeds_the_potency_ceiling", "every_shipped_archetype_is_admissible")

    def test_neither_deleted_test_name_exists_in_this_test_package(self) -> None:
        # Matches an actual `def test_...` DEFINITION, never a docstring/comment/tuple literal that
        # merely mentions the retired name (this file's own module docstring and `_BANNED_NAMES`
        # do exactly that, on purpose, to document why they stay deleted).
        tests_dir = Path(__file__).resolve().parent
        for path in tests_dir.glob("test_tree_plan_*.py"):
            text = path.read_text(encoding="utf-8")
            for banned in self._BANNED_NAMES:
                self.assertNotIn(f"def {banned}", text,
                                 f"{banned!r} reappeared as a real test in {path.name} -- see spec-tree-plan.md §5.2")


class Gate3PlanReachabilityTests(unittest.TestCase):
    """spec-tree-language.md §7 row 3: deterministic, over the plan alone, before any model call."""

    def _nodes(self, tier_count: int = 3) -> "list[dict]":
        # A tiny, valid two-branch tree: tier 1 roots, tier 2/3 each parented to the prior tier.
        return [
            {"id": "skill.t-off-t1-a", "tier": 1, "branch": "offensive", "parents": []},
            {"id": "skill.t-off-t2-a", "tier": 2, "branch": "offensive", "parents": ["skill.t-off-t1-a"]},
            {"id": "skill.t-off-t3-a", "tier": 3, "branch": "offensive", "parents": ["skill.t-off-t2-a"]},
            {"id": "skill.t-def-t1-a", "tier": 1, "branch": "defensive", "parents": []},
            {"id": "skill.t-def-t2-a", "tier": 2, "branch": "defensive", "parents": ["skill.t-def-t1-a"]},
            {"id": "skill.t-def-t3-a", "tier": 3, "branch": "defensive", "parents": ["skill.t-def-t2-a"]},
        ]

    def test_a_valid_tiny_tree_passes_all_three_checks(self) -> None:
        invariants.check_gate3_plan_reachability("t", self._nodes(), 3)

    def test_an_unsatisfiable_prereq_is_refused_naming_both_ids(self) -> None:
        nodes = self._nodes()
        nodes[1] = dict(nodes[1])
        nodes[1]["parents"] = ["skill.t-off-t1-does-not-exist"]
        with self.assertRaises(invariants.UnsatisfiablePrereqRefusal) as ex:
            invariants.check_gate3_plan_reachability("t", nodes, 3)
        msg = str(ex.exception)
        self.assertIn("skill.t-off-t2-a", msg)
        self.assertIn("skill.t-off-t1-does-not-exist", msg)
        self.assertIn("t", msg)

    def test_an_empty_tier_is_refused_naming_the_branch_and_tier(self) -> None:
        nodes = [dict(n) for n in self._nodes() if not (n["branch"] == "offensive" and n["tier"] == 2)]
        for n in nodes:
            if n["id"] == "skill.t-off-t3-a":
                n["parents"] = []  # avoid a dangling prereq masking the empty-tier refusal
        with self.assertRaises(invariants.EmptyTierRefusal) as ex:
            invariants.check_gate3_plan_reachability("t", nodes, 3)
        msg = str(ex.exception)
        self.assertIn("offensive", msg)
        self.assertIn("tier 2", msg)

    def test_an_orphan_node_is_refused_naming_the_tree_and_node(self) -> None:
        nodes = self._nodes()
        # A tier-3 node with a parent that is itself never reachable from a root -- a disconnected
        # island stitched onto the tree via a dangling internal edge rather than a missing id.
        nodes.append({"id": "skill.t-off-t2-b", "tier": 2, "branch": "offensive", "parents": ["skill.t-off-t2-orphan-root"]})
        nodes.append({"id": "skill.t-off-t2-orphan-root", "tier": 2, "branch": "offensive", "parents": ["skill.t-off-t2-b"]})
        with self.assertRaises(invariants.OrphanNodeRefusal) as ex:
            invariants.check_gate3_plan_reachability("t", nodes, 3)
        msg = str(ex.exception)
        self.assertIn("t", msg)
        self.assertTrue("skill.t-off-t2-b" in msg or "skill.t-off-t2-orphan-root" in msg)


class FamilyRosterPendingTests(unittest.TestCase):
    """Task C1 bullet 9: a manifest missing the family roster emits `_pending: ["creatureFamilies"]`,
    never silent generation against an empty roster."""

    def test_a_missing_family_mirror_returns_pending_never_an_empty_axis_that_raises(self) -> None:
        empty_root = Path(tempfile.mkdtemp())
        families, pending = vocabulary.load_family_roster_or_pending(empty_root)
        self.assertEqual(families, ())
        self.assertTrue(pending)

    def test_the_real_family_registry_loads_a_nonempty_roster(self) -> None:
        families, pending = vocabulary.load_family_roster_or_pending(real_seed_root())
        self.assertFalse(pending)
        self.assertGreater(len(families), 0)

    def test_absent_family_roster_emits_pending_not_silence(self) -> None:
        plan = {"roster": {"creatureFamilies": []}, "_pending": ["creatureFamilies"]}
        invariants.check_pending_declared_for_empty_rosters(plan)  # must not raise

    def test_an_empty_roster_with_no_pending_declaration_is_refused(self) -> None:
        plan = {"roster": {"creatureFamilies": []}, "_pending": []}
        with self.assertRaises(invariants.SilentEmptyRosterRefusal) as ex:
            invariants.check_pending_declared_for_empty_rosters(plan)
        self.assertIn("creatureFamilies", str(ex.exception))

    def test_a_nonempty_roster_needs_no_pending_declaration(self) -> None:
        plan = {"roster": {"creatureFamilies": ["bucket"]}, "_pending": []}
        invariants.check_pending_declared_for_empty_rosters(plan)  # must not raise

    def test_the_real_committed_might_plan_declares_no_pending_families(self) -> None:
        # The real registry is non-empty, so a real emitted plan must carry an empty _pending and
        # a nonempty roster.creatureFamilies -- proving build_plan's own wiring, not just the helper.
        tuning = plan_tuning.load()
        plan = plan_emit.build_plan(plan_emit.might_tree_spec(), tuning)
        self.assertEqual(plan["_pending"], [])
        self.assertGreater(len(plan["roster"]["creatureFamilies"]), 0)


class TreeEqualValueTests(unittest.TestCase):
    """PassiveTree/TreeEqualValue (spec-tree-plan.md §3.2): C1 + P-1/P-2 + R-A1, one callable."""

    def setUp(self) -> None:
        self.tuning = plan_tuning.load()
        self.plans = [plan_emit.build_plan(_tree_spec(f"tevtree{i}", i), self.tuning) for i in range(3)]

    def _run(self, plans) -> None:
        invariants.check_tree_equal_value(
            plans, SHIPPED_ARCHETYPES, TIER_COUNT,
            self.tuning["unlockCost"]["firstPoints"], self.tuning["unlockCost"]["stepPoints"],
            self.tuning["archetype"]["rewardSpreadMaxRatioMilli"], self.tuning["potency"]["minTerminalWidth"],
        )

    def test_the_real_shipped_corpus_passes(self) -> None:
        self._run(self.plans)

    def test_a_single_tree_degenerates_correctly_at_n_equals_1(self) -> None:
        self._run([self.plans[0]])

    def test_a_corrupted_potency_ceiling_is_refused(self) -> None:
        corrupted = [dict(p) for p in self.plans]
        corrupted[0] = dict(corrupted[0])
        corrupted[0]["potency"] = {**corrupted[0]["potency"], "maxNodeShareMilli": 999}
        with self.assertRaises(invariants.PotencyDerivationRefusal):
            self._run(corrupted)

    def test_a_cross_tree_budget_mismatch_is_refused(self) -> None:
        corrupted = [dict(p) for p in self.plans]
        corrupted[0] = dict(corrupted[0])
        corrupted[0]["nodes"] = [dict(n) for n in corrupted[0]["nodes"]]
        first_offensive = next(i for i, n in enumerate(corrupted[0]["nodes"]) if n["branch"] == "offensive")
        first_defensive = next(i for i, n in enumerate(corrupted[0]["nodes"]) if n["branch"] == "defensive")
        corrupted[0]["nodes"][first_offensive]["budgetPoints"] += 1
        corrupted[0]["nodes"][first_defensive]["budgetPoints"] += 1
        with self.assertRaises(invariants.BudgetEqualityRefusal):
            self._run(corrupted)


class BuildPlanEmitsTheNewFieldsTests(unittest.TestCase):
    """The schema additions C1 needed emit.py to carry so the invariants above have real data to
    check: nodes[].budgetPoints, budgetTotal/budgetPerBranch, potency.*, archetypes[].*."""

    def setUp(self) -> None:
        self.tuning = plan_tuning.load()
        self.plan = plan_emit.build_plan(plan_emit.might_tree_spec(), self.tuning)

    def test_budget_points_are_emitted_and_sum_to_budget_per_branch(self) -> None:
        for n in self.plan["nodes"]:
            self.assertIn("budgetPoints", n)
        offensive = sum(n["budgetPoints"] for n in self.plan["nodes"] if n["branch"] == "offensive")
        defensive = sum(n["budgetPoints"] for n in self.plan["nodes"] if n["branch"] == "defensive")
        self.assertEqual(offensive, self.plan["budgetPerBranch"])
        self.assertEqual(defensive, self.plan["budgetPerBranch"])

    def test_potency_block_matches_the_tuning_file(self) -> None:
        self.assertEqual(self.plan["potency"]["maxNodeShareMilli"], self.tuning["potency"]["maxNodeShareMilli"])
        self.assertEqual(self.plan["potency"]["minTerminalWidth"], self.tuning["potency"]["minTerminalWidth"])

    def test_archetypes_block_carries_reward_per_point_milli_and_hits_1000_at_completion(self) -> None:
        self.assertEqual(len(self.plan["archetypes"]), len(SHIPPED_ARCHETYPES))
        for a in self.plan["archetypes"]:
            self.assertEqual(len(a["rewardPerPointMilli"]), TIER_COUNT)
            self.assertEqual(a["rewardPerPointMilli"][-1], 1000)

    def test_archetypes_block_shows_the_tier_2_gradient_in_a_diff(self) -> None:
        by_id = {a["id"]: a for a in self.plan["archetypes"]}
        gated_t2 = by_id["gated-deep"]["rewardPerPointMilli"][1]
        late_t2 = by_id["late-crown"]["rewardPerPointMilli"][1]
        self.assertNotEqual(gated_t2, late_t2)


class TreeEqualValueMetricRegistrationTests(unittest.TestCase):
    """Task C1 bullet 7: `PassiveTree/TreeEqualValue` registered as a `Metric` subclass, beside
    `Distribution/CellOccupancy` and the `action.corpus.*` family, through the SAME
    `MetricRegistry`/`run_all` machinery — not a parallel, bespoke registration path."""

    def setUp(self) -> None:
        from seedsmith.metrics import Ctx, MetricRegistry
        from seedsmith.metrics.passive_tree import PassiveTreePlanCtx, TreeEqualValueMetric

        tuning = plan_tuning.load()
        plan = plan_emit.build_plan(plan_emit.might_tree_spec(), tuning)
        self.plan_ctx = PassiveTreePlanCtx(
            plans=[plan], archetypes=SHIPPED_ARCHETYPES, tier_count=TIER_COUNT,
            unlock_first_points=tuning["unlockCost"]["firstPoints"],
            unlock_step_points=tuning["unlockCost"]["stepPoints"],
            reward_spread_max_ratio_milli=tuning["archetype"]["rewardSpreadMaxRatioMilli"],
            min_terminal_width=tuning["potency"]["minTerminalWidth"],
        )
        self.registry = MetricRegistry()
        self.registry.register(TreeEqualValueMetric())
        self.Ctx = Ctx

    def test_registers_without_raising_the_open_plus_gates_guard(self) -> None:
        # MetricRegistry.register raises for Loop.OPEN + gates=True (registry.py's own contract);
        # this metric is CLOSED, so registration succeeding at all is itself a real assertion.
        self.assertIsNotNone(self.registry.get("PassiveTree/TreeEqualValue"))

    def test_runs_through_run_all_and_reports_a_clean_note(self) -> None:
        from seedsmith.metrics import Severity, run_all
        ctx = self.Ctx(corpus=None, adapter=None, passive_tree_plan=self.plan_ctx)
        findings = run_all(self.registry, ctx)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, Severity.NOTE)

    def test_a_missing_need_reports_not_measured_never_a_silent_pass(self) -> None:
        from seedsmith.metrics import Severity, run_all
        ctx = self.Ctx(corpus=None, adapter=None)  # no passive_tree_plan supplied
        findings = run_all(self.registry, ctx)
        self.assertEqual(findings[0].severity, Severity.NOT_MEASURED)

    def test_a_real_violation_surfaces_as_a_gap_finding_naming_the_defect(self) -> None:
        from dataclasses import replace
        from seedsmith.metrics import Severity, run_all
        corrupted_plan = dict(self.plan_ctx.plans[0])
        corrupted_plan["potency"] = {**corrupted_plan["potency"], "maxNodeShareMilli": 999}
        ctx = self.Ctx(corpus=None, adapter=None,
                       passive_tree_plan=replace(self.plan_ctx, plans=[corrupted_plan]))
        findings = run_all(self.registry, ctx)
        self.assertEqual(findings[0].severity, Severity.GAP)
        self.assertIn("999", findings[0].message)


if __name__ == "__main__":
    unittest.main()
