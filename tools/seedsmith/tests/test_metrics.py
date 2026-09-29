"""Tests for seedsmith.metrics (tasks/seedsmith-todo.md, S1).

    python -m pytest gk-forge/tools/seedsmith/tests/test_metrics.py -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters._stub import StubAdapter  # noqa: E402
from seedsmith.corpus import Corpus  # noqa: E402
from seedsmith.metrics import Ctx, Finding, Loop, Metric, MetricRegistry, Severity, run_all  # noqa: E402
from seedsmith.metrics.coverage import EmptyPartitionMetric  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class _OpenGatingMetric(Metric):
    """Deliberately contradictory: OPEN loop cannot verify its own fix, so it must never gate."""
    id = "Test/OpenGating"
    family = "Quality"
    loop = Loop.OPEN
    gates = True

    def run(self, ctx: Ctx) -> list[Finding]:
        return []


class _NeedsBudgetMetric(Metric):
    id = "Test/NeedsBudget"
    family = "Distribution"
    loop = Loop.CLOSED
    gates = False
    needs = frozenset({"corpus", "adapter", "budget"})

    def run(self, ctx: Ctx) -> list[Finding]:
        # if this ever runs without a budget, the test asserting NOT_MEASURED would fail loudly
        return [Finding(metric=self.id, severity=Severity.GAP, subject="x", message="ran anyway")]


class LoopGateContractTests(unittest.TestCase):
    def test_open_loop_gating_metric_raises_at_registration(self) -> None:
        registry = MetricRegistry()
        with self.assertRaises(ValueError):
            registry.register(_OpenGatingMetric())

    def test_open_loop_non_gating_metric_registers_fine(self) -> None:
        class _OkOpen(Metric):
            id = "Test/OkOpen"
            family = "Quality"
            loop = Loop.OPEN
            gates = False

            def run(self, ctx: Ctx) -> list[Finding]:
                return []

        registry = MetricRegistry()
        registry.register(_OkOpen())  # must not raise
        self.assertEqual(registry.get("Test/OkOpen").id, "Test/OkOpen")

    def test_unknown_needs_value_raises_at_class_definition(self) -> None:
        with self.assertRaises(ValueError):
            class _BadNeeds(Metric):
                id = "Test/BadNeeds"
                family = "Quality"
                loop = Loop.CLOSED
                gates = False
                needs = frozenset({"corpus", "moonbeams"})

                def run(self, ctx: Ctx) -> list[Finding]:
                    return []

    def test_duplicate_metric_id_raises(self) -> None:
        registry = MetricRegistry()
        registry.register(EmptyPartitionMetric())
        with self.assertRaises(ValueError):
            registry.register(EmptyPartitionMetric())


class NotMeasuredTests(unittest.TestCase):
    def test_metric_needing_absent_budget_reports_not_measured_never_a_pass(self) -> None:
        corpus = Corpus.load(FIXTURES / "clean")
        ctx = Ctx(corpus=corpus, adapter=StubAdapter())  # no budget supplied
        registry = MetricRegistry()
        registry.register(_NeedsBudgetMetric())

        findings = run_all(registry, ctx)

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, Severity.NOT_MEASURED)
        self.assertIn("budget", findings[0].evidence["missing"])

    def test_metric_runs_once_needs_are_satisfied(self) -> None:
        corpus = Corpus.load(FIXTURES / "clean")
        ctx = Ctx(corpus=corpus, adapter=StubAdapter(), budget=object())
        registry = MetricRegistry()
        registry.register(_NeedsBudgetMetric())

        findings = run_all(registry, ctx)

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, Severity.GAP)


class FindingSerializationTests(unittest.TestCase):
    def test_to_dict_carries_schema_version(self) -> None:
        finding = Finding(metric="X/Y", severity=Severity.GAP, subject="s", message="m")
        d = finding.to_dict()
        self.assertIn("schemaVersion", d)
        self.assertEqual(d["schemaVersion"], 1)


class EmptyPartitionMetricTests(unittest.TestCase):
    def test_clean_fixture_has_no_empty_partitions(self) -> None:
        corpus = Corpus.load(FIXTURES / "clean")
        ctx = Ctx(corpus=corpus, adapter=StubAdapter())
        registry = MetricRegistry()
        registry.register(EmptyPartitionMetric())

        findings = run_all(registry, ctx)
        self.assertEqual(findings, [])

    def test_broken_fixture_flags_exactly_the_empty_partition(self) -> None:
        corpus = Corpus.load(FIXTURES / "broken")
        ctx = Ctx(corpus=corpus, adapter=StubAdapter())
        registry = MetricRegistry()
        registry.register(EmptyPartitionMetric())

        findings = run_all(registry, ctx)

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].subject, "b")
        self.assertEqual(findings[0].severity, Severity.GAP)


if __name__ == "__main__":
    unittest.main()
