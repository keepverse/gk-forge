"""Tests for seedsmith.adapters.trees.plan.archetypes (task B1, spec-tree-plan.md §3.1, §4).

    python -m pytest gk-forge/tools/seedsmith/tests/test_tree_plan_budget.py -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.trees.plan.archetypes import (  # noqa: E402
    BROAD_AND_FLAT,
    GATED_DEEP,
    LATE_CROWN,
    SHIPPED_ARCHETYPES,
    Archetype,
    RewardSpreadRefusal,
    assign_archetype,
    check_reward_spread,
    mechanism_nodes,
    reward_per_skill_point,
)
from seedsmith.adapters.trees.plan.ladder import LadderError  # noqa: E402


class ArchetypeShapeTests(unittest.TestCase):
    def test_all_three_shipped_archetypes_sum_to_twenty(self) -> None:
        for a in SHIPPED_ARCHETYPES:
            self.assertEqual(sum(a.widths), 20, a.id)

    def test_a_malformed_width_vector_is_refused_at_construction(self) -> None:
        with self.assertRaises(LadderError):
            Archetype("bad", (2,) * 9)  # wrong length
        with self.assertRaises(LadderError):
            Archetype("bad", (1,) * 10)  # sums to 10, not 20

    def test_assignment_is_deterministic_and_append_safe(self) -> None:
        self.assertIs(assign_archetype(0), BROAD_AND_FLAT)
        self.assertIs(assign_archetype(1), GATED_DEEP)
        self.assertIs(assign_archetype(2), LATE_CROWN)
        self.assertIs(assign_archetype(3), BROAD_AND_FLAT)  # wraps, append-safe
        # Appending a 4th archetype must not move ordinal 0/1/2's assignment.
        four = SHIPPED_ARCHETYPES + (Archetype("extra", (2,) * 10),)
        self.assertIs(assign_archetype(0, four), BROAD_AND_FLAT)
        self.assertIs(assign_archetype(1, four), GATED_DEEP)
        self.assertIs(assign_archetype(2, four), LATE_CROWN)


class MechanismRampTests(unittest.TestCase):
    def test_broad_and_flat_matches_the_spec_prose_example(self) -> None:
        # "broad-and-flat puts one of two nodes at tiers 4-7 in the mechanism class"
        mech = mechanism_nodes(BROAD_AND_FLAT, 10, 0, 1000)
        for t in (4, 5, 6, 7):
            self.assertEqual(mech[t - 1], 1, f"tier {t}")

    def test_gated_deep_matches_the_spec_prose_example(self) -> None:
        # "gated-deep one of three at tier 3"
        mech = mechanism_nodes(GATED_DEEP, 10, 0, 1000)
        self.assertEqual(mech[2], 1)

    def test_r_m1_the_deepest_tier_is_fully_mechanism_for_every_archetype(self) -> None:
        for a in SHIPPED_ARCHETYPES:
            mech = mechanism_nodes(a, 10, 0, 1000)
            self.assertEqual(mech[-1], a.widths[-1], a.id)

    def test_tier_one_is_pure_magnitude_at_rampstart_zero(self) -> None:
        for a in SHIPPED_ARCHETYPES:
            mech = mechanism_nodes(a, 10, 0, 1000)
            self.assertEqual(mech[0], 0, a.id)

    def test_mechanism_count_never_exceeds_the_tiers_own_width(self) -> None:
        for a in SHIPPED_ARCHETYPES:
            mech = mechanism_nodes(a, 10, 0, 1000)
            for t in range(10):
                self.assertLessEqual(mech[t], a.widths[t])


class RewardSpreadTests(unittest.TestCase):
    def test_spread_matches_the_spec_table_at_every_tier(self) -> None:
        # spec-tree-plan.md §3.1's own table, first=5, step=2.
        expected_spread_x100 = [500, 600, 412, 300, 244, 212, 192, 161, 124, 100]
        for t in range(1, 11):
            ratios = {a.id: reward_per_skill_point(a, t, 5, 2) for a in SHIPPED_ARCHETYPES}
            vals = {aid: n / d for aid, (n, d) in ratios.items()}
            spread = max(vals.values()) / min(vals.values())
            self.assertAlmostEqual(spread * 100, expected_spread_x100[t - 1], delta=15,
                                   msg=f"tier {t}: got {spread:.2f}x")

    def test_spread_is_exactly_1_at_completion(self) -> None:
        ratios = [reward_per_skill_point(a, 10, 5, 2) for a in SHIPPED_ARCHETYPES]
        # All three must reduce to the SAME fraction at tier 10 (b cancels identically).
        vals = {n / d for n, d in ratios}
        self.assertEqual(len(vals), 1)

    def test_the_shipped_set_passes_at_the_shipped_bound_of_6000(self) -> None:
        # Must not raise — the shipped three pass at equality (measured max is exactly 6.0x at tier 2).
        check_reward_spread(SHIPPED_ARCHETYPES, 10, 5, 2, 6000)

    def test_a_tighter_bound_refuses_naming_the_tier_and_both_archetypes(self) -> None:
        with self.assertRaises(RewardSpreadRefusal) as ex:
            check_reward_spread(SHIPPED_ARCHETYPES, 10, 5, 2, 5000)  # tier 2 is 6.0x, exceeds 5.0x
        msg = str(ex.exception)
        self.assertIn("tier 2", msg)
        self.assertIn("late-crown", msg)
        self.assertIn("gated-deep", msg)

    def test_a_fourth_archetype_that_widens_the_spread_is_refused(self) -> None:
        # A pathological archetype that front-loads even harder than late-crown widens tier-2 spread.
        extreme = Archetype("too-front-loaded", (1, 1, 1, 1, 1, 1, 1, 1, 6, 6))
        with self.assertRaises(RewardSpreadRefusal):
            check_reward_spread(SHIPPED_ARCHETYPES + (extreme,), 10, 5, 2, 6000)

    def test_reward_check_is_walked_at_every_tier_not_only_completion(self) -> None:
        # The historical defect: a check that only looks at t=tierCount cannot see this. Confirm
        # the walk actually visits an intermediate tier by constructing a set whose ONLY violation
        # is mid-ladder (tier 2) while tier 10 (by construction) always agrees for any legal set.
        with self.assertRaises(RewardSpreadRefusal) as ex:
            check_reward_spread(SHIPPED_ARCHETYPES, 10, 5, 2, 5990)  # just below the real 6.0x at tier 2
        self.assertIn("tier 2", str(ex.exception))


if __name__ == "__main__":
    unittest.main()
