"""Tests for seedsmith.numerics (tasks/seedsmith-todo.md, S5).

    python -m pytest gk-forge/tools/seedsmith/tests/test_numerics.py -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters._stub import StubAdapter  # noqa: E402
from seedsmith.adapters.items import ItemsAdapter  # noqa: E402
from seedsmith.numerics import (  # noqa: E402
    BattleRulesetProgression,
    CalibrationLevelError,
    OpWeight,
    ProgressionPoint,
    TierBands,
    UnsharedChannelError,
    explain,
    largest_remainder_apportion,
    resolve,
    solve_base_share,
)
from seedsmith.numerics.formulas import primary_channel_m1, round_legible  # noqa: E402
from seedsmith.workspace_roots import owned_path  # noqa: E402

#: The forge repository. `data/seed/**` is gk-data's content pack and gk-forge carries neither, so
#: a `REPO_ROOT / "data" / "seed"` join names a path in a repository that does not have it -- the file
#: is reported missing while sitting present two directories away. The seed file below is therefore
#: resolved per FILE through `owned_path`, never by joining the local root.
REPO_ROOT = Path(__file__).resolve().parents[3]


class CommittedExampleTests(unittest.TestCase):
    """The two worked examples spec-numerics.md §1 verifies the formula against, independent of
    which sharePermille v1 actually chose (both examples predate the v1 normalisation)."""

    def test_vitality_30_permille_of_680_rounds_to_20(self) -> None:
        self.assertEqual(primary_channel_m1(30, 680), 20)

    def test_might_45_permille_of_92_rounds_to_4(self) -> None:
        self.assertEqual(primary_channel_m1(45, 92), 4)

    def test_round_legible_matches_plain_rounding_on_the_committed_examples(self) -> None:
        self.assertEqual(round_legible(30 * 680 / 1000), 20)
        self.assertEqual(round_legible(45 * 92 / 1000), 4)


class UnsharedChannelTests(unittest.TestCase):
    def test_channel_with_no_authored_share_raises_not_defaults(self) -> None:
        tuning = TierBands(version=1, base_share_permille=35,
                           channel_weight_permille={"vitality": 1000})
        progression = BattleRulesetProgression.from_adapter(ItemsAdapter())
        point = ProgressionPoint(level=10)
        with self.assertRaises(UnsharedChannelError):
            resolve("might", OpWeight.FLAT, 1, tuning, progression, point)

    def test_authored_channel_resolves_fine(self) -> None:
        tuning = TierBands(version=1, base_share_permille=35,
                           channel_weight_permille={"vitality": 1000})
        progression = BattleRulesetProgression.from_adapter(ItemsAdapter())
        point = ProgressionPoint(level=10)
        result = resolve("vitality", OpWeight.FLAT, 1, tuning, progression, point)
        self.assertGreater(result.value, 0)


class CalibrationLevelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tuning = TierBands(version=1, base_share_permille=35,
                                channel_weight_permille={"vitality": 1000})
        self.progression = BattleRulesetProgression.from_adapter(ItemsAdapter())

    def test_resolving_at_the_literal_calibration_level_raises(self) -> None:
        with self.assertRaises(CalibrationLevelError):
            resolve("vitality", OpWeight.FLAT, 1, self.tuning, self.progression,
                   ProgressionPoint(level=20))

    def test_calibration_level_allowed_when_explicitly_requested(self) -> None:
        result = resolve("vitality", OpWeight.FLAT, 1, self.tuning, self.progression,
                         ProgressionPoint(level=20), allow_calibration_level=True)
        self.assertGreater(result.value, 0)

    def test_other_levels_never_raise(self) -> None:
        for level in (1, 5, 19, 21, 100, 1000):
            resolve("vitality", OpWeight.FLAT, 1, self.tuning, self.progression,
                   ProgressionPoint(level=level))  # must not raise


class StubAdapterResolveTests(unittest.TestCase):
    """Proves numerics resolves against the stub adapter with NO bands.v1.json on disk at all —
    the whole point of B2's fix (spec-foundation §7.1): the locked shape constants are code, and
    channel identity comes only from adapter.channels()."""

    def test_resolves_against_stub_with_no_registry_file(self) -> None:
        adapter = StubAdapter()
        progression = BattleRulesetProgression.from_adapter(adapter)
        tuning = TierBands(version=1, base_share_permille=35,
                           channel_weight_permille={"power": 1000})
        result = resolve("power", OpWeight.FLAT, 3, tuning, progression, ProgressionPoint(level=5))
        self.assertEqual(result.tier, 3)
        self.assertGreater(result.value, 0)


class GuardrailTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tuning = TierBands(version=1, base_share_permille=35,
                                channel_weight_permille={"vitality": 1000, "might": 1000})
        self.progression = BattleRulesetProgression.from_adapter(ItemsAdapter())
        self.point = ProgressionPoint(level=10)

    def test_ladder_is_strictly_monotonic(self) -> None:
        r = resolve("vitality", OpWeight.FLAT, 5, self.tuning, self.progression, self.point)
        self.assertEqual(list(r.ladder), sorted(set(r.ladder)))
        self.assertEqual(len(set(r.ladder)), 5)

    def test_value_is_contained_in_its_own_band(self) -> None:
        r = resolve("vitality", OpWeight.FLAT, 3, self.tuning, self.progression, self.point)
        self.assertLessEqual(r.lo, r.value)
        self.assertLessEqual(r.value, r.hi)

    def test_od4_overlap_ties_are_accepted_not_rejected(self) -> None:
        # Reproduces might's own documented tie: hi_1 == lo_2. If the guardrail used `<=` for
        # "violated" (i.e. required strict `>`) this would raise; it must not.
        resolve("might", OpWeight.FLAT, 1, self.tuning, self.progression, self.point)  # no raise


class ExplainTests(unittest.TestCase):
    def test_explain_names_every_step_of_the_derivation(self) -> None:
        tuning = TierBands(version=1, base_share_permille=35,
                           channel_weight_permille={"vitality": 1000})
        progression = BattleRulesetProgression.from_adapter(ItemsAdapter())
        text = explain("vitality", OpWeight.FLAT, 2, tuning, progression, ProgressionPoint(level=10))
        for fragment in ("channel=vitality", "sharePermille", "referenceBase", "m1 =", "ladder"):
            self.assertIn(fragment, text)


class LargestRemainderTests(unittest.TestCase):
    def test_shares_sum_exactly_to_total(self) -> None:
        weights = {"a": 160, "b": 120, "c": 90, "d": 80, "e": 80, "f": 70, "g": 60, "h": 60,
                  "i": 60, "j": 50, "k": 50, "l": 50, "m": 40, "n": 30, "o": 30}
        result = largest_remainder_apportion(1000, weights)
        self.assertEqual(sum(result.values()), 1000)

    def test_real_role_budget_weights_sum_exactly(self) -> None:
        # core.v1.json roles.list budgetWeightMilli, read live rather than hand-copied.
        # Resolved per file against its owner -- `data/seed/items/_registry/core.v1.json` lives in
        # gk-data's pack, and joining it onto this repository's root names a file it does not have.
        weights = {r["roleId"]: r["budgetWeightMilli"]
                  for r in __import__("json").loads(
                      owned_path("data/seed/items/_registry/core.v1.json", REPO_ROOT)
                      .read_text(encoding="utf-8"))["roles"]["list"]}
        result = largest_remainder_apportion(1000, weights)
        self.assertEqual(sum(result.values()), 1000)

    def test_naive_rounding_would_have_drifted_on_this_input(self) -> None:
        # A weight set chosen so plain round(total*w/sum) does NOT sum to the total, proving the
        # guardrail this function exists for is real, not theoretical.
        weights = {"a": 1, "b": 1, "c": 1}  # 1000/3 = 333.33... each, floor-sums to 999
        naive = sum(round(1000 * w / 3) for w in weights.values())
        self.assertNotEqual(naive, 1000)
        self.assertEqual(sum(largest_remainder_apportion(1000, weights).values()), 1000)


class SolveBaseShareTests(unittest.TestCase):
    def test_positive_level_delta_yields_positive_base_share(self) -> None:
        share = solve_base_share(10, 20, affixes_per_item=1.0, mean_tier=2.0)
        self.assertGreater(share, 0)

    def test_larger_level_delta_demands_larger_base_share(self) -> None:
        small = solve_base_share(5, 20, affixes_per_item=1.0, mean_tier=2.0)
        large = solve_base_share(20, 20, affixes_per_item=1.0, mean_tier=2.0)
        self.assertGreater(large, small)


if __name__ == "__main__":
    unittest.main()
