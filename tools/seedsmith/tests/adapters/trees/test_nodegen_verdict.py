"""Tests for seedsmith.adapters.trees.nodegen.verdict (task H1) — `GATING_METRICS` dict +
`missing_thresholds()`, re-exported from A2; `RunReport`'s FAIL-beats-NOT_MEASURED,
held-partition-denies-PASS resolution (spec-tree-language.md §7 gate 23, §7.1).
"""
from __future__ import annotations

import unittest

from seedsmith.adapters.trees.nodegen import verdict
from seedsmith.adapters.trees import targets as a2_targets


class GatingMetricsReexportTests(unittest.TestCase):
    def test_gating_metrics_is_the_same_object_a2_defines(self) -> None:
        self.assertIs(verdict.GATING_METRICS, a2_targets.GATING_METRICS)

    def test_unresolved_count_metric_is_one_of_the_gating_metrics(self) -> None:
        self.assertIn(verdict.UNRESOLVED_COUNT_METRIC, verdict.GATING_METRICS)


class RunReportVerdictTests(unittest.TestCase):
    def test_pass_only_when_every_gating_metric_ran_and_cleared(self) -> None:
        report = verdict.RunReport()
        for metric in verdict.GATING_METRICS:
            report.record(metric, ran=True, cleared=True)
        self.assertEqual(report.verdict, verdict.Verdict.PASS)

    def test_a_fail_beats_a_not_measured(self) -> None:
        report = verdict.RunReport()
        metrics = list(verdict.GATING_METRICS)
        report.record(metrics[0], ran=True, cleared=False)   # FAIL
        report.record(metrics[1], ran=False, cleared=False)  # NOT_MEASURED
        self.assertEqual(report.verdict, verdict.Verdict.FAIL)

    def test_a_held_partition_alone_denies_a_pass(self) -> None:
        report = verdict.RunReport(held_partitions=["might"])
        for metric in verdict.GATING_METRICS:
            report.record(metric, ran=True, cleared=True)
        self.assertEqual(report.verdict, verdict.Verdict.NOT_MEASURED)

    def test_no_gating_outcomes_at_all_is_not_measured_not_a_pass(self) -> None:
        report = verdict.RunReport()
        self.assertEqual(report.verdict, verdict.Verdict.NOT_MEASURED)

    def test_to_dict_carries_the_verdict_and_metric_rows(self) -> None:
        report = verdict.RunReport()
        report.record("PassiveTree/UnresolvedCount", ran=True, cleared=True)
        as_dict = report.to_dict()
        self.assertIn("verdict", as_dict)
        self.assertEqual(len(as_dict["metrics"]), 1)


if __name__ == "__main__":
    unittest.main()
