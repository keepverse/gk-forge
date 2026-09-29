"""Tests for spec-tree-state.md §2.2c/§2.2d (task C11) — the archetype reward-per-skill-point band
and the wallet-clears-the-tier-it-opened band, walked at EVERY tier for ALL THREE shipped
archetypes, in exact integer ratios throughout (docs/architecture/numeric-types.md's overflow/precision rules — no float on a
magnitude or a comparison that gates content).

Why this file exists (spec-tree-state.md §2.2c): the OLD test,
`reward_per_skill_point_is_flat_when_first_equals_step_times_k_plus_one_over_two`
(`gk-forge/tools/seedsmith/tests/test_tree_plan_ladder.py`), asserts the flatness algebra for a given `k` — it
passes on a `k = 4` fixture and never reads `tree-plan`'s actual, deliberately non-uniform width
vectors. Checking only the endpoint (tier 10, where all three shipped archetypes agree by
construction — every archetype spends the same 40-node total) is precisely what let a 6.0× spread at
tier 2 survive undetected. That older test KEEPS its narrower scope — it stays evidence about the
algebra at constant width, never evidence about the shipped corpus (§2.2c's own instruction). This
file is the corpus evidence: it reads `tree-plan`'s REAL shipped width vectors
(`seedsmith.adapters.trees.plan.archetypes.SHIPPED_ARCHETYPES`) and the REAL tunables
(`gk-core/data/tuning/passive-tree.v1.json` via `plan_tuning.load()`), at every tier, for every archetype.

    python -m pytest gk-forge/tools/seedsmith/tests/test_tree_state_band.py -v
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.trees.plan import tuning as plan_tuning  # noqa: E402
from seedsmith.adapters.trees.plan.archetypes import (  # noqa: E402
    SHIPPED_ARCHETYPES,
    TIER_COUNT,
    reward_per_skill_point,
)

REPO_ROOT = Path(__file__).resolve().parents[3]  # tools/seedsmith/tests -> repo root

# tree-state's own two constants live in `aptitudes.v7.json` (class-system's tuning file, D34/D38,
# spec-tree-state.md §3/§8) — a different program's file, so there is no shared Python loader for it
# yet. Read directly, same `_require`-by-hand discipline as `plan_tuning.py`'s own loader: a missing
# key fails loudly rather than substituting a default (tunables-ssot T5). v6 -> v7 (D55, 2026-09-06)
# only touched creatureType/aspect/uniqueCreature; commander (read below) is untouched.
APTITUDES_TUNING_PATH = REPO_ROOT / "data" / "tuning" / "aptitudes.v7.json"


def _load_aptitude_economy() -> dict:
    doc = json.loads(APTITUDES_TUNING_PATH.read_text(encoding="utf-8"))
    return {
        # grant.aptitudePointsPerTheta == pointEconomy.aptitudePointsPerThetaMilliByScope.commander
        # (both 3) at the shipped file; spec-tree-state.md §2.2d's derivation cites the `grant` one.
        "aptitude_points_per_theta_commander": int(doc["grant"]["aptitudePointsPerTheta"]),
        "skill_points_per_theta_milli_commander": int(
            doc["pointEconomy"]["skillPointsPerThetaMilliByScope"]["commander"]),
    }


# BestResponse.DominanceMatrix's own corner shape (`gk-core/tools/HybridViability/Program.cs:78-80`),
# reproduced exactly as an integer fraction rather than as the decimal `0.54163` the spec prose uses:
# a corner build gives its spike `Total - Floor*(rosterLength-1)` out of `Total`
# (docs/research/passive-tree/12-rising-unlock-cost.md:255-258; spec-tree-state.md §2.2d, D38).
_CORNER_FLOOR = 4167
_CORNER_TOTAL_MILLI = 100_000
_CORNER_ROSTER_LENGTH = 12
CORNER_SHARE_NUM = _CORNER_TOTAL_MILLI - _CORNER_FLOOR * (_CORNER_ROSTER_LENGTH - 1)  # 54163
CORNER_SHARE_DEN = _CORNER_TOTAL_MILLI  # 100000


class RewardPerSkillPointBandTests(unittest.TestCase):
    """§2.2c's replacement for the `k = 4` fixture: walks every tier, every shipped archetype,
    against `tree-plan`'s REAL width vectors and the REAL `archetype.rewardSpreadMaxRatioMilli`
    tunable — never a private duplicate of either."""

    def setUp(self) -> None:
        self.tuning = plan_tuning.load()
        self.first = self.tuning["unlockCost"]["firstPoints"]
        self.step = self.tuning["unlockCost"]["stepPoints"]
        self.max_ratio_milli = self.tuning["archetype"]["rewardSpreadMaxRatioMilli"]
        self.assertEqual(len(SHIPPED_ARCHETYPES), 3, "the three shipped archetypes, no more, no fewer")

    def test_reward_per_skill_point_is_within_band_over_every_shipped_archetype_and_every_tier(self) -> None:
        for t in range(1, TIER_COUNT + 1):
            # reward_per_skill_point() already returns an exact (numerator, denominator) fraction in
            # lowest terms (archetypes.py's own gcd reduction) — reused here, never reimplemented, so
            # this test reads the SAME production formula the price side runs on.
            ratios = [(a.id, *reward_per_skill_point(a, t, self.first, self.step)) for a in SHIPPED_ARCHETYPES]

            def frac_ge(x, y):
                (_, xn, xd), (_, yn, yd) = x, y
                return xn * yd >= yn * xd  # cross-multiplication; no float division anywhere

            hi = lo = ratios[0]
            for r in ratios[1:]:
                if frac_ge(r, hi):
                    hi = r
                if frac_ge(lo, r):
                    lo = r
            hi_id, hi_n, hi_d = hi
            lo_id, lo_n, lo_d = lo
            # spread = (hi_n/hi_d) / (lo_n/lo_d) compared against max_ratio_milli/1000, cross-multiplied.
            self.assertLessEqual(
                hi_n * lo_d * 1000, self.max_ratio_milli * hi_d * lo_n,
                f"tier {t}: {hi_id}({hi_n}/{hi_d}) vs {lo_id}({lo_n}/{lo_d}) exceeds "
                f"archetype.rewardSpreadMaxRatioMilli={self.max_ratio_milli}")

    def test_the_spread_is_exactly_1000_milli_at_tier_ten_green_at_equality_by_design(self) -> None:
        # "green at equality by design" (todo C11 / spec §2.2c): every shipped archetype spends the
        # SAME total width (40 nodes across both branches, D29) by tier 10, so the reward-per-point
        # fraction must reduce to the IDENTICAL value for all three — asserted directly here as exact
        # fraction equality, not inferred from the band check above passing.
        t = TIER_COUNT
        ratios = [reward_per_skill_point(a, t, self.first, self.step) for a in SHIPPED_ARCHETYPES]
        first_n, first_d = ratios[0]
        for n, d in ratios[1:]:
            self.assertEqual(n * first_d, first_n * d,
                              "every shipped archetype must reduce to the identical fraction at tier 10")


class SkillWalletClearsTierBandTests(unittest.TestCase):
    """§2.2d's band read from the wallet side (`the_skill_wallet_clears_the_tier_it_just_opened_for
    _every_shipped_archetype`): the SAME band, walked as wallet-to-bill instead of reward-to-bill.
    `g` (`pointEconomy.skillPointsPerThetaMilliByScope.commander`) is asserted to reproduce from the
    corner-share form `a·corner·step·k²/s` (D38) as a CHECK — reproducing the numbers C6 already
    confirmed (10.40, rounded up to the shipped 11), never re-deriving them."""

    def setUp(self) -> None:
        self.tuning = plan_tuning.load()
        self.req_scale_points = self.tuning["tierLadder"]["reqScalePoints"]  # s = 5 (R2)
        self.max_ratio_milli = self.tuning["archetype"]["rewardSpreadMaxRatioMilli"]
        self.first = self.tuning["unlockCost"]["firstPoints"]
        self.step = self.tuning["unlockCost"]["stepPoints"]
        econ = _load_aptitude_economy()
        self.aptitude_points_per_theta = econ["aptitude_points_per_theta_commander"]  # a = 3
        self.skill_points_per_theta_milli = econ["skill_points_per_theta_milli_commander"]  # g = 11

    def test_g_reproduces_from_the_corner_share_form(self) -> None:
        # g = a * corner * step * k^2 / s  (D38, spec-tree-state.md §2.2d). k=4 is broad-and-flat's
        # own constant width (D29: 40 nodes / 10 tiers = 4/tier) -- the ONE shipped archetype the
        # constant-width form describes; it is a structural constant of THIS derivation, not a
        # re-reading of the archetype width vectors (which are non-uniform for the other two).
        a = self.aptitude_points_per_theta
        step = self.step
        k = 4
        s = self.req_scale_points
        numerator = a * CORNER_SHARE_NUM * step * k * k
        denominator = CORNER_SHARE_DEN * s
        # 5,199,648 / 500,000 = 10.399296 -- matches D38's stated "10.40" exactly; ceiling gives the
        # shipped 11 (D38: "round up ... so the focused build should always be able to complete the
        # tier its gate opened, with a small surplus").
        g_ceil = -(-numerator // denominator)  # exact integer ceiling division, no float
        self.assertEqual(g_ceil, 11)
        self.assertEqual(self.skill_points_per_theta_milli, 11,
                          "aptitudes.v7.json's shipped skillPointsPerThetaMilliByScope.commander must "
                          "still be the D38-settled value this test reproduces")

    def test_the_skill_wallet_clears_the_tier_it_just_opened_for_every_shipped_archetype(self) -> None:
        g = self.skill_points_per_theta_milli
        s = self.req_scale_points
        a = self.aptitude_points_per_theta
        first, step = self.first, self.step

        # archetype.rewardSpreadMaxRatioMilli = 6000, i.e. a clean integer band of 6x either side of
        # 1000 milli (1.0) -- no fraction reduction needed for the comparison below.
        band = self.max_ratio_milli // 1000
        self.assertEqual(band * 1000, self.max_ratio_milli,
                          "rewardSpreadMaxRatioMilli is expected to be an exact multiple of 1000 for "
                          "this integer-band comparison")

        for arche in SHIPPED_ARCHETYPES:
            for t in range(1, TIER_COUNT + 1):
                # theta at which tier t opens: Theta_T = s*T*(T+1) / (2a) (spec-tree-state.md §2.2d) --
                # kept as an exact (numerator, denominator) pair, never rounded, since only the FINAL
                # wallet/bill ratio is ever compared.
                theta_num = s * t * (t + 1)
                theta_den = 2 * a
                wallet_num = g * theta_num
                wallet_den = theta_den

                n = 2 * sum(arche.widths[:t])  # both branches -- the ACTUAL widths, never 40/10
                # TreeUnlockCost.Cumulative(n, first, step), mirrored exactly (n is always even*odd or
                # even, so the //2 is exact -- same identity archetypes.py's own reward_per_skill_point
                # already relies on).
                bill = n * (n - 1) * step // 2 + n * first

                # wallet/bill compared against [1/band, band] around 1000 milli, via cross-
                # multiplication only -- exact integers throughout.
                self.assertLessEqual(
                    wallet_num, band * wallet_den * bill,
                    f"{arche.id} tier {t}: wallet over-funds beyond the {band}x band (wallet="
                    f"{wallet_num}/{wallet_den}, bill={bill})")
                self.assertGreaterEqual(
                    wallet_num * band, wallet_den * bill,
                    f"{arche.id} tier {t}: wallet under-funds beyond the {band}x band (wallet="
                    f"{wallet_num}/{wallet_den}, bill={bill})")


if __name__ == "__main__":
    unittest.main()
