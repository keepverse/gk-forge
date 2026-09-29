"""Tests for seedsmith.metrics.balance (tasks/seedsmith-todo.md, S5).

    python -m pytest gk-forge/tools/seedsmith/tests/test_balance.py -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from seedsmith.adapters.items import ItemsAdapter  # noqa: E402
from seedsmith.metrics import Ctx, MetricRegistry, Severity, run_all  # noqa: E402
from seedsmith.metrics.balance import LadderInversion, OutOfEnvelope  # noqa: E402
from seedsmith.numerics import (  # noqa: E402
    BattleRulesetProgression,
    NumericsContext,
    ProgressionPoint,
    TierBands,
)


class _FakeProgression:
    """A `ProgressionModel` whose `content_ladder()` is NOT None, so LadderInversion's PAVA path
    is actually exercised — `BattleRulesetProgression` always returns None (progression is a
    stub), so this is the only way to test the pooling logic itself."""

    def __init__(self, ladder):
        self._ladder = ladder

    def reference_base(self, channel, point):
        return 100

    def axis(self):
        return "level"

    def content_ladder(self):
        return self._ladder


class LadderInversionTests(unittest.TestCase):
    def _ctx(self, ladder):
        tuning = TierBands(version=1, base_share_permille=35, channel_weight_permille={})
        numerics = NumericsContext(tuning=tuning, progression=_FakeProgression(ladder))
        return Ctx(corpus=None, adapter=None, numerics=numerics)

    def test_monotone_ladder_has_no_findings(self) -> None:
        ladder = [("t1", 10), ("t2", 20), ("t3", 30), ("t4", 40), ("t5", 50)]
        registry = MetricRegistry()
        registry.register(LadderInversion())
        findings = run_all(registry, self._ctx(ladder))
        self.assertEqual(findings, [])

    def test_an_inversion_is_reported_naming_both_rungs(self) -> None:
        # verdant-graft-90 reading flatter than verdant-graft-50 (spec-analytics §5's own case)
        ladder = [("verdant-graft-50", 100), ("verdant-graft-90", 80)]
        registry = MetricRegistry()
        registry.register(LadderInversion())
        findings = run_all(registry, self._ctx(ladder))

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, Severity.GAP)
        self.assertIn("verdant-graft-50", findings[0].subject)
        self.assertIn("verdant-graft-90", findings[0].subject)

    def test_content_ladder_none_reports_not_measured_never_a_pass(self) -> None:
        tuning = TierBands(version=1, base_share_permille=35, channel_weight_permille={})
        progression = BattleRulesetProgression.from_adapter(ItemsAdapter())
        numerics = NumericsContext(tuning=tuning, progression=progression)
        ctx = Ctx(corpus=None, adapter=None, numerics=numerics)

        registry = MetricRegistry()
        registry.register(LadderInversion())
        findings = run_all(registry, ctx)

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, Severity.NOT_MEASURED)

    def test_missing_numerics_context_entirely_also_reports_not_measured(self) -> None:
        registry = MetricRegistry()
        registry.register(LadderInversion())
        ctx = Ctx(corpus=None, adapter=None)  # numerics defaults to None
        findings = run_all(registry, ctx)

        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, Severity.NOT_MEASURED)
        self.assertIn("numerics", findings[0].evidence["missing"])


class OutOfEnvelopeTests(unittest.TestCase):
    def test_the_shipped_tuning_resolves_clean_for_every_channel_it_can_resolve(self) -> None:
        """No GAP over the shipped tuning — and the channels the metric could NOT resolve are
        reported as NOT_MEASURED, one per channel, rather than crashing or silently passing.

        Since tier-bands v2 (item-content T10) the file authors a weight for all 109 affix-family
        stems, so `FamilyExpansion` stops refusing them; `adapters.items.channels` still carries a
        `BattleRuleset` reference base for only the 14 primary ones. That difference is a real,
        named gap in the progression model, and NOT_MEASURED is how this suite says so.
        """
        from seedsmith.metrics import Severity

        tuning = TierBands.load("latest")
        progression = BattleRulesetProgression.from_adapter(ItemsAdapter())
        numerics = NumericsContext(tuning=tuning, progression=progression)
        ctx = Ctx(corpus=None, adapter=None, numerics=numerics)

        registry = MetricRegistry()
        registry.register(OutOfEnvelope())
        findings = run_all(registry, ctx)

        self.assertEqual([f for f in findings if f.severity is Severity.GAP], [])

        from seedsmith.adapters.items.channels import PRIMARY_CHANNEL_IDS
        unmeasured = {f.subject for f in findings if f.severity is Severity.NOT_MEASURED}
        self.assertEqual(unmeasured, set(tuning.channel_weight_permille) - PRIMARY_CHANNEL_IDS)

    def test_the_fourteen_primary_channels_alone_still_resolve_with_no_findings(self) -> None:
        # The historical shape of the check above, pinned against v1 so "clean" keeps a meaning
        # that does not depend on how many stems the latest tuning has grown to.
        tuning = TierBands.load(1)
        progression = BattleRulesetProgression.from_adapter(ItemsAdapter())
        numerics = NumericsContext(tuning=tuning, progression=progression)
        ctx = Ctx(corpus=None, adapter=None, numerics=numerics)

        registry = MetricRegistry()
        registry.register(OutOfEnvelope())
        self.assertEqual(run_all(registry, ctx), [])

    def test_a_pathological_tuning_that_zeros_out_m1_is_caught(self) -> None:
        # channelWeight so small the m1 formula rounds to 0, which makes every tier equal —
        # exactly the monotonicity failure this metric exists to catch before it ships.
        tuning = TierBands(version=99, base_share_permille=1, channel_weight_permille={
            "vitality": 1,
        })
        progression = BattleRulesetProgression.from_adapter(ItemsAdapter())
        numerics = NumericsContext(tuning=tuning, progression=progression)
        ctx = Ctx(corpus=None, adapter=None, numerics=numerics)

        registry = MetricRegistry()
        registry.register(OutOfEnvelope())
        findings = run_all(registry, ctx)
        self.assertGreater(len(findings), 0)
        self.assertTrue(all(f.severity == Severity.GAP for f in findings))


if __name__ == "__main__":
    unittest.main()
