"""Tests for seedsmith.adapters.trees.plan.ladder (task B1, spec-tree-plan.md §2-3).

Every expected value here is copied from spec-tree-plan.md's own worked tables — this is a
known-answer test suite, not a suite that asserts whatever the code happens to produce.

    python -m pytest gk-forge/tools/seedsmith/tests/test_tree_plan_ladder.py -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.trees.plan.ladder import (  # noqa: E402
    LadderError,
    TierLadder,
    cumulative_power,
    node_budget_milli,
    req,
    tier_budget_milli,
)


class ReqTests(unittest.TestCase):
    def test_req_matches_the_spec_table_exactly(self) -> None:
        # spec-tree-plan.md §2's own computed table, k=5.
        expected = [5, 15, 30, 50, 75, 105, 140, 180, 225, 275]
        self.assertEqual([req(t, 5) for t in range(1, 11)], expected)

    def test_req_is_always_an_exact_integer(self) -> None:
        # t(t+1) is a product of consecutive integers, always even, so k*t(t+1)/2 never rounds.
        for k in range(1, 20):
            for t in range(1, 50):
                self.assertEqual(req(t, k) * 2, k * t * (t + 1))

    def test_tier_below_one_is_refused(self) -> None:
        with self.assertRaises(LadderError):
            req(0, 5)


class RewardPerPointTests(unittest.TestCase):
    def test_reward_per_point_is_exactly_b_over_k_at_every_tier(self) -> None:
        # D26's claim: W(T)/req(T) = b/k at every tier, not only at completion.
        ladder = TierLadder(tier_count=10, req_scale_points=5, b=1)
        for t in range(1, 11):
            num, den = ladder.reward_per_point(t)
            self.assertEqual((num, den), (1, 5), f"tier {t}")


class TierBudgetTests(unittest.TestCase):
    def test_tier_budget_matches_the_spec_table_at_ten_tiers(self) -> None:
        expected = (18, 36, 55, 73, 91, 109, 127, 145, 164, 182)
        self.assertEqual(tier_budget_milli(10), expected)

    def test_tier_budget_always_sums_to_1000(self) -> None:
        for tier_count in range(1, 41):
            self.assertEqual(sum(tier_budget_milli(tier_count)), 1000, f"tier_count={tier_count}")

    def test_the_width_vector_never_enters_this_sum(self) -> None:
        # spec-tree-plan.md §3: Sum_t tierBudget[t] = B_b * (Sum_t t)/T_tri = B_b, an identity in T
        # that holds regardless of any archetype's width vector — asserted by NOT taking widths as
        # an argument at all (a signature check, not just a value check).
        import inspect
        sig = inspect.signature(tier_budget_milli)
        self.assertEqual(list(sig.parameters), ["tier_count"])


class NodeBudgetSplitTests(unittest.TestCase):
    """Every one of these is copied from spec-tree-plan.md §3's worked tables for the three shipped
    archetypes — verified digit-for-digit before ladder.py was written, replayed here as tests."""

    def test_broad_and_flat_every_tier(self) -> None:
        tier_shares = tier_budget_milli(10)
        widths = [2] * 10
        expected = [(9, 9), (18, 18), (27, 28), (36, 37), (45, 46), (54, 55), (63, 64), (72, 73),
                   (82, 82), (91, 91)]
        for i in range(10):
            self.assertEqual(node_budget_milli(tier_shares[i], widths[i]), expected[i], f"tier {i+1}")

    def test_gated_deep_every_tier(self) -> None:
        tier_shares = tier_budget_milli(10)
        widths = [3, 3, 3, 2, 2, 2, 2, 1, 1, 1]
        expected = [(6, 6, 6), (12, 12, 12), (18, 18, 19), (36, 37), (45, 46), (54, 55), (63, 64),
                   (145,), (164,), (182,)]
        for i in range(10):
            self.assertEqual(node_budget_milli(tier_shares[i], widths[i]), expected[i], f"tier {i+1}")

    def test_late_crown_every_tier(self) -> None:
        tier_shares = tier_budget_milli(10)
        widths = [1, 1, 2, 2, 2, 2, 2, 2, 3, 3]
        expected = [(18,), (36,), (27, 28), (36, 37), (45, 46), (54, 55), (63, 64), (72, 73),
                   (54, 54, 56), (60, 60, 62)]
        for i in range(10):
            self.assertEqual(node_budget_milli(tier_shares[i], widths[i]), expected[i], f"tier {i+1}")

    def test_a_tier_always_sums_to_its_own_share_regardless_of_width(self) -> None:
        for share in range(0, 300):
            for width in range(1, 6):
                self.assertEqual(sum(node_budget_milli(share, width)), share)

    def test_the_last_node_never_gets_less_than_the_others(self) -> None:
        # base = share // width, remainder >= 0 is always added to the last node.
        for share in range(0, 300):
            for width in range(1, 6):
                parts = node_budget_milli(share, width)
                self.assertTrue(all(p <= parts[-1] for p in parts))


class CumulativePowerTests(unittest.TestCase):
    def test_matches_the_spec_table(self) -> None:
        expected = [1, 3, 6, 10, 15, 21, 28, 36, 45, 55]
        self.assertEqual([cumulative_power(t, 1) for t in range(1, 11)], expected)


if __name__ == "__main__":
    unittest.main()
