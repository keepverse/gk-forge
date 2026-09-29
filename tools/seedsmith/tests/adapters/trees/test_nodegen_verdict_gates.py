"""Tests for seedsmith.adapters.trees.nodegen.verdict's task-H2 additions:
`hard_gate_ids`/`assert_exactly_one_hard_gate` (spec-tree-language.md §7.1, §7 gate 23's own
"exactly one gate is promoted to hard-fail first").

Resolves the acceptance wording's own naming collision (see verdict.py's module-level comment):
"GATING_METRICS has exactly one entry" cannot mean `adapters.trees.targets.GATING_METRICS` (that
dict has SIX entries, and H1's own `test_nodegen_verdict.py` already exercises all six) — it means
exactly one metric registered under one family carries `gates=True`, read off a REAL
`metrics.registry.MetricRegistry`, never off `GATING_METRICS`.
"""
from __future__ import annotations

import unittest

from seedsmith.adapters.trees.nodegen import verdict
from seedsmith.metrics.model import Ctx, Finding, Loop, Metric, Severity
from seedsmith.metrics.registry import MetricRegistry


class _StubClosedMetric(Metric):
    """A minimal CLOSED-loop metric, `gates` set per-instance via a class attribute override at
    construction time (Metric's own `gates` is a `ClassVar`, so each stub subclasses fresh)."""

    family = "PassiveTree"
    loop = Loop.CLOSED
    needs = frozenset()
    covers = ()

    def run(self, ctx: Ctx) -> "list[Finding]":
        return []


def _closed_metric(metric_id: str, *, gates: bool) -> Metric:
    return type(metric_id.replace("/", "_"), (_StubClosedMetric,), {"id": metric_id, "gates": gates})()


class HardGateIdsTests(unittest.TestCase):
    def test_zero_gating_metrics_in_an_empty_registry(self) -> None:
        registry = MetricRegistry()
        self.assertEqual(verdict.hard_gate_ids(registry, "PassiveTree"), [])

    def test_finds_the_one_gating_metric_among_several_non_gating_ones(self) -> None:
        registry = MetricRegistry()
        registry.register(_closed_metric("PassiveTree/QuotaDrift", gates=False))
        registry.register(_closed_metric("PassiveTree/CellOccupancy", gates=False))
        registry.register(_closed_metric("PassiveTree/UnresolvedCount", gates=True))
        self.assertEqual(verdict.hard_gate_ids(registry, "PassiveTree"), ["PassiveTree/UnresolvedCount"])

    def test_never_counts_a_different_familys_gating_metric(self) -> None:
        registry = MetricRegistry()
        registry.register(_closed_metric("PassiveTree/UnresolvedCount", gates=True))
        other = _closed_metric("CreatureRoster/UnresolvedCount", gates=True)
        other.__class__.family = "CreatureRoster"
        registry.register(other)
        self.assertEqual(verdict.hard_gate_ids(registry, "PassiveTree"), ["PassiveTree/UnresolvedCount"])


class AssertExactlyOneHardGateTests(unittest.TestCase):
    def test_passes_against_the_real_shipped_creature_roster_registry(self) -> None:
        """The one place §7.1's rule already holds in the real, shipped registry today
        (`metrics/creature_roster.py:369`'s own promotion) — proof the invariant is not vacuous."""
        from seedsmith.metrics.creature_roster import ALL_CREATURE_ROSTER_METRICS

        registry = MetricRegistry()
        for metric_cls in ALL_CREATURE_ROSTER_METRICS:
            registry.register(metric_cls())
        verdict.assert_exactly_one_hard_gate(registry, "CreatureRoster")  # must not raise

    def test_raises_when_a_family_has_zero_hard_gates(self) -> None:
        """PassiveTree's own real state today: `PassiveTree/TreeEqualValue` (task C1) is the only
        metric registered so far, and it ships `gates=False` on purpose (promotion is a later,
        deliberate act) — so the invariant correctly refuses to call that a pass."""
        registry = MetricRegistry()
        registry.register(_closed_metric("PassiveTree/TreeEqualValue", gates=False))
        with self.assertRaises(ValueError):
            verdict.assert_exactly_one_hard_gate(registry, "PassiveTree")

    def test_raises_when_a_family_has_two_hard_gates(self) -> None:
        registry = MetricRegistry()
        registry.register(_closed_metric("PassiveTree/UnresolvedCount", gates=True))
        registry.register(_closed_metric("PassiveTree/QuotaDrift", gates=True))
        with self.assertRaises(ValueError) as ctx:
            verdict.assert_exactly_one_hard_gate(registry, "PassiveTree")
        self.assertIn("2", str(ctx.exception))

    def test_passes_once_the_full_eight_metric_passive_tree_family_is_simulated(self) -> None:
        """A fixture standing in for H4's own end state (spec-tree-language.md §7 gates 15-22: 8
        `PassiveTree/*` metrics, exactly one — `UnresolvedCount` — at `gates=True`). H2 cannot make
        this true in the REAL registry ahead of H4 without doing H4's own job; this proves the
        MECHANISM accepts the shape H4 is expected to land in."""
        registry = MetricRegistry()
        non_gating_ids = [
            "PassiveTree/QuotaDrift", "PassiveTree/MechanismRamp", "PassiveTree/CellOccupancy",
            "PassiveTree/ExclusionRate", "PassiveTree/ExclusionResolvable",
            "PassiveTree/NearDuplicate", "PassiveTree/NameCollision",
        ]
        for metric_id in non_gating_ids:
            registry.register(_closed_metric(metric_id, gates=False))
        registry.register(_closed_metric("PassiveTree/UnresolvedCount", gates=True))
        verdict.assert_exactly_one_hard_gate(registry, "PassiveTree")  # must not raise


class OpenLoopMetricNeverGatesTests(unittest.TestCase):
    """The acceptance bullet's second clause: "an OPEN-loop metric registered with gates=True
    raises" — already the shipped behaviour of `MetricRegistry.register` (spec-metrics.md §6, "the
    second place `Loop.OPEN + gates=True` is rejected"); proven here scoped to a PassiveTree-shaped
    metric specifically, rather than trusting that the existing generic S1 test covers this family
    too."""

    def test_an_open_loop_passive_tree_metric_with_gates_true_is_refused_at_registration(self) -> None:
        class OpenLoopHazard(Metric):
            id = "PassiveTree/Rationale"
            family = "PassiveTree"
            loop = Loop.OPEN
            gates = True
            needs = frozenset()
            covers = ()

            def run(self, ctx: Ctx) -> "list[Finding]":
                return []

        registry = MetricRegistry()
        with self.assertRaises(ValueError):
            registry.register(OpenLoopHazard())


if __name__ == "__main__":
    unittest.main()
