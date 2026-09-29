"""Tests for seedsmith.adapters.trees.nodegen.tuning (task H1) — a thin re-export of A2's own
parser, never a second one.
"""
from __future__ import annotations

import unittest

from seedsmith.adapters.trees.nodegen import tuning
from seedsmith.adapters.trees import targets as a2_targets


class TuningReexportTests(unittest.TestCase):
    def test_load_returns_the_same_type_a2_defines(self) -> None:
        loaded = tuning.load()
        self.assertIsInstance(loaded, a2_targets.PassiveTreeTargets)

    def test_gating_metrics_is_the_same_object_a2_defines(self) -> None:
        self.assertIs(tuning.GATING_METRICS, a2_targets.GATING_METRICS)

    def test_missing_thresholds_is_the_same_function_a2_defines(self) -> None:
        self.assertIs(tuning.missing_thresholds, a2_targets.missing_thresholds)

    def test_the_live_targets_file_loads_clean_with_no_missing_threshold(self) -> None:
        loaded = tuning.load()
        self.assertEqual(tuning.missing_thresholds(loaded), [])


if __name__ == "__main__":
    unittest.main()
