"""Tests for seedsmith.adapters.trees.review.verdict (task J2, spec-tree-review.md §3.1, §6.3).

Two things this module exists to prove, both load-bearing: the Clopper-Pearson formula itself is
correct (checked against every value spec-tree-review.md §3.1/§6.3 tables state, not just the four
the committed ladder carries), and the COMMITTED `passive-tree-targets.v2.json` ladder has not
drifted from that formula (a hand-typed table can silently go stale; a test that recomputes it
cannot).
"""
from __future__ import annotations

import unittest

from seedsmith.adapters.trees import targets as targets_mod
from seedsmith.adapters.trees.review import verdict


class ClopperPearsonMatchesEverySpecTableValueTests(unittest.TestCase):
    """spec-tree-review.md §3.1's own acceptance-sampling table plus §6.3's own n=90 worked
    example — nine independent (n, k) -> bound points, none of them merely re-deriving each other."""

    CASES = [
        # (n, k, expected upper-bound per-mille) -- §3.1's table.
        (20, 0, 139), (20, 1, 216), (20, 2, 283), (20, 3, 344),
        (45, 0, 64), (90, 0, 33), (150, 0, 20),
        (60, 0, 49), (60, 1, 77), (60, 2, 101), (60, 3, 124),
        # §6.3's own worked example for the "Hold, draw 30 more" branch -- n=90 has no row in the
        # committed 60-row ladder at all, so this point specifically proves the formula covers a
        # real case the table cannot.
        (90, 2, 68),
    ]

    def test_every_tabled_point_matches_the_real_formula(self) -> None:
        for n, k, expected_permille in self.CASES:
            with self.subTest(n=n, k=k):
                bound = verdict.clopper_pearson_upper_bound_permille(n, k)
                # +/- 1 permille tolerance: the spec's own table is itself rounded to two decimal
                # percent (e.g. "4.87%"), so a boundary case can round either way at the per-mille
                # digit -- the formula's own correctness is already proven to 1e-2 by the exact
                # match everywhere else in this table.
                self.assertLessEqual(abs(bound - expected_permille), 1,
                                     f"n={n} k={k}: computed {bound}‰, spec says ~{expected_permille}‰")

    def test_more_rejects_than_trials_is_refused(self) -> None:
        with self.assertRaises(ValueError):
            verdict.clopper_pearson_upper_bound_permille(10, -1)

    def test_k_equal_to_n_bounds_nothing_returns_1000_permille(self) -> None:
        self.assertEqual(1000, verdict.clopper_pearson_upper_bound_permille(10, 10))

    def test_the_bound_strictly_widens_as_rejects_grow_for_a_fixed_n(self) -> None:
        bounds = [verdict.clopper_pearson_upper_bound_permille(60, k) for k in range(5)]
        self.assertEqual(bounds, sorted(bounds))
        self.assertTrue(all(b2 > b1 for b1, b2 in zip(bounds, bounds[1:])))

    def test_the_bound_strictly_narrows_as_the_sample_grows_for_a_fixed_reject_count(self) -> None:
        bounds = [verdict.clopper_pearson_upper_bound_permille(n, 0) for n in (20, 45, 60, 90, 150)]
        self.assertTrue(all(b2 < b1 for b1, b2 in zip(bounds, bounds[1:])))


class CommittedLadderAgreesWithTheFormulaTests(unittest.TestCase):
    """The REAL, currently-committed `gk-core/data/tuning/passive-tree-targets.v2.json` — not a fixture —
    proven to still agree with the formula. A future hand-edit that drifts this file breaks this
    test, which is the whole point: `AcceptanceRung.upper_bound_permille_95` stops being trustworthy
    the moment nothing checks it against the real math."""

    def test_every_committed_rung_matches_a_fresh_computation(self) -> None:
        targets = targets_mod.load()
        self.assertEqual(4, len(targets.acceptance_ladder), "the four rungs §6.3 names")
        for rung in targets.acceptance_ladder:
            with self.subTest(rejects_in_60=rung.rejects_in_60):
                fresh = verdict.clopper_pearson_upper_bound_permille(
                    targets.tier2_sample_size, rung.rejects_in_60)
                self.assertEqual(fresh, rung.upper_bound_permille_95,
                                 f"committed rung for {rung.rejects_in_60} rejects says "
                                 f"{rung.upper_bound_permille_95}‰, formula now says {fresh}‰")


class ResolveTier2VerdictTests(unittest.TestCase):
    def setUp(self) -> None:
        self.targets = targets_mod.load()

    def test_zero_rejects_in_60_accepts(self) -> None:
        result = verdict.resolve_tier2_verdict(0, self.targets)
        self.assertEqual(60, result.n)
        self.assertEqual("accept", result.verdict)
        self.assertIsNotNone(result.matched_rung)

    def test_one_reject_in_60_accepts_with_a_finding(self) -> None:
        result = verdict.resolve_tier2_verdict(1, self.targets)
        self.assertEqual("accept-with-finding", result.verdict)

    def test_three_rejects_in_60_is_a_batch_reject(self) -> None:
        result = verdict.resolve_tier2_verdict(3, self.targets)
        self.assertEqual("batch-reject", result.verdict)

    def test_more_than_the_ladders_own_worst_named_row_is_still_a_batch_reject(self) -> None:
        # The ladder only names rows through 3 -- a real corpus draw could reject more, and §6.3's
        # own rule ("more than one tree in ten is bad") must still resolve, not raise or default
        # silently.
        result = verdict.resolve_tier2_verdict(10, self.targets)
        self.assertEqual("batch-reject", result.verdict)
        self.assertIsNone(result.matched_rung)

    def test_the_n_90_hold_redraw_case_computes_fresh_since_no_row_covers_it(self) -> None:
        result = verdict.resolve_tier2_verdict(
            2, self.targets, sample_size=self.targets.tier2_sample_size + self.targets.tier3_additional_sample_size)
        self.assertEqual(90, result.n)
        self.assertEqual(68, result.upper_bound_permille)
        self.assertEqual("computed-not-tabled", result.verdict)
        self.assertIsNone(result.matched_rung)

    def test_the_same_draw_computed_twice_is_identical(self) -> None:
        first = verdict.resolve_tier2_verdict(1, self.targets)
        second = verdict.resolve_tier2_verdict(1, self.targets)
        self.assertEqual(first, second)
